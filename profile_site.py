"""Public profile content; writes require the existing administrator session."""
import base64,json
from fastapi.responses import Response
DDL='''
CREATE TABLE IF NOT EXISTS site_profile(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS site_media(id TEXT PRIMARY KEY,mime TEXT NOT NULL,data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS site_posts(id TEXT PRIMARY KEY,title TEXT,caption TEXT,image TEXT,created INTEGER,hidden INTEGER DEFAULT 0);
'''
DEFAULT={'name':'Қалдарбек Ерасыл Ерболатұлы','title':'IT Engineer · Жас маман','bio':'2002 жылы Майдантал ауылында дүниеге келген. Майдантал жалпы орта мектебінің 2020 жылғы түлегі. Оқу жолын Қайнар академиялық колледжінде бастап, денсаулығына байланысты Түркістан қаласындағы Болашақ колледжіне ауысқан. Колледжді үздік дипломмен тәмамдаған.','education':'Білімі: бакалавр','avatar':''}
def public(db,include_hidden=False):
 row=db.execute('SELECT payload FROM site_profile WHERE id=1').fetchone()
 return {'profile':json.loads(row[0]) if row else DEFAULT,'posts':[dict(x) for x in db.execute('SELECT id,title,caption,image,created,hidden FROM site_posts '+('' if include_hidden else 'WHERE hidden=0 ')+'ORDER BY created DESC,id DESC LIMIT 100')]}
def media(db,id,must):
 row=db.execute('SELECT mime,data FROM site_media WHERE id=?',(id,)).fetchone();must(row,'Сурет табылмады',404)
 return Response(bytes(row['data']),media_type=row['mime'],headers={'X-Content-Type-Options':'nosniff'})
def image(db,b,must,uid):
 must(isinstance(b,dict),'Сурет дұрыс емес');mime=b.get('mime');must(mime in ('image/jpeg','image/png'),'JPG немесе PNG таңдаңыз')
 try:data=base64.b64decode(b.get('data',''),validate=True)
 except Exception:must(False,'Сурет дұрыс емес')
 must(0<len(data)<=2*1024*1024,'Сурет 2 МБ-тан аспасын')
 must(data.startswith(b'\xff\xd8\xff') if mime=='image/jpeg' else data.startswith(b'\x89PNG\r\n\x1a\n'),'Сурет пішімі дұрыс емес')
 id=uid();db.execute('INSERT INTO site_media VALUES(?,?,?)',(id,mime,data));return id
def admin(path,method,b,db,now,must,uid):
 if path=='admin/site/content' and method=='GET':return public(db,True)
 must(method=='POST','Әдіс дұрыс емес',405)
 def text(key,limit):
  value=b.get(key,'');must(isinstance(value,str) and len(value.strip())<=limit,'Мәтін тым ұзын');return value.strip()
 if path=='admin/site/profile':
  profile={k:text(k,n) for k,n in [('name',100),('title',100),('bio',3000),('education',300)]};must(profile['name'],'Аты-жөніңізді жазыңыз')
  old=public(db)['profile'].get('avatar','');profile['avatar']=image(db,b['upload'],must,uid) if b.get('upload') else ('' if b.get('removeAvatar') else old)
  db.execute('INSERT INTO site_profile VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(profile),))
  if old and old!=profile['avatar']:db.execute('DELETE FROM site_media WHERE id=?',(old,))
 elif path=='admin/site/post':
  title=text('title',140);caption=text('caption',5000);must(title or caption,'Пост мәтінін жазыңыз')
  id=b.get('id');old=db.execute('SELECT * FROM site_posts WHERE id=?',(id,)).fetchone() if id else None;must(not id or old,'Пост табылмады',404)
  must(old or db.execute('SELECT COUNT(*) FROM site_posts').fetchone()[0]<100,'100 пост шегіне жетті')
  picture=image(db,b['upload'],must,uid) if b.get('upload') else (old['image'] if old else '')
  if old:
   db.execute('UPDATE site_posts SET title=?,caption=?,image=? WHERE id=?',(title,caption,picture,id))
   if old['image'] and old['image']!=picture:db.execute('DELETE FROM site_media WHERE id=?',(old['image'],))
  else:db.execute('INSERT INTO site_posts VALUES(?,?,?,?,?,0)',(uid(),title,caption,picture,now))
 elif path=='admin/site/visibility':
  must(type(b.get('hidden')) is bool,'Күй дұрыс емес');must(db.execute('UPDATE site_posts SET hidden=? WHERE id=?',(int(b['hidden']),b.get('id'))).rowcount,'Пост табылмады',404)
 else:must(False,'Табылмады',404)
 db.commit();return {'ok':True}
