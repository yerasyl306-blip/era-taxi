"""Rural seat pooling, server-ordered daily queue and monthly membership."""
import json,math,re,calendar,base64,hashlib
from datetime import datetime,timedelta,timezone
from fastapi.responses import Response
from city_pricing import route_geometry,metres,CENTER
TZ=timezone(timedelta(hours=5))
DDL='''
CREATE TABLE IF NOT EXISTS rural_routes(id TEXT PRIMARY KEY,name TEXT,points TEXT,geometry TEXT,distance INTEGER,fare INTEGER,active INTEGER,created INTEGER);
CREATE TABLE IF NOT EXISTS rural_members(driverId TEXT PRIMARY KEY,started INTEGER,paidUntil INTEGER);
CREATE TABLE IF NOT EXISTS rural_queue(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,driverId TEXT,routeId TEXT,direction INTEGER,day TEXT,capacity INTEGER,state TEXT,created INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS rural_one_active ON rural_queue(driverId) WHERE state IN ('queued','departed');
CREATE TABLE IF NOT EXISTS rural_bookings(id TEXT PRIMARY KEY,queueId TEXT,passengerId TEXT,seats INTEGER,price INTEGER,state TEXT,created INTEGER,reason TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS rural_fifo ON rural_queue(routeId,direction,day,seq);
CREATE TABLE IF NOT EXISTS rural_receipts(id TEXT PRIMARY KEY,driverId TEXT,amount INTEGER,status TEXT,created INTEGER,reviewed INTEGER,reason TEXT,mime TEXT,image BLOB,sha TEXT UNIQUE,ocr TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS rural_pending ON rural_receipts(driverId) WHERE status='pending';
'''
def row(db,sql,*args):
 r=db.execute(sql,args).fetchone();return dict(r) if r else None

def rows(db,sql,*args):return [dict(r) for r in db.execute(sql,args)]

def month_after(ms):
 d=datetime.fromtimestamp(ms/1000,TZ);year=d.year+(d.month==12);month=d.month%12+1
 return int(d.replace(year=year,month=month,day=min(d.day,calendar.monthrange(year,month)[1])).timestamp()*1000)

def day_key(now):return (datetime.fromtimestamp(now/1000,TZ)-timedelta(hours=4)).date().isoformat()

def rollover(db,now):
 old=rows(db,"SELECT id FROM rural_queue WHERE state='queued' AND day<>?",day_key(now))
 for q in old:
  db.execute("UPDATE rural_bookings SET state='cancelled',reason='04:00 кезек жаңарды' WHERE queueId=? AND state='reserved'",(q['id'],))
  db.execute("UPDATE rural_queue SET state='expired' WHERE id=?",(q['id'],))

def membership(db,driver,now):
 m=row(db,'SELECT * FROM rural_members WHERE driverId=?',driver)
 return {'startedAt':m['started'] if m else None,'paidUntil':m['paidUntil'] if m else None,'active':bool(m and m['paidUntil']>now),'monthlyFee':300,'pending':row(db,"SELECT id FROM rural_receipts WHERE driverId=? AND status='pending'",driver)}

def route_view(r):
 return {**r,'points':json.loads(r['points']),'geometry':json.loads(r['geometry'])}

def reserved(db,qid):return db.execute("SELECT COALESCE(SUM(seats),0) FROM rural_bookings WHERE queueId=? AND state IN ('reserved','travelling')",(qid,)).fetchone()[0]

def queue_view(db,q,u):
 q=dict(q);q['occupied']=reserved(db,q['id']);q['available']=q['capacity']-q['occupied']
 q['position']=db.execute("SELECT COUNT(*) FROM rural_queue WHERE routeId=? AND direction=? AND day=? AND state='queued' AND seq<=?",(q['routeId'],q['direction'],q['day'],q['seq'])).fetchone()[0] if q['state']=='queued' else None
 if q['driverId']==u['id']:
  q['passengers']=rows(db,"SELECT b.id,b.seats,b.price,b.state,u.name,u.phone FROM rural_bookings b JOIN users u ON u.id=b.passengerId WHERE b.queueId=? AND b.state IN ('reserved','travelling') ORDER BY b.created",q['id'])
 return q

