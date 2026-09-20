import os,tempfile,unittest,uuid
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='yntaly-test-')
from fastapi.testclient import TestClient
from main import app,connection
from city_pricing import waiting_fare,distance_fare,in_service
class CityTest(unittest.TestCase):
 def test_rates(self):
  self.assertEqual([distance_fare(2000,t) for t in ['vmeste','econom','comfort','comfort_plus']],[140,170,180,200])
  self.assertEqual([waiting_fare(t) for t in [0,59999,60000,90000,120000,180000]],[0,0,0,13,25,50])
  self.assertFalse(in_service({'lat':43.5166,'lon':68.4996}))
 def test_flow(self):
  with TestClient(app) as c,patch('main.route_metres',return_value=2000):
   def reg(phone,role):
    r=c.post('/api/register',json={'phone':phone,'name':'QA','role':role,'password':'Test-only-12345'});self.assertEqual(r.status_code,200);return {'Authorization':'Bearer '+r.json()['token']}
   p=reg('77000000001','passenger');d=reg('77000000002','driver');other=reg('77000000003','driver')
   coords={'pickup':{'lat':43.302,'lon':68.27},'destination':{'lat':43.311,'lon':68.28},'tariff':'econom'}
   self.assertEqual(c.post('/api/quote',headers=p,json={**coords,'destination':{'lat':43.516,'lon':68.5}}).status_code,400)
   q=c.post('/api/quote',headers=p,json=coords).json();self.assertEqual(q['price'],170)
   b={**coords,'id':str(uuid.uuid4()),'from':'Түркістан','to':'Түркістан','quoteId':q['quoteId'],'when':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'address':'QA 1','destinationAddress':'QA 2','price':1,'distanceM':1}
   self.assertEqual(c.post('/api/orders',headers=p,json={**b,'to':'Кентау'}).status_code,400)
   r=c.post('/api/orders',headers=p,json=b);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['price'],170)
   route='/api/orders/'+b['id'];self.assertEqual(c.post('/api/orders',headers=p,json=b).json()['id'],b['id'])
   self.assertEqual(c.post(route+'/offers',headers=d,json={'price':1}).status_code,200)
   order=c.get('/api/orders',headers=p).json()[0];self.assertEqual(order['offers'][0]['price'],170)
   c.post(route+'/accept',headers=p,json={'offerId':order['offers'][0]['id']})
   self.assertEqual(c.post(route+'/arrive',headers=p,json={}).status_code,400)
   self.assertEqual(c.post(route+'/arrive',headers=d,json={}).status_code,409)
   self.assertEqual(c.get(route+'/location',headers=other).status_code,403)
   c.put(route+'/location',headers=d,json={**coords['pickup'],'accuracy':10})
   self.assertEqual(c.post(route+'/arrive',headers=d,json={}).status_code,200)
   with connection() as db:start=db.execute('SELECT started FROM waiting WHERE orderId=?',(b['id'],)).fetchone()[0]
   with patch('main.now',return_value=start+180000):
    self.assertEqual(c.post(route+'/start',headers=d,json={}).status_code,200)
    self.assertEqual(c.post(route+'/start',headers=d,json={}).status_code,200)
   for _ in range(2):self.assertEqual(c.post(route+'/complete',headers=d,json={}).status_code,200)
   ledger=c.get('/api/ledger',headers=d).json();self.assertEqual(len(ledger['rows']),1);self.assertEqual(ledger['gross'],220);self.assertEqual(ledger['commission'],11);self.assertEqual(ledger['net'],209)
   self.assertEqual(c.get(route+'/location',headers=p).status_code,409)
   self.assertEqual(c.delete('/api/me',headers=p).status_code,200)
   with patch('main.route_metres',side_effect=TimeoutError):
    otherp=reg('77000000004','passenger');self.assertEqual(c.post('/api/quote',headers=otherp,json=coords).status_code,503)
if __name__=='__main__':unittest.main()
