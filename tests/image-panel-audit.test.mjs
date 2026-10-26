// Independent real loopback HTTP tests with an explicit synthetic MCP client.
// These do not establish actual browser, worker, DM or scientific pixel qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createImagePanel} from '../tools/image_panel.mjs';
const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32);
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1kAAAAASUVORK5CYII=';
const panelMap={domain:'spatial_pixels',source_object_id:A,source_rect_xyxy:[0,0,128,96],image_rect_xyxy:[0,0,128,96]};
const object=id=>({object_id:id,kind:'view',panels:[panelMap],annotations:[],display:{gamma:1,display_range:[0,255]}});
async function fixture({deferB=false,hashMismatch=false}={}){
 const workspace=mkdtempSync(path.join(os.tmpdir(),'dm-independent-panel-')),calls=[];
 let release,accepted;
 const gate=new Promise(resolve=>{release=resolve;}),started=new Promise(resolve=>{accepted=resolve;});
 const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_preview','image_result'].map(name=>({name,inputSchema:{}}))}:{}};},
 async tool(name,args){calls.push({name,args});if(args.object_id===B&&deferB){accepted();await gate;}
  const data=object(args.object_id??C);
  if(hashMismatch&&args.object_id===A)data.files_sha256={'unannotated.png':'0'.repeat(64)};
  return {data,png};},async close(){}};
 if(hashMismatch){mkdirSync(path.join(workspace,'objects',A),{recursive:true});writeFileSync(path.join(workspace,'objects',A,'unannotated.png'),Buffer.from(png,'base64'));}
 let instance;
 try{instance=await createImagePanel({workspace,python:path.resolve('independent-not-executed-python.exe'),object_id:A,client,panel_id:C});}
 catch(e){rmSync(workspace,{recursive:true,force:true});throw e;}
 const origin=instance.url.split('/#')[0],headers={'X-Panel-Token':instance.token,Origin:origin,'Content-Type':'application/json'};
 const post=async(route,body)=>{const r=await fetch(origin+route,{method:'POST',headers,body:JSON.stringify(body)});return {status:r.status,value:await r.json()};};
 return {instance,workspace,headers,origin,calls,post,release,started,async close(){release();await instance.close();rmSync(workspace,{recursive:true,force:true});}};
}

test('independent server: browser draft arriving inside present preparation queues exact result and preserves prior view',async()=>{
 const f=await fixture({deferB:true});
 try{
  const original={object_id:B,expected_object_id:A,draft_revision:0,request_id:'audit-present'};
  const waiting=f.post('/api/present',original);await f.started;
  const draft=await f.post('/api/action',{expected_object_id:A,action:'draft',params:{draft_revision:1,dirty:true,gesture_active:true}});
  assert.equal(draft.status,200);assert.equal(draft.value.edit_state.gesture_active,true);
  f.release();const presented=await waiting;
  assert.equal(presented.status,200);assert.equal(presented.value.presentation.status,'queued');assert.equal(presented.value.object.object_id,A);assert.equal(presented.value.pending_result.object_id,B);
  const refused=await f.post('/api/action',{expected_object_id:A,action:'accept-result',params:{}});assert.equal(refused.status,409);
  await f.post('/api/action',{expected_object_id:A,action:'draft',params:{draft_revision:2,dirty:false,gesture_active:false}});
  const accepted=await f.post('/api/action',{expected_object_id:A,action:'accept-result',params:{}});assert.equal(accepted.value.object.object_id,B);
  const old=await fetch(f.origin+'/api/present?request_id=audit-present',{headers:f.headers});const receipt=await old.json();assert.equal(receipt.presentation.status,'queued');assert.equal(receipt.object.object_id,A);assert.equal(f.instance.state().object.object_id,B);
  const replay=await f.post('/api/present',original);assert.equal(replay.status,200);assert.equal(replay.value.presentation.status,'queued');assert.equal(f.calls.filter(c=>c.args.object_id===B).length,1);
 }finally{await f.close();}
});

test('independent server: clean PNG hash mismatch fails closed before returning a visible panel',async()=>{
 await assert.rejects(()=>fixture({hashMismatch:true}),/hash or format mismatch/);
});
