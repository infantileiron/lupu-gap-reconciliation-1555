import csv,hashlib,io,json,math
from src.models.entities import ConservationReview
from src.utils import repository as repo
from src.utils.identity import new_id,now
from src.constants.domain import INTERVAL_Z,MAX_REGION_RECORDS,MAX_CONSERVATION_CELLS,MAX_WEIGHT_ROWS
from src.services.kalman import rts_gap_moments
from src.services.pchip import pchip_values
from src.services import linalg as la
from src.config.settings import TASK_MODE, REDIS_URL, ARTIFACT_DIR

def list_reviews():return repo.all_rows('conservation_reviews')

def create(data):
    run=repo.get('runs',data.run_id)
    if run['status']!='completed':raise ValueError('只有已完成的重建运行可以发起站群守恒复核')
    # 导入时刻即校验CSV结构，错误在入队前明确拒绝。
    weights=parse_weights(data.weights_csv);parse_regions(data.regions_csv)
    if sum(r['status'] in ('queued','running') for r in repo.all_rows('conservation_reviews'))>=10:
        raise ValueError('守恒复核队列已满，请等待已有任务完成')
    review=repo.put('conservation_reviews',ConservationReview(new_id('cons'),data.name,data.run_id,data.weights_csv,data.regions_csv,created_at=now()))
    if TASK_MODE=='inline':return run_conservation(review['id'])
    try:
        import redis
        redis.Redis.from_url(REDIS_URL).rpush('gap-conservation:jobs',review['id'])
    except Exception:
        review['status']='failed';review['error']='队列不可用，请恢复Redis后重新提交'
        repo.put('conservation_reviews',review)
        raise ValueError(review['error'])
    return review

def _write_artifact(review):
    ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
    (ARTIFACT_DIR/(review['id']+'.json')).write_text(json.dumps(review['result'],ensure_ascii=False,allow_nan=False))

def run_conservation(review_id):
    review=repo.get('conservation_reviews',review_id)
    if review['status'] in ('running','completed'):return review
    review['status']='running';repo.put('conservation_reviews',review)
    try:
        result=_compute(review)
        review['result']=result;review['status']='completed';review['error']=''
        _write_artifact(review)
    except Exception as exc:
        review['status']='failed';review['error']=str(exc)
    return repo.put('conservation_reviews',review)

def _finite_float(text,allow_blank=False):
    text=(text or '').strip()
    if allow_blank and text.lower() in ('','na','null'):return None
    value=float(text)
    if not math.isfinite(value):raise ValueError
    return value

def parse_weights(csv_text):
    reader=csv.DictReader(io.StringIO(csv_text.lstrip('﻿')))
    if not reader.fieldnames or 'station' not in reader.fieldnames or 'weight' not in reader.fieldnames:
        raise ValueError('权重CSV需要station,weight两列')
    weights={}
    for n,row in enumerate(reader,2):
        if n>MAX_WEIGHT_ROWS+1:raise ValueError(f'权重记录最多{MAX_WEIGHT_ROWS}行')
        try:
            station=row['station'].strip();weight=_finite_float(row['weight'])
            if not 1<=len(station)<=30 or not math.isfinite(weight) or weight<=0:raise ValueError
        except (ValueError,TypeError,AttributeError):
            raise ValueError(f'权重CSV第{n}行无效：站点非空且权重须为正有限值')
        if station in weights:raise ValueError(f'权重CSV站点{station}重复，每个测站只能有一条权重')
        weights[station]=weight
    if not weights:raise ValueError('权重CSV至少一行')
    return weights