def receipt_upload(db,u,b,now,must,uid):
 must(not membership(db,u['id'],now)['active'],'Төлем мерзімі әлі келген жоқ',409)
 must(row(db,'SELECT 1 FROM rural_members WHERE driverId=?',u['id']),'Алдымен Старт басыңыз',409)
 must(not row(db,"SELECT 1 FROM rural_receipts WHERE driverId=? AND status='pending'",u['id']),'Чек тексеріліп жатыр',409)
 mime=b.get('mime');must(mime in ['image/jpeg','image/png'],'JPG немесе PNG қажет')
 try:data=base64.b64decode(b.get('image',''),validate=True)
 except Exception:must(False,'Чек дұрыс емес')
 must(0<len(data)<=3*1024*1024,'Чек 3 МБ-тан аспасын')
 must((mime=='image/jpeg' and data.startswith(b'\xff\xd8\xff')) or (mime=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')),'Сурет қажет')
 sha=hashlib.sha256(data).hexdigest();must(not row(db,'SELECT 1 FROM rural_receipts WHERE sha=?',sha) and not row(db,'SELECT 1 FROM receipts WHERE sha=?',sha),'Чек бұрын жіберілген',409)
 rid=uid();db.execute('INSERT INTO rural_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,u['id'],300,'pending',now,None,'',mime,data,sha,str(b.get('ocr',''))[:10000]));return {'id':rid}

def admin(path,method,b,db,now,must,uid):
 if path=='admin/rural/routes':
  return [route_view(r) for r in rows(db,'SELECT * FROM rural_routes ORDER BY created DESC')]
 if path in ['admin/rural/preview','admin/rural/create']:
  must(method=='POST','POST қажет',405);points=b.get('points');must(isinstance(points,list) and 2<=len(points)<=10,'2–10 координата қажет')
  for p in points:
   must(isinstance(p,dict) and all(type(p.get(k)) in (float,int) and math.isfinite(p[k]) for k in ['lat','lon']),'Координата дұрыс емес')
   must(-90<=p['lat']<=90 and -180<=p['lon']<=180 and metres(p,dict(zip(['lat','lon'],CENTER)))<=150000,'Нүкте Түркістаннан 150 км ішінде болсын')
  try:result=route_geometry(points)
  except Exception:must(False,'Жол маршруты табылмады. Нүктелерді жолға жақын таңдаңыз.',503)
  if path.endswith('preview'):return result
  name=b.get('name');fare=b.get('fare');must(isinstance(name,str) and 1<=len(name.strip())<=100,'Бағыт атауы қажет');must(type(fare) is int and 1<=fare<=100000,'Бір орын бағасын енгізіңіз')
  rid=uid();db.execute('INSERT INTO rural_routes VALUES(?,?,?,?,?,?,1,?)',(rid,name.strip(),json.dumps(points),json.dumps(result['geometry']),result['distanceM'],fare,now));db.commit();return {'id':rid}
 if path=='admin/rural/toggle':
  must(method=='POST' and type(b.get('active')) is bool,'Сұрау дұрыс емес');must(row(db,'SELECT 1 FROM rural_routes WHERE id=?',b.get('id')),'Бағыт жоқ',404)
  db.execute('UPDATE rural_routes SET active=? WHERE id=?',(int(b['active']),b['id']));db.commit();return {'ok':True}
 if path=='admin/rural/summary':
  return {'paid':db.execute("SELECT COALESCE(SUM(amount),0) FROM rural_receipts WHERE status='approved'").fetchone()[0],'members':rows(db,'SELECT m.*,u.name,u.phone FROM rural_members m JOIN users u ON u.id=m.driverId'),'receipts':rows(db,'SELECT r.id,r.amount,r.status,r.reason,r.ocr,r.created,u.name,u.phone FROM rural_receipts r JOIN users u ON u.id=r.driverId ORDER BY r.created DESC LIMIT 200')}
 match=re.fullmatch(r'admin/rural/receipts/([a-f0-9]+)/(image|approve|reject)',path);must(match,'Табылмады',404);rid,action=match.groups()
 r=row(db,'SELECT * FROM rural_receipts WHERE id=?',rid);must(r,'Чек жоқ',404)
 if action=='image':return Response(bytes(r['image']),media_type=r['mime'],headers={'Cache-Control':'no-store'})
 must(method=='POST','POST қажет',405);db.execute('BEGIN IMMEDIATE');r=row(db,'SELECT * FROM rural_receipts WHERE id=?',rid)
 target='approved' if action=='approve' else 'rejected'
 if r['status']==target:db.commit();return {'ok':True}
 must(r['status']=='pending','Чек қаралған',409)
 reason=str(b.get('reason',''))[:500]
 if action=='approve':
  must(b.get('bankConfirmed') is True,'Банкке түскен ақшаны тексеріңіз');m=row(db,'SELECT * FROM rural_members WHERE driverId=?',r['driverId']);db.execute('UPDATE rural_members SET paidUntil=? WHERE driverId=?',(month_after(max(now,m['paidUntil'])),r['driverId']))
 else:must(reason.strip(),'Себебін жазыңыз')
 db.execute('UPDATE rural_receipts SET status=?,reviewed=?,reason=? WHERE id=?',(target,now,reason,rid));db.commit();return {'ok':True}

def handle(path,method,b,db,u,now,must,uid):
 db.execute('BEGIN IMMEDIATE');rollover(db,now)
 if path=='rural/state' and method=='GET':
  routes=[route_view(r) for r in rows(db,'SELECT * FROM rural_routes ORDER BY name')]
  result={'routes':routes,'serverTime':now,'day':day_key(now),'canStart':datetime.fromtimestamp(now/1000,TZ).hour>=4}
  if u['role']=='driver':
   q=row(db,"SELECT * FROM rural_queue WHERE driverId=? AND state IN ('queued','departed')",u['id']);result.update(membership=membership(db,u['id'],now),queue=queue_view(db,q,u) if q else None,receipts=rows(db,'SELECT id,amount,status,reason FROM rural_receipts WHERE driverId=? ORDER BY created DESC LIMIT 20',u['id']))
  else:
   bookings=rows(db,'SELECT b.*,q.state AS tripState,q.routeId,q.direction,u.name AS driverName,u.phone AS driverPhone FROM rural_bookings b JOIN rural_queue q ON q.id=b.queueId JOIN users u ON u.id=q.driverId WHERE b.passengerId=? ORDER BY b.created DESC LIMIT 30',u['id'])
   for booking in bookings:
    if booking['state'] not in ['reserved','travelling']:booking.pop('driverPhone',None)
   result['bookings']=bookings
  result['availability']=rows(db,"SELECT q.routeId,q.direction,COUNT(*) AS cars,SUM(q.capacity-(SELECT COALESCE(SUM(b.seats),0) FROM rural_bookings b WHERE b.queueId=q.id AND b.state='reserved')) AS seats FROM rural_queue q JOIN rural_members m ON m.driverId=q.driverId WHERE q.state='queued' AND m.paidUntil>? GROUP BY q.routeId,q.direction",now)
  db.commit();return result
 must(method=='POST','POST қажет',405)
 if path=='rural/start':
  must(u['role']=='driver','Тек жүргізуші',403);must(datetime.fromtimestamp(now/1000,TZ).hour>=4,'Старт таңғы 04:00-ден бастап ашылады',409)
  q=row(db,"SELECT * FROM rural_queue WHERE driverId=? AND state IN ('queued','departed')",u['id'])
  if q:db.commit();return queue_view(db,q,u)
  must(not row(db,"SELECT 1 FROM orders WHERE driverId=? AND state IN ('accepted','in_progress')",u['id']),'Алдымен қала сапарын аяқтаңыз',409)
  r=row(db,'SELECT * FROM rural_routes WHERE id=? AND active=1',b.get('routeId'));must(r,'Бағыт қолжетімсіз',404)
  capacity=b.get('capacity');direction=b.get('direction');must(type(capacity) is int and 1<=capacity<=8,'Орын саны 1–8');must(type(direction) is int and direction in [0,1],'Бағытты таңдаңыз')
  db.execute('INSERT OR IGNORE INTO rural_members VALUES(?,?,?)',(u['id'],now,month_after(now)))
  must(membership(db,u['id'],now)['active'],'Айлық төлем 300 ₸. Чекті жүктеп, растауды күтіңіз.',402)
  qid=uid();db.execute("INSERT INTO rural_queue(id,driverId,routeId,direction,day,capacity,state,created) VALUES(?,?,?,?,?,?,'queued',?)",(qid,u['id'],r['id'],direction,day_key(now),capacity,now));db.commit();return queue_view(db,row(db,'SELECT * FROM rural_queue WHERE id=?',qid),u)
 if path=='rural/book':
  must(u['role']=='passenger','Тек жолаушы',403);key=b.get('id');must(isinstance(key,str) and re.fullmatch(r'[a-zA-Z0-9-]{1,64}',key),'ID қажет')
  old=row(db,'SELECT * FROM rural_bookings WHERE id=?',key)
  if old:
   must(old['passengerId']==u['id'],'Рұқсат жоқ',403);oldq=row(db,'SELECT * FROM rural_queue WHERE id=?',old['queueId']);must(old['seats']==b.get('seats') and oldq['routeId']==b.get('routeId') and oldq['direction']==b.get('direction'),'Қайталанған бронь өзгерген',409);db.commit();return old
  must(not row(db,"SELECT 1 FROM rural_bookings WHERE passengerId=? AND state IN ('reserved','travelling')",u['id']),'Белсенді бронь бар',409)
  r=row(db,'SELECT * FROM rural_routes WHERE id=? AND active=1',b.get('routeId'));must(r,'Бағыт қолжетімсіз',404)
  n=b.get('seats');must(type(n) is int and 1<=n<=8,'Орын саны 1–8');must(type(b.get('direction')) is int and b['direction'] in [0,1],'Бағыт дұрыс емес')
  qs=rows(db,"SELECT q.* FROM rural_queue q JOIN rural_members m ON m.driverId=q.driverId WHERE q.routeId=? AND q.direction=? AND q.state='queued' AND q.day=? AND m.paidUntil>? ORDER BY q.seq",r['id'],b['direction'],day_key(now),now)
  q=next((q for q in qs if q['capacity']>reserved(db,q['id'])),None);must(q,'Әзірге кезекте бос көлік жоқ. Жаңартып көріңіз.',409)
  free=q['capacity']-reserved(db,q['id']);must(n<=free,'Кезектегі бірінші көлікте '+str(free)+' орын ғана бос',409)
  db.execute("INSERT INTO rural_bookings(id,queueId,passengerId,seats,price,state,created) VALUES(?,?,?,?,?,'reserved',?)",(key,q['id'],u['id'],n,r['fare']*n,now));db.commit();return row(db,'SELECT * FROM rural_bookings WHERE id=?',key)
 if path=='rural/cancel-booking':
  booking=row(db,'SELECT * FROM rural_bookings WHERE id=?',b.get('id'));must(booking and booking['passengerId']==u['id'],'Рұқсат жоқ',403);must(booking['state'] in ['reserved','cancelled'],'Сапар басталған',409)
  db.execute("UPDATE rural_bookings SET state='cancelled',reason='Жолаушы бас тартты' WHERE id=?",(booking['id'],))
 elif path in ['rural/leave','rural/depart','rural/finish']:
  must(u['role']=='driver','Тек жүргізуші',403);q=row(db,'SELECT * FROM rural_queue WHERE id=? AND driverId=?',b.get('id'),u['id']);must(q,'Кезек табылмады',404)
  if path.endswith('leave'):
   must(q['state'] in ['queued','cancelled'],'Сапар басталған',409);db.execute("UPDATE rural_bookings SET state='cancelled',reason='Жүргізуші кезектен шықты' WHERE queueId=? AND state='reserved'",(q['id'],));db.execute("UPDATE rural_queue SET state='cancelled' WHERE id=?",(q['id'],))
  elif path.endswith('depart'):
   must(q['state'] in ['queued','departed'],'Кезек жабық',409);must(reserved(db,q['id'])>0,'Жолаушы жоқ',409)
   db.execute("UPDATE rural_queue SET state='departed' WHERE id=?",(q['id'],));db.execute("UPDATE rural_bookings SET state='travelling' WHERE queueId=? AND state='reserved'",(q['id'],))
  else:
   must(q['state'] in ['departed','completed'],'Сапар басталмаған',409);db.execute("UPDATE rural_queue SET state='completed' WHERE id=?",(q['id'],));db.execute("UPDATE rural_bookings SET state='completed' WHERE queueId=? AND state='travelling'",(q['id'],))
 elif path=='rural/receipt':
  must(u['role']=='driver','Тек жүргізуші',403);result=receipt_upload(db,u,b,now,must,uid);db.commit();return result
 else:must(False,'Табылмады',404)
 db.commit();return {'ok':True}
