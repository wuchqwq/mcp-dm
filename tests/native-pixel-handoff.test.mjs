// Saved synthetic receipts and independent file validators, never a DM call.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {handoff,canonical} from '../tools/native_snapshot_handoff.mjs';
import {handoffRegion} from '../tools/native_region_handoff.mjs';
import {readFixture} from './fixtures/native-operations.mjs';
import {pixelReadFixture} from './fixtures/native-pixel-handoff.mjs';

const python=process.env.DM_TEST_PYTHON||'python',session='a'.repeat(32),pid=1234;
const json=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const sha=b=>createHash('sha256').update(b).digest('hex');
function temp(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pixel-handoff-'));t.after(()=>fs.rmSync(dir,{recursive:true}));return dir;}
function receipt(op,args,id,result){return {protocol:'NB2',session,id,request_id:id,state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,
  timings_us:{queue:0,execute:1},original_operation:op,normalized_args:args,
  result_type:op==='STATUS'?'status':op==='READ'?'native_data_snapshot':'native_fourier_operation',result_version:op==='STATUS'||op==='READ'?1:2,...(result?{result}:{})};}
function saved(t,options={}){
  const dir=temp(t),f=pixelReadFixture(options),filename=path.join(dir,'saved.json');
  fs.writeFileSync(filename,JSON.stringify({...f.read,native_receipt:receipt('READ',f.args,'pixel-read')}));
  return {...f,dir,target:handoff({workspace:dir,output:'capture',requestId:'saved-pixel-handoff',snapshot:filename}).capture_dir};
}

test('pixel Fourier exports retain native calibration, frame identity and mathematical pixel axes in separate fields',t=>{
  for(const options of [{},{crop:true},{frame:true},{unknownUnits:false},{operation:'VENDOR_NORM_PIXEL'},{operation:'VENDOR_ARG_PIXEL'},{spatial:true}]){
    const f=saved(t,options),info=json(path.join(f.target,'input.json')),sem=info.scientific_semantics;
    assert.equal(sem.coordinate_mode,'pixel');assert.equal(sem.physical_calibration_applied,false);
    assert.ok(sem.coordinate_axes.every(axis=>axis.native_minus_mathematical_zero===null));
    assert.equal(sem.coordinate_axes[0].unit,options.spatial?'pixel':'cycles_per_pixel');
    assert.equal(info.source_metadata.calibration[0].unit,f.read.source.calibration[0].unit);
    assert.equal(info.frame_ancestry?.normalized_args[1],options.frame?1:undefined);
    const script=String.raw`import json,sys,numpy as np
from pathlib import Path
from tools.verify_native_region import verify_science,verify_frame_ancestry
from crystallography.capture import load_capture,CaptureError
p=Path(sys.argv[1]);i=json.loads((p/'input.json').read_text(encoding='utf-8'))
verify_science(i);verify_frame_ancestry(i)
assert np.load(p/'input.npy',allow_pickle=False).dtype==np.dtype('<f4')
s=i['scientific_semantics'];assert s['coordinate_mode']=='pixel' and s['physical_calibration_applied'] is False
c=load_capture(p,'image',expected_host_pid=1234,expected_session='a'*32)
assert c.provenance['source_mode_declared']=='image' and c.source_mode=='image'
assert c.coordinate_axes[0]['unit']==s['coordinate_axes'][0]['unit']
try:c.frequency_axes_cycles_per_nm()
except CaptureError:pass
else:raise AssertionError('generic image input admitted physical FFT analysis')
c.assert_unchanged()
if s['domain']=='frequency' and s['representation']!='phase_radians':
 c=load_capture(p,'fft',expected_host_pid=1234,expected_session='a'*32)
 assert c.coordinate_axes[0]['unit']=='cycles_per_pixel'
 try:c.frequency_axes_cycles_per_nm()
 except CaptureError:pass
 else:raise AssertionError('pixel coordinates became physical reciprocal units')
 c.assert_unchanged()
print('independent pixel coordinate/provenance PASS')`;
    assert.match(execFileSync(python,['-c',script,f.target],{encoding:'utf8'}),/pixel coordinate\/provenance PASS/);
  }
});

test('independent Python refuses rehashed pixel axes relabelled physical or shifted to the native half-bin',t=>{
  const base=saved(t,{frame:true});
  const mutations=[i=>i.scientific_semantics.coordinate_mode='physical',i=>i.scientific_semantics.physical_calibration_applied=true,
    i=>i.scientific_semantics.coordinate_axes[0].unit='1/nm',i=>i.scientific_semantics.coordinate_axes[0].native_minus_mathematical_zero=0,
    i=>i.scientific_context.result.frequency_grid.axes[0].physical_frequency_step=.125,
    i=>i.scientific_context.result.frequency_grid.axes[0].native_calibration_scale=1,
    i=>i.scientific_context.result.frequency_grid.axes[0].native_calibration_unit='nm',
    i=>i.scientific_context.result.frequency_grid.axes[0].frequency_at_index_zero=-.5625,
    i=>i.scientific_context.result.frequency_grid.axes[0].dc_index=4.5,
    i=>i.scientific_context.result.qualification='NOT_QUALIFIED',i=>i.scientific_context.result.candidate_probe=true,
    i=>i.frame_ancestry.result.qualification='NOT_QUALIFIED'];
  for(const [index,mutate] of mutations.entries()){
    const target=path.join(base.dir,'bad-'+index);fs.cpSync(base.target,target,{recursive:true});
    const info=json(path.join(target,'input.json')),manifest=json(path.join(target,'capture.json'));mutate(info);
    const encoded=Buffer.from(canonical(info));fs.writeFileSync(path.join(target,'input.json'),encoded);
    manifest.input_metadata_sha256=manifest.input_metadata_file_sha256=sha(encoded);manifest.frame_ancestry=info.frame_ancestry;
    fs.writeFileSync(path.join(target,'capture.json'),JSON.stringify(manifest));
    for(const mode of ['fft','image'])assert.throws(()=>execFileSync(python,['-c',"from crystallography.capture import load_capture;import sys;load_capture(sys.argv[1],sys.argv[2])",target,mode],{stdio:'pipe'}),`${index}/${mode}`);
  }
});

test('chunked pixel exports save the exact new-op creation QUERY and reject a lost pixel mode',async t=>{
  for(const bad of [false,true]){
    const dir=temp(t),f=pixelReadFixture({frame:true}),source=f.producer.image,calls=[];
    const bridge={async execute(op,args,{requestId}){
      calls.push([op,args]);if(op==='STATUS')return receipt(op,args,requestId,{backend:'digitalmicrograph-native',host_pid:pid,ready:true,binary_gate:true,compatibility:{state:'SUPPORTED'}});
      const read=readFixture(args,{source,provenance:f.read.source_provenance});
      read.scientific_context=f.read.scientific_context;read.frame_ancestry=f.read.frame_ancestry;
      return receipt(op,args,requestId,read);
    },async query(id){calls.push(['QUERY',id]);const result=structuredClone(f.producer);if(bad)delete result.coordinate_mode;
      return receipt('REAL_PIXEL',[88],id,result);},close(){}};
    const action=()=>handoffRegion({workspace:dir,output:'capture',requestId:'pixel-region',imageId:source.id,
      rect:[0,0,8,4],session,hostPid:pid,blockSamples:8},()=>bridge);
    if(bad){await assert.rejects(action,/pixel source creation mode\/operation/);assert.equal(fs.existsSync(path.join(dir,'capture','input.npy')),false);}
    else{
      const result=await action(),info=json(path.join(result.capture_dir,'input.json'));
      assert.equal(info.native_source_creation_record.original_operation,'REAL_PIXEL');
      assert.deepEqual(info.native_source_creation_record.normalized_args,[88]);
      assert.equal(calls.filter(([op])=>op==='REAL_PIXEL').length,0,'export must not repeat a producer');
      const verified=JSON.parse(execFileSync(python,['tools/verify_native_region.py','--capture',result.capture_dir,'--host-pid','1234','--session',session],{encoding:'utf8'}));
      assert.equal(verified.status,'PASS_INDEPENDENT_CHUNKED_FILES');
    }
  }
});
