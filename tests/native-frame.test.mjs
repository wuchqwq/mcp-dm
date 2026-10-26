// Typed protocol/encoder controls only; no DigitalMicrograph is loaded here.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {NativeBridge,validateNativeFrame,validateNativeDataSnapshot,nativeFrameAncestry} from '../lib/native_bridge.mjs';
import {frameHandoffFixture} from './fixtures/native-frame-handoff.mjs';
import {readFixture} from './fixtures/native-operations.mjs';

function directFrameRead(options={}) {
  const f=frameHandoffFixture(options);
  const args=[f.result.image_id,0,0,4,2];
  const read=readFixture(args,{source:structuredClone(f.result.image),provenance:structuredClone(f.provenance)});
  const bytes=Buffer.alloc(32);[0,32767,32768,65535,1,100,1024,65534].forEach((value,i)=>bytes.writeFloatLE(value,i*4));
  read.values_base64=bytes.toString('base64');read.frame_ancestry=structuredClone(f.ancestry);
  return {f,args,read};
}

test('FRAME declares independent float32 storage and keeps unknown units distinct from scientific calibration',()=>{
  for(const unknownUnits of [false,true]) {
    const {f,args,read}=directFrameRead({unknownUnits});
    validateNativeFrame(f.result,[31,1]);validateNativeDataSnapshot(read,args);
    assert.equal(f.result.source.dtype,'uint16');assert.equal(f.result.image.dtype,'float32');
    assert.equal(f.result.image.calibration_complete,!unknownUnits);
    assert.equal(f.result.frame_axis.unit,null);assert.equal(f.result.frame_axis.usable,false);
    assert.equal(f.result.frame_axis.calibrated_value,.75);
    assert.equal(nativeFrameAncestry(read).result.source.id,31);
    const reordered=structuredClone(read);reordered.source=Object.fromEntries(Object.entries(read.source).reverse());
    validateNativeDataSnapshot(reordered,args);
  }
});

test('FRAME typed result refuses wrong frame, source, axes, conversion, alias and known allocation budgets',()=>{
  const mutations=[r=>r.frame_index=0,r=>r.source_image_id=32,r=>r.image_id=r.source_image_id,
    r=>r.source.ndim=2,r=>r.source.dtype='int16',r=>r.source.data_type_code=1,r=>r.source.is_unsigned=false,
    r=>r.source.packing_style=2,r=>r.source.shape.reverse(),r=>r.source.dm_dimensions.reverse(),
    r=>r.frame_axis.dm_dimension=0,r=>r.frame_axis.numpy_axis=2,r=>r.frame_axis.index_base=1,
    r=>r.frame_axis.role='time',r=>r.frame_axis.calibrated_value=1,r=>r.frame_axis.usable=true,
    r=>r.image.calibration[0].scale*=-1,r=>r.image.calibration[1].origin++,
    r=>r.dtype_conversion.lossless_values=false,r=>r.dtype_conversion.input_dtype='uint32',
    r=>r.dtype_conversion.output_dtype='uint16',r=>r.output_bytes/=2,r=>r.validation_peak_new_image_bytes=r.output_bytes,
    r=>r.intensity_calibration_applied=true,r=>r.intensity_calibration_output.scale=2,
    r=>r.source_write_requested=true,r=>r.computation='NumPy cast',r=>r.visible_dm_document=true,
    r=>r.candidate_probe=true,r=>r.qualification='NOT_QUALIFIED'];
  for(const [index,mutate] of mutations.entries()) {
    const {result}=frameHandoffFixture();mutate(result);
    assert.throws(()=>validateNativeFrame(result,[31,1]),Error,'independent mutation '+index);
  }
});

test('direct FRAME READ rejects signed-wrap, stretched and fractional values without restricting a derived operation',()=>{
  for(const value of [-32768,-1,.5,65536,Infinity,NaN]) {
    const {args,read}=directFrameRead();const bytes=Buffer.from(read.values_base64,'base64');bytes.writeFloatLE(value,0);read.values_base64=bytes.toString('base64');
    assert.throws(()=>validateNativeDataSnapshot(read,args),Error,'impossible copied uint16 value '+value);
  }
  const {read,args}=directFrameRead();
  read.source_image_id=read.source.id=88;read.source_provenance={operation:'UNARY',request_id:'derived-negate',source_image_ids:[77],semantics:'native negate'};
  const bytes=Buffer.from(read.values_base64,'base64');bytes.writeFloatLE(-32768,0);read.values_base64=bytes.toString('base64');
  validateNativeDataSnapshot(read,[88,...args.slice(1)]);
});

test('frame ancestry refuses another creation, a projection, missing parent and false binary lineage',()=>{
  for(const mutate of [r=>r.frame_ancestry.normalized_args[1]=2,r=>r.frame_ancestry.result.frame_index=0,
    r=>r.source_provenance.request_id='foreign-frame',r=>r.source_provenance.source_image_ids=[32],
    r=>r.source_provenance=null,r=>r.source_provenance.operation='BINARY',r=>r.frame_ancestry.status='unresolved_lineage',
    r=>r.frame_ancestry.result.retention={token:9}]) {
    const {read}=directFrameRead();mutate(read);assert.throws(()=>nativeFrameAncestry(read));
  }
  const {read}=directFrameRead();read.source_provenance.operation='UNARY';
  assert.throws(()=>nativeFrameAncestry(read),/cannot alias/);
});

test('invalid FRAME submission is refused before any pipe exchange',async()=>{
  const bridge=new NativeBridge({session:'a'.repeat(32)});let calls=0;
  bridge._exchange=async()=>{calls++;throw Error('must not dispatch');};
  try {
    for(const args of [[31],[31,-1],[31,1.5],[31,2**32],[0,1],[31,1,2]])
      await assert.rejects(bridge.execute('FRAME',args,{requestId:'saved-frame'}),TypeError);
    assert.equal(calls,0);
  } finally {bridge.close();}
});

test('actual C++ surrogate FRAME/READ fixture passes independent Node typed validation',
  {skip:!process.env.DM_NATIVE_FRAME_FIXTURE},()=>{
    const f=JSON.parse(fs.readFileSync(process.env.DM_NATIVE_FRAME_FIXTURE,'utf8'));
    validateNativeFrame(f.frame_result,f.frame_args);validateNativeDataSnapshot(f.read_result,f.read_args);
    assert.deepEqual(nativeFrameAncestry(f.read_result).normalized_args,f.frame_args);
    assert.equal(f.frame_result.retention.creation_request_id,nativeFrameAncestry(f.read_result).request_id);
  });
