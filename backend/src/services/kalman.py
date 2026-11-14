import math

def kalman_rts(times,values,q,r,initial_variance=10000,initial_level=None):
 if len(times)!=len(values) or not times:raise ValueError('滤波时间/序列长度无效')
 if any(not math.isfinite(x) for x in (q,r,initial_variance)) or min(q,r,initial_variance)<=0:raise ValueError('q/r/初始方差必须是正有限值')
 if any(not math.isfinite(t) for t in times) or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('时间必须严格递增唯一')
 known=[v for v in values if v is not None]
 if not known:raise ValueError('没有训练观测，不能初始化离线重建')
 if any(not math.isfinite(v) for v in known) or initial_level is not None and not math.isfinite(initial_level):raise ValueError('观测或初值非有限')
 initial=known[0] if initial_level is None else initial_level;mp=[];pp=[];mf=[];pf=[]
 for i,(t,y) in enumerate(zip(times,values)):
  mean=initial if i==0 else mf[-1];variance=initial_variance if i==0 else pf[-1]+q*(t-times[i-1])
  mp.append(mean);pp.append(variance)
  if y is None:mf.append(mean);pf.append(variance)
  else:
   gain=variance/(variance+r);mf.append(mean+gain*(y-mean));pf.append(r*variance/(variance+r))
 ms=list(mf);ps=list(pf)
 for i in range(len(times)-2,-1,-1):
  gain=pf[i]/pp[i+1];ms[i]=mf[i]+gain*(ms[i+1]-mp[i+1])
  # Algebraically equivalent RTS variance, with a nonnegative stable decomposition.
  ps[i]=min(pf[i],max(0.,pf[i]*(1-gain)+gain*gain*ps[i+1]))
 return {'filtered_mean':mf,'filtered_variance':pf,'smoothed_mean':ms,'state_variance':ps,'observation_variance':[p+r for p in ps],'initial_level_used':initial,'initial_variance':initial_variance}

def rts_gap_moments(times,values,q,r,initial_variance=10000,initial_level=None):
 # 与kalman_rts相同的离线平滑，另返回目标缺失时刻之间的联合（跨时刻）协方差。
 base=kalman_rts(times,values,q,r,initial_variance,initial_level)
 n=len(times);pf=base['filtered_variance']
 log_abs=[0.0]*n;signs=[1]*n
 for i in range(n-1):
  c=pf[i]/(pf[i]+q*(times[i+1]-times[i]))
  if c==0:signs[i]=0
  elif c<0:signs[i]=-1;log_abs[i]=math.log(-c)
  else:log_abs[i]=math.log(c)
 # 对数前缀和，避免长序列上C连乘下溢为0。
 log_prefix=[0.0]*(n+1);neg_prefix=[0]*(n+1)
 for i in range(n):
  neg_prefix[i+1]=neg_prefix[i]+(1 if signs[i]<0 else 0)
  log_prefix[i+1]=log_prefix[i]+(log_abs[i] if signs[i]!=0 else 0.0)
 ps=base['state_variance']
 target=[i for i,v in enumerate(values) if v is None]
 def lag_cov(i,j):
  if i==j:return ps[i]
  lo,hi=(i,j) if i<j else (j,i)
  if signs[lo]==0 or any(signs[k]==0 for k in range(lo,hi)):return 0.0
  product_sign=-1 if (neg_prefix[hi]-neg_prefix[lo])%2 else 1
  # RTS恒等式：P_s(lo,hi)=(∏C_lo..C_hi-1)·P_s(hi)，基准为较晚时刻的平滑方差。
  return product_sign*math.exp(log_prefix[hi]-log_prefix[lo])*ps[hi]
 k=len(target);cov=[[0.0]*k for _ in range(k)]
 for a,i in enumerate(target):
  for b,j in enumerate(target):
   if b<a:cov[a][b]=cov[b][a]
   else:cov[a][b]=lag_cov(i,j)
 return {'smoothed_mean':base['smoothed_mean'],'state_variance':ps,'observation_variance':base['observation_variance'],'gap_indices':target,'gap_covariance':cov,'initial_level_used':base['initial_level_used']}
