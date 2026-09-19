import os,tempfile,unittest,uuid
from datetime import datetime,timedelta,timezone
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='yntaly-test-')
from fastapi.testclient import TestClient
from main import app,connection

class SharedServerTest(unittest.TestCase):
 def test_shared_orders_private_tracking_and_exactly_once_commission(self):
  with TestClient(app) as c:
   def register(phone,role):
    r=c.post('/api/register',json={'phone':phone,'name':role,'role':role,'password':'Test-only-12345'});self.assertEqual(r.status_code,200,r.text);return {'Authorization':'Bearer '+r.json()['token']}
   passenger=register('77000000001','passenger');driver=register('77000000002','driver');other=register('77000000003','driver')
   payload={'id':str(uuid.uuid4()),'from':'Кентау','to':'Түркістан','tariff':'salon','price':2500,'when':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'address':'Қонаев 29','destinationAddress':'Тест 2','pickup':{'lat':43.516,'lon':68.50}}
   r=c.post('/api/orders',headers=passenger,json=payload);self.assertEqual(r.status_code,200,r.text);oid=r.json()['id'];route='/api/orders/'+oid
   self.assertNotIn('address',c.get('/api/orders',headers=other).json()[0]['payload'])
   self.assertEqual(c.post(route+'/offers',headers=driver,json={'price':2501}).status_code,200)
   offer=c.get('/api/orders',headers=passenger).json()[0]['offers'][0]['id']
   self.assertEqual(c.post(route+'/accept',headers=passenger,json={'offerId':offer}).status_code,200)
   self.assertEqual(c.get(route+'/location',headers=other).status_code,403)
   self.assertEqual(c.put(route+'/location',headers=other,json={'lat':43.5,'lon':68.5}).status_code,403)
   self.assertEqual(c.put(route+'/location',headers=driver,json={'lat':43.516,'lon':68.5,'accuracy':12}).status_code,200)
   self.assertEqual(c.get(route+'/location',headers=passenger).json()['location']['lat'],43.516)
   with connection() as db:db.execute('UPDATE locations SET updated=0');db.commit()
   self.assertIsNone(c.get(route+'/location',headers=passenger).json()['location'])
   self.assertEqual(c.post(route+'/start',headers=driver,json={}).status_code,200)
   for _ in range(2):self.assertEqual(c.post(route+'/complete',headers=driver,json={}).status_code,200)
   ledger=c.get('/api/ledger',headers=driver).json();self.assertEqual(len(ledger['rows']),1);self.assertEqual(ledger['commission'],125);self.assertEqual(ledger['net'],2376)
   self.assertEqual(c.get(route+'/location',headers=passenger).status_code,409)
   day=datetime.now(timezone(timedelta(hours=5))).date().isoformat()
   self.assertEqual(c.put('/api/journal',headers=driver,json={'day':day,'startKm':100,'endKm':150,'fuel':1000,'income':2501}).status_code,200)
   self.assertEqual(c.get('/api/report',headers=driver).json()['net'],1376)
   self.assertEqual(c.delete('/api/me',headers=passenger).status_code,200)
   self.assertEqual(c.get('/api/me',headers=passenger).status_code,401)
   with connection() as db:self.assertNotIn('Қонаев',db.execute('SELECT payload FROM orders').fetchone()[0])

if __name__=='__main__':unittest.main()
