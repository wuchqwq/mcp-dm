import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImagePanel} from '../tools/image_panel.mjs';

const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32),D='d'.repeat(32),F='f'.repeat(32);
const grid={domain:'spatial_pixels',source_object_id:F,source_rect_xyxy:[0,0,32,32],image_rect_xyxy:[0,0,32,32]};
const scientificGrid={source_grid_object_id:F,shape_yx:[32,32],array_sha256:'1'.repeat(64),coordinate_space:'source_pixels'};
const marks=['first','second'].map((annotation_id,index)=>({annotation_id,kind:'point',status:'hypothesized',color:'cyan',text:annotation_id,
 anchor:{coordinate_space:'source_pixels',source_object_id:F,coordinates:[5+index*5,5]}}));
const selected={kind:'point',coordinate_space:'source_pixels',source_object_id:F,coordinates:[10,6],panel:grid};
const clone=value=>structuredClone(value);

async function fixture(run,{declared,sourcePath='C:\\private\\sample.tiff',backend,holdEdit=false,foreignEdit=false}={}){
 const workspace=mkdtempSync(path.join(tmpdir(),'dm-draft-transport-'));let release,entered,editCount=0;
 const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve),calls=[];
 const frame={object_id:F,kind:'frame',...(backend?{upstream_backend:backend}:{frame_index:0,source_object_id:'e'.repeat(32),source_identity:{path:sourcePath}})};
 const base={kind:'view',parent_object_id:F,panels:[grid],scientific_grid_identity:scientificGrid,shape_yx:[32,32],display:{gamma:1},annotations:marks,
  ...(declared?{user_context:{data_meaning:declared}}:{})};
 const records=new Map([[A,{...base,object_id:A}],[C,{...base,object_id:C}],[F,frame]]);
 const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_annotate'].map(name=>({name,inputSchema:{}}))}:{}};},
  async tool(name,args){calls.push({name,args:clone(args)});if(name==='image_info')return {data:clone(records.get(args.object_id)),png:'iVBORw0KGgo='};
   assert.equal(name,'image_annotate');if(holdEdit&&editCount===0){entered();await gate;}
   const id=editCount++===0?B:D,data={...clone(base),object_id:id,parent_object_id:args.object_id,kind:'annotate',request_id:args.request_id};
   if(foreignEdit)data.panels=[{...grid,source_rect_xyxy:[0,0,16,16]}];
   records.set(id,data);return {data,png:'iVBORw0KGgo='};
  },async close(){}};
 const panel=await createImagePanel({workspace,python:path.resolve('unused-python'),object_id:A,client});
 const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
 const post=async(route,body)=>{const response=await fetch(origin+route,{method:'POST',headers,body:JSON.stringify(body)});return {status:response.status,raw:await response.text()};};
 const act=async(action,params={},extra={})=>{const response=await post('/api/action',{expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params,...extra});return {...response,data:JSON.parse(response.raw)};};
 const saved=()=>JSON.parse(readFileSync(path.join(panel.journal,'current-selection.json'),'utf8'));
 let closed=false;const close=async()=>{if(!closed){closed=true;await panel.close();}};
 try{await run({panel,act,post,saved,calls,release,started,close});}finally{release();await close();rmSync(workspace,{recursive:true,force:true});}
}

test('lightweight draft acknowledgment omits scientific images and catalog while legacy reply is unchanged',async()=>fixture(async({act,panel})=>{
 const reply=await act('draft',{draft_revision:1,dirty:true,gesture_active:true,selection:selected},{lightweight:true});
 assert.equal(reply.status,200);assert.equal(reply.data.object_id,A);assert.deepEqual(reply.data.selection,selected);
 for(const name of ['object','png_base64','clean_png_base64','tools'])assert.equal(reply.data[name],undefined);
 assert.ok(reply.raw.length<JSON.stringify(panel.state()).length);
 const old=await act('draft',{draft_revision:2,dirty:false,gesture_active:false});
 assert.equal(old.data.object.object_id,A);assert.ok(old.data.tools);assert.ok(old.data.png_base64);
 assert.equal((await act('select',{selection:selected},{lightweight:true})).status,400);
 assert.equal((await act('draft',{draft_revision:3,dirty:false,gesture_active:false},{lightweight:'yes'})).status,400);
}));