def parse_regions(csv_text):
    reader=csv.DictReader(io.StringIO(csv_text.lstrip('﻿')))
    required={'time_hour','region_mean'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('区域CSV需要time_hour,region_mean两列；可选region_variance（空/NA表示硬守恒约束）')
    records=[];seen={}
    for n,row in enumerate(reader,2):
        if n>MAX_REGION_RECORDS+1:raise ValueError(f'区域记录最多{MAX_REGION_RECORDS}行')
        try:
            t=_finite_float(row['time_hour']);mean=_finite_float(row['region_mean'])
            variance=_finite_float(row.get('region_variance'),allow_blank=True)
            if not 0<=t<=10000000 or variance is not None and (not math.isfinite(variance) or variance<0):raise ValueError
        except (ValueError,TypeError):
            raise ValueError(f'区域CSV第{n}行无效：时间/均值有限，区域方差须为非负有限值或留空')
        # 完全重复的记录保留到约束层做消冗（不改变解）；同时刻但均值/方差不同属矛盾，整次拒绝。
        if t in seen:
            if seen[t]!=(mean,variance):
                raise ValueError(f'区域CSV时刻{t}存在互相矛盾的重复行（区域均值或方差不一致），整次拒绝')
        else:seen[t]=(mean,variance)
        records.append({'time_hour':t,'region_mean':mean,'region_variance':variance})
    if not records:raise ValueError('区域CSV至少一行')
    return records

def _rref_hard(rows,k):
    # 对硬约束 [G_hard | c] 做带列主元的Gauss-Jordan消元；返回(保留行, 冗余行时刻, 矛盾明细或None)。
    # 每行携带原始索引，行交换后仍能正确映射回输入顺序。
    work=[([float(x) for x in g],float(c),idx) for idx,(g,c,_t) in enumerate(rows)]
    pivot_row=0;nr=len(work)
    for col in range(k):
        if pivot_row>=nr:break
        cand=max(range(pivot_row,nr),key=lambda i:abs(work[i][0][col]))
        if abs(work[cand][0][col])<=1e-10:continue
        work[pivot_row],work[cand]=work[cand],work[pivot_row]
        g,c,oidx=work[pivot_row];pivot=g[col]
        work[pivot_row]=([v/pivot for v in g],c/pivot,oidx)
        for i in range(nr):
            if i==pivot_row:continue
            gi,ci,oi=work[i];factor=gi[col]
            if factor:work[i]=([a-factor*b for a,b in zip(gi,work[pivot_row][0])],ci-factor*work[pivot_row][1],oi)
        pivot_row+=1
    kept_idx=[];redundant=[];conflict=None
    for g,c,oidx in work:
        scale=max([abs(x) for x in g]+[1.0])
        if all(abs(x)<=1e-9*scale for x in g):
            if abs(c)>1e-8*max(scale,abs(c)):
                conflict={'row_index':oidx,'left_over':c};return None,None,conflict
            redundant.append(rows[oidx][2])
        else:kept_idx.append(oidx)
    return [rows[i] for i in sorted(kept_idx)],sorted(redundant),None

def run_conservation(review_id):
    review=repo.get('conservation_reviews',review_id)
    if review['status'] in ('running','completed'):return review
    review['status']='running';repo.put('conservation_reviews',review)
    try:
        result=_compute(review)
        review['result']=result;review['status']='completed';review['error']=''
    except Exception as exc:
        review['status']='failed';review['error']=str(exc)
    return repo.put('conservation_reviews',review)

def _station_map(dataset):
    stations={}
    for row in dataset['rows']:
        stations.setdefault(row['station'],[]).append(row)
    return stations

def _compute(review):
    run=repo.get('runs',review['run_id'])
    if run['status']!='completed':raise ValueError('引用的重建运行未完成，不能发起守恒复核')
    study=repo.get('studies',run['study_id']);dataset=repo.get('datasets',study['dataset_id'])
    mask=repo.get('masks',study['mask_id'])
    if mask['dataset_id']!=dataset['id']:raise ValueError('研究、掩码与数据集不一致，拒绝复核')
    weights=parse_weights(review['weights_csv']);regions=parse_regions(review['regions_csv'])
    if len(regions)>MAX_REGION_RECORDS:raise ValueError(f'参与求解的区域记录不能超过{MAX_REGION_RECORDS}条')
    station_rows=_station_map(dataset)
    unknown_stations=sorted(set(weights)-set(station_rows))
    if unknown_stations:raise ValueError('权重包含数据集不存在的测站：'+','.join(unknown_stations))
    # 每个测站单独重算离线RTS联合矩；生产结果只用于一致性核对，不被修改。
    priors={};pchips={}
    for station in weights:
        rows=station_rows[station];times=[r['time_hour'] for r in rows];values=[r['value'] for r in rows]
        moments=rts_gap_moments(times,values,study['q_per_hour'],study['observation_r'],study['initial_variance'],study['initial_level'])
        pchips[station]=pchip_values(times,values,times)
        if run['result']['station']==station:
            stored=run['result']['production']['series']
            for i,p in enumerate(stored):
                if abs(moments['smoothed_mean'][i]-p['rts_mean'])>1e-8+1e-10*max(1.0,abs(p['rts_mean'])):
                    raise ValueError('离线重建联合矩与已保存生产结果不一致，拒绝使用旧结果之外的先验')
        priors[station]={'times':times,'values':values,'moments':moments}
    time_index={s:{t:i for i,t in enumerate(p['times'])} for s,p in priors.items()}
    mask_targets=set(mask['target_times'])
    # 逐条区域记录匹配；异步时刻不凑近，只接受精确时刻。
    unmatched=[];isolated=[];effective=[]
    for rec in regions:
        t=rec['time_hour'];cells=[];ok=True;is_isolated=False
        for station in weights:
            idx=time_index[station].get(t)
            if idx is None:ok=False;break
            if t in mask_targets and station==mask['station']:is_isolated=True
            cells.append((station,idx))
        if not ok:
            unmatched.append({'time_hour':t,'reason':'至少一个加权测站在该时刻无记录；异步时刻不做凑近匹配'});continue
        if is_isolated:
            isolated.append({'time_hour':t,'reason':'该时刻位于连续遮挡窗口，含遮挡真值，整列区域记录隔离不参与联合调整'})
            continue
        effective.append({'time_hour':t,'region_mean':rec['region_mean'],'region_variance':rec['region_variance'],'cells':cells})
    if not effective:raise ValueError('没有可参与联合调整的区域记录（全部未匹配或被遮挡隔离），拒绝整次复核')
    # 完全重复的区域记录（同时刻/同均值/同方差）只保留一条，软约束不被重复计数；时刻记入消冗。
    unique_effective=[];dup_times=[];seen_eff=set()
    for rec in effective:
        key=(rec['time_hour'],rec['region_mean'],rec['region_variance'])
        if key in seen_eff:dup_times.append(rec['time_hour']);continue
        seen_eff.add(key);unique_effective.append(rec)
    effective=unique_effective
    # 仅纳入被有效区域记录引用到的缺失单元；实测值保持不动，未被引用的缺口不进联合调整、原样保留。
    referenced=set()
    for rec in effective:
        for station,idx in rec['cells']:
            if priors[station]['values'][idx] is None:referenced.add((station,idx))
    cells=[];cell_pos={}
    for station in weights:
        p=priors[station]
        for gap_idx in p['moments']['gap_indices']:
            if (station,gap_idx) not in referenced:continue
            cell_pos[(station,gap_idx)]=len(cells)
            i=gap_idx;t=p['times'][i];mean=p['moments']['smoothed_mean'][i]
            obs_var=p['moments']['observation_variance'][i]
            cells.append({'station':station,'time_hour':t,'prior_mean':mean,'prior_observation_variance':obs_var,
                          'prior_low':mean-INTERVAL_Z*math.sqrt(obs_var),'prior_high':mean+INTERVAL_Z*math.sqrt(obs_var),
                          'pchip_single_station':pchips[station][i]})
    k=len(cells)
    if k>MAX_CONSERVATION_CELLS:raise ValueError(f'参与调整的缺失单元超过{MAX_CONSERVATION_CELLS}个，请缩小区域时刻范围')
    # 先验协方差：站内取RTS跨时刻状态协方差的对应子块并在对角加观测噪声r，站间块对角（独立局部水平过程）。
    gap_local={station:{gi:a for a,gi in enumerate(priors[station]['moments']['gap_indices'])} for station in weights}
    sigma=[[0.0]*k for _ in range(k)]
    for station in weights:
        p=priors[station];cov=p['moments']['gap_covariance'];local=gap_local[station]
        for ia,ga in enumerate(p['moments']['gap_indices']):
            if (station,ga) not in cell_pos:continue
            for ib,gb in enumerate(p['moments']['gap_indices']):
                if (station,gb) not in cell_pos:continue
                va=cov[ia][ib]+(study['observation_r'] if ia==ib else 0.0)
                x,y=cell_pos[(station,ga)],cell_pos[(station,gb)]
                sigma[x][y]=va;sigma[y][x]=va
    mu=[c['prior_mean'] for c in cells]
    if k==0:
        # 所有有效记录时刻均有实测：无缺失可调整，逐条对账实测加权均值（硬约束不一致已在构造时拒绝）。
        reconciliation=[]
        for rec in effective:
            raw_total=sum(weights[s] for s,_ in rec['cells'])
            total=sum(weights[s]/raw_total*priors[s]['values'][idx] for s,idx in rec['cells'])
            residual=total-rec['region_mean']
            if rec['region_variance'] is None and abs(residual)>1e-7*max(1.0,abs(rec['region_mean'])):
                raise ValueError(f"硬守恒约束在时刻{rec['time_hour']}与实测加权均值矛盾（残差{residual:.6g}），整次拒绝")
            var=rec['region_variance']
            reconciliation.append({'time_hour':rec['time_hour'],'is_hard':var is None,'region_mean':rec['region_mean'],
                                   'region_variance':var,'observed_part':total,'fitted_missing_part':0.0,'weighted_total':total,
                                   'residual':residual,'residual_variance':var,'standardized_residual':residual/math.sqrt(var) if var else None,
                                   'w_missing_sum':0.0,'w_obs_sum':1.0})
        checksum=hashlib.sha256(json_dump_sorted({'run_id':review['run_id'],'weights':weights,'regions':regions,
                                                  'mask_targets':sorted(mask_targets),'dataset_id':dataset['id']}).encode()).hexdigest()
        return {'run_id':review['run_id'],'study_id':study['id'],'dataset_id':dataset['id'],'mask_id':mask['id'],
                'station_weights':weights,'region_count':len(regions),'effective_count':len(effective),
                'unmatched_records':unmatched,'isolated_records':isolated,'redundant_times':sorted(set(dup_times)),
                'hard_constraint_count':sum(1 for rec in effective if rec['region_variance'] is None),
                'cell_count':0,'cells':[],'reconciliation':reconciliation,'max_hard_residual':max((abs(x['residual']) for x in reconciliation if x['is_hard']),default=0.0),
                'checksum':checksum,'notes':['所有匹配时刻均有实测，无缺失值需要联合调整；实测值原样保留并逐条对账区域均值',
                                              '区域时刻须精确匹配，异步时刻不凑近；遮挡窗口区域记录整列隔离']}
    # 构造约束矩阵。
    g_all=[];hard_rows=[];record_meta=[]
    for rec in effective:
        g=[0.0]*k;observed_part=0.0;w_missing_sum=0.0;w_obs_sum=0.0;missing_detail=[];observed_detail=[]
        raw_total=sum(weights[s] for s,_ in rec['cells'])
        for station,idx in rec['cells']:
            w=weights[station]/raw_total;value=priors[station]['values'][idx]
            if value is None:
                col=cell_pos[(station,idx)];g[col]=w;w_missing_sum+=w;missing_detail.append({'station':station,'weight_normalized':w,'weight_raw':weights[station]})
            else:
                observed_part+=w*value;w_obs_sum+=w;observed_detail.append({'station':station,'weight_normalized':w,'value':value})
        target=rec['region_mean']-observed_part
        g_all.append((g,target,rec))
        record_meta.append({'time_hour':rec['time_hour'],'region_variance':rec['region_variance'],'w_missing_sum':w_missing_sum,'w_obs_sum':w_obs_sum,'missing':missing_detail,'observed':observed_detail,'observed_part':observed_part})
        if rec['region_variance'] is None:
            if w_missing_sum<=1e-12:
                residual=sum(d['weight_normalized']*d['value'] for d in observed_detail)-rec['region_mean']
                if abs(residual)>1e-7*max(1.0,abs(rec['region_mean'])):
                    raise ValueError(f"硬守恒约束在时刻{rec['time_hour']}无缺失可调整且与实测加权均值矛盾（残差{residual:.6g}），整次拒绝")
                continue
            hard_rows.append((g,target,rec['time_hour']))
    # 重复/线性相关硬约束消冗；矛盾硬约束整次拒绝并定位冲突时刻。
    if hard_rows:
        kept,redundant,conflict=_rref_hard(hard_rows,k)
        if conflict is not None:
            bad=hard_rows[conflict['row_index']][2]
            raise ValueError(f"相互矛盾的硬守恒约束，整次拒绝：冲突定位到区域时刻{bad}（消元后剩余左端0、右端{conflict['left_over']:.6g}）")
        kept_times={r[2] for r in kept};hard_set=kept_times
        redundant_times=sorted(set(redundant)|set(dup_times))
    else:
        kept=[];redundant_times=sorted(set(dup_times));hard_set=set()
    # g_all 已基于去重后的 effective 构造；hard_set 外的记录全部作为软约束（或纯实测校验行）。
    gh=[r[0] for r in kept];ch=[r[1] for r in kept];p=len(kept)
    soft=[(g,target,meta) for (g,target,rec),meta in zip(g_all,record_meta) if rec['time_hour'] not in hard_set]
    # 带先验协方差的约束GLS：min (x-mu)' Sigma^-1 (x-mu) + 软项，硬项 G_h x=c_h。
    # 正规方程 H x = b，其中 H=Sigma^-1+G_s'R_s^-1G_s，b=Sigma^-1 mu+G_s'R_s^-1 c_s。
    precision=la.jittered_invert(sigma)
    h=[row[:] for row in precision];rhs=[0.0]*k
    for g,target,meta in soft:
        var=meta['region_variance']
        if var is None:continue
        inv=1.0/var if var>0 else 1e12
        for i in range(k):
            rhs[i]+=inv*g[i]*target
            for j in range(k):h[i][j]+=inv*g[i]*g[j]
    h_inv=la.jittered_invert(h)
    b=[sum(precision[i][j]*mu[j] for j in range(k))+rhs[i] for i in range(k)]
    x_soft=la.matvec(h_inv,b)
    if p:
        gt=la.transpose(gh)
        s=la.matmul(la.matmul(gh,h_inv),gt)
        # 硬约束相对于软无约束解的缺口，lambda=S^-1(c_h-G_h x_soft)。
        d=[c-sum(g*v for g,v in zip(row,x_soft)) for row,c in zip(gh,ch)]
        lam=la.solve_spd(s,d)
        x_hat=[v+w for v,w in zip(x_soft,la.matvec(la.matmul(h_inv,gt),lam))]
        s_inv=la.jittered_invert(s)
        correction=la.matmul(la.matmul(la.matmul(h_inv,gt),s_inv),gh)
        h_inv_corr=la.matmul(correction,h_inv)
        posterior=[[h_inv[i][j]-h_inv_corr[i][j] for j in range(k)] for i in range(k)]
    else:
        x_hat=x_soft
        posterior=h_inv
    # 单元级输出：实测值不出现于此；新区间按后验有噪观测方差。
    cell_results=[]
    for i,c in enumerate(cells):
        pv=max(0.0,posterior[i][i]);sd=math.sqrt(pv)
        cell_results.append({**c,'adjusted_mean':x_hat[i],'posterior_variance':pv,
                             'adjusted_low':x_hat[i]-INTERVAL_Z*sd,'adjusted_high':x_hat[i]+INTERVAL_Z*sd,
                             'delta':x_hat[i]-mu[i],'variance_reduction':c['prior_observation_variance']-pv})
    # 区域残差对账（硬约束残差为0；软约束给标准化残差）。
    reconciliation=[];hard_resid_max=0.0
    for (g,target,rec),meta in zip(g_all,record_meta):
        fitted_missing=sum(g[i]*x_hat[i] for i in range(k))
        weighted_total=meta['observed_part']+fitted_missing
        residual=weighted_total-rec['region_mean']
        gpg=sum(g[i]*sum(posterior[i][j]*g[j] for j in range(k)) for i in range(k))
        is_hard=rec['time_hour'] in hard_set
        if is_hard:
            var_res=None;z=None;hard_resid_max=max(hard_resid_max,abs(residual))
        else:
            var_res=(meta['region_variance'] or 0.0)+gpg
            z=residual/math.sqrt(var_res) if var_res>0 else None
        reconciliation.append({'time_hour':rec['time_hour'],'is_hard':is_hard,'region_mean':rec['region_mean'],
                               'region_variance':rec['region_variance'],'observed_part':meta['observed_part'],
                               'fitted_missing_part':fitted_missing,'weighted_total':weighted_total,'residual':residual,
                               'residual_variance':var_res,'standardized_residual':z,
                               'w_missing_sum':meta['w_missing_sum'],'w_obs_sum':meta['w_obs_sum']})
    checksum=hashlib.sha256(json_dump_sorted({'run_id':review['run_id'],'weights':weights,'regions':regions,
                                              'mask_targets':sorted(mask_targets),'dataset_id':dataset['id']}).encode()).hexdigest()
    return {'run_id':review['run_id'],'study_id':study['id'],'dataset_id':dataset['id'],'mask_id':mask['id'],
            'station_weights':weights,'region_count':len(regions),'effective_count':len(effective),
            'unmatched_records':unmatched,'isolated_records':isolated,
            'redundant_times':redundant_times,'hard_constraint_count':p,
            'cell_count':k,'cells':cell_results,'reconciliation':reconciliation,
            'max_hard_residual':hard_resid_max,'checksum':checksum,
            'notes':['仅联合调整原始缺失值；实测值原样保留，不参与未知量','先验为离线RTS联合矩，使用缺失时刻间完整相关协方差（站内相关、站间块对角），对角加观测噪声r',
                     '区域方差留空为硬守恒约束（精确满足）；填非负方差为软约束，按完整相关不确定性GLS分配调整',
                     '区域时刻须与所有加权测站时刻精确匹配，异步时刻不凑近匹配；未匹配记录列出但不参与求解',
                     '重复或线性相关的软/硬约束自动消冗且不改变解；相互矛盾的约束整次拒绝并定位冲突时刻',
                     '连续遮挡窗口内的区域记录含遮挡真值，整列隔离；遮挡重算结果与生产结果互不修改',
                     '新区间为后验有噪观测95%区间；原单站RTS/PCHIP结果同表对照；区域残差逐条对账']}

def json_dump_sorted(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False)
