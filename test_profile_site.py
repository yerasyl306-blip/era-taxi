import os,tempfile,unittest,base64
from unittest.mock import patch
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp(prefix='profile-tests-'))
from fastapi.testclient import TestClient
from main import app,password
class ProfileTest(unittest.TestCase):
 def test_admin_public_lifecycle(self):
  with TestClient(app) as c,patch.dict(os.environ,{'ADMIN_PASSWORD_SALT':'test','ADMIN_PASSWORD_HASH':password('test-secret','test')}):
   self.assertEqual(c.post('/api/admin/site/profile',json={}).status_code,401)
   token=c.post('/api/admin/login',json={'password':'test-secret'}).json()['token'];h={'Authorization':'Bearer '+token}
   original=c.get('/api/site').json()['profile']
   png=base64.b64encode(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNn0AAAAASUVORK5CYII=')).decode()
   profile={**original,'name':'QA profile','upload':{'mime':'image/png','data':png}}
   self.assertEqual(c.post('/api/admin/site/profile',headers=h,json=profile).status_code,200)
   saved=c.get('/api/site').json()['profile'];self.assertEqual(saved['name'],'QA profile');self.assertEqual(c.get('/api/site/media/'+saved['avatar']).status_code,200)
   self.assertEqual(c.post('/api/admin/site/post',headers=h,json={'title':'QA','caption':'<script>alert(1)</script>','upload':{'mime':'image/svg+xml','data':png}}).status_code,400)
   self.assertEqual(c.post('/api/admin/site/post',headers=h,json={'title':'QA','caption':'<script>alert(1)</script>','upload':{'mime':'image/png','data':png}}).status_code,200)
   post=c.get('/api/site').json()['posts'][0];id=post['id']
   self.assertEqual(c.post('/api/admin/site/post',headers=h,json={'id':id,'title':'Edited','caption':'Updated'}).status_code,200)
   c.post('/api/admin/site/visibility',headers=h,json={'id':id,'hidden':True});self.assertFalse(any(p['id']==id for p in c.get('/api/site').json()['posts']))
   self.assertTrue(any(p['id']==id for p in c.get('/api/admin/site/content',headers=h).json()['posts']))
   c.post('/api/admin/site/visibility',headers=h,json={'id':id,'hidden':False});self.assertTrue(any(p['id']==id for p in c.get('/api/site').json()['posts']))
   self.assertEqual(c.post('/api/admin/site/profile',headers=h,json={**profile,'upload':{'mime':'image/png','data':'bad'}}).status_code,400)
   self.assertEqual(c.get('/api/site').json()['profile']['name'],'QA profile')
if __name__=='__main__':unittest.main()
