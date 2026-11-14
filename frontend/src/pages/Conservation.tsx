import {useState} from 'react';
import * as api from '../api/conservation';
import * as runsApi from '../api/runs';
import {useResource} from '../hooks/useResource';
import {refreshResources} from '../stores/resources';
import PageTitle from '../components/common/PageTitle';
import Notice from '../components/common/Notice';
import StatusBadge from '../components/common/StatusBadge';
import EmptyState from '../components/common/EmptyState';
import {decimal} from '../utils/format';
import type {User,ConservationReview} from '../types/entities';

const DEFAULT_WEIGHTS='station,weight\nLP-01,1.0\nLP-02,1.0\nLP-03,1.0\n';
const DEFAULT_REGIONS='time_hour,region_mean,region_variance\n60,11.20,\n331,10.60,0.25\n';

export default function Conservation({user}:{user:User}){
 const{data,error}=useResource(api.list,[]);
 const{data:runs}=useResource(runsApi.list,[]);
 const completed=runs.filter(r=>r.status==='completed');
 const [runId,setRunId]=useState(sessionStorage.getItem('gap-selected-run')||'run-demo');
 const [name,setName]=useState('区域加权站群守恒复核');
 const [weights,setWeights]=useState(DEFAULT_WEIGHTS);
 const [regions,setRegions]=useState(DEFAULT_REGIONS);
 const [selected,setSelected]=useState<string>(data.find(r=>r.id==='cons-demo')?.id||'');
 const [message,setMessage]=useState('');
 const active:ConservationReview|undefined=data.find(r=>r.id===selected)||data[0];
 const canEdit=user.role!=='viewer';
 return <>
  <PageTitle chapter="06" title="区域加权均值守恒，只联合调整缺失值" description="导入时刻、区域均值与测站权重。实测值原样保留，仅缺失值参与联合调整；按离线重建的完整相关协方差分配，硬约束精确满足、软约束按区域方差加权。异步时刻不凑近匹配，遮挡窗口区域记录整列隔离。"/>
  <Notice error={error||message}/>
  {canEdit&&<form className="paper form-grid" onSubmit={async e=>{e.preventDefault();try{
    const created=await api.create({name,run_id:runId,weights_csv:weights,regions_csv:regions});
    setSelected(created.id);refreshResources();setMessage('');
   }catch(e:any){setMessage(e.message)}}}>
   <label>复核名称<input aria-label="复核名称" value={name} onChange={e=>setName(e.target.value)}/></label>
   <label>引用的完成运行<select aria-label="引用的完成运行" value={runId} onChange={e=>setRunId(e.target.value)}>
    {completed.map(r=><option key={r.id} value={r.id}>{r.id}</option>)}
   </select></label>
   <label className="wide">测站权重 CSV（station,weight；权重为正，按时刻归一化）
    <textarea aria-label="测站权重CSV" value={weights} onChange={e=>setWeights(e.target.value)}/></label>
   <label className="wide">区域记录 CSV（time_hour,region_mean,region_variance；方差留空=硬守恒约束）
    <textarea aria-label="区域记录CSV" value={regions} onChange={e=>setRegions(e.target.value)}/></label>
   <button className="primary">发起站群守恒复核</button>
  </form>}
  <section className="paper">
   <h2>守恒复核记录</h2>
   {data.length===0?<EmptyState text="导入权重与区域记录后发起复核。"/>:data.map(r=><article className={'record'+(active?.id===r.id?' selected-record':'')} key={r.id}>
    <div><b>{r.name}</b><small>{r.id} · 运行 {r.run_id}{r.status==='completed'?` · 调整单元 ${r.result.cell_count} · 硬约束 ${r.result.hard_constraint_count}`:''}</small></div>
    <div className="actions"><StatusBadge status={r.status}/><button onClick={()=>setSelected(r.id)}>查明细</button></div>
   </article>)}
  </section>
  {active&&<ConservationDetail review={active}/>}
 </>;
}

