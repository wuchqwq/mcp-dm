def probes(s):
    s=replace(s,"return `${component} ${numberText(sample.value)}${index} · 最近邻采样；数值单位未声明`;", "return `${component} ${numberText(sample.value)} · 坐标 [${(sample.point??[]).map(numberText).join(', ')}] ${result.coordinate_space==='frequency_cycles_per_pixel'?'cycles/pixel':'源数组坐标'}${index} · 最近邻；数值单位未声明`;")
    s=replace(s,'left=48,right=12,top=12,bottom=30;', 'left=64,right=20,top=22,bottom=42;')
    s=replace(s,"export function profilePlot(result,{width=560,height=160}={}){", "export function profilePlot(result,{width=560,height=200}={}){")
    pos=s.index('export class DataProbes')
    s=s[:pos]+r'''export function profileTicks(min,max,count=5){
 if(!finite(min)||!finite(max)||!Number.isInteger(count)||count<2||count>9)return [];
 if(min===max)return [min];return Array.from({length:count},(_,i)=>min+(max-min)*i/(count-1));
}
export function profileReadout(result,index){
 const samples=profileData(result);if(!Number.isInteger(index)||index<0||index>=samples.value.length)return null;
 return {index,x:samples.physical_distance?.[index]??samples.distance[index],unit:result.physical_distance_unit??result.distance_unit,
  value:samples.value[index],requested:samples.coordinates_xy[index],sampled:samples.sampled_coordinates_xy?.[index]??null,arrayIndex:samples.indices_xy[index],component:result.component};
}
export function nearestProfileSample(result,x){
 const s=profileData(result),xs=s.physical_distance??s.distance;if(!finite(x))return null;let best=null,delta=Infinity;
 for(let i=0;i<xs.length;i++){if(!finite(xs[i])||!finite(s.value[i]))continue;const d=Math.abs(xs[i]-x);if(d<delta){best=i;delta=d;}}return best;
}
''' + s[pos:]
    pos=s.index(' renderResult(result){')
    s=s[:pos]+r''' restoreSavedResults(results){
  const state=this.getState(),grid=state?.object?.scientific_grid_identity;
  for(const kind of ['statistics','profile']){const value=results?.[kind];if(!value)continue;
   const compatible=grid&&same(grid,value.scientific_grid_identity)||!grid&&value.parent_object_id===state?.object?.object_id;
   if(!compatible)continue;
   if(kind==='profile'&&value.samples?.physical_distance&&!same(value.xy_calibration,state?.object?.xy_calibration))continue;
   if(this[kind]?.object_id!==value.object_id)this.renderResult(value);
  }
 }
''' + s[pos:]
    start=s.index(' renderProfile(){')
    s=s[:start]+r''' renderProfile(){
  if(!this.profile)return;const result=this.profile,samples=profileData(result),body=this.el('profile-values'),plot=this.el('profile-plot');
  if(this.el('profile-summary'))this.el('profile-summary').textContent=`${samples.value.length} 点 · ${componentNames[result.component]??'未知分量'} · 最近邻 · 线宽 ${result.sampling?.line_width??'未知'} px · 距离 ${result.physical_distance_unit??result.distance_unit??'未知'} · 数值单位未声明${samples.value.length>200?'；表格显示前 200 点，CSV 包含全部采样':''}`;
  const rows=[];if(body&&this.document){body.replaceChildren();for(let i=0;i<Math.min(200,samples.value.length);i++){const row=this.document.createElement('tr');row.tabIndex=0;row.dataset.sampleIndex=String(i);for(const v of [i,...samples.coordinates_xy[i],samples.physical_distance?.[i]??samples.distance[i],samples.value[i]]){const cell=this.document.createElement('td');cell.textContent=numberText(v);row.append(cell);}body.append(row);rows.push(row);}}
  if(!plot||!this.document)return;plot.replaceChildren();plot.setAttribute('viewBox','0 0 560 200');plot.setAttribute('tabindex','0');plot.setAttribute('aria-label','已保存剖面；左右方向键读取原始采样值');
  const model=profilePlot(result),range=model.range,fmt=v=>finite(v)?String(Number(v.toPrecision(5))):'未知';
  const create=(tag,attributes,text)=>{const e=this.document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attributes))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;plot.append(e);return e;};
  create('path',{d:'M64 22V158H540',fill:'none',stroke:'#6c8496','stroke-width':1});
  const labelX=`距离 (${model.xLabel??'未知单位'})`,labelY=`${model.yLabel??'数值'}（单位未标定）`;
  create('text',{x:300,y:192,'text-anchor':'middle',fill:'#afc4ce','font-size':10},labelX);
  create('text',{x:64,y:12,fill:'#afc4ce','font-size':10},labelY);
  if(!range)return;
  const px=x=>64+(x-range.xmin)/(range.xmax-range.xmin||1)*476,py=y=>158-(y-range.ymin)/(range.ymax-range.ymin||1)*136;
  for(const x of profileTicks(range.xmin,range.xmax)){const p=px(x);create('line',{x1:p,x2:p,y1:158,y2:162,stroke:'#7894a3'});create('text',{x:p,y:176,'text-anchor':'middle',fill:'#afc4ce','font-size':10},fmt(x));}
  for(const y of profileTicks(range.ymin,range.ymax,4)){const p=py(y);create('line',{x1:60,x2:64,y1:p,y2:p,stroke:'#7894a3'});create('text',{x:57,y:p+3,'text-anchor':'end',fill:'#afc4ce','font-size':10},fmt(y));}
  for(const segment of model.segments)create('polyline',{points:segment.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#6bd6df','stroke-width':1.5});
  const cross=create('line',{x1:0,x2:0,y1:22,y2:158,stroke:'#c7d9df','stroke-dasharray':'3 3',visibility:'hidden'}),dot=create('circle',{r:3,fill:'#e8f5f7',visibility:'hidden'});let selected=0;
  const highlight=index=>{const r=profileReadout(result,index);if(!r)return;selected=index;for(let i=0;i<rows.length;i++)rows[i].setAttribute('aria-selected',String(i===index));
   if(finite(r.x)&&finite(r.value)){cross.setAttribute('x1',px(r.x));cross.setAttribute('x2',px(r.x));cross.setAttribute('visibility','visible');dot.setAttribute('cx',px(r.x));dot.setAttribute('cy',py(r.value));dot.setAttribute('visibility','visible');}else{cross.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');}
   if(this.el('profile-readout'))this.el('profile-readout').textContent=`采样 ${index} · 距离 ${numberText(r.x)} ${r.unit??''} · ${componentNames[r.component]??'数值'} ${numberText(r.value)} · 请求坐标 [${r.requested.join(', ')}] · 原数组索引 [${r.arrayIndex.join(', ')}]`;
  };
  plot.onpointermove=event=>{const box=plot.getBoundingClientRect();if(!box.width||!box.height)return;const scale=Math.min(box.width/560,box.height/200),offset=(box.width-560*scale)/2,x=(event.clientX-box.left-offset)/scale;if(x<64||x>540)return;const index=nearestProfileSample(result,range.xmin+(x-64)/476*(range.xmax-range.xmin));if(index!==null)highlight(index);};
  plot.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();highlight(event.key==='Home'?0:event.key==='End'?samples.value.length-1:Math.max(0,Math.min(samples.value.length-1,selected+(event.key==='ArrowRight'?1:-1))));}};
  rows.forEach((row,i)=>{row.onclick=()=>highlight(i);row.onfocus=()=>highlight(i);});highlight(0);
 }
}
'''
    return s
