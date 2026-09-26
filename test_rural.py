import os,tempfile,unittest,uuid,base64
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp(prefix='rural-tests-'))
from fastapi.testclient import TestClient
from main import app,connection,password
import rural

def stamp(s):return int(datetime.fromisoformat(s+'+05:00').timestamp()*1000)
class RuralTest(unittest.TestCase):
 def test_calendar_month(self):
  self.assertEqual(rural.month_after(stamp('2026-01-31T04:00:00')),stamp('2026-02-28T04:00:00'))
  self.assertEqual(rural.month_after(stamp('2026-12-15T04:00:00')),stamp('2027-01-15T04:00:00'))
  self.assertEqual(rural.day_key(stamp('2026-09-22T03:59:59')),'2026-09-21')
  self.assertEqual(rural.day_key(stamp('2026-09-22T04:00:00')),'2026-09-22')
 def test_pool_queue_membership(self):
  clock=stamp('2026-09-22T04:00:00');geometry={'type':'LineString','coordinates':[[68.27,43.302],[68.28,43.311]]}
  with TestClient(app) as c,patch('main.now',return_value=clock) as now,patch.dict(os.environ,{'ADMIN_PASSWORD_SALT':'qa','ADMIN_PASSWORD_HASH':password('Qa-admin-only','qa')}),patch('rural.route_geometry',return_value={'geometry':geometry,'distanceM':2000}):
   def req(method,path,h=None,code=200,**kw):
    r=c.request(method,'/api/'+path,headers=h,**kw);self.assertEqual(r.status_code,code,r.text);return r.json()
   def reg(role):
    a=req('POST','register',json={'phone':'77'+str(uuid.uuid4().int)[:9],'password':'Rural-test-only','role':role,'name':'QA rural'});return {'Authorization':'Bearer '+a['token']},a['user']['id']
   d,did=reg('driver');d2,did2=reg('driver');p,pid=reg('passenger');p2,pid2=reg('passenger');p3,pid3=reg('passenger')
   a=req('POST','admin/login',json={'password':'Qa-admin-only'});admin={'Authorization':'Bearer '+a['token']}
   route={'name':'QA A to B','fare':500,'points':[{'lat':43.302,'lon':68.27},{'lat':43.311,'lon':68.28}]}
   req('POST','admin/rural/create',d,code=401,json=route)
   req('POST','admin/rural/create',admin,code=400,json={**route,'points':[{'lat':999,'lon':68.27}]*2})
   rid=req('POST','admin/rural/create',admin,json=route)['id']
   self.assertEqual(req('GET','rural/state',p)['routes'][-1]['geometry'],geometry)
   now.return_value=clock-1;req('POST','rural/start',d,code=409,json={'routeId':rid,'direction':0,'capacity':2})
   now.return_value=clock
   q=req('POST','rural/start',d,json={'routeId':rid,'direction':0,'capacity':2});q2=req('POST','rural/start',d2,json={'routeId':rid,'direction':0,'capacity':3});self.assertEqual([q['position'],q2['position']],[1,2])
   self.assertEqual(req('POST','rural/start',d,json={'routeId':rid,'direction':0,'capacity':8})['id'],q['id'])
   b={'id':uuid.uuid4().hex,'routeId':rid,'direction':0,'seats':1};book=req('POST','rural/book',p,json=b);self.assertEqual(book['queueId'],q['id']);self.assertEqual(book['price'],500)
   self.assertEqual(req('POST','rural/book',p,json=b)['id'],b['id']);req('POST','rural/book',p,code=409,json={**b,'seats':2})
   req('POST','rural/book',p2,code=409,json={**b,'id':uuid.uuid4().hex,'seats':2})
   b2={**b,'id':uuid.uuid4().hex};self.assertEqual(req('POST','rural/book',p2,json=b2)['queueId'],q['id'])
   b3={**b,'id':uuid.uuid4().hex};self.assertEqual(req('POST','rural/book',p3,json=b3)['queueId'],q2['id'])
   self.assertEqual(req('GET','rural/state',d)['queue']['occupied'],2)
   req('POST','rural/cancel-booking',p2,code=403,json={'id':b['id']})
   req('POST','rural/depart',d,json={'id':q['id']})
   req('POST','rural/cancel-booking',p,code=409,json={'id':b['id']})
   req('POST','rural/finish',d,json={'id':q['id']});req('POST','rural/finish',d,json={'id':q['id']})
   self.assertEqual(req('GET','ledger',d)['commission'],0)
   now.return_value=clock+86400000
   self.assertIsNone(req('GET','rural/state',d2)['queue']);self.assertEqual(req('GET','rural/state',p3)['bookings'][0]['state'],'cancelled')
   newq=req('POST','rural/start',d,json={'routeId':rid,'direction':0,'capacity':1});self.assertEqual(newq['position'],1)
   req('POST','rural/leave',d,json={'id':newq['id']})
   until=rural.month_after(clock)
   with connection() as db:db.execute('UPDATE sessions SET expires=?',(until+86400000,));db.commit()
   now.return_value=until
   req('POST','rural/start',d,code=402,json={'routeId':rid,'direction':0,'capacity':1})
   image=base64.b64encode(b'\xff\xd8\xffunique-rural-test').decode()
   receipt=req('POST','rural/receipt',d,json={'mime':'image/jpeg','image':image,'ocr':'fake paid text'})
   req('POST','rural/start',d,code=402,json={'routeId':rid,'direction':0,'capacity':1})
   a=req('POST','admin/login',json={'password':'Qa-admin-only'});admin={'Authorization':'Bearer '+a['token']}
   endpoint='admin/rural/receipts/'+receipt['id']
   req('GET',endpoint+'/image',p,code=401)
   req('POST',endpoint+'/approve',admin,code=400,json={})
   req('POST',endpoint+'/approve',admin,json={'bankConfirmed':True});req('POST',endpoint+'/approve',admin,json={'bankConfirmed':True})
   self.assertEqual(req('GET','rural/state',d)['membership']['paidUntil'],rural.month_after(until))
   self.assertEqual(req('GET','admin/rural/summary',admin)['paid'],300)
   req('POST','rural/start',d,json={'routeId':rid,'direction':0,'capacity':1})
   req('POST','admin/rural/toggle',admin,json={'id':rid,'active':False})
   req('POST','rural/book',p,code=404,json={**b,'id':uuid.uuid4().hex})
 def test_immediate_city(self):
  with TestClient(app) as c,patch('main.route_metres',return_value=2000):
   a=c.post('/api/register',json={'phone':'77'+str(uuid.uuid4().int)[:9],'name':'QA immediate','role':'passenger','password':'Test-only-now'}).json();h={'Authorization':'Bearer '+a['token']}
   coords={'pickup':{'lat':43.302,'lon':68.27},'destination':{'lat':43.311,'lon':68.28},'tariff':'econom'}
   q=c.post('/api/quote',headers=h,json=coords).json();r=c.post('/api/orders',headers=h,json={**coords,'id':uuid.uuid4().hex,'quoteId':q['quoteId'],'from':'Түркістан','to':'Түркістан','address':'QA','destinationAddress':'QA2','when':'2099-01-01T00:00:00Z'})
   self.assertEqual(r.status_code,200,r.text);p=r.json()['payload'];self.assertTrue(p['immediate']);self.assertNotIn('2099',p['when'])