function ConservationDetail({review}:{review:ConservationReview}){
 if(review.status==='failed')return <section className="paper"><h2>复核被整次拒绝</h2><p className="reject-text">{review.error}</p><small>已有结果未被修改；请修正冲突约束后重新发起。</small></section>;
 if(review.status!=='completed'||!review.result)return <section className="paper"><h2>计算中</h2><p>独立 worker 正在做联合调整，每 3 秒自动刷新。</p></section>;
 const r=review.result;
 return <>
  <section className="paper">
   <h2>复核结论与约束对账</h2>
   <div className="gap-summary">
    <div><small>区域记录 / 参与调整</small><strong>{r.region_count}<em> / {r.effective_count}</em></strong></div>
    <div><small>硬约束 / 消冗 / 调整单元</small><strong>{r.hard_constraint_count}<em> / {r.redundant_times.length} / {r.cell_count}</em></strong></div>
    <div><small>未匹配 / 遮挡隔离</small><b>{r.unmatched_records.length} / {r.isolated_records.length}</b><span>异步不凑近 · 含遮挡真值整列隔离</span></div>
    <div><small>硬约束最大残差</small><strong>{decimal(r.max_hard_residual,6)}</strong><span>硬守恒精确满足时为 0</span></div>
   </div>
   <div className="table-scroll"><table>
    <thead><tr><th>时刻h</th><th>类型</th><th>区域均值</th><th>实测加权部分</th><th>缺失拟合部分</th><th>加权合计</th><th>残差</th><th>标准化残差z</th></tr></thead>
    <tbody>{r.reconciliation.map(x=><tr key={x.time_hour}>
     <td>{x.time_hour}</td><td>{x.is_hard?'硬守恒':'软约束'}</td><td>{decimal(x.region_mean,4)}</td>
     <td>{decimal(x.observed_part,4)}</td><td>{decimal(x.fitted_missing_part,4)}</td><td>{decimal(x.weighted_total,4)}</td>
     <td>{decimal(x.residual,6)}</td><td>{x.standardized_residual==null?'—':decimal(x.standardized_residual,3)}</td>
    </tr>)}</tbody>
   </table></div>
   {(r.unmatched_records.length>0||r.isolated_records.length>0||r.redundant_times.length>0)&&<div className="flag-grid">
    {r.unmatched_records.map(u=><p className="flag warn" key={'u'+u.time_hour}>未匹配 {u.time_hour}h：{u.reason}</p>)}
    {r.isolated_records.map(i=><p className="flag isolate" key={'i'+i.time_hour}>遮挡隔离 {i.time_hour}h：{i.reason}</p>)}
    {r.redundant_times.map(t=><p className="flag ok" key={'r'+t}>重复/线性相关约束 {t}h 已消冗，不改变解</p>)}
   </div>}
  </section>
  <section className="paper table-scroll">
   <h2>缺失单元：新区间与原单站对照</h2>
   <table>
    <thead><tr><th>测站</th><th>时刻h</th><th>原RTS单站均值</th><th>原PCHIP单站</th><th>原95%区间</th><th>联合调整均值</th><th>调整量Δ</th><th>新95%区间</th><th>方差缩减</th></tr></thead>
    <tbody>{r.cells.map((c,i)=><tr key={c.station+'-'+c.time_hour+'-'+i}>
     <td>{c.station}</td><td>{c.time_hour}</td><td>{decimal(c.prior_mean,4)}</td>
     <td>{c.pchip_single_station==null?'边缘不可估':decimal(c.pchip_single_station,4)}</td>
     <td>[{decimal(c.prior_low,3)}, {decimal(c.prior_high,3)}]</td>
     <td><b>{decimal(c.adjusted_mean,4)}</b></td><td>{decimal(c.delta,4)}</td>
     <td>[{decimal(c.adjusted_low,3)}, {decimal(c.adjusted_high,3)}]</td>
     <td>{decimal(c.variance_reduction,5)}</td>
    </tr>)}</tbody>
   </table>
    <small>仅原始缺失单元出现于此；实测值不进未知量、原样保留。新区间基于后验有噪观测方差（完整相关协方差约束GLS）。</small>
  </section>
  <aside className="method-note"><h3>假设与解释边界</h3>
   {r.notes.map(n=><p key={n}>{n}</p>)}
   <small>SHA256 {r.checksum}</small>
  </aside>
 </>;
}
