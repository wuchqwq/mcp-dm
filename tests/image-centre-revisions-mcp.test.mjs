// Actual stdio MCP + external image worker. Protocol fixtures are not real DM.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,writeFileSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {imageMetadata,readFixture} from './fixtures/native-operations.mjs';
import {handoff} from '../tools/native_snapshot_handoff.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const hash=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
function fixture(directory){
 const source=imageMetadata(77,{shape:[16,24]});
 Object.assign(source.calibration[0],{origin:6,scale:-.25,calibrated_value_at_pixel_zero:1.5,unit:'1/nm'});
 Object.assign(source.calibration[1],{origin:5,scale:.5,calibrated_value_at_pixel_zero:-2.5,unit:'1/nm'});
 const args=[77,0,0,24,16],read=readFixture(args,{source}),native_receipt={protocol:'NB2',session:'a'.repeat(32),id:'centre-source',request_id:'centre-source',state:'completed',host_pid:1234,worker_tid:20,exec_tid:10,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
 const snapshot=path.join(directory,'snapshot.json');writeFileSync(snapshot,JSON.stringify({...read,native_receipt}));
 return handoff({workspace:directory,output:'capture',requestId:'encode-centre-fixture',snapshot}).capture_path??path.join(directory,'capture');
}
function client(workspace){
 const child=spawn(process.execPath,[path.join(root,'server.mjs')],{env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python},stdio:['pipe','pipe','pipe'],windowsHide:true});
 let next=1,buffer='',stderr='';const pending=new Map();child.stderr.on('data',v=>stderr+=v);child.stdin.on('error',()=>{});
 child.stdout.on('data',v=>{buffer+=v;let end;while((end=buffer.indexOf('\n'))>=0){const row=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);const w=pending.get(row.id);if(w){pending.delete(row.id);clearTimeout(w.timer);w.resolve(row);}}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=next++,timer=setTimeout(()=>{pending.delete(id);reject(Error(stderr||'MCP timeout'));},30000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 return {rpc,tool:(name,args)=>rpc('tools/call',{name,arguments:args}),async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
function value(row){assert.equal(row.error,undefined,JSON.stringify(row));assert.notEqual(row.result.isError,true,JSON.stringify(row.result));return JSON.parse(row.result.content.find(c=>c.type==='text').text);}

test('typed centre/reuse tools reject missing original IDs before the external worker',async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'centre-schema-')),workspace=path.join(directory,'workspace'),c=client(workspace);
 try{
  const catalog=(await c.rpc('tools/list')).result.tools;
  for(const name of ['image_center','image_remeasure'])assert.ok(catalog.find(t=>t.name===name));
  assert.equal((await c.tool('image_center',{object_id:'a'.repeat(32),center_xy:[1,1],coordinate_space:'source_array_indices',source_text:'missing ID'})).error.code,-32602);
  assert.equal((await c.tool('image_remeasure',{object_id:'a'.repeat(32),measurement_object_id:'b'.repeat(32)})).error.code,-32602);
  assert.equal(existsSync(workspace),false);
 }finally{await c.close();rmSync(directory,{recursive:true,force:true});}
});

test('MCP centre→same saved peaks→scale revision→view/export→fresh-client original recovery keeps exact source',async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'centre-mcp-')),input=fixture(directory),workspace=path.join(directory,'workspace');let c=client(workspace);
 try{
  const original=hash(path.join(input,'input.npy'));
  const frame=value(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'open-centre'}));
  const old=value(await c.tool('image_measure',{object_id:frame.object_id,points:[[6,5],[10,7]],request_id:'original-peaks'}));
  const centre=value(await c.tool('image_center',{object_id:frame.object_id,center_xy:[7,4],coordinate_space:'source_array_indices',source_text:'Synthetic explicit corrected centre',request_id:'correct-centre'}));
  const measured=value(await c.tool('image_remeasure',{object_id:centre.object_id,measurement_object_id:old.object_id,request_id:'reused-peaks'}));
  assert.deepEqual(measured.points,[[7,4],[10,7]]);assert.deepEqual(measured.physical_vector_xy,[-.75,1.5]);
  assert.ok(Math.abs(measured.d_spacing-1/Math.sqrt(2.8125))<1e-14);
  assert.equal(measured.remeasurement.dc_endpoint_updated,true);assert.equal(measured.remeasurement.previous_manifest_sha256,hash(old.manifest_path));
  const scaled=value(await c.tool('image_calibrate',{object_id:centre.object_id,scope:'image',xy_scale:{x:-.5,y:.5,unit:'1/nm'},source_text:'Synthetic independently corrected scale',request_id:'correct-scale'}));
  const updated=value(await c.tool('image_remeasure',{object_id:scaled.object_id,measurement_object_id:measured.object_id,request_id:'updated-scale-measure'}));
  assert.deepEqual(updated.points,measured.points);assert.deepEqual(updated.physical_vector_xy,[-1.5,1.5]);
  assert.equal(updated.calibration_dependency.calibration_id,scaled.object_id);assert.equal(updated.calibration_dependency.centre_revision_id,centre.object_id);
  const preview=await c.tool('image_preview',{object_id:scaled.object_id,max_size:256,upscale:true,request_id:'view-corrected'});
  assert.ok(preview.result.content.find(b=>b.type==='image'&&b.mimeType==='image/png'));
  const displayed=value(preview),output=path.join(directory,'export');
  value(await c.tool('image_export',{object_id:displayed.object_id,output_dir:output,request_id:'export-corrected'}));
  assert.equal(hash(path.join(output,'data.npy')),original);assert.equal(hash(path.join(input,'input.npy')),original);
  const exported=JSON.parse(readFileSync(path.join(output,'manifest.json'),'utf8'));
  assert.deepEqual(exported.xy_calibration.dc_index_xy,[7,4]);assert.equal(exported.xy_calibration.calibration_id,scaled.object_id);
  await c.close();c=client(workspace);
  assert.equal(value(await c.tool('image_result',{request_id:'updated-scale-measure'})).object_id,updated.object_id);
  assert.equal(value(await c.tool('image_result',{request_id:'original-peaks'})).object_id,old.object_id);
  assert.deepEqual(value(await c.tool('image_result',{request_id:'original-peaks'})).points,[[6,5],[10,7]]);
  assert.equal((await c.tool('image_center',{object_id:frame.object_id,center_xy:[6,4],coordinate_space:'source_array_indices',source_text:'changed',request_id:'correct-centre'})).result.isError,true);
 }finally{await c.close();rmSync(directory,{recursive:true,force:true});}
});

test('MCP cannot reuse saved points across a fresh capture or implicitly change point positions',async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'centre-refusals-')),input=fixture(directory),workspace=path.join(directory,'workspace'),c=client(workspace);
 try{
  const frame=value(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'first-capture'}));
  const old=value(await c.tool('image_measure',{object_id:frame.object_id,points:[[6,5],[10,7]],request_id:'first-measure'}));
  const fresh=value(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'new-explicit-capture'}));
  const bad=await c.tool('image_remeasure',{object_id:fresh.object_id,measurement_object_id:old.object_id,request_id:'wrong-capture'});
  assert.equal(bad.result.isError,true);assert.match(bad.result.content[0].text,/MEASUREMENT_SCOPE_MISMATCH/);
  const changed=await c.tool('image_remeasure',{object_id:frame.object_id,measurement_object_id:old.object_id,points:[[6,5],[11,7]],request_id:'missing-correction-source'});
  assert.equal(changed.result.isError,true);assert.match(changed.result.content[0].text,/source_text/);
 }finally{await c.close();rmSync(directory,{recursive:true,force:true});}
});
