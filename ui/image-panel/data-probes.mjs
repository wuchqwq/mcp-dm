// Scientific readouts from the same saved provider arrays used by MCP. Canvas
// colors are never sampled and pointer motion creates no scientific records.
import {tabularCell} from './measurement-workspace.mjs';
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const componentNames={raw:'原始数值',real:'FFT 实部',imag:'FFT 虚部',amplitude:'FFT 幅值',power:'FFT 功率 |F|²'};
const numberText=value=>finite(value)?String(value):'未知';
const canonical=value=>JSON.stringify(value??null,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const same=(left,right)=>canonical(left)===canonical(right);
function objectBinding(state){return {object_id:state?.object?.object_id,state_revision:state?.state_revision};}
function sameBinding(state,binding){const now=objectBinding(state);return now.object_id===binding.object_id&&now.state_revision===binding.state_revision;}
export function probeText(result){
 const component=componentNames[result?.component]??'未知分量',sample=result?.samples?.[0];
 if(!sample)return '尚未读取原数组数值';
 const index=Array.isArray(sample.array_index_xy)?` · 原数组 [${sample.array_index_xy.join(', ')}]`:'';
 return `${component} ${numberText(sample.value)}${index} · 最近邻采样；数值单位未声明`;
}
export function statisticsText(result){
 const stats=result?.statistics;if(!stats)return '选择 ROI 后读取原数组统计';
 const roi=result.source_rect_xyxy??result.frequency_rect;
 return `${componentNames[result.component]??'未知分量'}${roi?' · 保存 ROI '+JSON.stringify(roi):''} · n=${numberText(stats.sample_count)} · 均值 ${numberText(stats.mean)} · 标准差 ${numberText(stats.stddev)} · 最小 ${numberText(stats.minimum)} · 最大 ${numberText(stats.maximum)} · 数值单位未声明`;
}
function profileData(result){
 const samples=result?.samples;
 if(result?.kind!=='profile'||!samples||!Array.isArray(samples.value)||samples.value.length<2||samples.value.length>4096||!Array.isArray(samples.distance)||samples.distance.length!==samples.value.length)throw new Error('剖面数值或采样数量不完整（允许 2–4096 点）');
 for(const key of ['coordinates_xy','indices_xy'])if(!Array.isArray(samples[key])||samples[key].length!==samples.value.length)throw new Error('剖面科学坐标与数值数量不一致');
 if(samples.physical_distance!==null&&samples.physical_distance!==undefined&&(!Array.isArray(samples.physical_distance)||samples.physical_distance.length!==samples.value.length||typeof result.physical_distance_unit!=='string'||!result.physical_distance_unit))throw new Error('物理剖面轴缺少完整标定或单位');
 return samples;
}
export function exportProfileCSV(result){
 const samples=profileData(result),columns=['sample','source_x','source_y','array_index_x','array_index_y','distance','distance_unit','physical_distance','physical_distance_unit','value','component','dtype','source_object_id','result_object_id','request_id','interpolation','line_width'];
 const rows=samples.value.map((value,index)=>[index,samples.coordinates_xy[index]?.[0],samples.coordinates_xy[index]?.[1],samples.indices_xy[index]?.[0],samples.indices_xy[index]?.[1],samples.distance[index],result.distance_unit,samples.physical_distance?.[index],result.physical_distance_unit,value,result.component,result.dtype,result.parent_object_id??result.source_object_id,result.object_id,result.request_id,result.sampling?.interpolation,result.sampling?.line_width]);
 return [columns,...rows].map(row=>row.map(value=>tabularCell(value)).join(',')).join('\r\n')+'\r\n';
}
// Plot positions are only presentation. Missing values split segments rather
// than being converted to zero or joined across an unmeasured interval.
export function profilePlot(result,{width=560,height=160}={}){
 const samples=profileData(result),physical=Array.isArray(samples.physical_distance),distance=physical?samples.physical_distance:samples.distance;
 const finitePairs=samples.value.map((value,index)=>[distance[index],value]).filter(([x,y])=>finite(x)&&finite(y));
 if(!finitePairs.length)return {segments:[],xLabel:physical?result.physical_distance_unit:result.distance_unit,yLabel:componentNames[result.component]??'数值',range:null};
 const xs=finitePairs.map(pair=>pair[0]),ys=finitePairs.map(pair=>pair[1]),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),left=48,right=12,top=12,bottom=30;
 let segment=[],segments=[];for(let index=0;index<samples.value.length;index++){const x=distance[index],y=samples.value[index];if(!finite(x)||!finite(y)){if(segment.length)segments.push(segment);segment=[];continue;}segment.push([left+(x-xmin)/(xmax-xmin||1)*(width-left-right),height-bottom-(y-ymin)/(ymax-ymin||1)*(height-top-bottom)]);}if(segment.length)segments.push(segment);
 return {segments,xLabel:physical?result.physical_distance_unit:result.distance_unit,yLabel:componentNames[result.component]??'数值',range:{xmin,xmax,ymin,ymax}};
}
export class DataProbes {
 constructor({getState,api,onError=()=>{},document:doc=globalThis.document,interval=125,setTimer=globalThis.setTimeout?.bind(globalThis),clearTimer=globalThis.clearTimeout?.bind(globalThis),now=()=>performance.now()}={}){
  if(!finite(interval)||interval<100||interval>1000)throw new Error('Scientific probe throttle must be 100–1000 ms');
  Object.assign(this,{getState,api,onError,document:doc,interval,setTimer,clearTimer,now});this.el=id=>doc?.getElementById(id);this.pending=null;this.inflight=false;this.timer=null;this.sequence=0;this.lastStart=-Infinity;this.lastSelection=null;this.currentBinding=null;this.statistics=null;this.profile=null;
  if(this.el('probe-component'))this.el('probe-component').onchange=()=>{this.sequence++;this.pending=null;this.setProbeText('分量已切换；等待原数组采样');if(this.lastSelection)this.observe(this.lastSelection);};
  if(this.el('profile-csv'))this.el('profile-csv').onclick=()=>{try{if(!this.profile)throw new Error('先保存一条剖面');const url=URL.createObjectURL(new Blob(['\uFEFF',exportProfileCSV(this.profile)],{type:'text/csv;charset=utf-8'})),anchor=this.document.createElement('a');anchor.href=url;anchor.download='mcp-dm-profile.csv';anchor.click();this.setTimer(()=>URL.revokeObjectURL(url),1000);}catch(error){this.onError(error);}};
 }
 component(){return this.el('probe-component')?.value||'raw';}
 setProbeText(text){if(this.el('probe-value'))this.el('probe-value').textContent=text;}
 clear(){this.sequence++;this.pending=null;this.lastSelection=null;if(this.timer!==null){this.clearTimer(this.timer);this.timer=null;}this.setProbeText('尚未读取原数组数值');}
 refreshCurrent(){
  const state=this.getState(),binding=objectBinding(state);if(this.currentBinding&&sameBinding(state,this.currentBinding))return false;
  this.clear();this.currentBinding=binding;
  const component=this.el('probe-component'),dtype=state?.object?.dtype,complex=typeof dtype==='string'&&dtype.startsWith('complex')||state?.object?.panels?.some(panel=>panel.domain==='frequency');
  if(component&&(typeof dtype==='string'||state?.object?.panels?.length)){if(complex&&component.value==='raw')component.value='amplitude';else if(!complex)component.value='raw';for(const option of component.options??[])option.disabled=complex?option.value==='raw':option.value!=='raw';}
  const grid=state?.object?.scientific_grid_identity;
  if(this.profile?.samples?.physical_distance&&!same(this.profile.xy_calibration,state?.object?.xy_calibration)){this.profile=null;this.el('profile-plot')?.replaceChildren();this.el('profile-values')?.replaceChildren();if(this.el('profile-summary'))this.el('profile-summary').textContent='标定已修订；旧剖面物理轴待重测，历史科学记录仍保留';}
  for(const kind of ['statistics','profile'])if(this[kind]&&(!grid||!same(this[kind].scientific_grid_identity,grid))){this[kind]=null;if(kind==='statistics'&&this.el('statistics-summary'))this.el('statistics-summary').textContent='当前对象已变化；之前的统计记录仍保存，请重新选择 ROI';if(kind==='profile'){this.el('profile-plot')?.replaceChildren();this.el('profile-values')?.replaceChildren();if(this.el('profile-summary'))this.el('profile-summary').textContent='当前对象已变化；之前的剖面记录仍保存';}}
  return true;
 }
 observe(selection){
  const binding=objectBinding(this.getState());if(!binding.object_id||!selection||!Array.isArray(selection.coordinates)||selection.coordinates.length!==2||!selection.coordinates.every(finite)||typeof selection.source_object_id!=='string'||!['source_pixels','source_array_indices','frequency_cycles_per_pixel'].includes(selection.coordinate_space))return false;
  const component=this.component();if(!(component in componentNames))return false;
  this.lastSelection={...selection,coordinates:[...selection.coordinates]};this.setProbeText(`${componentNames[component]} · 坐标 [${selection.coordinates.map(numberText).join(', ')}] · 等待原数组采样`);this.pending={binding,sequence:++this.sequence,component,selection:this.lastSelection};this.schedule();return true;
 }
 schedule(){if(this.inflight||this.timer!==null||!this.pending)return;const delay=Math.max(0,this.interval-(this.now()-this.lastStart));this.timer=this.setTimer(()=>{this.timer=null;void this.submit();},delay);}
 async submit(){
  if(this.inflight||!this.pending)return;const query=this.pending;this.pending=null;if(!sameBinding(this.getState(),query.binding))return;
  this.inflight=true;this.lastStart=this.now();
  try{const result=await this.api('/api/probe',{expected_object_id:query.binding.object_id,source_object_id:query.selection.source_object_id,coordinate_space:query.selection.coordinate_space,coordinates:query.selection.coordinates,component:query.component});
   if(query.sequence!==this.sequence||!sameBinding(this.getState(),query.binding)||this.component()!==query.component||result.object_id!==query.binding.object_id||result.component!==query.component||result.coordinate_space!==query.selection.coordinate_space||!same(result.samples?.[0]?.point,query.selection.coordinates))return;
   this.setProbeText(probeText(result));this.lastResult=result;
  }catch(error){if(query.sequence===this.sequence&&sameBinding(this.getState(),query.binding)){this.setProbeText('原数组读取未完成；未使用显示灰度替代');this.onError(error);}}
  finally{this.inflight=false;this.schedule();}
 }
 renderResult(result){
  const value=result?.last_operation??result;if(!value||!['statistics','profile'].includes(value.kind))return false;
  const state=this.getState(),grid=state?.object?.scientific_grid_identity;
  if(grid&&value.scientific_grid_identity&&!same(grid,value.scientific_grid_identity)){this.onError(new Error('数值结果属于另一科学网格；未投到当前图上'));return false;}
  if(!grid&&value.parent_object_id!==state?.object?.object_id&&value.source_object_id!==state?.object?.object_id){this.onError(new Error('缺少同一科学网格的结果绑定；请在当前对象重新读取'));return false;}
  if(value.kind==='statistics'){this.statistics=value;if(this.el('statistics-summary'))this.el('statistics-summary').textContent=statisticsText(value);return true;}
  try{profileData(value);if(value.samples.physical_distance&&!same(value.xy_calibration,state?.object?.xy_calibration))throw new Error('剖面物理轴属于旧标定版本；需在当前标定重新读取');this.profile=value;this.renderProfile();return true;}catch(error){this.onError(error);return false;}
 }
 renderProfile(){
  if(!this.profile)return;const result=this.profile,samples=profileData(result),body=this.el('profile-values'),plot=this.el('profile-plot');
  if(this.el('profile-summary'))this.el('profile-summary').textContent=`${samples.value.length} 点 · ${componentNames[result.component]??'未知分量'} · 最近邻 · 线宽 ${result.sampling?.line_width??'未知'} px · 距离 ${result.physical_distance_unit??result.distance_unit??'未知'} · 数值单位未声明${samples.value.length>200?'；表格显示前 200 点，CSV 包含全部采样':''}`;
  if(body&&this.document){body.replaceChildren();for(let index=0;index<Math.min(200,samples.value.length);index++){const row=this.document.createElement('tr');for(const value of [index,...samples.coordinates_xy[index],samples.physical_distance?.[index]??samples.distance[index],samples.value[index]]){const cell=this.document.createElement('td');cell.textContent=numberText(value);row.append(cell);}body.append(row);}}
  if(plot&&this.document){plot.replaceChildren();plot.setAttribute('viewBox','0 0 560 160');const model=profilePlot(result),create=(tag,attributes,text)=>{const element=this.document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attributes))element.setAttribute(key,value);if(text!==undefined)element.textContent=text;plot.append(element);};create('path',{d:'M48 12V130H548',fill:'none',stroke:'#6c8496','stroke-width':1});for(const segment of model.segments)create('polyline',{points:segment.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#6bd6df','stroke-width':1.5});create('text',{x:280,y:155,'text-anchor':'middle',fill:'#a8bfcb','font-size':10},model.xLabel??'未知距离单位');if(model.range){create('text',{x:44,y:18,'text-anchor':'end',fill:'#a8bfcb','font-size':9},String(Number(model.range.ymax.toPrecision(5))));create('text',{x:44,y:130,'text-anchor':'end',fill:'#a8bfcb','font-size':9},String(Number(model.range.ymin.toPrecision(5))));}}
 }
}
