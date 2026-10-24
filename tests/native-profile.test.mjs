import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {validateNativeLineProfile,validateNativeGuiRois,validateNativeDataSnapshot} from '../lib/native_bridge.mjs';
import {encodeNpy,encodeNpyHeader,encodeProfileNpy,validateSavedSnapshot,handoff} from '../tools/native_snapshot_handoff.mjs';
import {profileArgs,profileFixture,savedProfileFixture} from './fixtures/native-profile.mjs';
import {guiRoisFixture,normalizedGuiMapping} from './fixtures/native-rois.mjs';

test('PROFILE preserves true 1D f64, signed native axis, raw intensity and exact GUI trajectory',()=>{
  for (const args of [profileArgs,[77,0,0x7fffffff,0,5,1,2,1,1],[77,31,9,4,2,6,2,1,1]]) {
    const result=profileFixture(args); validateNativeLineProfile(result,args,'saved-profile');
    assert.equal(Buffer.from(result.values_base64,'base64').readDoubleLE(16),16777217);
    assert.equal(result.image.calibration[0].scale,-result.distance_step);
    assert.throws(()=>validateNativeDataSnapshot(result,[77,0,0,2,2]));
  }
});

test('PROFILE rejects wrong identity, geometry, rank, dtype, calibration, intensity and byte semantics',()=>{
  const changes=[r=>r.source_image_id++,r=>r.image_id=77,r=>r.source_gui_line.document_id++,r=>r.source_gui_line.display_id++,
    r=>r.source_gui_line.roi_id++,r=>r.source_gui_line.raw_line.x0++,r=>r.source_gui_line.effective_line[0]++,
    r=>r.source_gui_line.rotation_degrees=360,r=>r.source_gui_line.slice_ids=[1],r=>r.source_gui_line.coordinate_mapping.scale[0]=1,
    r=>r.image.ndim=2,r=>r.image.shape=[1,4],r=>r.image.dm_dimensions=[4,1],r=>r.image.dtype='float32',r=>r.image.data_type_code=2,
    r=>r.image.calibration[0].scale=0.25,r=>r.image.calibration[0].origin=1,r=>r.image.calibration[0].numpy_axis=1,
    r=>r.source.calibration[1].scale=0.5,r=>r.source.calibration[1].unit='px',r=>r.source.packing_style=2,
    r=>r.distance_step=-0.25,r=>r.distance_zero=1,r=>r.axes=['distance'],r=>r.source_sample_step_xy=[-1,0],
    r=>r.intensity_calibration.origin++,r=>r.intensity_calibration.scale=Infinity,r=>r.intensity_calibration.unit='',
    r=>r.intensity_calibration_applied=true,r=>r.intensity_semantics='counts',r=>r.raw_bytes=16,r=>r.values_base64+='=',
    r=>r.values_base64=Buffer.alloc(16).toString('base64'),r=>r.retention.creation_request_id='foreign',r=>delete r.retention,
    r=>r.snapshot_atomic=true,r=>r.source_write_requested=true,r=>r.candidate_probe=true,r=>r.qualification='NOT_QUALIFIED'];
  for (const change of changes) {const result=profileFixture();change(result);assert.throws(()=>validateNativeLineProfile(result,profileArgs,'saved-profile'),change.toString());}
  for(const value of [Infinity,-Infinity,NaN]) {const result=profileFixture(),bytes=Buffer.from(result.values_base64,'base64');bytes.writeDoubleLE(value,0);result.values_base64=bytes.toString('base64');assert.throws(()=>validateNativeLineProfile(result,profileArgs));}
  for(const args of [[77,31,9,4,2,1,2,1,1],[77,31,9,4,2,1,5,2,1],[77,31,9,4,2,1,5,1,2],[77,0x80000000,9,4,2,1,5,1,1]])
    assert.throws(()=>validateNativeLineProfile(profileFixture(),args));
});

test('zero allocated PROFILE image ID cannot satisfy retained identity or saved handoff',()=>{
  const result=profileFixture();result.image_id=result.image.id=0;
  assert.throws(()=>validateNativeLineProfile(result,profileArgs,'saved-profile'),/identity/);
  const saved=savedProfileFixture();saved.image_id=saved.image.id=0;
  assert.throws(()=>validateSavedSnapshot(Buffer.from(JSON.stringify(saved))),/identity/);
  const workspace=fs.mkdtempSync(path.join(os.tmpdir(),'dm-profile-zero-'));
  try {
    const filename=path.join(workspace,'saved.json');fs.writeFileSync(filename,JSON.stringify(saved));
    assert.throws(()=>handoff({workspace,output:'capture',requestId:'zero-export',snapshot:filename}),/identity/);
    assert.deepEqual(fs.readdirSync(workspace),['saved.json'],'invalid allocated identity is rejected before journal or output creation');
  } finally {fs.rmSync(workspace,{recursive:true,force:true});}
});

