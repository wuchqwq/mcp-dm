// Saved synthetic receipts only. No socket, DM import, vendor call or histogram
// calculation is performed by these handoff tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {canonical,encodeHistogramNpy,encodeNpy,encodeProfileNpy,handoff,validateSavedSnapshot} from '../tools/native_snapshot_handoff.mjs';
import {histogramArgs,histogramFloatBits,histogramIntensityFixture,savedHistogramFixture} from './fixtures/native-histogram.mjs';

const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const json=filename=>JSON.parse(fs.readFileSync(filename,'utf8'));
const save=(filename,value)=>fs.writeFileSync(filename,JSON.stringify(value));
function temporary(t) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'native-histogram-handoff-'));
  t.after(()=>fs.rmSync(directory,{recursive:true}));return directory;
}
function prepare(directory,payload=savedHistogramFixture()) {
  const filename=path.join(directory,'saved.json');save(filename,payload);return filename;
}
function options(workspace,snapshot) {return {workspace,snapshot,output:'capture',requestId:'export-histogram'};}
function wire(values) {const out=Buffer.alloc(values.length*8);values.forEach((value,i)=>out.writeDoubleLE(value,i*8));return out;}

test('histogram saved receipt accepts bins greater than source pixels and preserves two distinct byte representations',()=>{
  const value=savedHistogramFixture(),snapshot=validateSavedSnapshot(Buffer.from(JSON.stringify(value)));
  assert.ok(value.bins>value.source_pixels);assert.equal(snapshot.receipt.original_operation,'HISTOGRAM');
  assert.equal(snapshot.values.length,64);assert.equal(snapshot.nativeValues.length,32);
  assert.equal(snapshot.wireHash,sha(snapshot.values));assert.equal(snapshot.pixelHash,sha(snapshot.nativeValues));
  assert.notEqual(snapshot.wireHash,snapshot.pixelHash);
  assert.deepEqual([...Array(8)].map((_,i)=>snapshot.nativeValues.readUInt32LE(i*4)),[1,0,1,0,0,1,0,1]);
  const wrapped={content:[{type:'text',text:JSON.stringify(value)}]};
  assert.deepEqual(validateSavedSnapshot(Buffer.from(JSON.stringify(wrapped))).result,valueWithoutReceipt(value));
});
function valueWithoutReceipt(value) {const {native_receipt,...rest}=value;void native_receipt;return rest;}

test('histogram encoder writes true rank1 uint32, preserving the full unsigned transport range exactly',()=>{
  // These are encoder-only values. The live histogram count admission has the
  // much smaller complete-source-pixel bound, not arbitrary uint32 counts.
  const values=[0,16777217,2147483648,4294967295],bytes=wire(values),npy=encodeHistogramNpy([4],bytes);
  const offset=10+npy.readUInt16LE(8);
  assert.match(npy.subarray(10,offset).toString(),/'descr': '<u4'.*'shape': \(4,\)/);
  assert.equal(npy.length-offset,16);
  assert.deepEqual(values.map((_,i)=>npy.readUInt32LE(offset+i*4)),values);
  assert.throws(()=>encodeNpy([4],bytes,'uint32'));
  assert.notDeepEqual(npy,encodeProfileNpy([4],bytes));
  for (const value of [NaN,Infinity,-Infinity,-1,0.5,4294967296])
    assert.throws(()=>encodeHistogramNpy([2],wire([0,value])),/exact uint32/);
  for (const [shape,bytes] of [[[1],wire([1])],[[4097],Buffer.alloc(4097*8)],[[1,2],wire([1,2])],[[2],Buffer.alloc(8)]])
    assert.throws(()=>encodeHistogramNpy(shape,bytes));
});