edit('ui/image-panel/data-probes.mjs',probes)
p=ROOT/'tests/image-panel-ui.test.mjs'
s=p.read_text(encoding='utf-8')+r'''

// Human workflow regressions: actual app handlers with this file's existing DOM/API shim.
function humanPointFixture(){const s=fixture();s.object.annotations=[{annotation_id:'human-A',kind:'point',text:'A',color:'cyan',status:'hypothesized',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates:[60,50]}}];return s;}
test('human workflow: choosing a mark never leaves a sticky edit mode; blank drag cannot move it',async()=>{
 const h=await harness(humanPointFixture());h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',40,38);await h.finish();
 assert.equal(h.$('mode').value,'select');const before=copy(h.server().object.annotations[0].anchor);
 h.event('pointerdown',90,70);h.event('pointermove',105,85);h.event('pointerup',105,85);await h.finish();
 assert.equal(h.inspect().draft.kind,'rectangle');assert.deepEqual(h.server().object.annotations[0].anchor,before);assert.equal(h.calls.filter(c=>c.action==='edit').length,0);
 h.event('pointerdown',100,75);h.event('pointerup',100,75);await h.finish();assert.equal(h.inspect().draft,null);
});
test('human workflow: undo newer Gamma before older science geometry; redo follows the same chronological order',async()=>{
 const h=await harness(humanPointFixture());h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',50,38);await h.finish();
 const moved=copy(h.server().object.annotations[0].anchor.coordinates);assert.deepEqual(moved,[70,50]);
 h.$('gamma').value='2';h.$('gamma').oninput();await h.click('undo');await h.finish();
 assert.equal(Number(h.$('gamma').value),1);assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,moved);
 await h.click('undo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[60,50]);
 await h.click('redo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,moved);
 await h.click('redo');assert.equal(Number(h.$('gamma').value),2);
});
test('human workflow: a newer marker move is undone before an earlier unsaved Gamma change',async()=>{
 const h=await harness(humanPointFixture());h.$('gamma').value='2';h.$('gamma').oninput();h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',50,38);await h.finish();
 await h.click('undo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[60,50]);assert.equal(Number(h.$('gamma').value),2);
 await h.click('undo');assert.equal(Number(h.$('gamma').value),1);
});
test('human workflow: a rectangle measurement is refused before creating a scientific mark',async()=>{
 const h=await harness();h.draw('rectangle');await h.click('measure');assert.equal(h.calls.length,0);assert.equal(h.server().object.annotations.length,0);assert.match(h.$('message').textContent,/线段|ROI/);
});
test('human workflow: saved-view back opens the stored object and never resubmits FFT',async()=>{
 const first=fixture(),h=await harness(first);h.draw('rectangle');const fft=copy(first);fft.object.object_id='c'.repeat(32);fft.object.kind='fft';fft.object.panels=[{domain:'frequency',source_object_id:'d'.repeat(32),fft_shape_yx:[96,128],image_rect_xyxy:[0,0,128,96]}];h.actionResult(fft);await h.click('fft');
 assert.equal(h.$('view-back').disabled,false);h.actionResult(first);await h.click('view-back');assert.equal(h.calls.at(-1).action,'show');assert.equal(h.calls.at(-1).params.object_id,viewId);assert.equal(h.calls.filter(c=>c.action==='fft').length,1);assert.equal(h.inspect().state.object.object_id,viewId);
});
test('human workflow: result tabs expose one result type without changing the scientific object',async()=>{
 const h=await harness();await h.click('results-tab-profile');assert.equal(h.$('results-profile').hidden,false);assert.equal(h.$('results-measurements').hidden,true);assert.equal(h.$('numeric-data').open,true);await h.click('results-tab-measurements');assert.equal(h.$('numeric-data').open,false);assert.equal(h.calls.length,0);
});
'''
p.write_text(s,encoding='utf-8')
