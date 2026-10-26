// Real loopback panel -> stdio MCP -> independent Python over a saved synthetic
// READ receipt. No DM process, experimental input or browser is used.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createImagePanel,StdioImageClient} from '../tools/image_panel.mjs';
import {imageMetadata,readFixture} from './fixtures/native-operations.mjs';
import {handoff} from '../tools/native_snapshot_handoff.mjs';

const python=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python';
test('reciprocal panel routes lines and peaks with preserved scale-only DC, withdrawal and recovery',async()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'reciprocal-panel-')),workspace=path.join(dir,'workspace');let client,panel;
 try{
  const source=imageMetadata(77,{shape:[16,32]});
  Object.assign(source.calibration[0],{origin:4,scale:.25,calibrated_value_at_pixel_zero:-1,unit:'1/nm'});
  Object.assign(source.calibration[1],{origin:2,scale:-.5,calibrated_value_at_pixel_zero:1,unit:'1/nm'});
  const args=[77,0,0,32,16],value=readFixture(args,{source});
  const native_receipt={protocol:'NB2',session:'a'.repeat(32),id:'read-origin',request_id:'read-origin',state:'completed',host_pid:1234,worker_tid:20,exec_tid:10,
   timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
  const snapshot=path.join(dir,'read.json');writeFileSync(snapshot,JSON.stringify({...value,native_receipt}));
  const capture=handoff({workspace:dir,output:'capture',requestId:'encode-origin',snapshot}).capture_dir;
  const original=readFileSync(path.join(capture,'input.npy'));
  client=new StdioImageClient({workspace,python});await client.rpc('initialize',{});
  const opened=(await client.tool('image_open',{source_path:capture,source_kind:'capture',request_id:'open-capture'})).data;
  const view=(await client.tool('image_preview',{object_id:opened.object_id,request_id:'view-capture'})).data;
  const exe=spawnSync(python,['-c','import sys; print(sys.executable)'],{encoding:'utf8'});assert.equal(exe.status,0,exe.stderr);
  panel=await createImagePanel({workspace,python:exe.stdout.trim(),object_id:view.object_id});
  const origin=panel.url.split('/#')[0];
  const send=async(action,params={},status=200)=>{
   const r=await fetch(origin+'/api/action',{method:'POST',headers:{'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'},
    body:JSON.stringify({expected_object_id:panel.state().object.object_id,action,params})});
   const data=await r.json();assert.equal(r.status,status,JSON.stringify(data));return data;
  };
  const selection=(kind,coordinates)=>{const p=panel.state().object.panels[0];return {kind,coordinates,coordinate_space:'source_array_indices',source_object_id:p.source_object_id,panel:p};};
  const line=await send('measure',{selection:selection('line',[4,2,8,5])});
  assert.deepEqual(line.last_operation.physical_vector_xy,[1,-1.5]);
  assert.equal(line.last_operation.physical_unit,null);assert.ok(Math.abs(line.last_operation.d_spacing-1/Math.hypot(1,1.5))<=4*Number.EPSILON,'Python/JavaScript hypot may differ by one rounding bit');
  const revised=await send('calibrate',{scope:'image',coordinate_domain:'reciprocal_space',xy_scale:{x:.2,y:-.4,unit:'1/nm'},source_text:'Synthetic scale correction, unchanged pixel centre'});
  assert.deepEqual(revised.object.xy_calibration.dc_index_xy,[4,2]);
  const point=await send('measure',{selection:selection('point',[8,5])});
  assert.ok(Math.abs(point.last_operation.d_spacing-1/Math.hypot(.8,1.2))<1e-14);
  const request=point.last_operation.request_id,measurement=point.last_operation.object_id;
  await client.close();client=new StdioImageClient({workspace,python});await client.rpc('initialize',{});
  assert.equal((await client.tool('image_result',{request_id:request})).data.object_id,measurement);
  await send('calibrate',{scope:'image',xy_scale:null,source_text:'Withdraw scale, retain historical pixel centre'});
  const refused=await send('measure',{selection:selection('point',[8,5])},400);assert.match(refused.error,/active calibration.*DC/);
  const pixels=await send('measure',{selection:selection('line',[4,2,8,5])});assert.equal(pixels.last_operation.distance_pixels,5);assert.equal(pixels.last_operation.period,null);
  await send('calibrate',{scope:'image',coordinate_domain:'reciprocal_space',xy_scale:{x:.2,y:-.4,unit:'1/nm'},source_text:'Restore scale after review'});
  const restored=await send('measure',{selection:selection('point',[8,5])});assert.equal(restored.last_operation.d_spacing,point.last_operation.d_spacing);
  assert.deepEqual(readFileSync(path.join(capture,'input.npy')),original);
 }finally{await panel?.close();await client?.close();rmSync(dir,{recursive:true,force:true});}
});
