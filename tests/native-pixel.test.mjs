// Protocol/coordinate controls only; neither fixtures nor C++ callbacks prove DM.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {NativeBridge,validateNativePixelCrop,validateDerivedOperation,validateNativeDataSnapshot,nativeScientificSemantics} from '../lib/native_bridge.mjs';
import {pixelCropFixture,pixelFilterFixture,pixelFourierFixture,pixelReadFixture} from './fixtures/native-pixel.mjs';
import {fourierFixture} from './fixtures/native-operations.mjs';

test('explicit pixel crop preserves raw signed calibration and unknown units; old default is unchanged',()=>{
  for(const unknownUnits of [true,false]) {
    const result=pixelCropFixture({unknownUnits});validateNativePixelCrop(result,[77,1,2,5,6]);
    assert.equal(result.source.calibration_complete,!unknownUnits);
    assert.equal(result.image.calibration[0].scale,-.25);assert.equal(result.image.calibration[0].origin,4);
    assert.equal(result.image.calibration[0].unit,unknownUnits?null:'nm');
  }
  validateDerivedOperation(fourierFixture('FFT'),'FFT',[77],2);
});
test('pixel crop rejects guessed mode, coordinates, calibration, source identity and evidence',()=>{
  for(const mutate of [r=>delete r.coordinate_mode,r=>r.coordinate_mode='physical',r=>r.source_image_id++,r=>r.image_id=77,
    r=>r.image.calibration[0].unit='pixel',r=>r.image.calibration[0].origin++,r=>r.image.calibration[0].scale=1,
    r=>r.source.calibration[0].scale=0,r=>r.source.calibration[0].issue='invalid_calibration_and_unknown_units',
    r=>r.effective_rect[0]++,r=>r.calibration_zero_verification[0].tolerance=1,r=>r.output_bytes++,
    r=>r.source_write_requested=true,r=>r.candidate_probe=true,r=>r.qualification='NOT_QUALIFIED']) {
    const result=pixelCropFixture();mutate(result);assert.throws(()=>validateNativePixelCrop(result,[77,1,2,5,6]));
  }
});
test('all pixel filters and Fourier operations retain actual metadata without requiring physical units',()=>{
  for(const unknownUnits of [false,true]) {
    for(const kind of [1,2,3,4]) validateDerivedOperation(pixelFilterFixture(kind,{unknownUnits}),'FILTER_PIXEL',[77,kind],1);
    for(const operation of ['FFT_PIXEL','IFFT_PIXEL','REAL_PIXEL','IMAG_PIXEL','VENDOR_ARG_PIXEL','VENDOR_NORM_PIXEL']) {
      const result=pixelFourierFixture(operation,{unknownUnits});validateDerivedOperation(result,operation,[77],2);
      if(result.frequency_grid) {
        assert.deepEqual(result.frequency_grid.axes.map(a=>a.cycles_per_pixel_step),[.125,.25]);
        assert.equal(result.frequency_grid.axes[0].physical_frequency_step,null);
        assert.equal(result.frequency_grid.axes[0].native_calibration_scale,result.image.calibration[0].scale);
      }
    }
  }
});
test('pixel Fourier refuses physical-grid laundering, invalid numeric calibration, old result version and wrong operation',()=>{
  for(const mutate of [r=>delete r.coordinate_mode,r=>r.operation='FFT',r=>r.coordinate_mode='physical',
    r=>r.frequency_grid.coordinate_mode='physical',r=>r.frequency_grid.axes[0].physical_frequency_step=1,
    r=>r.frequency_grid.axes[0].unit='1/nm',r=>r.frequency_grid.axes[0].native_calibration_scale=1,
    r=>r.frequency_grid.axes[0].native_calibration_unit='nm',r=>r.frequency_grid.axes[0].frequency_at_index_zero=.5,
    r=>r.frequency_grid.axes[0].cycles_per_pixel_step=-.125,r=>r.source.calibration[0].scale=0,
    r=>r.image.calibration[0].issue='invalid_calibration_and_unknown_units',r=>r.candidate_probe=true,r=>r.qualification='NOT_QUALIFIED']) {
    const result=pixelFourierFixture();mutate(result);assert.throws(()=>validateDerivedOperation(result,'FFT_PIXEL',[77],2));
  }
  assert.throws(()=>validateDerivedOperation(pixelFourierFixture(),'FFT_PIXEL',[77],1));
  assert.throws(()=>validateDerivedOperation(pixelFourierFixture(),'FFT',[77],2));
});
test('READ supplies cycles per pixel or spatial pixel axes without mixing native calibration units',()=>{
  for(const spatial of [false,true]) {
    const {result,args}=pixelReadFixture({spatial});validateNativeDataSnapshot(result,args);
    const science=nativeScientificSemantics(result,{requireFourierContext:true});
    assert.equal(science.coordinate_mode,'pixel');assert.equal(science.physical_calibration_applied,false);
    assert.equal(science.domain,spatial?'spatial':'frequency');
    assert.deepEqual(science.coordinate_axes.map(a=>a.unit),[spatial?'pixel':'cycles_per_pixel',spatial?'pixel':'cycles_per_pixel']);
    assert.deepEqual(science.coordinate_axes.map(a=>a.scale),spatial?[1,1]:[.125,.25]);
    assert.deepEqual(science.coordinate_axes.map(a=>a.calibrated_value_at_pixel_zero),spatial?[2,1]:[-.25,-.25]);
    assert.deepEqual(science.coordinate_axes.map(a=>a.native_minus_mathematical_zero),[null,null]);
    assert.equal(result.source.calibration_complete,false);
  }
});
test('QUERY preserves explicit pixel mode and rejects a different submitted mode or missing scientific identity',()=>{
  const bridge=new NativeBridge({session:'a'.repeat(32)}),result=pixelFourierFixture();
  const reply={protocol:'NB2',session:'a'.repeat(32),id:'saved-pixel',state:'completed',host_pid:123,worker_tid:20,exec_tid:10,
    timings_us:{queue:0,execute:1},original_operation:'FFT_PIXEL',normalized_args:[77],result_type:'native_fourier_operation',result_version:2,result};
  try {
    bridge._validateReply(reply,'saved-pixel');
    assert.equal(bridge._validateOperationResult('QUERY',[],reply).original_operation,'FFT_PIXEL');
    assert.throws(()=>bridge._validateOperationResult('FFT',[77],reply),/differ/);
    assert.throws(()=>bridge._validateReply({...reply,result_version:1},'saved-pixel'),/schema identity/);
    const {result:read,args}=pixelReadFixture();delete read.scientific_context;
    assert.throws(()=>nativeScientificSemantics(read,{requireFourierContext:true}),/SCIENTIFIC_CONTEXT_REQUIRED/);
    assert.throws(()=>bridge._validateOperationResult('CROP',[77,1,2,5,6],{...reply,original_operation:'CROP',normalized_args:[77,1,2,5,6],result_type:'image_crop',result_version:1,result:pixelCropFixture()}),/Legacy CROP/);
  } finally {bridge.close();}
});
test('bad pixel-mode arguments are refused before any native exchange',async()=>{
  const bridge=new NativeBridge({session:'a'.repeat(32)});let exchanges=0;
  bridge._exchange=async()=>{exchanges++;throw Error('must not dispatch');};
  try {
    for(const [operation,args] of [['FFT_PIXEL',[0]],['CROP_PIXEL',[0,0,0,4,4]],['FILTER_PIXEL',[0,1]],
      ['FFT_PIXEL',[77,1]],['FILTER_PIXEL',[77,-1]],['FFT_PIXEL',[-1]]])
      await assert.rejects(bridge.execute(operation,args,{requestId:'saved-pixel'}),TypeError);
    assert.equal(exchanges,0);
  } finally {bridge.close();}
});
test('actual C++ pixel surrogate packets pass independent Node validation', {skip:!process.env.DM_NATIVE_PIXEL_FIXTURE},()=>{
  const packets=JSON.parse(fs.readFileSync(process.env.DM_NATIVE_PIXEL_FIXTURE,'utf8'));
  assert.ok(packets.length>=20);
  for(const {operation,args,result,result_version} of packets) {
    if(operation==='CROP_PIXEL') validateNativePixelCrop(result,args);
    else if(operation==='READ') {validateNativeDataSnapshot(result,args);nativeScientificSemantics(result,{requireFourierContext:true});}
    else validateDerivedOperation(result,operation,args,result_version);
  }
});
