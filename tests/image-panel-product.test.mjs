// A real loopback panel with a controlled typed image client. These are
// gesture-handoff regressions, not worker, browser or scientific qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImagePanel} from '../tools/image_panel.mjs';

const A='a'.repeat(32),F='f'.repeat(32);
const grid={domain:'frequency',source_object_id:F,fft_shape_yx:[32,48],image_rect_xyxy:[0,0,192,128]};
const anchor=coordinates=>({coordinate_space:'frequency_cycles_per_pixel',source_object_id:F,coordinates});
async function fixture({deferred=false}={}){
 const workspace=mkdtempSync(path.join(tmpdir(),'dm-panel-product-')),calls=[],records=new Map();
 let next=0,release,enter;
 const entered=new Promise(resolve=>enter=resolve),gate=new Promise(resolve=>release=resolve);
 records.set(A,{object_id:A,kind:'annotation',panels:[grid],display:{gamma:1},annotations:[
  {annotation_id:'guide-a',kind:'arrow',status:'hypothesized',text:'candidate A',anchor:anchor([-.125,.125,.125,-.0625])},
  {annotation_id:'guide-b',kind:'point',status:'hypothesized',anchor:anchor([.25,.25])},
 ]});
 const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_annotate','image_measure'].map(name=>({name,inputSchema:{}}))}:{}};},
  async tool(name,args){
   calls.push({name,args:structuredClone(args)});
   if(name==='image_info')return {data:structuredClone(records.get(args.object_id)),png:'iVBORw0KGgo='};
   if(name==='image_annotate'){
    if(deferred){enter();await gate;}
    const data=structuredClone(records.get(args.object_id));
    data.object_id=(++next).toString(16).padStart(32,'0');data.parent_object_id=args.object_id;data.request_id=args.request_id;
    for(const update of args.updates){const mark=data.annotations.find(value=>value.annotation_id===update.annotation_id);for(const [key,value] of Object.entries(update)){if(key==='coordinates')mark.anchor.coordinates=value;else mark[key]=value;}}
    records.set(data.object_id,data);return {data,png:'iVBORw0KGgo='};
   }
   assert.equal(name,'image_measure');return {data:{object_id:'b'.repeat(32),kind:'measure',request_id:args.request_id,points:args.points,coordinate_space:args.coordinate_space}};
  },async close(){}};
 const panel=await createImagePanel({workspace,python:path.resolve('unused-python.exe'),object_id:A,client});
 const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
 const act=async(action,params={},revision=panel.state().edit_state.draft_revision)=>{
  const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:panel.state().object.object_id,draft_revision:revision,action,params})});
  const state=await response.json();assert.equal(response.status,200,JSON.stringify(state));return state;
 };
 return {workspace,panel,act,calls,records,entered,release,async close(){release();await panel.close();rmSync(workspace,{recursive:true,force:true});}};
}

test('saving one moved mark retains its exact scientific selection for continue and measurement',async()=>{
 const f=await fixture();try{
  const coordinates=[-.0625,.125,.1875,-.125];
  const state=await f.act('edit',{updates:[{annotation_id:'guide-a',coordinates,text:'moved candidate'}]});
  assert.deepEqual(state.last_operation.annotation_ids,['guide-a']);
  assert.deepEqual(state.selection,{kind:'arrow',...anchor(coordinates),panel:grid});
  assert.equal(state.object.annotations[0].status,'hypothesized');
  assert.deepEqual(state.object.annotations[1].anchor,anchor([.25,.25]));
  assert.equal(state.edit_state.dirty,false);assert.equal(state.edit_state.annotation_edit,null);
  const saved=JSON.parse(readFileSync(path.join(f.panel.journal,'current-selection.json')));
  assert.deepEqual(saved.selection,state.selection);assert.deepEqual(saved.last_operation.annotation_ids,['guide-a']);
  await f.act('measure',{selection:state.selection});
  const measured=f.calls.find(value=>value.name==='image_measure').args;
  assert.equal(measured.object_id,state.object.object_id);assert.equal(measured.coordinate_space,'frequency_cycles_per_pixel');
  assert.deepEqual(measured.points,[coordinates.slice(0,2),coordinates.slice(2)]);
  assert.equal(f.calls.filter(value=>value.name==='image_annotate').length,1);
 }finally{await f.close();}
});

test('a later draft keeps its own selection until the saved mark result is explicitly accepted',async()=>{
 const f=await fixture({deferred:true});try{
  const original={kind:'point',...anchor([.25,.25]),panel:grid};
  await f.act('select',{selection:original});
  const saving=f.act('edit',{updates:[{annotation_id:'guide-a',coordinates:[-.125,.0625,.125,-.125]}]},0);
  await f.entered;
  await f.act('draft',{draft_revision:1,dirty:true,gesture_active:false,selection:original});f.release();
  const pending=await saving;
  assert.equal(pending.object.object_id,A);assert.deepEqual(pending.selection,original);assert.equal(pending.edit_state.dirty,true);
  assert.equal(pending.last_operation.state,'completed_pending_view');assert.deepEqual(pending.last_operation.annotation_ids,['guide-a']);
  await f.act('draft',{draft_revision:2,dirty:false,gesture_active:false});
  const accepted=await f.act('accept-result');
  assert.deepEqual(accepted.last_operation.annotation_ids,['guide-a']);assert.equal(accepted.selection.kind,'arrow');
  assert.deepEqual(accepted.selection.coordinates,[-.125,.0625,.125,-.125]);assert.equal(accepted.selection.source_object_id,F);
 }finally{await f.close();}
});

test('withdrawn or outside-view marks are never substituted with another convenient current mark',async()=>{
 const f=await fixture();try{
  let state=await f.act('edit',{updates:[{annotation_id:'guide-a',status:'retracted'}]});
  assert.equal(state.selection,null);assert.deepEqual(state.last_operation.annotation_ids,['guide-a']);
  // This pre-existing scientific anchor is valid in a wider parent view, but
  // does not become a selectable point in this current frequency zoom.
  f.records.get(state.object.object_id).panels=[{...grid,fft_rect_xyxy:[24,16,36,24]}];
  state=await f.act('edit',{updates:[{annotation_id:'guide-a',status:'hypothesized',text:'still outside'}]});
  assert.equal(state.selection,null);assert.deepEqual(state.last_operation.annotation_ids,['guide-a']);
  assert.ok(state.object.annotations.some(value=>value.annotation_id==='guide-b'));
 }finally{await f.close();}
});
