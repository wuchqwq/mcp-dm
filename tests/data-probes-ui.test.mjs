// Protocol/presentation tests. Source-array numerical kernels are tested by the
// provider; these tests never use Canvas grayscale as a scientific reference.
import test from 'node:test';
import assert from 'node:assert/strict';
import {DataProbes,probeText,statisticsText,exportProfileCSV,profilePlot} from '../ui/image-panel/data-probes.mjs';
const A='a'.repeat(32),B='b'.repeat(32),S='c'.repeat(32),grid={source_object_id:S,coordinate_space:'source_pixels',array_sha256:'same-array'};
const selection=x=>({source_object_id:S,coordinate_space:'source_pixels',coordinates:[x,4]});
function response(query,value=query.coordinates[0]){return {object_id:query.expected_object_id,kind:'probe',component:query.component,coordinate_space:query.coordinate_space,samples:[{point:query.coordinates,array_index_xy:query.coordinates,sampled_coordinate_xy:query.coordinates,value}]};}
function fixture(){
 let time=0,id=0,state={object:{object_id:A,dtype:'uint16',scientific_grid_identity:grid},state_revision:1};const timers=new Map(),calls=[],errors=[];
 const elements=new Map([['probe-value',{textContent:''}],['probe-component',{value:'raw',options:['raw','real','imag','amplitude','power'].map(value=>({value}))}],['statistics-summary',{textContent:''}],['profile-summary',{textContent:''}],['profile-readout',{textContent:''}],['profile-csv',{disabled:false}]]);
 const instance=new DataProbes({getState:()=>state,document:{getElementById:key=>elements.get(key)},onError:e=>errors.push(e),now:()=>time,setTimer:(fn,delay)=>{const ident=++id;timers.set(ident,{fn,due:time+delay});return ident;},clearTimer:ident=>timers.delete(ident),api:(url,body)=>new Promise((resolve,reject)=>calls.push({url,body,resolve,reject}))});
 return {instance,calls,errors,elements,get state(){return state;},setState:value=>{state=value;},async tick(delta=0){time+=delta;const due=[...timers].filter(([_id,value])=>value.due<=time);for(const [ident,value]of due){timers.delete(ident);value.fn();}for(let i=0;i<6;i++)await Promise.resolve();},async settle(){for(let i=0;i<6;i++)await Promise.resolve();},timers};
}
test('pointer queries coalesce to latest coordinate, throttle and keep at most one in flight',async()=>{
 const f=fixture();for(let x=0;x<30;x++)f.instance.observe(selection(x));assert.equal(f.calls.length,0);await f.tick();assert.equal(f.calls.length,1);assert.deepEqual(f.calls[0].body.coordinates,[29,4]);
 for(let x=30;x<60;x++)f.instance.observe(selection(x));await f.tick(1000);assert.equal(f.calls.length,1);
 f.calls[0].resolve(response(f.calls[0].body));await f.settle();assert.match(f.elements.get('probe-value').textContent,/等待原数组/);await f.tick();assert.equal(f.calls.length,2);assert.deepEqual(f.calls[1].body.coordinates,[59,4]);
 f.calls[1].resolve(response(f.calls[1].body,1234));await f.settle();assert.match(f.elements.get('probe-value').textContent,/原始数值 1234/);assert.match(f.elements.get('probe-value').textContent,/最近邻/);assert.equal(f.errors.length,0);
});
test('late responses from another frame, another state revision or wrong echoed coordinates never become the current value',async()=>{
 for(const change of ['frame','revision','coordinate']){const f=fixture();f.instance.observe(selection(8));await f.tick();if(change==='frame'){f.setState({object:{object_id:B,dtype:'uint16',scientific_grid_identity:{...grid,array_sha256:'another-array'}},state_revision:2});f.instance.refreshCurrent();}else if(change==='revision')f.setState({...f.state,state_revision:2});const value=response(f.calls[0].body,999);if(change==='coordinate')value.samples[0].point=[90,90];f.calls[0].resolve(value);await f.settle();assert.doesNotMatch(f.elements.get('probe-value').textContent,/999/);}
});
test('complex component choices are explicit and changing a component drops older responses',async()=>{
 const f=fixture();f.setState({object:{object_id:A,kind:'annotate',panels:[{domain:'frequency'}]},state_revision:1});f.instance.refreshCurrent();assert.equal(f.instance.component(),'amplitude');
 f.instance.observe({...selection(.125),coordinate_space:'frequency_cycles_per_pixel'});await f.tick();assert.equal(f.calls[0].body.component,'amplitude');f.elements.get('probe-component').value='imag';f.elements.get('probe-component').onchange();f.calls[0].resolve(response(f.calls[0].body,18));await f.settle();assert.doesNotMatch(f.elements.get('probe-value').textContent,/18/);await f.tick(125);assert.equal(f.calls[1].body.component,'imag');f.calls[1].resolve(response(f.calls[1].body,-2.5));await f.settle();assert.match(f.elements.get('probe-value').textContent,/FFT 虚部 -2.5/);
 f.setState({object:{object_id:B,dtype:'uint16',panels:[{domain:'spatial_pixels'}]},state_revision:2});f.instance.refreshCurrent();assert.equal(f.instance.component(),'raw');assert.equal(f.elements.get('probe-component').options.find(o=>o.value==='power').disabled,true);
});
test('clear cancels queued sampling; a failed backend read never substitutes preview brightness',async()=>{
 const f=fixture();f.instance.observe(selection(3));f.instance.clear();await f.tick();assert.equal(f.calls.length,0);f.instance.observe(selection(4));await f.tick();f.calls[0].reject(new Error('source unavailable'));await f.settle();assert.match(f.elements.get('probe-value').textContent,/未使用显示灰度替代/);assert.equal(f.errors.length,1);
});
function profile(overrides={}){return {object_id:B,parent_object_id:A,kind:'profile',component:'raw',dtype:'uint16',request_id:'profile-1',scientific_grid_identity:grid,samples:{coordinates_xy:[[0,4],[1,4],[2,4],[3,4]],indices_xy:[[0,4],[1,4],[2,4],[3,4]],distance:[0,1,2,3],value:[10,20,null,40],physical_distance:null},distance_unit:'pixel',physical_distance_unit:null,sampling:{interpolation:'nearest',line_width:1,sample_count:4},...overrides};}
test('profile CSV uses numerical backend samples, distinct units and complete provenance',()=>{
 const value=profile({dtype:'=not-a-unit',parent_object_id:'@source'}),csv=exportProfileCSV(value);assert.match(csv,/^sample,source_x,source_y/);assert.match(csv,/,0,pixel,,,10,raw,'=not-a-unit,'@source,/);assert.match(csv,/2,2,4,2,4,2,pixel,,,,raw,/);assert.match(csv,/profile-1,nearest,1/);assert.doesNotMatch(csv,/nm|electron/i);
 const physical=profile({samples:{...profile().samples,physical_distance:[0,.2,.4,.6]},physical_distance_unit:'nm'});assert.match(exportProfileCSV(physical),/,1,pixel,0.2,nm,20,/);
 assert.throws(()=>exportProfileCSV({...physical,physical_distance_unit:null}),/缺少完整标定/);
});
test('plot represents raw saved values and splits missing samples rather than inventing zeros',()=>{
 const model=profilePlot(profile());assert.deepEqual(model.segments.map(s=>s.length),[2,1]);assert.deepEqual(model.range,{xmin:0,xmax:3,ymin:10,ymax:40});assert.equal(model.xLabel,'pixel');assert.equal(model.yLabel,'原始数值');
 assert.match(statisticsText({component:'power',statistics:{sample_count:4,mean:12,stddev:3,minimum:2,maximum:18}}),/FFT 功率 \|F\|²/);assert.match(probeText({component:'real',samples:[{value:NaN}]}),/未知/);
});
test('saved statistics/profile cannot leak across scientific grids or silently keep an old physical scale',()=>{
 const f=fixture();assert.equal(f.instance.renderResult({kind:'statistics',parent_object_id:A,scientific_grid_identity:{...grid,array_sha256:'wrong'},statistics:{mean:100}}),false);assert.equal(f.instance.statistics,null);
 assert.equal(f.instance.renderResult({kind:'statistics',parent_object_id:A,scientific_grid_identity:grid,component:'raw',statistics:{sample_count:2,mean:3,stddev:1,minimum:2,maximum:4}}),true);assert.match(f.elements.get('statistics-summary').textContent,/均值 3/);
 const xy={calibration_id:'scale-1',revision:1};f.setState({...f.state,object:{...f.state.object,xy_calibration:xy}});const p=profile({xy_calibration:xy,samples:{...profile().samples,physical_distance:[0,.2,.4,.6]},physical_distance_unit:'nm'});assert.equal(f.instance.renderResult(p),true);
 f.setState({object:{...f.state.object,xy_calibration:{calibration_id:'scale-2',revision:2}},state_revision:2});f.instance.refreshCurrent();assert.equal(f.instance.profile,null);assert.match(f.elements.get('profile-summary').textContent,/旧剖面物理轴待重测/);assert.equal(f.instance.renderResult(p),false);
});

