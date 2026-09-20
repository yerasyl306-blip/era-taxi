"""Manual bank reconciliation: OCR is advisory, never payment authorization."""
import base64,hashlib,hmac,os,secrets,re,sqlite3
from fastapi.responses import Response

HOURS=14*60*60*1000
DDL='''
CREATE TABLE IF NOT EXISTS driver_cycles(driverId TEXT PRIMARY KEY,started INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dismissed(orderId TEXT,driverId TEXT,PRIMARY KEY(orderId,driverId));
CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,driverId TEXT,amount INTEGER,orderIds TEXT,status TEXT,created INTEGER,reviewed INTEGER,reason TEXT,mime TEXT,image BLOB,sha TEXT UNIQUE,ocr TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_receipt ON receipts(driverId) WHERE status='pending';
CREATE TABLE IF NOT EXISTS settled(orderId TEXT PRIMARY KEY,receiptId TEXT);
CREATE TABLE IF NOT EXISTS admin_sessions(token TEXT PRIMARY KEY,expires INTEGER);
'''

def outstanding(db,driver):
 return [dict(x) for x in db.execute('SELECT l.* FROM ledger l LEFT JOIN settled s ON s.orderId=l.orderId WHERE l.driverId=? AND s.orderId IS NULL',(driver,))]

def cycle(db,driver,now):
 db.execute('INSERT OR IGNORE INTO driver_cycles VALUES(?,?)',(driver,now))
 start=db.execute('SELECT started FROM driver_cycles WHERE driverId=?',(driver,)).fetchone()[0]
 rows=outstanding(db,driver);amount=sum(r['commission'] for r in rows)
 pending=db.execute("SELECT id,status,amount FROM receipts WHERE driverId=? AND status='pending'",(driver,)).fetchone()
 if now>=start+HOURS and amount==0 and not pending:
  start=now;db.execute('UPDATE driver_cycles SET started=? WHERE driverId=?',(now,driver))
 return {'startedAt':start,'expiresAt':start+HOURS,'blocked':now>=start+HOURS and amount>0,'amount':amount,'pending':dict(pending) if pending else None,'payeePhone':'+77088137753','commissionPercent':5}

