import os,tempfile,unittest,uuid,base64
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp(prefix='billing-test-'))
from fastapi.testclient import TestClient
from main import app,connection,password
import billing

class BillingTest(unittest.TestCase):
 def test_cycle_receipt_admin_dispatch(self):
  with TestClient(app) as c,patch('main.route_metres',return_value=10000):
   def register(role):
    phone='77'+str(uuid.uuid4().int)[:9]
    r=c.post('/api/register',json={'phone':phone,'name':'QA','role':role,'password':'Unit-test-only'});self.assertEqual(r.status_code,200,r.text);a=r.json();return {'Authorization':'Bearer '+a['token']},a['user']['id']
   p,pid=register('passenger');d,did=register('driver');other,otherid=register('driver')
   def order():
    coords={'pickup':{'lat':43.302,'lon':68.27},'destination':{'lat':43.311,'lon':68.28},'tariff':'econom'}
    q=c.post('/api/quote',headers=p,json=coords).json()
    r=c.post('/api/orders',headers=p,json={**coords,'id':str(uuid.uuid4()),'quoteId':q['quoteId'],'from':'Түркістан','to':'Түркістан','address':'QA','destinationAddress':'QA2','when':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()});self.assertEqual(r.status_code,200,r.text);return r.json()['id']
   oid=order();route='/api/orders/'+oid
   self.assertNotIn('commission',c.get('/api/orders',headers=p).json()[0])
   self.assertEqual(c.get('/api/billing',headers=p).status_code,403)
   self.assertEqual(c.post(route+'/dismiss',headers=other,json={}).status_code,200)
   self.assertNotIn(oid,[o['id'] for o in c.get('/api/orders',headers=other).json()])
   self.assertIn(oid,[o['id'] for o in c.get('/api/orders',headers=d).json()])
   self.assertEqual(c.post(route+'/take',headers=d,json={}).status_code,200)
   self.assertEqual(c.post(route+'/take',headers=other,json={}).status_code,409)
   c.post(route+'/start',headers=d,json={});c.post(route+'/complete',headers=d,json={})
   bill=c.get('/api/billing',headers=d).json();self.assertEqual(bill['amount'],43);self.assertFalse(bill['blocked'])
   with connection() as db:db.execute('UPDATE driver_cycles SET started=started-? WHERE driverId=?',(billing.HOURS+1,did));db.commit()
   second=order();self.assertEqual(c.post('/api/orders/'+second+'/take',headers=d,json={}).status_code,402)
   image=base64.b64encode(b'\xff\xd8\xffsynthetic-test-receipt').decode()
   receipt={'mime':'image/jpeg','image':image,'ocr':'forged OCR says paid'}
   r=c.post('/api/billing/receipt',headers=d,json=receipt);self.assertEqual(r.status_code,200,r.text);rid=r.json()['id']
   self.assertTrue(c.get('/api/billing',headers=d).json()['blocked'])
   self.assertEqual(c.post('/api/billing/receipt',headers=d,json=receipt).status_code,409)
   self.assertEqual(c.get('/api/admin/summary',headers=d).status_code,401)
   salt='unit-test-salt';pw='Only-in-unit-test'
   with patch.dict(os.environ,{'ADMIN_PASSWORD_SALT':salt,'ADMIN_PASSWORD_HASH':password(pw,salt)}):
    self.assertEqual(c.post('/api/admin/login',json={'password':'bad'}).status_code,401)
    a=c.post('/api/admin/login',json={'password':pw});self.assertEqual(a.status_code,200,a.text);admin={'Authorization':'Bearer '+a.json()['token']}
    self.assertEqual(c.post('/api/admin/receipts/'+rid+'/approve',headers=admin,json={}).status_code,400)
    self.assertEqual(c.get('/api/admin/receipts/'+rid+'/image',headers=d).status_code,401)
    for _ in range(2):self.assertEqual(c.post('/api/admin/receipts/'+rid+'/approve',headers=admin,json={'bankConfirmed':True}).status_code,200)
    result=c.get('/api/billing',headers=d).json();self.assertEqual(result['amount'],0);self.assertFalse(result['blocked'])
    self.assertEqual(c.get('/api/admin/summary',headers=admin).json()['paid'],43)
    self.assertEqual(c.post('/api/orders/'+second+'/take',headers=d,json={}).status_code,200)
   c.post('/api/orders/'+second+'/cancel',headers=p,json={})

if __name__=='__main__':unittest.main()
