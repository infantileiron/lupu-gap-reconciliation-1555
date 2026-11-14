import {useState} from 'react';import * as reviews from '../api/reviews';import * as reports from '../api/reports';import * as runs from '../api/runs';import * as conservation from '../api/conservation';import {download} from '../api/client';import {useResource} from '../hooks/useResource';import {refreshResources} from '../stores/resources';import PageTitle from '../components/common/PageTitle';import Notice from '../components/common/Notice';import StatusBadge from '../components/common/StatusBadge';import type {User} from '../types/entities';
export default function Archive({user}:{user:User}){
 const{data:rv,error}=useResource(reviews.list,[]),{data:rp}=useResource(reports.list,[]),{data:rr}=useResource(runs.list,[]),{data:cs}=useResource(conservation.list,[]);
 const[id,setId]=useState(sessionStorage.getItem('gap-selected-run')||'run-demo'),[comment,setComment]=useState(''),[message,setMessage]=useState(''),[picked,setPicked]=useState<Record<string,string>>({});
 const consFor=(runId:string)=>cs.filter(c=>c.run_id===runId&&c.status==='completed');
 return <><PageTitle chapter="07" title="把缺口处理，连同验证与守恒依据归档" description="分析员提交，缺测复核工程师复核。报告固定引用批准结果，可选附带同一运行的站群守恒复核，完整导出原始观测、缺口输出、方差、遮挡误差与区域残差对账。"/><Notice error={error||message}/>
 {user.role!=='viewer'&&<form className="paper form-grid" onSubmit={async e=>{e.preventDefault();try{await reviews.create({run_id:id,comment:comment||'已分开检查原始观测与区间口径、边缘留空与验证分母，请复核。'});refreshResources();setMessage('')}catch(e:any){setMessage(e.message)}}}>
  <label>完成的运行<select aria-label="完成的运行" value={id} onChange={e=>setId(e.target.value)}>{rr.filter(x=>x.status==='completed').map(x=><option key={x.id} value={x.id}>{x.id}</option>)}</select></label>
  <label>缺口说明<textarea value={comment} onChange={e=>setComment(e.target.value)} placeholder="已分开检查原始观测与区间口径、边缘留空与验证分母，请复核。"/></label><button className="primary">提交缺口复核</button>
 </form>}
 <section className="paper"><h2>缺口复核记录</h2>{rv.map(r=>{
   const options=consFor(r.run_id);const consId=picked[r.id]||'';
   return <article className="review-row" key={r.id}><StatusBadge status={r.status}/><div><b>{r.run_id}</b><p>{r.comment}</p><small>{r.reviewer||'等待缺测复核工程师复核'}</small></div>
   <div className="actions">{user.role==='admin'&&r.status==='pending'&&['approved','rejected'].map(status=><button key={status} onClick={async()=>{try{await reviews.decide(r.id,{status,comment:status==='approved'?'已核验无泄漏遮挡、区间口径与共有内点分母，批准归档。':'请补充长缺口与边缘不可估说明后重提。'});refreshResources()}catch(e:any){setMessage(e.message)}}}>{status==='approved'?'批准归档':'退回复查'}</button>)}
   {user.role!=='viewer'&&r.status==='approved'&&<button onClick={async()=>{try{await reports.create({title:'芦浦测站缺测离线复核报告',run_id:r.run_id,review_id:r.id,conservation_id:options.find(c=>c.id===consId)?.id||null});refreshResources()}catch(e:any){setMessage(e.message)}}}>生成归档报告</button>}
   {user.role!=='viewer'&&r.status==='approved'&&options.length>0&&<label className="inline-select">附带守恒复核<select aria-label="附带守恒复核" value={consId} onChange={e=>setPicked({...picked,[r.id]:e.target.value})}><option value="">不附带</option>{options.map(c=><option key={c.id} value={c.id}>{c.name}（{c.id}）</option>)}</select></label>}</div></article>;
 })}</section>
 <section className="paper"><h2>已批准报告</h2>{rp.map(r=><article className="record report-row" key={r.id}><div><b>{r.title}</b><small>{r.run_id}{r.conservation_id?' · 含站群守恒复核 '+r.conservation_id:''}</small></div><button onClick={()=>download('/reports/'+r.id+'/download','芦浦测站缺测.csv').catch(e=>setMessage(e.message))}>下载缺口证据 CSV ↓</button></article>)}</section></>;
}