test('histogram NPY independently reopens as native uint32 with raw intensity bin geometry and original receipt',t=>{
  const directory=temporary(t),payload=savedHistogramFixture(),snapshot=prepare(directory,payload);
  const receipt=handoff(options(directory,snapshot));assert.equal(receipt.capture_mode,'native_histogram');
  assert.deepEqual(receipt.shape,[8]);assert.equal(receipt.dtype,'uint32');assert.equal(receipt.native_result_image_id,99);
  const target=path.join(directory,'capture');assert.deepEqual(fs.readdirSync(target).sort(),['capture.json','input.json','input.npy']);
  const script=String.raw`import hashlib,json,sys,numpy as np
from pathlib import Path
p=Path(sys.argv[1]);i=json.loads((p/'input.json').read_text());m=json.loads((p/'capture.json').read_text());s=json.loads((p.parent/'saved.json').read_text())
a=np.load(p/'input.npy',allow_pickle=False);expected=np.array([1,0,1,0,0,1,0,1],dtype='<u4')
assert a.dtype==np.dtype('<u4') and a.shape==(8,) and a.tobytes()==expected.tobytes()
assert i['shape']==[8] and i['axes']==['bin_index'] and i['axis_mode']=='bin_index' and i['calibration_complete'] is False
assert 'shape_yx' not in i and 'source_rect_xyxy' not in i and 'source_line_xyxy' not in i
assert i['raw_bytes']==i['native_storage_bytes']==32 and i['wire_raw_bytes']==64 and i['wire_scalar_dtype']=='float64'
assert hashlib.sha256(a.tobytes()).hexdigest()==i['pixel_sha256']==m['pixel_sha256']
import base64
assert hashlib.sha256(base64.b64decode(s['values_base64'])).hexdigest()==i['wire_values_sha256']==m['wire_values_sha256']
assert i['wire_values_sha256']!=i['pixel_sha256']
assert i['requested_range']==[-4,4] and i['bin_left_edge']==-4 and i['bin_width']==1 and i['bins']==8
assert i['counts_complete'] is True and i['counts_sum']==i['source_pixels']==4
assert i['source_intensity_calibration']==dict(origin=7.5,scale=-2,unit='arb') and i['intensity_calibration_applied'] is False
assert i['native_histogram_result']['image']['data_type_code']==11 and i['native_histogram_result']['raw_bytes']==64
assert i['native_receipt']==s['native_receipt'] and i['source_metadata']==s['source'] and i['histogram_metadata']==s['image']
assert i['source_calibration_dm']==s['source']['calibration'] and i['histogram_calibration']==s['image']['calibration']
assert m['source_dtype']=='float32' and m['output_dtype']=='uint32' and m['source_data_type_code']==2
assert m['descriptor_unchanged'] is None and m['source_descriptor_reobserved'] is False and i['dm_file_save'] is False and i['pixel_capture_atomic'] is False
assert hashlib.sha256((p/'input.npy').read_bytes()).hexdigest()==i['input_sha256']==m['input_sha256']
assert hashlib.sha256(json.dumps(i,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()==m['input_metadata_sha256']
print('independent uint32 histogram package PASS; synthetic receipt only')`;
  const check=spawnSync(process.env.DM_TEST_PYTHON||'python',['-c',script,target],{encoding:'utf8'});
  assert.equal(check.status,0,check.stderr);assert.match(check.stdout,/package PASS/);
});

test('histogram complete sparse 4096-bin destination does not require 4096 source pixels',t=>{
  const directory=temporary(t),args=[77,4096,histogramFloatBits(-4),histogramFloatBits(4)],counts=Array(4096).fill(0);
  counts[0]=1;counts[4095]=1;
  const snapshot=prepare(directory,savedHistogramFixture(args,'saved-histogram',{shape:[1,2],counts}));
  const receipt=handoff(options(directory,snapshot));assert.deepEqual(receipt.shape,[4096]);
  const info=json(path.join(directory,'capture','input.json'));assert.equal(info.source_pixels,2);
  assert.equal(info.native_storage_bytes,16384);assert.equal(info.wire_raw_bytes,32768);assert.equal(info.counts_sum,2);
});