test('a validated same-array display revision retains saved raw statistics and unchanged profile values',()=>{
 const f=fixture(),p=profile();assert.equal(f.instance.renderResult(p),true);assert.equal(f.instance.renderResult({kind:'statistics',parent_object_id:A,scientific_grid_identity:grid,component:'raw',statistics:{sample_count:4,mean:22.5,stddev:11,minimum:10,maximum:40}}),true);
 const before=JSON.stringify(f.instance.profile.samples);f.setState({object:{object_id:B,dtype:'uint16',scientific_grid_identity:{...grid},display:{gamma:2}},state_revision:2});f.instance.refreshCurrent();assert.equal(JSON.stringify(f.instance.profile.samples),before);assert.equal(f.instance.statistics.statistics.mean,22.5);assert.equal(f.calls.length,0);
 f.setState({object:{object_id:B,dtype:'uint16'},state_revision:3});f.instance.refreshCurrent();assert.equal(f.instance.profile,null,'unknown grid cannot be assumed equal to the previous scientific array');
});

test('invalidated grid or calibration clears exact sample readout and its old plot handlers and disables export',()=>{
 for(const change of ['grid','calibration']){
  const f=fixture(),xy={calibration_id:'scale-1',revision:1};
  assert.equal(f.elements.get('profile-csv').disabled,true,'no profile is initially available to export');
  f.setState({...f.state,object:{...f.state.object,xy_calibration:xy}});
  const p=profile({xy_calibration:xy,samples:{...profile().samples,physical_distance:[0,.2,.4,.6]},physical_distance_unit:'nm'});
  assert.equal(f.instance.renderResult(p),true);assert.equal(f.elements.get('profile-csv').disabled,false);
  const readout=f.elements.get('profile-readout');readout.textContent='采样 1 · 距离 0.2 nm · 原始数值 20';
  const plot={children:['old curve'],onpointermove:()=>{readout.textContent='old nm';},onkeydown:()=>{readout.textContent='old nm';},replaceChildren(){this.children=[];}};
  const rows={children:['old sample'],replaceChildren(){this.children=[];}};f.elements.set('profile-plot',plot);f.elements.set('profile-values',rows);
  const object={...f.state.object,...(change==='grid'?{scientific_grid_identity:{...grid,array_sha256:'new-array'}}:{xy_calibration:{calibration_id:'scale-2',revision:2}})};
  f.setState({object,state_revision:2});f.instance.refreshCurrent();f.instance.restoreSavedResults({profile:p});
  assert.equal(f.instance.profile,null);assert.equal(readout.textContent,'');assert.deepEqual(plot.children,[]);assert.deepEqual(rows.children,[]);
  assert.equal(plot.onpointermove,null);assert.equal(plot.onkeydown,null);assert.equal(f.elements.get('profile-csv').disabled,true);
  assert.match(f.elements.get('profile-summary').textContent,change==='grid'?/当前对象已变化/:/旧剖面物理轴待重测/);
  assert.equal(f.calls.length,0,'invalidation and restore checks do not launch new science');
 }
});

test('default host timers retain their browser receiver',()=>{
 const set=globalThis.setTimeout,clear=globalThis.clearTimeout;let scheduled=0,cancelled=0;
 try{
  globalThis.setTimeout=function(){assert.equal(this,globalThis,'browser host timer receiver');scheduled++;return 77;};
  globalThis.clearTimeout=function(id){assert.equal(this,globalThis,'browser host clear receiver');assert.equal(id,77);cancelled++;};
  const value=new DataProbes({getState:()=>({object:{object_id:A},state_revision:1}),document:{getElementById:()=>null},api:()=>{throw new Error('Timer was not fired');}});
  value.observe(selection(1));value.clear();assert.equal(scheduled,1);assert.equal(cancelled,1);
 }finally{globalThis.setTimeout=set;globalThis.clearTimeout=clear;}
});
