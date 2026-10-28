// Actual loopback action routing with a typed controlled image client. These
// tests do not claim a human clicked, a browser rendered, or DM was involved.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImagePanel} from '../tools/image_panel.mjs';

const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32);
const grid={domain:'source_array_indices',source_object_id:A,source_rect_xyxy:[0,0,32,32],image_rect_xyxy:[0,0,32,32]};
const selected={kind:'point',coordinate_space:'source_array_indices',source_object_id:A,coordinates:[7,12],panel:grid};
const statement={source_text:'这里存在孪晶；具体关系请继续检验。',authority:'synthetic_fixture'};

async function fixture(fn,{deferred=false}={}){
 const workspace=mkdtempSync(path.join(tmpdir(),'dm-panel-feedback-')),journal=path.join(workspace,'panel-journal'),calls=[],records=new Map(),results=new Map();
 let release,entered;
 const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve);
 records.set(A,{object_id:A,kind:'view',panels:[grid],annotations:[],display:{gamma:1}});
 records.set(B,{object_id:B,kind:'view',panels:[{...grid,source_object_id:B}],annotations:[],display:{gamma:1}});
 const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_context','image_result'].map(name=>({name,inputSchema:{}}))}:{}};},
  async tool(name,args){
   calls.push({name,args:structuredClone(args)});
   if(name==='image_info')return {data:structuredClone(records.get(args.object_id)),png:'iVBORw0KGgo='};
   if(name==='image_result')return {data:structuredClone(results.get(args.request_id))};
   assert.equal(name,'image_context');
   const intent=JSON.parse(readFileSync(path.join(journal,args.request_id+'.request.json')));
   assert.equal(intent.name,'image_context');assert.deepEqual(intent.arguments,args);
   if(deferred){entered();await gate;}
   const data={object_id:C,kind:'context',request_id:args.request_id,parent_object_id:args.object_id,
    user_context:structuredClone(args.metadata),research_observation_scope:{confirmation_scope:'twinning_present_only',source_object_id:args.object_id,scientific_grid_identity:{source_object_id:A}}};
   records.set(C,data);results.set(args.request_id,data);return {data};
  },async close(){}};
 const panel=await createImagePanel({workspace,python:path.resolve('unused-python.exe'),object_id:A,client,journalDirectory:journal}),origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
 const post=async(route,body)=>{const response=await fetch(origin+route,{method:'POST',headers,body:JSON.stringify(body)});return {status:response.status,data:await response.json()};};
 const act=(action,params={},extra={})=>post('/api/action',{expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params,...extra});
 try{await fn({panel,post,act,calls,started,release,journal});}finally{release();await panel.close();rmSync(workspace,{recursive:true,force:true});}
}

test('scoped observation journals the existing context tool and preserves selected image, drafts and peak authority',async()=>fixture(async({panel,act,calls,journal})=>{
 await act('draft',{draft_revision:3,dirty:true,gesture_active:false,selection:selected});
 const before=panel.state(),response=await act('research-observation',statement);
 assert.equal(response.status,200);const after=response.data;
 assert.equal(after.object.object_id,A);assert.equal(after.png_base64,before.png_base64);
 assert.deepEqual(after.selection,selected);assert.deepEqual(after.edit_state,before.edit_state);
 assert.equal(after.research_observation.object_id,C);assert.equal(after.research_observation.authority,'synthetic_fixture');
 assert.equal(after.research_observation.base_object_id,A);assert.equal(after.research_observation.scope.confirmation_scope,'twinning_present_only');
 assert.equal(after.research_observation.current_view_relation,'same_saved_view');
 assert.deepEqual(calls.find(call=>call.name==='image_context').args.metadata,{research_observation:{kind:'twinning_present',...statement}});
 assert.equal(calls.filter(call=>call.name==='image_context').length,1);
 const saved=JSON.parse(readFileSync(path.join(journal,'current-selection.json')));
 assert.deepEqual(saved.research_observation,after.research_observation);
 assert.equal(saved.object_id,A);assert.deepEqual(saved.edit_state,before.edit_state);
 assert.equal(readdirSync(journal).filter(name=>name.endsWith('.request.json')).length,1);
}));

test('wrong view, forged HKL confirmation, unsupported authority and empty observation are refused before tool writes',async()=>fixture(async({act,calls})=>{
 for(const [params,extra] of [[statement,{expected_object_id:B}],[{...statement,confirmation_scope:'all_hkl'},{}],
  [{...statement,authority:'agent_hypothesis'},{}],[{...statement,source_text:'   '},{}]]){
  assert.ok((await act('research-observation',params,extra)).status>=400);
 }
 assert.equal(calls.filter(call=>call.name==='image_context').length,0);
}));

test('new draft arriving during observation persistence survives and same-ID recovery does not render or write another context',async()=>fixture(async({panel,act,calls,started,release})=>{
 const waiting=act('research-observation',statement);await started;
 assert.equal((await act('draft',{draft_revision:8,dirty:true,gesture_active:false,selection:selected})).status,200);
 release();assert.equal((await waiting).status,200);
 const after=panel.state();assert.equal(after.object.object_id,A);assert.equal(after.edit_state.draft_revision,8);assert.equal(after.edit_state.dirty,true);
 assert.equal((await act('recover')).status,200);
 assert.equal(panel.state().object.object_id,A);assert.equal(panel.state().edit_state.draft_revision,8);
 assert.equal(calls.filter(call=>call.name==='image_context').length,1);assert.equal(calls.filter(call=>call.name==='image_result').length,1);
},{deferred:true}));

test('switching results retains the original observation binding as historical instead of confirming another image',async()=>fixture(async({panel,act,post})=>{
 await act('research-observation',{...statement,authority:'user_confirmed'});
 const shown=await post('/api/present',{object_id:B,expected_object_id:A,draft_revision:0,request_id:'show-new-result'});
 assert.equal(shown.status,200);assert.equal(shown.data.presentation.status,'shown');
 const after=panel.state();assert.equal(after.object.object_id,B);assert.equal(after.research_observation.base_object_id,A);
 assert.equal(after.research_observation.current_view_relation,'different_saved_view_review_scope');
 assert.equal(after.research_observation.authority,'user_confirmed');assert.equal(after.research_observation.scope.source_object_id,A);
}));
