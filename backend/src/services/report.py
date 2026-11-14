import csv,io
from fastapi import HTTPException
from src.models.entities import Report
from src.config.settings import ARTIFACT_DIR
from src.utils import repository as repo
from src.utils.identity import new_id,now

def safe_cell(value):return "'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value
def list_reports():return repo.all_rows('reports')
def _load_conservation(data,run):
    if not getattr(data,'conservation_id',None):return None
    cons=repo.get('conservation_reviews',data.conservation_id)
    if cons['run_id']!=run['id']:raise ValueError('守恒复核必须引用同一运行')
    if cons['status']!='completed':raise ValueError('引用的守恒复核未完成，不能写入报告')
    return cons
def create(data):
 run,review=repo.get('runs',data.run_id),repo.get('reviews',data.review_id)
 if review['status']!='approved' or review['run_id']!=run['id'] or run['status']!='completed':raise ValueError('报告必须引用该运行批准复核')
 conservation=_load_conservation(data,run)
 report=repo.put('reports',Report(new_id('rpt'),data.run_id,data.review_id,data.title,conservation and conservation['id'],now()));ARTIFACT_DIR.mkdir(parents=True,exist_ok=True);(ARTIFACT_DIR/(report['id']+'.csv')).write_text(download(report['id'],report.get('conservation_id')),encoding='utf-8');return report
def download(id,conservation_id=None):
 report=repo.get('reports',id);run=repo.get('runs',report['run_id']);r=run['result'];review=repo.get('reviews',report['review_id'])
 if conservation_id is None:conservation_id=report.get('conservation_id')
 if review['status']!='approved':raise HTTPException(403,'复核未通过')
 conservation=repo.get('conservation_reviews',conservation_id) if conservation_id else None
 if conservation is not None and (conservation['run_id']!=run['id'] or conservation['status']!='completed'):raise HTTPException(403,'守恒复核不可用')
 out=io.StringIO();w=csv.writer(out);m=r['validation']['metrics']
 w.writerow(['report','station','points','missing','pchip_unfilled_gaps','q_per_hour','observation_r','validation_targets','common_count','rts_mae_common','pchip_mae_common','rts_observation_interval_coverage','checksum']);w.writerow([safe_cell(report['title']),safe_cell(r['station']),r['point_count'],r['missing_count'],r['pchip_unfilled_gaps'],r['study']['q_per_hour'],r['study']['observation_r'],m['target_count'],m['common_count'],m['rts_mae_common'],m['pchip_mae_common'],m['rts_observation_interval_coverage'],r['checksum']])
 w.writerow([]);fields=['time_hour','original_value','is_gap','rts_output','pchip_output','rts_mean','state_variance','observation_variance','state_low','state_high','observation_low','observation_high'];w.writerow(fields)
 for p in r['production']['series']:w.writerow([p[k] for k in fields])
 w.writerow([]);fields=['time_hour','validation_truth','training_value','rts_mean','pchip','state_variance','observation_variance','observation_low','observation_high'];w.writerow(fields)
 for p in r['validation']['targets']:w.writerow([p[k] for k in fields])
 if conservation is not None:
  c=conservation['result'];w.writerow([]);w.writerow(['# 站群守恒复核',conservation['id'],c['checksum']])
  w.writerow(['station','weight'])
  for station,weight in c['station_weights'].items():w.writerow([station,weight])
  w.writerow([]);w.writerow(['区域记录数','参与调整','未匹配','遮挡隔离','硬约束数','线性相关消冗','调整缺失单元','硬约束最大残差'])
  w.writerow([c['region_count'],c['effective_count'],len(c['unmatched_records']),len(c['isolated_records']),c['hard_constraint_count'],len(c['redundant_times']),c['cell_count'],c['max_hard_residual']])
  w.writerow([]);w.writerow(['station','time_hour','prior_mean','pchip_single_station','prior_low','prior_high','adjusted_mean','posterior_variance','adjusted_low','adjusted_high','delta','variance_reduction'])
  for cell in c['cells']:w.writerow([cell['station'],cell['time_hour'],cell['prior_mean'],cell['pchip_single_station'],cell['prior_low'],cell['prior_high'],cell['adjusted_mean'],cell['posterior_variance'],cell['adjusted_low'],cell['adjusted_high'],cell['delta'],cell['variance_reduction']])
  w.writerow([]);w.writerow(['time_hour','is_hard','region_mean','region_variance','observed_part','fitted_missing_part','weighted_total','residual','residual_variance','standardized_residual','w_missing_sum','w_obs_sum'])
  for rec in c['reconciliation']:w.writerow([rec[k] for k in ('time_hour','is_hard','region_mean','region_variance','observed_part','fitted_missing_part','weighted_total','residual','residual_variance','standardized_residual','w_missing_sum','w_obs_sum')])
  w.writerow([]);w.writerow(['说明','实测值原样保留仅调整缺失值；硬约束精确满足；遮挡窗口区域记录整列隔离；异步时刻不凑近匹配'])
 return '﻿'+out.getvalue()