test('PROFILE and GUI line budgets accept exactly4096 f64 samples, reject4097 and keep uint32 input distinct',()=>{
  for(const unsigned of [false,true]) {
    const args=[77,31,9,4,0,0,4095,0,1],result=profileFixture(args,'saved-profile',{unsigned,shape:[1,4096]});
    validateNativeLineProfile(result,args,'saved-profile');assert.equal(result.raw_bytes,32768);
    assert.equal(result.source.dtype,unsigned?'uint32':'float32');assert.equal(result.dtype,'float64');
  }
  const args=[77,31,9,4,0,0,4096,0,1],tooLarge=profileFixture(args,'saved-profile',{shape:[1,4097]});
  assert.throws(()=>validateNativeLineProfile(tooLarge,args));
  const result=guiRoisFixture(),display=result.displays[0],roi=display.rois[0];
  result.image=tooLarge.source;
  Object.assign(roi,{type:'line',raw_rectangle:null,rect:null,raw_line:{x0:0,y0:0,x1:4096,y1:0},line:null,
    coordinate_mapping:normalizedGuiMapping([1,4097]),analysis_eligible:false,issue:'line_sample_budget'});
  validateNativeGuiRois(result,77,2);roi.issue=null;roi.analysis_eligible=true;roi.line=[0,0,4096,0];assert.throws(()=>validateNativeGuiRois(result,77,2));
});

test('ROIS v2 line eligibility is separate from historical v1 immutable rectangles',()=>{
  validateNativeGuiRois(guiRoisFixture(77,1),77,1);
  assert.throws(()=>validateNativeGuiRois(guiRoisFixture(77,1),77,2));
  assert.throws(()=>validateNativeGuiRois(guiRoisFixture(77,2),77,1));
  const result=guiRoisFixture(),display=result.displays[0],roi=display.rois[0];
  Object.assign(roi,{type:'line',raw_rectangle:null,rect:null,raw_line:{x0:2,y0:1,x1:5,y1:1},line:[2,1,5,1]});
  validateNativeGuiRois(result,77,2);
  for(const [raw_line,issue] of [[{x0:2,y0:1,x1:2,y1:1},'empty_line'],[{x0:2.5,y0:1,x1:5,y1:1},'fractional_line'],
    [{x0:2,y0:1,x1:5,y1:2},'unsupported_line_orientation'],[{x0:2,y0:1,x1:12,y1:1},'out_of_bounds_line']]) {
    Object.assign(roi,{raw_line,line:null,analysis_eligible:false,issue});validateNativeGuiRois(result,77,2);
    roi.analysis_eligible=true;assert.throws(()=>validateNativeGuiRois(result,77,2));
  }
  Object.assign(roi,{raw_line:{x0:2,y0:1,x1:5,y1:1},analysis_eligible:false,line:null,issue:'rotated_line',rotation_degrees:360});
  validateNativeGuiRois(result,77,2);
  roi.rotation_degrees=0;display.source_layout='unsupported';roi.coordinate_mapping.source_pixel_aligned=false;roi.issue='unsupported_image_source';
  validateNativeGuiRois(result,77,2);
  display.source_layout='direct_image_canonical_xy';roi.coordinate_mapping.offset=[1,0];roi.issue='unsupported_coordinate_mapping';
  validateNativeGuiRois(result,77,2);
});

test('profile NPY is true rank1 little-endian f64; existing 2D helpers stay closed',()=>{
  const saved=validateSavedSnapshot(Buffer.from(JSON.stringify(savedProfileFixture()))),npy=encodeProfileNpy(saved.result.shape,saved.values);
  assert.match(npy.subarray(10,10+npy.readUInt16LE(8)).toString(),/'descr': '<f8'.*'shape': \(4,\)/);
  assert.ok(npy.subarray(10+npy.readUInt16LE(8)).equals(saved.values));
  assert.throws(()=>encodeNpy([4],saved.values,'float64'));assert.throws(()=>encodeNpyHeader([4],'float64'));
  assert.throws(()=>encodeProfileNpy([1,4],saved.values));assert.throws(()=>encodeProfileNpy([4097],Buffer.alloc(4097*8)));
});

test('saved PROFILE handoff exclusively writes, reopens with NumPy and recovers identical files without DM',()=>{
  const workspace=fs.mkdtempSync(path.join(os.tmpdir(),'dm-profile-'));
  try {
    const filename=path.join(workspace,'saved.json');fs.writeFileSync(filename,JSON.stringify(savedProfileFixture()));
    const args={workspace,output:'capture',requestId:'export-profile',snapshot:filename},result=handoff(args);
    assert.equal(result.capture_mode,'native_profile');assert.deepEqual(result.shape,[4]);
    assert.deepEqual(handoff(args),result);
    const info=JSON.parse(fs.readFileSync(path.join(workspace,'capture','input.json'))),manifest=JSON.parse(fs.readFileSync(path.join(workspace,'capture','capture.json')));
    assert.equal(Object.hasOwn(info,'shape_yx'),false);assert.equal(Object.hasOwn(manifest,'source_rect_xyxy'),false);
    assert.deepEqual(info.profile_calibration,info.profile_metadata.calibration);assert.equal(info.distance_step,0.25);
    const check=spawnSync(process.env.DM_TEST_PYTHON||'python',['-c',"import numpy as np,sys; a=np.load(sys.argv[1],allow_pickle=False); assert a.shape==(4,) and a.dtype==np.dtype('<f8'); assert a.tolist()==[-2.5,0.1,16777217,4294967295]",path.join(workspace,'capture','input.npy')],{encoding:'utf8'});
    assert.equal(check.status,0,check.stderr);
    assert.throws(()=>handoff({...args,requestId:'other-export'}));
    fs.appendFileSync(path.join(workspace,'capture','input.npy'),'x');assert.throws(()=>handoff(args));
  } finally {fs.rmSync(workspace,{recursive:true,force:true});}
});
