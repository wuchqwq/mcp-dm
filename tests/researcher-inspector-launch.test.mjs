import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {parseResearcherArgs,startResearcherInspector} from '../tools/researcher_inspector.mjs';

function fixture(){
 const root=mkdtempSync(path.join(os.tmpdir(),'microscopy-inspector-launch-')),workspace=path.join(root,'workspace'),python=path.join(root,'python'),source=path.join(root,'source.tiff');
 writeFileSync(python,'not-executed');writeFileSync(source,'transport-fixture-not-decoded');
 const calls=[],records=new Map(),ids={image_open:'a'.repeat(32),image_frame:'b'.repeat(32),image_preview:'c'.repeat(32)},clients=[];let failPreview=false;
 const createClient=()=>{const client={closed:false,async rpc(method){assert.equal(method,'initialize');return {result:{}};},async tool(name,args){
  calls.push({name,args});
  if(name==='image_result'){const prior=records.get(args.request_id);if(!prior)throw new Error('Saved request unresolved');return {data:prior};}
  if(name==='image_info')return {data:{object_id:args.object_id,kind:'annotated'}};
  const durable=readdirSync(path.join(workspace,'researcher-inspector','startup')).filter(n=>n.endsWith('.request.json')).map(n=>JSON.parse(readFileSync(path.join(workspace,'researcher-inspector','startup',n))));
  assert.ok(durable.some(item=>item.name===name&&item.arguments.request_id===args.request_id),'request exists before dispatch');
  const data={object_id:ids[name],request_id:args.request_id};records.set(args.request_id,data);
  if(failPreview&&name==='image_preview')throw new Error('Connection lost after operation');
  return {data};
 },async close(){client.closed=true;}};clients.push(client);return client;};
 const opened=[];const openPanel=async args=>{opened.push(args);assert.ok(readFileSync(path.join(args.journalDirectory,'..','run.json')),'run binding exists before panel');mkdirSync(args.journalDirectory,{recursive:true});writeFileSync(path.join(args.journalDirectory,'current-selection.json'),JSON.stringify({object_id:args.object_id,edit_state:{dirty:false}}));return {url:'http://127.0.0.1:12345/#private-test-token',async close(){}};};
 return {root,workspace,python,source,calls,records,clients,opened,options:{workspace,python,source,frame:2},deps:{createClient,openPanel},set failPreview(v){failPreview=v;},close(){rmSync(root,{recursive:true,force:true});}};
}

test('researcher entry accepts source and human frame without IDs, rejects ambiguous arguments',()=>{
 const args=['--source',path.resolve('source.tiff'),'--workspace',path.resolve('output'),'--python',path.resolve('python'),'--frame','2'];
 assert.equal(parseResearcherArgs(args).frame,2);
 for(const extra of [['--frame','0'],['--frame','1.5'],['--object','a'.repeat(32)],['--workspace','relative']])assert.throws(()=>parseResearcherArgs([...args,...extra]));
});

test('researcher entry journals real tool calls, binds local TIFF and reopens last saved object without recomputation',async()=>{
 const f=fixture();try{
  const first=await startResearcherInspector(f.options,f.deps);assert.equal(first.resumed,false);assert.deepEqual(f.calls.map(c=>c.name),['image_open','image_frame','image_preview']);assert.equal(f.calls[1].args.frame_index,1);assert.ok(f.clients[0].closed);
  const edited='d'.repeat(32);writeFileSync(path.join(f.opened[0].journalDirectory,'current-selection.json'),JSON.stringify({object_id:edited,edit_state:{dirty:true}}));await first.close();f.calls.length=0;
  const reopened=await startResearcherInspector({workspace:f.workspace,python:f.python},f.deps);assert.equal(reopened.resumed,true);assert.equal(reopened.previous_unsaved_draft,true);assert.deepEqual(f.calls,[{name:'image_info',args:{object_id:edited}}]);assert.equal(f.opened[1].object_id,edited);assert.notEqual(f.opened[0].journalDirectory,f.opened[1].journalDirectory);await reopened.close();
 }finally{f.close();}
});

test('accepted startup with lost response only queries original IDs; no automatic write replay',async()=>{
 const f=fixture();try{
  f.failPreview=true;await assert.rejects(startResearcherInspector(f.options,f.deps),/Connection lost/);assert.equal(f.opened.length,0);f.calls.length=0;f.failPreview=false;
  const resumed=await startResearcherInspector(f.options,f.deps);assert.deepEqual(f.calls.map(c=>c.name),['image_result','image_result','image_result']);assert.equal(f.opened.length,1);await resumed.close();
 }finally{f.close();}
});

test('source conflicts and escaped resume records fail before starting a new panel',async()=>{
 const f=fixture();try{
  const first=await startResearcherInspector(f.options,f.deps);await first.close();const other=path.join(f.root,'other.tiff');writeFileSync(other,'different');
  await assert.rejects(startResearcherInspector({...f.options,source:other},f.deps),/different TIFF/);assert.equal(f.opened.length,1);
  const pointer=path.join(f.workspace,'researcher-inspector','latest-panel.json'),saved=JSON.parse(readFileSync(pointer));saved.run_id='../../foreign';writeFileSync(pointer,JSON.stringify(saved));
  await assert.rejects(startResearcherInspector({workspace:f.workspace,python:f.python},f.deps),/binding is invalid/);assert.equal(f.opened.length,1);
 }finally{f.close();}
});

test('actual no-model entry and reopen use existing stdio MCP / Python records and preserve input',{skip:process.env.DM_RESEARCHER_ENTRY_REAL_TEST!=='1'},async()=>{
 const root=mkdtempSync(path.join(os.tmpdir(),'researcher-inspector-real-')),source=path.join(root,'synthetic.tiff'),workspace=path.join(root,'workspace');let first,reopened;
 try{
  const command=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python';
  const setup=spawnSync(command,['-c',"import sys,numpy as np,tifffile; print(sys.executable); a=np.arange(32*48,dtype=np.uint16).reshape(32,48); tifffile.imwrite(sys.argv[1],np.stack([a,a+7]),photometric='minisblack',metadata=None)",source],{encoding:'utf8'});assert.equal(setup.status,0,setup.stderr);const python=setup.stdout.trim(),input=readFileSync(source);
  first=await startResearcherInspector({workspace,python,source,frame:2});const savedId=first.panel.state().object.object_id;
  assert.equal(first.panel.state().frame_identity.frame_index,1);
  const origin=first.panel.url.split('/#')[0],response=await fetch(origin+'/api/state',{headers:{'X-Panel-Token':first.panel.token}});assert.equal(response.status,200);const state=await response.json();assert.equal(state.object.object_id,savedId);assert.ok(state.png_base64.length>0,'actual backend returns PNG');
  await first.close();first=null;const before=readdirSync(path.join(workspace,'objects')).sort();
  reopened=await startResearcherInspector({workspace,python});assert.equal(reopened.panel.state().object.object_id,savedId);assert.deepEqual(readdirSync(path.join(workspace,'objects')).sort(),before,'reopening saved result does not create another frame/view');assert.deepEqual(readFileSync(source),input);
 }finally{await first?.close();await reopened?.close();rmSync(root,{recursive:true,force:true});}
});
