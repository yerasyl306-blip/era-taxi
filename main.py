"""Single-instance Python API with a persistent SQLite volume and private live GPS."""
import hashlib,hmac,json,math,os,re,secrets,sqlite3,time
from contextlib import contextmanager,asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from fastapi import FastAPI,Request
import billing
from city_pricing import TARIFFS,in_service,route_metres,distance_fare,waiting_fare,metres,arrival_eta
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).parent
DB=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'taxi.sqlite'
CITIES={'Түркістан'}
TZ=timezone(timedelta(hours=5))
def now(): return int(time.time()*1000)
def uid(): return secrets.token_hex(16)
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def password(s,salt): return hashlib.scrypt(s.encode(),salt=salt.encode(),n=16384,r=8,p=1,dklen=64).hex()
class Problem(Exception):
 def __init__(self,message,status=400): self.message,self.status=message,status
def must(value,message='Рұқсат жоқ',status=400):
 if not value: raise Problem(message,status)
def text(v,limit=200):
 must(isinstance(v,str) and 0<len(v.strip())<=limit,'Мәтінді тексеріңіз');return v.strip()
def number(v,maximum=1000000,minimum=1):
 must(type(v) is int and minimum<=v<=maximum,'Санды тексеріңіз');return v
def point(v):
 if v is None: return None
 must(isinstance(v,dict),'Геолокация дұрыс емес')
 for key,limit in [('lat',90),('lon',180)]: must(type(v.get(key)) in (float,int) and math.isfinite(v[key]) and abs(v[key])<=limit,'Геолокация дұрыс емес')
 return {'lat':v['lat'],'lon':v['lon']}
