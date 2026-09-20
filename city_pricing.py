"""Turkistan pilot service area, road quote and server-clock waiting fare."""
import json,math,os,threading,time,urllib.request

TARIFFS={'vmeste':70,'econom':85,'comfort':90,'comfort_plus':100}
CENTER=(43.3019457,68.2703698)
SERVICE_RADIUS_KM=12
_routing_lock=threading.Lock()
_last_request=0.0

def metres(a,b):
 lat1,lat2=map(math.radians,[a['lat'],b['lat']])
 dlat=lat2-lat1;dlon=math.radians(b['lon']-a['lon'])
 return 6371000*2*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)))

def in_service(p):
 return isinstance(p,dict) and all(type(p.get(k)) in (float,int) and math.isfinite(p[k]) for k in ['lat','lon']) and -90<=p['lat']<=90 and -180<=p['lon']<=180 and metres(p,dict(zip(['lat','lon'],CENTER)))<=SERVICE_RADIUS_KM*1000

def distance_fare(distance_m,tariff='econom'):
 return max(1,(int(distance_m)*TARIFFS[tariff]+500)//1000)

def waiting_fare(elapsed_ms):
 # First 60 seconds free. Remaining time prorated; round once to whole tenge.
 return (max(0,int(elapsed_ms)-60000)*25+30000)//60000

def route_details(a,b):
 global _last_request
 base=os.environ.get('ROUTING_URL','https://routing.openstreetmap.de/routed-car/route/v1/driving').rstrip('/')
 url=f"{base}/{a['lon']},{a['lat']};{b['lon']},{b['lat']}?overview=false&alternatives=false&steps=false&radiuses=150;150"
 with _routing_lock:
  delay=1.05-(time.monotonic()-_last_request)
  if delay>0:time.sleep(delay)
  _last_request=time.monotonic()
  req=urllib.request.Request(url,headers={'User-Agent':'YntalyTaxi/0.3 (https://yntaly-taxi.yerasyl306gmail-com.chatgpt.site)','Referer':'https://yntaly-taxi.yerasyl306gmail-com.chatgpt.site/'})
  with urllib.request.urlopen(req,timeout=15) as response:data=json.load(response)
 if data.get('code')!='Ok' or not data.get('routes'):raise ValueError('Route unavailable')
 distance=data['routes'][0]['distance']
 if not math.isfinite(distance) or not 0<=distance<=60000:raise ValueError('Route outside service limits')
 return {'distanceM':int(distance+0.5),'seconds':int(data['routes'][0]['duration']+0.5)}


def route_metres(a,b):
 result=route_details(a,b)
 if result['distanceM']<100:raise ValueError('Route too short')
 return result['distanceM']

_eta_cache={}
def arrival_eta(order_id,location,pickup):
 if not location or not pickup:return None
 cached=_eta_cache.get(order_id)
 if cached and time.monotonic()-cached[0]<30:return cached[1]
 try:
  minutes=max(1,math.ceil(route_details(location,pickup)['seconds']/60))
 except Exception:minutes=None
 if len(_eta_cache)>500:_eta_cache.clear()
 _eta_cache[order_id]=(time.monotonic(),minutes)
 return minutes