def handle(path,method,b,req,db,u,now,must,uid,digest,password):
 import json
 if path=='admin/login' and method=='POST':
  salt=os.environ.get('ADMIN_PASSWORD_SALT','');expected=os.environ.get('ADMIN_PASSWORD_HASH','')
  admin_secret=os.environ.get('ADMIN_PASSWORD') or os.environ.get('admin')
  if not expected and admin_secret:
   salt='yntaly-admin-environment';expected=password(admin_secret,salt)
  must(salt and expected,'Админ құпиясөзі серверде әлі бапталмаған',503)
  candidate=b.get('password','');must(isinstance(candidate,str) and len(candidate)<=128,'Құпиясөз дұрыс емес',401)
  must(hmac.compare_digest(password(candidate,salt),expected),'Құпиясөз дұрыс емес',401)
  token=secrets.token_hex(32);db.execute('INSERT INTO admin_sessions VALUES(?,?)',(digest(token),now+3600000));db.commit();return {'token':token}
 if path.startswith('admin/'):
  token=req.headers.get('authorization','').removeprefix('Bearer ')
  must(db.execute('SELECT 1 FROM admin_sessions WHERE token=? AND expires>?',(digest(token),now)).fetchone(),'Админ ретінде кіріңіз',401)
  if path=='admin/logout':db.execute('DELETE FROM admin_sessions WHERE token=?',(digest(token),));db.commit();return {'ok':True}
  if path=='admin/summary':
   total=db.execute('SELECT COALESCE(SUM(commission),0) FROM ledger').fetchone()[0]
   paid=db.execute('SELECT COALESCE(SUM(l.commission),0) FROM ledger l JOIN settled s ON s.orderId=l.orderId').fetchone()[0]
   receipts=[dict(r) for r in db.execute('SELECT r.id,r.driverId,u.name,u.phone,r.amount,r.status,r.created,r.ocr,r.reason FROM receipts r JOIN users u ON u.id=r.driverId ORDER BY r.created DESC LIMIT 200')]
   drivers=[dict(r) for r in db.execute("SELECT u.id,u.name,u.phone,COALESCE(SUM(CASE WHEN s.orderId IS NULL THEN l.commission ELSE 0 END),0) AS due FROM users u LEFT JOIN ledger l ON l.driverId=u.id LEFT JOIN settled s ON s.orderId=l.orderId WHERE u.role='driver' AND u.deleted=0 GROUP BY u.id")]
   return {'total':total,'paid':paid,'due':total-paid,'drivers':drivers,'receipts':receipts}
  m=re.fullmatch(r'admin/receipts/([a-f0-9]+)/(image|approve|reject)',path)
  must(m,'Табылмады',404);rid,action=m.groups()
  if action=='image':
   r=db.execute('SELECT mime,image FROM receipts WHERE id=?',(rid,)).fetchone();must(r,'Чек жоқ',404);return Response(bytes(r['image']),media_type=r['mime'],headers={'Cache-Control':'no-store'})
  must(method=='POST','Әдіс дұрыс емес',405);db.execute('BEGIN IMMEDIATE')
  r=db.execute('SELECT * FROM receipts WHERE id=?',(rid,)).fetchone();must(r,'Чек жоқ',404)
  target='approved' if action=='approve' else 'rejected'
  if r['status']==target:db.commit();return {'ok':True}
  must(r['status']=='pending','Чек бұрын қаралған',409)
  if action=='approve':
   must(b.get('bankConfirmed') is True,'Банкке түскен ақшаны растаңыз')
   for oid in json.loads(r['orderIds']):db.execute('INSERT INTO settled VALUES(?,?)',(oid,rid))
   db.execute('UPDATE driver_cycles SET started=? WHERE driverId=?',(now,r['driverId']))
  reason=str(b.get('reason',''))[:500]
  if action=='reject':must(reason.strip(),'Бас тарту себебін жазыңыз')
  db.execute('UPDATE receipts SET status=?,reviewed=?,reason=? WHERE id=?',(target,now,reason,rid));db.commit();return {'ok':True}
 must(u and u['role']=='driver','Тек жүргізуші',403)
 if path=='billing' and method=='GET':
  result=cycle(db,u['id'],now);db.commit()
  result['receipts']=[dict(r) for r in db.execute('SELECT id,amount,status,reason,created FROM receipts WHERE driverId=? ORDER BY created DESC LIMIT 20',(u['id'],))];return result
 if path=='billing/receipt' and method=='POST':
  db.execute('BEGIN IMMEDIATE');state=cycle(db,u['id'],now);must(state['blocked'],'Төлем уақыты әлі келген жоқ',409);must(not state['pending'],'Чек тексеріліп жатыр',409)
  mime=b.get('mime');must(mime in ['image/jpeg','image/png'],'JPG немесе PNG чек жүктеңіз')
  try:data=base64.b64decode(b.get('image',''),validate=True)
  except Exception:must(False,'Чек файлы дұрыс емес')
  must(0<len(data)<=3*1024*1024,'Чек 3 МБ-тан аспасын')
  must((mime=='image/jpeg' and data.startswith(b'\xff\xd8\xff')) or (mime=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')),'Файл сурет емес')
  sha=hashlib.sha256(data).hexdigest();must(not db.execute('SELECT 1 FROM receipts WHERE sha=?',(sha,)).fetchone(),'Бұл чек бұрын жіберілген',409)
  rows=outstanding(db,u['id']);rid=uid();ocr=str(b.get('ocr',''))[:10000]
  db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,u['id'],sum(r['commission'] for r in rows),json.dumps([r['orderId'] for r in rows]),'pending',now,None,'',mime,data,sha,ocr));db.commit();return {'id':rid,'status':'pending'}
 must(False,'Табылмады',404)
