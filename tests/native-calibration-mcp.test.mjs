// Actual stdio MCP and independent Python worker over saved protocol fixtures.
// No real DigitalMicrograph, browser or vendor execution is represented here.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {imageMetadata,readFixture} from './fixtures/native-operations.mjs';
import {handoff} from '../tools/native_snapshot_handoff.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
function capture(directory,reciprocal=false){
 const source=imageMetadata(77,{shape:[16,32]});
 Object.assign(source.calibration[0],{origin:4,scale:reciprocal?.25:-.5,calibrated_value_at_pixel_zero:reciprocal?-1:2,unit:reciprocal?'1/nm':'nm'});
 Object.assign(source.calibration[1],{origin:2,scale:reciprocal?-.5:2,calibrated_value_at_pixel_zero:reciprocal?1:-4,unit:reciprocal?'1/nm':'nm'});
 const args=[77,0,0,32,16],value=readFixture(args,{source});
 const native_receipt={protocol:'NB2',session:'a'.repeat(32),id:'read-original',request_id:'read-original',state:'completed',host_pid:1234,worker_tid:20,exec_tid:10,
  timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
 const snapshot=path.join(directory,'read.json');writeFileSync(snapshot,JSON.stringify({...value,native_receipt}));
 return handoff({workspace:directory,output:'capture',requestId:'save-native',snapshot}).capture_dir;
}
function client(workspace){
 const child=spawn(process.execPath,[path.join(root,'server.mjs')],{env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python},stdio:['pipe','pipe','pipe'],windowsHide:true});
 let id=0,buffer='',stderr='';const pending=new Map();
 child.stdin.on('error',()=>{});child.stderr.on('data',c=>stderr+=c);
 child.stdout.on('data',c=>{buffer+=c;let n;while((n=buffer.indexOf('\n'))>=0){const v=JSON.parse(buffer.slice(0,n));buffer=buffer.slice(n+1);const p=pending.get(v.id);if(p){pending.delete(v.id);clearTimeout(p.timer);p.resolve(v);}}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const next=++id,timer=setTimeout(()=>{pending.delete(next);reject(Error(stderr||'MCP timeout'));},30000);pending.set(next,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:next,method,params})+'\n');});
 return {rpc,tool:(name,args)=>rpc('tools/call',{name,arguments:args}),async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
function result(message){assert.equal(message.error,undefined);assert.notEqual(message.result.isError,true,JSON.stringify(message.result));return JSON.parse(message.result.content[0].text);}
function png(message){const item=message.result.content.find(c=>c.type==='image');assert.ok(item,'Actual MCP image block required');assert.equal(item.mimeType,'image/png');}

test('native calibration automatically enters stdio measurement, FFT render, user revision, export and fresh-client recovery',async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'native-cal-mcp-')),input=capture(directory),workspace=path.join(directory,'workspace');let c=client(workspace);
 try{
  const original=sha(readFileSync(path.join(input,'input.npy')));
  const opened=result(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'open-native'}));
  assert.equal(opened.xy_calibration.source,'native_dm_capture');assert.equal(opened.xy_calibration.coordinate_domain,'real_space');
  assert.equal((await c.tool('image_calibrate',{object_id:opened.object_id,scope:'image',coordinate_domain:'reciprocal_space',xy_scale:{x:.2,y:.2,unit:'1/nm'},source_text:'Negative control: no array reinterpretation through scale',request_id:'refuse-domain-reinterpretation'})).result.isError,true);
  const measured=result(await c.tool('image_measure',{object_id:opened.object_id,points:[[1,1],[7,3]],request_id:'measure-native'}));
  assert.equal(measured.physical_distance,5);assert.equal(measured.physical_unit,'nm');assert.deepEqual(measured.physical_vector_xy,[-3,4]);
  const preview=await c.tool('image_preview',{object_id:opened.object_id,max_size:320,upscale:true,request_id:'native-view'});png(preview);assert.equal(result(preview).scale_bar.provenance,'native_dm_capture');
  const fft=await c.tool('image_fft',{object_id:opened.object_id,rect:[0,0,8,8],window:'none',subtract_mean:false,request_id:'native-fft'});png(fft);const saved=result(fft),hash=sha(readFileSync(saved.array_path));
  const revised=result(await c.tool('image_calibrate',{object_id:saved.object_id,scope:'image',xy_scale:{x:-.25,y:1,unit:'nm'},source_text:'Synthetic user correction, not experimental data',request_id:'revise-scale'}));
  assert.equal(revised.xy_calibration.revision,2);assert.equal(revised.xy_calibration.previous_calibration_id,opened.object_id);
  const updated=await c.tool('image_preview',{object_id:revised.object_id,spectrum_axes:true,max_size:320,upscale:true,request_id:'replot-saved-fft'});png(updated);const view=result(updated);
  assert.equal(view.fft_recomputed,false);assert.equal(sha(readFileSync(view.array_path)),hash);assert.equal(view.physical_frequency_axes[1].step,-.5);
  const output=path.join(directory,'export');result(await c.tool('image_export',{object_id:view.object_id,output_dir:output,request_id:'export-fft'}));
  const provenance=JSON.parse(readFileSync(path.join(output,'provenance.json'),'utf8'));assert.equal(provenance.objects[opened.object_id].xy_calibration.source,'native_dm_capture');
  assert.equal(sha(readFileSync(path.join(input,'input.npy'))),original);
  await c.close();c=client(workspace);assert.equal(result(await c.tool('image_result',{request_id:'measure-native'})).object_id,measured.object_id);
  assert.equal((await c.tool('image_calibrate',{object_id:opened.object_id,scope:'image',xy_scale:{x:1,y:1,unit:'nm'},source_text:'changed',request_id:'revise-scale'})).result.isError,true);
 }finally{await c.close();rmSync(directory,{recursive:true,force:true});}
});

test('reciprocal native scalar uses explicit array-index coordinates and refuses a real-space scale through stdio',async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'native-recip-mcp-')),input=capture(directory,true),c=client(path.join(directory,'workspace'));
 try{
  const opened=result(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'open-reciprocal'}));
  const measured=result(await c.tool('image_measure',{object_id:opened.object_id,coordinate_space:'source_array_indices',points:[[4,2],[8,5]],request_id:'reciprocal-vector'}));
  assert.equal(measured.measurement_domain,'reciprocal_space');assert.equal(measured.dc_reference_point_index,0);assert.equal(measured.physical_distance,null);
  assert.equal(measured.physical_frequency_unit,'cycles/nm');assert.deepEqual(measured.physical_vector_xy,[1,-1.5]);assert.equal(measured.d_spacing,1/Math.sqrt(3.25));
  assert.equal((await c.tool('image_measure',{object_id:opened.object_id,coordinate_space:'source_pixels',points:[[4,2],[8,5]],request_id:'wrong-space'})).result.isError,true);
  assert.equal((await c.tool('image_calibrate',{object_id:opened.object_id,scope:'image',xy_scale:{x:1,y:1,unit:'nm'},source_text:'wrong real-space input',request_id:'wrong-domain'})).result.isError,true);
  const corrected=result(await c.tool('image_calibrate',{object_id:opened.object_id,scope:'image',coordinate_domain:'reciprocal_space',xy_scale:{x:.2,y:-.4,unit:'1/nm'},source_text:'Synthetic explicit reciprocal correction',request_id:'reciprocal-revision'}));
  assert.equal(corrected.xy_calibration.coordinate_domain,'reciprocal_space');assert.equal(corrected.xy_calibration.revision,2);
 }finally{await c.close();rmSync(directory,{recursive:true,force:true});}
});