@contextmanager
def connection():
 db=sqlite3.connect(DB,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
 try: yield db
 finally: db.close()
def one(db,sql,*args):
 r=db.execute(sql,args).fetchone();return dict(r) if r else None
def allrows(db,sql,*args): return [dict(r) for r in db.execute(sql,args)]
def initialize():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with connection() as db: db.executescript((ROOT/'schema.sql').read_text());db.executescript(billing.DDL);db.commit()
@asynccontextmanager
async def lifespan(app): initialize();yield
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
origins=['https://appassets.androidplatform.net','https://yntaly-taxi.yerasyl306gmail-com.chatgpt.site']+os.environ.get('ALLOWED_ORIGINS','').split(',')
app.add_middleware(CORSMiddleware,allow_origins=[s for s in origins if s],allow_methods=['GET','POST','PUT','DELETE','OPTIONS'],allow_headers=['Authorization','Content-Type'])
@app.exception_handler(Problem)
async def problem_handler(req,e): return JSONResponse({'error':e.message},status_code=e.status)
@app.middleware('http')
async def bounded(req,call_next):
 if req.url.path.startswith('/api/'):
  limit=4300000 if req.url.path=='/api/billing/receipt' else 32768
  if int(req.headers.get('content-length','0'))>limit: return JSONResponse({'error':'Сұрау тым үлкен'},status_code=413)
  raw=await req.body()
  if len(raw)>limit:return JSONResponse({'error':'Сұрау тым үлкен'},status_code=413)
 response=await call_next(req);response.headers['X-Content-Type-Options']='nosniff'
 if req.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
 return response
def rate(db,key,maximum):
 bucket=now()//60000;key=digest(key)+':'+str(bucket)
 db.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET n=n+1',(key,now()+120000))
 count=one(db,'SELECT n FROM limits WHERE key=?',key)['n'];db.execute('DELETE FROM limits WHERE expires<?',(now(),));db.execute('DELETE FROM locations WHERE updated<?',(now()-45000,));db.commit()
 must(count<=maximum,'Кейінірек қайталаңыз',429)
def user(db,req):
 token=req.headers.get('authorization','').removeprefix('Bearer ')
 u=one(db,'SELECT u.id,u.phone,u.name,u.role FROM users u JOIN sessions s ON s.userId=u.id WHERE s.token=? AND s.expires>? AND u.deleted=0',digest(token),now())
 must(u,'Қайта кіріңіз',401);return u
def view(db,o,u):
 o=dict(o);p=json.loads(o['payload']);participant=u['id'] in (o['passengerId'],o['driverId'])
 if not participant:
  for k in ['pickup','destination','address','destinationAddress']:p.pop(k,None)
 o['payload']=p;o['offers']=[f for f in allrows(db,'SELECT o.*,u.name FROM offers o JOIN users u ON u.id=o.driverId WHERE orderId=?',o['id']) if u['id']==o['passengerId'] or u['id']==f['driverId']]
 o['contact']=one(db,'SELECT phone,name FROM users WHERE id=?',o['passengerId'] if u['role']=='driver' else o['driverId']) if participant and o['driverId'] else None
 w=one(db,'SELECT * FROM waiting WHERE orderId=?',o['id']);o['waiting']=None
 if w:
  elapsed=max(0,(w['ended'] if w['ended'] is not None else now())-w['started']);o['waiting']={'elapsedMs':elapsed,'active':w['ended'] is None,'fee':w['fee'] if w['ended'] is not None else waiting_fare(elapsed)}
 if u['role']=='driver':o['commission']=(o['price']*5+50)//100;o['driverNet']=o['price']-o['commission']
 return o
@app.api_route('/api/{path:path}',methods=['GET','POST','PUT','DELETE'])
def api(path:str,req:Request,b:dict=None):
 b=b or {};method=req.method
 with connection() as db:
  if path=='health': return {'ok':True,'runtime':'python','locationTtlSeconds':45,'version':'0.4.0','city':'Түркістан'}
  rate(db,((req.client.host if req.client else 'unknown')+':auth') if path in ['register','login'] else req.headers.get('authorization',req.client.host if req.client else 'unknown'),20 if path in ['register','login'] else 300)
  if path in ['register','login'] and method=='POST':
   phone=re.sub(r'[\s()+-]','',text(b.get('phone')));must(re.fullmatch(r'7\d{10}',phone),'Телефон +7 және 10 сан болсын')
   pw=b.get('password');must(isinstance(pw,str) and 8<=len(pw)<=128,'Құпиясөз 8–128 таңба болсын')
   if path=='register':
    must(b.get('role') in ['driver','passenger'],'Рөл дұрыс емес');salt=uid()
    try:db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,0)',(uid(),phone,text(b.get('name'),60),b['role'],salt,password(pw,salt)));db.commit()
    except sqlite3.IntegrityError:raise Problem('Телефон тіркелген',409)
   u=one(db,'SELECT * FROM users WHERE phone=? AND deleted=0',phone)
   candidate=password(pw,u['salt'] if u else 'dummy-salt-for-missing-user');must(u and hmac.compare_digest(u['hash'],candidate),'Телефон немесе құпиясөз қате',401)
   token=secrets.token_hex(32);db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),u['id'],now()+7*86400000));db.execute('DELETE FROM sessions WHERE expires<?',(now(),));db.commit()
   return {'token':token,'user':{k:u[k] for k in ['id','phone','name','role']}}
  if path.startswith('admin/'):
   rate(db,'admin:'+path+':'+str(req.client.host if req.client else 'unknown'),10 if path=='admin/login' else 120)
   return billing.handle(path,method,b,req,db,None,now(),must,uid,digest,password)
  u=user(db,req)
  if u['role']=='driver':
   billing.cycle(db,u['id'],now());db.commit()
  if path in ['billing','billing/receipt']:return billing.handle(path,method,b,req,db,u,now(),must,uid,digest,password)
  if path=='me' and method=='GET':return u
  if path=='logout' and method=='POST':
   db.execute('DELETE FROM sessions WHERE token=?',(digest(req.headers['authorization'][7:]),));db.execute('DELETE FROM locations WHERE driverId=?',(u['id'],));db.commit();return {'ok':True}
  if path=='orders' and method=='GET':
   sql='SELECT * FROM orders WHERE passengerId=? ORDER BY created DESC LIMIT 100' if u['role']=='passenger' else "SELECT * FROM orders WHERE state='open' OR driverId=? ORDER BY created DESC LIMIT 100"
   rows=allrows(db,sql,u['id'])
   if u['role']=='driver':rows=[o for o in rows if o['driverId']==u['id'] or not one(db,'SELECT 1 FROM dismissed WHERE orderId=? AND driverId=?',o['id'],u['id'])]
   return [view(db,o,u) for o in rows]
  if path=='quote' and method=='POST':
   must(u['role']=='passenger');must(b.get('tariff') in TARIFFS,'Тариф дұрыс емес')
   a=point(b.get('pickup'));d=point(b.get('destination'));must(in_service(a) and in_service(d),'Тек Түркістан қызмет аумағы: орталықтан 12 км')
   rate(db,'routing:'+u['id'],8)
   try:distance=route_metres(a,d)
   except Exception:raise Problem('Жол бағыты есептелмеді. Кейінірек қайталаңыз.',503)
   q={'tariff':b['tariff'],'pickup':a,'destination':d,'distanceM':distance,'price':distance_fare(distance,b['tariff']),'ratePerKm':TARIFFS[b['tariff']]}
   qid=uid();db.execute('DELETE FROM quotes WHERE expires<?',(now(),));db.execute('INSERT INTO quotes VALUES(?,?,?,?)',(qid,u['id'],json.dumps(q),now()+600000));db.commit()
   return {**q,'quoteId':qid,'expiresAt':now()+600000}
  if path=='orders' and method=='POST':
   must(u['role']=='passenger');key=text(b.get('id'),64);must(re.fullmatch(r'[a-zA-Z0-9-]+',key),'ID дұрыс емес')
   db.execute('BEGIN IMMEDIATE');prior=one(db,'SELECT * FROM orders WHERE id=?',key)
   if prior:
    must(prior['passengerId']==u['id'] and json.loads(prior['payload']).get('quoteId')==b.get('quoteId'),'Қайталанған сұрау өзгерген',409)
    return view(db,prior,u)
   quote=one(db,'SELECT * FROM quotes WHERE id=? AND userId=? AND expires>?',b.get('quoteId'),u['id'],now());must(quote,'Алдымен маршрут бағасын есептеңіз',409);q=json.loads(quote['payload'])
   must(b.get('from')=='Түркістан' and b.get('to')=='Түркістан' and b.get('tariff')==q['tariff'],'Тек Түркістан ішіндегі сапар')
   must(b.get('pickup')==q['pickup'] and b.get('destination')==q['destination'],'Мекенжай өзгерді. Бағаны қайта есептеңіз',409)
   try:stamp=int(datetime.fromisoformat(b['when'].replace('Z','+00:00')).timestamp()*1000)
   except (ValueError,KeyError,TypeError):raise Problem('Уақыт дұрыс емес')
   must(now()-60000<=stamp<now()+30*86400000,'Уақыт алдағы 30 күнде болсын')
   p={k:b.get(k) for k in ['from','to','tariff','when','quoteId']};p.update(address=text(b.get('address')),destinationAddress=text(b.get('destinationAddress')),pickup=q['pickup'],destination=q['destination'],note=text(b['note'],500) if b.get('note') else '',distanceM=q['distanceM'],baseFare=q['price'],pricingVersion=1)
   db.execute("INSERT INTO orders VALUES(?,?,NULL,'open',?,?,?)",(key,u['id'],json.dumps(p,ensure_ascii=False),q['price'],now()));db.execute('DELETE FROM quotes WHERE id=?',(quote['id'],));db.commit();return view(db,one(db,'SELECT * FROM orders WHERE id=?',key),u)
  match=re.fullmatch(r'orders/([^/]+)/(offers|accept|take|dismiss|arrive|start|complete|cancel|location)',path)
  if match:
   oid,action=match.groups();db.execute('BEGIN IMMEDIATE');o=one(db,'SELECT * FROM orders WHERE id=?',oid);must(o,'Тапсырыс табылмады',404)
   if action=='location':
    must(u['id'] in [o['passengerId'],o['driverId']],'Рұқсат жоқ',403);must(o['state'] in ['accepted','in_progress'],'Сапар белсенді емес',409)
    if method=='GET':
     loc=one(db,'SELECT lat,lon,accuracy,updated FROM locations WHERE orderId=? AND updated>?',oid,now()-45000);db.commit()
     eta=arrival_eta(oid,loc,json.loads(o['payload']).get('pickup')) if o['state']=='accepted' else None
     return {'location':loc,'stale':loc is None,'etaMinutes':eta,'state':o['state']}
    must(u['id']==o['driverId'],'Тек жүргізуші',403)
    if method=='DELETE':db.execute('DELETE FROM locations WHERE orderId=?',(oid,))
    elif method=='PUT':
     p=point(b);acc=b.get('accuracy',0);must(type(acc) in [float,int] and math.isfinite(acc) and 0<=acc<=5000,'GPS дәлдігін тексеріңіз')
     db.execute('INSERT INTO locations VALUES(?,?,?,?,?,?) ON CONFLICT(orderId) DO UPDATE SET lat=excluded.lat,lon=excluded.lon,accuracy=excluded.accuracy,updated=excluded.updated',(oid,u['id'],p['lat'],p['lon'],acc,now()))
    else:raise Problem('Әдіс қолжетімсіз',405)
   else:
    must(method=='POST','Әдіс қолжетімсіз',405)
    if action=='dismiss':
     must(u['role']=='driver');must(o['state']=='open','Тапсырыс жабық',409);db.execute('INSERT OR IGNORE INTO dismissed VALUES(?,?)',(oid,u['id']))
    elif action=='take':
     must(u['role']=='driver');must(json.loads(o['payload']).get('pricingVersion')==1,'Ескі тапсырысты қайта жасаңыз',409);must(not billing.cycle(db,u['id'],now())['blocked'],'Комиссияны төлеп, растауды күтіңіз',402);must(o['state']=='open' or o['driverId']==u['id'],'Тапсырысты басқа жүргізуші алды',409)
     if o['state']=='open':
      must(not one(db,"SELECT id FROM orders WHERE driverId=? AND state IN ('accepted','in_progress')",u['id']),'Алдымен белсенді сапарды аяқтаңыз',409)
      db.execute("UPDATE orders SET driverId=?,state='accepted' WHERE id=?",(u['id'],oid))
    elif action=='offers':
     must(not billing.cycle(db,u['id'],now())['blocked'],'Комиссияны төлеңіз',402)
     must(u['role']=='driver');must(o['state']=='open','Тапсырыс жабық',409);p=json.loads(o['payload']);must(p.get('pricingVersion')==1,'Ескі тапсырыс: жаңа нұсқада қайта жасаңыз',409);b['price']=o['price'];db.execute('INSERT INTO offers VALUES(?,?,?,?) ON CONFLICT(orderId,driverId) DO UPDATE SET price=excluded.price',(uid(),oid,u['id'],b['price']))
    elif action=='accept':
     must(o['passengerId']==u['id']);offer=one(db,'SELECT * FROM offers WHERE id=? AND orderId=?',b.get('offerId'),oid);must(offer,'Ұсыныс жоқ');must(o['state']=='open' or (o['state']=='accepted' and o['driverId']==offer['driverId']),'Тапсырыс жабық',409)
     must(not billing.cycle(db,offer['driverId'],now())['blocked'],'Жүргізуші қазір қолжетімсіз',409)
     if o['state']=='open':
       must(not one(db,"SELECT id FROM orders WHERE driverId=? AND state IN ('accepted','in_progress')",offer['driverId']),'Жүргізуші басқа сапарда',409)
       db.execute("UPDATE orders SET driverId=?,price=?,state='accepted' WHERE id=?",(offer['driverId'],offer['price'],oid))
    elif action=='arrive':
     must(o['driverId']==u['id']);must(o['state']=='accepted','Күту тек келісілген сапарға қосылады',409)
     p=json.loads(o['payload']);loc=one(db,'SELECT * FROM locations WHERE orderId=? AND updated>?',oid,now()-45000)
     must(loc and loc['accuracy']<=100 and p.get('pickup') and metres(loc,p['pickup'])<=200,'Алатын нүктеге жақындап, нақты GPS бөлісуді қосыңыз',409)
     db.execute('INSERT OR IGNORE INTO waiting(orderId,started) VALUES(?,?)',(oid,now()))
    elif action in ['start','complete']:
     must(o['driverId']==u['id']);target='in_progress' if action=='start' else 'completed';source='accepted' if action=='start' else 'in_progress';must(o['state'] in [source,target],'Сапар күйі сәйкес емес',409)
     if action=='start' and o['state']=='accepted':
      w=one(db,'SELECT * FROM waiting WHERE orderId=?',oid)
      if w and w['ended'] is None:
       end=now();fee=waiting_fare(end-w['started']);db.execute('UPDATE waiting SET ended=?,fee=? WHERE orderId=?',(end,fee,oid));db.execute('UPDATE orders SET price=price+? WHERE id=?',(fee,oid))
     db.execute('UPDATE orders SET state=? WHERE id=?',(target,oid))
     if action=='complete':
      fee=(o['price']*5+50)//100;db.execute('INSERT OR IGNORE INTO ledger VALUES(?,?,?,?,?,?)',(oid,u['id'],o['price'],fee,o['price']-fee,now()));db.execute('DELETE FROM locations WHERE orderId=?',(oid,))
    elif action=='cancel':
     must(u['id'] in [o['passengerId'],o['driverId']]);must(o['state'] in ['open','accepted','cancelled'],'Сапарды тоқтату мүмкін емес',409);db.execute("UPDATE orders SET state='cancelled' WHERE id=?",(oid,));db.execute('UPDATE waiting SET ended=COALESCE(ended,?),fee=0 WHERE orderId=?',(now(),oid));db.execute('DELETE FROM locations WHERE orderId=?',(oid,))
   db.commit();return {'ok':True}
  if path in ['journal','report','ledger']:
   must(u['role']=='driver')
   if path=='ledger' and method=='GET':
    rows=allrows(db,'SELECT * FROM ledger WHERE driverId=? ORDER BY created DESC',u['id']);return {'rows':rows,'commission':sum(x['commission'] for x in rows),'gross':sum(x['gross'] for x in rows),'net':sum(x['net'] for x in rows)}
   if path=='journal' and method=='PUT':
    try:day=datetime.strptime(b['day'],'%Y-%m-%d').date();must(str(day)==b['day'] and day<=datetime.now(TZ).date(),'Күн дұрыс емес')
    except (ValueError,KeyError,TypeError):raise Problem('Күн дұрыс емес')
    for k in ['startKm','endKm','fuel','income']:number(b.get(k),10000000,0)
    must(0<=b['endKm']-b['startKm']<=3000,'Одометрді тексеріңіз');db.execute('BEGIN IMMEDIATE')
    prev=one(db,'SELECT endKm FROM journal WHERE userId=? AND day<? ORDER BY day DESC LIMIT 1',u['id'],b['day']);nxt=one(db,'SELECT startKm FROM journal WHERE userId=? AND day>? ORDER BY day LIMIT 1',u['id'],b['day']);must((not prev or b['startKm']>=prev['endKm']) and (not nxt or b['endKm']<=nxt['startKm']),'Одометр көрші күнмен сәйкес емес')
    db.execute('INSERT INTO journal VALUES(?,?,?,?,?,?,?) ON CONFLICT(userId,day) DO UPDATE SET startKm=excluded.startKm,endKm=excluded.endKm,fuel=excluded.fuel,income=excluded.income',(uid(),u['id'],b['day'],b['startKm'],b['endKm'],b['fuel'],b['income']));db.commit();return {'ok':True}
   if path=='journal' and method=='GET':return allrows(db,'SELECT * FROM journal WHERE userId=? ORDER BY day DESC',u['id'])
   if path=='report' and method=='GET':
    period=req.query_params.get('period','day');must(period in ['day','week','month']);end=datetime.now(TZ).date();start=end-timedelta(days=end.weekday()) if period=='week' else end.replace(day=1) if period=='month' else end
    rows=allrows(db,'SELECT * FROM journal WHERE userId=? AND day BETWEEN ? AND ?',u['id'],str(start),str(end));income=sum(x['income'] for x in rows);fuel=sum(x['fuel'] for x in rows);fee=sum(x['commission'] for x in allrows(db,'SELECT * FROM ledger WHERE driverId=? AND created>=?',u['id'],int(datetime.combine(start,datetime.min.time(),TZ).timestamp()*1000)))
    return {'income':income,'fuel':fuel,'commission':fee,'net':income-fuel-fee,'km':sum(x['endKm']-x['startKm'] for x in rows),'days':len(rows)}
  if path=='me' and method=='DELETE':
   db.execute('BEGIN IMMEDIATE')
   if u['role']=='driver':must(not billing.outstanding(db,u['id']),'Алдымен комиссия берешегін жабыңыз',409)
   must(not one(db,"SELECT id FROM orders WHERE (passengerId=? OR driverId=?) AND state IN ('open','accepted','in_progress')",u['id'],u['id']),'Белсенді сапарларды аяқтаңыз',409)
   db.execute('DELETE FROM quotes WHERE userId=?',(u['id'],));db.execute('DELETE FROM sessions WHERE userId=?',(u['id'],));db.execute('DELETE FROM journal WHERE userId=?',(u['id'],));db.execute('DELETE FROM offers WHERE driverId=?',(u['id'],));db.execute('DELETE FROM locations WHERE driverId=?',(u['id'],));db.execute('UPDATE users SET phone=?,name=?,salt=?,hash=?,deleted=1 WHERE id=?',('deleted-'+uid(),'Жойылған пайдаланушы',uid(),uid(),u['id']))
   for old in allrows(db,'SELECT id,payload FROM orders WHERE passengerId=?',u['id']):
    p=json.loads(old['payload']);p.update(address='Жойылған',destinationAddress='Жойылған',pickup=None,destination=None,note='');db.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),old['id']))
   db.commit();return {'ok':True}
  raise Problem('Табылмады',404)

web=ROOT.parent/'web'
if web.exists():app.mount('/',StaticFiles(directory=web,html=True),name='web')