test('intermediate snapshots coalesce but gesture transitions publish the latest durable handoff',async()=>fixture(async({act,saved,panel})=>{
 await act('draft',{draft_revision:1,dirty:true,gesture_active:true},{lightweight:true});
 assert.equal(saved().edit_state.draft_revision,1);
 for(let revision=2;revision<=9;revision++)await act('draft',{draft_revision:revision,dirty:true,gesture_active:true},{lightweight:true});
 assert.equal(panel.state().edit_state.draft_revision,9);assert.equal(saved().edit_state.draft_revision,1);
 assert.equal(panel.state().draft_persistence.pending,true);
 await act('draft',{draft_revision:10,dirty:true,gesture_active:false,selection:selected},{lightweight:true});
 assert.equal(saved().edit_state.draft_revision,10);assert.deepEqual(saved().selection,selected);
 assert.equal(panel.state().draft_persistence.pending,false);
 await act('draft',{draft_revision:11,dirty:true,gesture_active:false},{lightweight:true});
 await new Promise(resolve=>setTimeout(resolve,140));
 assert.equal(saved().edit_state.draft_revision,11);assert.equal(panel.state().draft_persistence.pending,false);
}));

test('source label uses explicit declaration or fixed provenance and never the filename as a synthetic claim',async()=>{
 await fixture(async({panel})=>assert.deepEqual(panel.state().source_identity,{kind:'synthetic',label:'合成演示',basis:'explicit user_context.data_meaning statement'}),{declared:'synthetic_demo'});
 await fixture(async({panel})=>{const source=panel.state().source_identity;assert.equal(source.kind,'tiff');assert.equal(source.filename,'synthetic-looking-file.tiff');assert.ok(!JSON.stringify(source).includes('private'));},{sourcePath:'C:\\private\\synthetic-looking-file.tiff'});
 await fixture(async({panel})=>assert.equal(panel.state().source_identity.kind,'dm_capture'),{backend:'digitalmicrograph-native'});
 await fixture(async({panel})=>assert.equal(panel.state().source_identity.kind,'dm_capture'),{backend:'saved digitalmicrograph-native READ numeric snapshot'});
 await fixture(async({panel})=>assert.equal(panel.state().source_identity.kind,'unknown'),{backend:'external-provider-unidentified'});
});

test('normal helper closure flushes a pending latest draft snapshot and clears its timer',async()=>fixture(async({act,saved,panel,close})=>{
 await act('draft',{draft_revision:1,dirty:true,gesture_active:false},{lightweight:true});
 await act('draft',{draft_revision:2,dirty:true,gesture_active:false},{lightweight:true});
 assert.equal(panel.state().draft_persistence.pending,true);assert.equal(saved().edit_state.draft_revision,1);
 await close();assert.equal(saved().edit_state.draft_revision,2);assert.equal(panel.state().draft_persistence.pending,false);
}));

test('automatic same-grid edit adoption preserves newer active draft and pending Agent result',async()=>fixture(async({act,post,panel,started,release,calls})=>{
 await act('draft',{draft_revision:1,dirty:true,gesture_active:false},{lightweight:true});
 const agent=await post('/api/present',{object_id:C,expected_object_id:A,draft_revision:1,request_id:'saved-agent-result'});
 assert.equal(JSON.parse(agent.raw).presentation.status,'queued');
 const save=act('edit',{updates:[{annotation_id:'first',coordinates:[6,5]}],auto_commit:true});await started;
 await act('draft',{draft_revision:2,dirty:true,gesture_active:true,selection:selected,annotation_edit:{annotation_id:'second',coordinates:[10,6]}},{lightweight:true});
 release();const reply=await save;assert.equal(reply.status,200);assert.equal(reply.data.auto_edit_committed,true);
 assert.equal(reply.data.object.object_id,B);assert.equal(reply.data.edit_state.base_object_id,B);
 assert.equal(reply.data.edit_state.draft_revision,2);assert.equal(reply.data.edit_state.gesture_active,true);
 assert.deepEqual(reply.data.edit_state.annotation_edit.coordinates,[10,6]);assert.deepEqual(reply.data.selection,selected);
 assert.equal(reply.data.pending_result.object_id,C);
 const next=await act('edit',{updates:[{annotation_id:'second',coordinates:[10,6]}],auto_commit:true});
 assert.equal(next.data.object.object_id,D);assert.equal(panel.state().pending_result.object_id,C);
 assert.equal(calls.filter(call=>call.name==='image_annotate').at(-1).args.object_id,B);
},{holdEdit:true}));

test('automatic adoption refuses a changed render window rather than rebasing unrelated geometry',async()=>fixture(async({act,panel})=>{
 const reply=await act('edit',{updates:[{annotation_id:'first',coordinates:[6,5]}],auto_commit:true});
 assert.equal(reply.status,409);assert.equal(panel.state().object.object_id,A);
 assert.match(reply.data.error,/same scientific grid/);
},{foreignEdit:true}));