test('identity-intensity histogram handoff keeps observed native axis separate from exact bin edges and uint32 counts',t=>{
  const directory=temporary(t),payload={...histogramIntensityFixture(),native_receipt:savedHistogramFixture().native_receipt};
  const snapshot=prepare(directory,payload),args=options(directory,snapshot),receipt=handoff(args);
  const target=path.join(directory,'capture'),info=json(path.join(target,'input.json'));
  assert.deepEqual(handoff(args),receipt);assert.deepEqual(info.axes,['intensity_bin']);
  assert.equal(info.axis_roles[0].role,'intensity_bin');assert.equal(info.calibration_complete,true);
  assert.equal(info.axis_mode,'source_intensity_units');assert.equal(info.axis_calibration_is_bin_left_edge,true);
  for(const key of ['axis_zero_requested','axis_zero_observed','axis_scale_observed','axis_roundtrip_error',
    'axis_roundtrip_bound','axis_max_coordinate_error','axis_tolerance','axis_unavailable_reason'])assert.deepEqual(info[key],payload[key]);
  assert.equal(info.histogram_calibration[0].origin,4);assert.equal(info.histogram_calibration[0].calibrated_value_at_pixel_zero,-4);
  assert.equal(info.intensity_calibration_applied,false);assert.equal(info.dtype,'uint32');
  assert.equal(info.raw_bytes,32);assert.equal(info.wire_raw_bytes,64);
  const check=spawnSync(process.env.DM_TEST_PYTHON||'python',['-c',
    "import numpy as np,sys; a=np.load(sys.argv[1],allow_pickle=False); assert a.dtype==np.dtype('<u4') and a.shape==(8,); assert a.tolist()==[1,0,1,0,0,1,0,1]",
    path.join(target,'input.npy')],{encoding:'utf8'});assert.equal(check.status,0,check.stderr);
});

test('saved calibrated histograms reject fake units, offset observations and inflated roundtrip bounds before writing',t=>{
  for(const change of [p=>p.source_intensity_calibration.origin=7.5,p=>p.source_intensity_calibration.scale=-2,
    p=>p.axis_tolerance='binary32 arbitrary tolerance',p=>p.axis_roundtrip_bound=1,p=>p.axis_max_coordinate_error=1,
    p=>{p.image.calibration[0].calibrated_value_at_pixel_zero+=2**-22;p.axis_zero_observed=p.image.calibration[0].calibrated_value_at_pixel_zero;p.axis_roundtrip_error=2**-22;}]) {
    const directory=temporary(t),payload={...histogramIntensityFixture(),native_receipt:savedHistogramFixture().native_receipt};
    change(payload);const snapshot=prepare(directory,payload);
    assert.throws(()=>handoff(options(directory,snapshot)),undefined,change.toString());
    assert.deepEqual(fs.readdirSync(directory),['saved.json']);
  }
});

test('inconsistent histogram counts, source, calibration, encoding or receipt are rejected before creating outputs',t=>{
  const changes=[p=>p.values_base64=wire([1,0,1,0,0,1,0,0]).toString('base64'),
    p=>p.values_base64=wire([1,0,1,0,0,1,0,-1]).toString('base64'),
    p=>p.values_base64=wire([1,0,1,0,0,1,0,0.5]).toString('base64'),
    p=>p.values_base64=wire([1,0,1,0,0,1,0,Infinity]).toString('base64'),
    p=>p.values_base64=wire([1,0,1,0,0,1,0,4294967296]).toString('base64'),
    p=>p.values_base64+='=',p=>p.counts_encoding='uint32 little endian',p=>p.raw_bytes=p.output_bytes,p=>p.output_bytes=p.raw_bytes,
    p=>p.dtype='float64',p=>p.image.data_type_code=12,p=>p.image.shape=[1,8],p=>p.image_id=p.image.id=0,
    p=>p.source_image_id++,p=>p.source.dtype='uint32',p=>p.source_pixels++,p=>p.counts_sum++,p=>p.counts_complete=false,
    p=>p.bin_left_edge++,p=>p.bin_width=0.5,p=>p.requested_range[0]++,p=>p.bin_edge_rule='bin centers',
    p=>p.axis_mode='source_intensity_units',p=>p.axis_calibration_is_bin_left_edge=true,p=>p.image.calibration_complete=true,
    p=>p.source_intensity_calibration.scale=null,p=>p.intensity_calibration_applied=true,p=>p.intensity_semantics='calibrated electron counts',
    p=>p.source_write_requested=true,p=>p.snapshot_atomic=true,p=>delete p.retention,p=>p.retention.creation_request_id='other',
    p=>p.native_receipt.normalized_args[0]++,p=>p.native_receipt.original_operation='READ',p=>p.native_receipt.result_type='native_line_profile',
    p=>p.native_receipt.exec_tid=p.native_receipt.worker_tid,p=>p.native_receipt.state='running'];
  for (let i=0;i<changes.length;++i) {
    const directory=temporary(t),payload=savedHistogramFixture();changes[i](payload);const snapshot=prepare(directory,payload);
    assert.throws(()=>handoff(options(directory,snapshot)),undefined,`negative ${i}: ${changes[i]}`);
    assert.deepEqual(fs.readdirSync(directory),['saved.json']);
  }
});

