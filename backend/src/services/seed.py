import random,math
from src.utils import repository as repo
from src.utils.identity import now
from src.utils.security import hash_password
from src.services.statistics import analyze
from src.services.conservation import run_conservation

def demo_rows():
 rng=random.Random(2309);rows=[]
 for station,offset in [('LP-01',0),('LP-02',2),('LP-03',-1.2)]:
  walk=0
  for t in range(480):
   walk+=rng.gauss(0,.035);level=10+offset+1.3*math.sin(2*math.pi*t/48)+.003*t+walk;truth=round(level+rng.gauss(0,.22),5)
   missing=t<5 or 60<=t<=64 or 160<=t<=184 or t>=474 or station=='LP-02' and 330<=t<=333 or station=='LP-03' and 350<=t<=357
   rows.append({'station':station,'time_hour':float(t),'value':None if missing else truth,'truth':truth})
 return rows

def seed():
 repo.init_db()
 for role,name in [('admin','缺测复核工程师'),('analyst','测站数据分析员'),('viewer','环境观察员')]:
  email=f'{role}@lupu.test';repo.put('users',{'id':email,'email':email,'name':name,'role':role,'password_hash':hash_password('Gap2026!')},insert_only=True)
 rows=demo_rows();repo.put('datasets',{'id':'ds-stations','name':'三测站 · 480小时观测档案','source':'station_gaps_202611.csv','rows':rows,'created_at':now()},insert_only=True)
 mask={'id':'mask-block12','name':'LP-01连续遮挡100—111h','dataset_id':'ds-stations','station':'LP-01','start_hour':100.,'end_hour':111.,'target_times':[float(x) for x in range(100,112)],'created_at':now()};repo.put('masks',mask,insert_only=True)
 study={'id':'study-local-level','name':'固定q/r离线缺口复核','dataset_id':'ds-stations','mask_id':'mask-block12','q_per_hour':.03,'observation_r':.09,'initial_variance':10000.,'initial_level':None,'created_at':now()};repo.put('studies',study,insert_only=True)
 repo.put('runs',{'id':'run-demo','study_id':'study-local-level','status':'completed','result':analyze(rows,mask,study),'error':'','created_at':now()},insert_only=True)
 repo.put('reviews',{'id':'review-demo','run_id':'run-demo','comment':'RTS仅作离线重建；共用内点MAE与P+R观测覆盖已分开核验，原始观测不覆盖。','status':'approved','reviewer':'admin@lupu.test','created_at':now()},insert_only=True)
 repo.put('reports',{'id':'report-demo','run_id':'run-demo','review_id':'review-demo','title':'芦浦测站缺口与遮挡验证复核册','created_at':now()},insert_only=True)
 _seed_conservation(rows)
 return {t:len(repo.all_rows(t)) for t in ('users','datasets','masks','studies','runs','reviews','reports','conservation_reviews')}

def _seed_conservation(rows):
 if any(r['id']=='cons-demo' for r in repo.all_rows('conservation_reviews')):return
 weights_csv='station,weight\nLP-01,1.0\nLP-02,1.0\nLP-03,1.0\n'
 run=repo.get('runs','run-demo')
 rts={}
 for station in ('LP-01','LP-02','LP-03'):
  study=repo.get('studies',run['study_id'])
  st=[r for r in rows if r['station']==station]
  times=[r['time_hour'] for r in st];values=[r['value'] for r in st]
  from src.services.reconstruction import reconstruct
  series=reconstruct(times,values,study)['series']
  rts[station]={p['time_hour']:p['rts_mean'] for p in series}
 lines=['time_hour,region_mean,region_variance']
 for t in (60.,62.,64.):
  mean=sum(rts[s][t] for s in ('LP-01','LP-02','LP-03'))/3.0
  lines.append(f'{t:g},{mean:.6f},')
 for t in (331.,333.):
  mean=sum(rts[s][t] for s in ('LP-01','LP-02','LP-03'))/3.0
  lines.append(f'{t:g},{mean:.6f},0.25')
 lines.append('12.5,9.0,0.25')
 lines.append('105.,10.8,')
 regions_csv='\n'.join(lines)+'\n'
 repo.put('conservation_reviews',{'id':'cons-demo','name':'三站区域加权守恒复核','run_id':'run-demo','weights_csv':weights_csv,'regions_csv':regions_csv,'status':'queued','result':{},'error':'','created_at':now()},insert_only=True)
 run_conservation('cons-demo')
