// Actual stdio MCP + existing external image worker over a SYNTHETIC encoded
// reciprocal scalar READ fixture. No DM/native host, private data or FFT runs.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync,writeFileSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {imageMetadata,readFixture} from './fixtures/native-operations.mjs';
import {handoff} from '../tools/native_snapshot_handoff.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const hash=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
const imageRef=object=>({provider:'image',object_id:object.object_id});
function capture(directory) {
  const source=imageMetadata(77,{shape:[16,24]});
  Object.assign(source.calibration[0],{origin:6,scale:-.25,calibrated_value_at_pixel_zero:1.5,unit:'1/nm'});
  Object.assign(source.calibration[1],{origin:5,scale:.5,calibrated_value_at_pixel_zero:-2.5,unit:'1/nm'});
  const args=[77,0,0,24,16],read=readFixture(args,{source});
  const native_receipt={protocol:'NB2',session:'a'.repeat(32),id:'context-centre-source',request_id:'context-centre-source',state:'completed',
    host_pid:1234,worker_tid:20,exec_tid:10,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
  const snapshot=path.join(directory,'snapshot.json');writeFileSync(snapshot,JSON.stringify({...read,native_receipt}));
  return handoff({workspace:directory,output:'capture',requestId:'encode-context-centre-fixture',snapshot}).capture_path??path.join(directory,'capture');
}
function client(workspace,contexts) {
  const child=spawn(process.execPath,[path.join(root,'server.mjs')],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,
    DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python,DM_ANALYSIS_CONTEXT_WORKSPACE:contexts}});
  let next=1,buffer='',stderr='';const pending=new Map();
  child.stderr.on('data',part=>stderr=(stderr+part).slice(-16384));child.stdin.on('error',()=>{});
  child.stdout.on('data',part=>{buffer+=part;let end;while((end=buffer.indexOf('\n'))>=0){const row=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);const wait=pending.get(row.id);if(wait){pending.delete(row.id);clearTimeout(wait.timer);wait.resolve(row);}}});
  child.once('exit',()=>{for(const wait of pending.values()){clearTimeout(wait.timer);wait.reject(Error('Context test server exited: '+stderr));}pending.clear();});
  const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=next++,timer=setTimeout(()=>{pending.delete(id);reject(Error(stderr||'Context center MCP timeout'));},30000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
  return {rpc,tool:(name,args)=>rpc('tools/call',{name,arguments:args}),async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
function value(reply) {
  assert.equal(reply.error,undefined,JSON.stringify(reply));assert.notEqual(reply.result?.isError,true,JSON.stringify(reply));
  return JSON.parse(reply.result.content.find(part=>part.type==='text').text);
}
function refusal(reply,pattern) {assert.equal(reply.error,undefined);assert.equal(reply.result.isError,true);assert.match(reply.result.content[0].text,pattern);}
function geometry(context,object) {
  for(const role of ['calibration','center']) {
    assert.equal(context.slots[role].status,'active');
    assert.equal(context.slots[role].ref.objectId,object.object_id);
    assert.equal(context.slots[role].proof.scientific.calibration.calibration_id,object.xy_calibration.calibration_id);
  }
}

test('actual MCP center-only and scale-only Context revisions keep one current compound geometry and reusable raw anchors', {timeout:180000}, async()=>{
  const directory=mkdtempSync(path.join(tmpdir(),'analysis-context-centre-')),input=capture(directory),workspace=path.join(directory,'images'),contexts=path.join(directory,'contexts');
  const sourceHash=hash(path.join(input,'input.npy'));let c=client(workspace,contexts);
  try {
    const tools=(await c.rpc('tools/list')).result.tools.map(tool=>tool.name);for(const name of ['analysis_create','analysis_read','analysis_update'])assert.ok(tools.includes(name));
    const frame=value(await c.tool('image_open',{source_path:input,source_kind:'capture',request_id:'open-scalar'}));
    const frameHash=hash(frame.array_path),old=value(await c.tool('image_measure',{object_id:frame.object_id,points:[[6,5],[10,7]],request_id:'measure-original'}));
    assert.deepEqual(old.physical_vector_xy,[-1,1]);assert.ok(Math.abs(old.d_spacing-1/Math.sqrt(2))<1e-14);
    value(await c.tool('analysis_create',{analysis_id:'scalar',request_id:'create',reason:'Synthetic reciprocal scalar with signed axes'}));
    let selected=value(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:1,request_id:'select-initial',reason:'Select initial immutable scalar and geometry',selections:{
      experiment:imageRef(frame),calibration:imageRef(frame),center:imageRef(frame),points:[imageRef(old)],measurements:[imageRef(old)]}}));
    assert.equal(selected.context.revision,2);assert.equal(selected.context.slots.measurements[0].status,'active');
    const center=value(await c.tool('image_center',{object_id:frame.object_id,center_xy:[7,4],coordinate_space:'source_array_indices',source_text:'Synthetic user corrects only reciprocal scalar center to [7,4]',request_id:'correct-center'}));
    refusal(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:2,request_id:'reject-explicit-mixed-geometry',reason:'Explicit old scale record and new center cannot be current together',
      selections:{calibration:imageRef(frame),center:imageRef(center)}}),/SCIENTIFIC_BINDING_MISMATCH.*different geometry revisions/);
    selected=value(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:2,request_id:'select-center-only',reason:'Correct only the selected center',selections:{center:imageRef(center)}}));
    const centerRevision=selected.context.revision;geometry(selected.context,center);
    assert.equal(selected.context.slots.points[0].status,'active');assert.equal(selected.context.slots.points[0].ref.objectId,old.object_id);
    assert.equal(selected.context.slots.measurements[0].status,'stale');assert.equal(selected.context.slots.experiment.ref.objectId,frame.object_id);
    refusal(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:centerRevision,request_id:'reject-old-center-measure',reason:'Old measurement cannot be relabelled',selections:{measurements:[imageRef(old)]}}),/SCIENTIFIC_BINDING_MISMATCH/);
    const measured=value(await c.tool('image_remeasure',{object_id:center.object_id,measurement_object_id:old.object_id,request_id:'remeasure-center'}));
    assert.deepEqual(measured.points,[[7,4],[10,7]]);assert.deepEqual(measured.physical_vector_xy,[-.75,1.5]);
    assert.ok(Math.abs(measured.d_spacing-1/Math.sqrt(2.8125))<1e-14);assert.equal(measured.remeasurement.dc_endpoint_updated,true);
    selected=value(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:centerRevision,request_id:'select-new-center-measure',reason:'Accept remeasurement with corrected DC endpoint',selections:{points:[imageRef(measured)],measurements:[imageRef(measured)]}}));
    assert.equal(selected.context.slots.measurements[0].status,'active');
    const scale=value(await c.tool('image_calibrate',{object_id:center.object_id,scope:'image',xy_scale:{x:-.5,y:.5,unit:'1/nm'},source_text:'Synthetic user changes signed X scale; the corrected center remains [7,4]',request_id:'correct-scale'}));
    assert.deepEqual(scale.xy_calibration.dc_index_xy,[7,4]);assert.equal(scale.xy_calibration.centre_revision_id,center.object_id);
    selected=value(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:selected.context.revision,request_id:'select-scale-only',reason:'Correct only the selected scale',selections:{calibration:imageRef(scale)}}));
    const scaleRevision=selected.context.revision;geometry(selected.context,scale);
    assert.equal(selected.context.slots.points[0].status,'active');assert.equal(selected.context.slots.points[0].ref.objectId,measured.object_id);
    assert.equal(selected.context.slots.measurements[0].status,'stale');
    refusal(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:scaleRevision,request_id:'reject-old-scale-measure',reason:'Old scale result cannot be relabelled',selections:{measurements:[imageRef(measured)]}}),/SCIENTIFIC_BINDING_MISMATCH/);
    const updated=value(await c.tool('image_remeasure',{object_id:scale.object_id,measurement_object_id:measured.object_id,request_id:'remeasure-scale'}));
    assert.deepEqual(updated.points,measured.points);assert.deepEqual(updated.physical_vector_xy,[-1.5,1.5]);
    assert.ok(Math.abs(updated.d_spacing-1/Math.sqrt(4.5))<1e-14);
    selected=value(await c.tool('analysis_update',{analysis_id:'scalar',expected_revision:scaleRevision,request_id:'select-new-scale-measure',reason:'Accept remeasurement while retaining unchanged point anchors',selections:{measurements:[imageRef(updated)]}}));
    assert.equal(selected.context.slots.measurements[0].status,'active');assert.equal(selected.context.slots.measurements[0].ref.objectId,updated.object_id);
    const finalRevision=selected.context.revision;
    const requests=readdirSync(path.join(workspace,'requests')).map(name=>JSON.parse(readFileSync(path.join(workspace,'requests',name),'utf8')));
    assert.ok(!requests.some(record=>record.parameters?.action==='fft'),'scalar center/scale revisions must not run any FFT');
    assert.equal(selected.context.slots.fft,undefined);assert.equal(hash(frame.array_path),frameHash);assert.equal(hash(path.join(input,'input.npy')),sourceHash);
    await c.close();c=client(workspace,contexts);
    const resumed=value(await c.tool('analysis_read',{analysis_id:'scalar'}));assert.equal(resumed.context.revision,finalRevision);geometry(resumed.context,scale);
    assert.equal(resumed.context.slots.measurements[0].ref.objectId,updated.object_id);
    const original=value(await c.tool('analysis_read',{analysis_id:'scalar',request_id:'select-center-only'}));assert.equal(original.context.revision,centerRevision);geometry(original.context,center);
    assert.equal(value(await c.tool('image_result',{request_id:'remeasure-scale'})).object_id,updated.object_id);
    assert.equal(value(await c.tool('image_result',{request_id:'measure-original'})).object_id,old.object_id);
    assert.equal(hash(path.join(input,'input.npy')),sourceHash);
  } finally {await c.close();rmSync(directory,{recursive:true,force:true});}
});