test('same saved histogram handoff ID verifies identical files; path or saved receipt changes conflict',t=>{
  const directory=temporary(t),snapshot=prepare(directory),args=options(directory,snapshot),first=handoff(args);
  const files=[snapshot,path.join(directory,'handoff-requests',args.requestId+'.json'),
    ...['capture.json','input.json','input.npy'].map(name=>path.join(directory,'capture',name))];
  const before=files.map(filename=>[sha(fs.readFileSync(filename)),fs.statSync(filename).mtimeMs]);
  assert.deepEqual(handoff(args),first);assert.deepEqual(files.map(filename=>[sha(fs.readFileSync(filename)),fs.statSync(filename).mtimeMs]),before);
  assert.throws(()=>handoff({...args,output:'different'}),/CONFLICT/);
  const changed=json(snapshot);changed.native_receipt.timings_us.queue++;save(snapshot,changed);
  assert.throws(()=>handoff(args),/CONFLICT/);assert.deepEqual(files.slice(1).map(filename=>[sha(fs.readFileSync(filename)),fs.statSync(filename).mtimeMs]),before.slice(1));
});

test('histogram handoff refuses existing output and preserves incomplete request journals without retry',t=>{
  const directory=temporary(t),snapshot=prepare(directory),args=options(directory,snapshot),target=path.join(directory,'capture');
  fs.mkdirSync(target);fs.writeFileSync(path.join(target,'input.npy'),'USER BYTES');
  assert.throws(()=>handoff(args),/exist/i);assert.equal(fs.readFileSync(path.join(target,'input.npy'),'utf8'),'USER BYTES');
  const failed=json(path.join(directory,'handoff-requests',args.requestId+'.json'));assert.equal(failed.state,'FAILED');
  assert.equal(handoff(args).state,'UNKNOWN_INCOMPLETE');
  assert.equal(fs.readFileSync(path.join(target,'input.npy'),'utf8'),'USER BYTES');
});

test('coherently rehashed histogram sidecar still cannot replace the saved native scientific identity',t=>{
  const directory=temporary(t),snapshot=prepare(directory),args=options(directory,snapshot);handoff(args);
  const target=path.join(directory,'capture'),infoPath=path.join(target,'input.json'),manifestPath=path.join(target,'capture.json');
  const info=json(infoPath),manifest=json(manifestPath),journalPath=path.join(directory,'handoff-requests',args.requestId+'.json'),journal=json(journalPath);
  info.bin_left_edge=3;info.requested_range=[3,11];info.source_intensity_calibration.scale=2;
  save(infoPath,info);manifest.input_metadata_sha256=sha(canonical(info));manifest.input_metadata_file_sha256=sha(fs.readFileSync(infoPath));save(manifestPath,manifest);
  for(const name of ['input.npy','input.json','capture.json'])journal.capture_receipt.files_sha256[name]=sha(fs.readFileSync(path.join(target,name)));
  save(journalPath,journal);assert.throws(()=>handoff(args),/metadata\/receipt/);
});
