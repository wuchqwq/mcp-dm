import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeHistogram, validateNativeShow} from '../lib/native_bridge.mjs';
import {histogramArgs, histogramFixture, histogramFloatBits} from './fixtures/native-histogram.mjs';

test('HISTOGRAM admits empty bins and more bins than pixels through the exact native count contract', () => {
  for (const bins of [2, 8, 64, 4096]) {
    const args=[77,bins,histogramFloatBits(-4),histogramFloatBits(4)];
    const counts=Array(bins).fill(0); counts[bins-1]=1;
    const result=histogramFixture(args,'sparse-counts',{shape:[1,1],counts});
    validateNativeHistogram(result,args,'sparse-counts');
    assert.equal(result.output_bytes,bins*4); assert.equal(result.raw_bytes,bins*8);
    assert.equal(result.dtype,'uint32'); assert.equal(result.axis_mode,'bin_index');
  }
});

test('HISTOGRAM validates the full source, wire type, bin geometry and retained original identity', () => {
  const changes=[r=>r.image_id=r.image.id=0,r=>r.source_image_id++,r=>r.image_id=r.source_image_id,
    r=>r.source.id++,r=>r.source.dtype='uint32',r=>r.source.pixels++,r=>r.source.packing_style=2,
    r=>r.source_pixels=0,r=>r.source_pixels=4194305,r=>r.bins++,r=>r.shape=[1,8],r=>r.image.shape=[4],
    r=>r.source_min=-5,r=>r.source_max=5,r=>r.source_min=NaN,r=>r.requested_range[0]=-5,r=>r.bin_width=2,
    r=>r.bin_left_edge=0,r=>r.bin_edge_rule='centres',r=>r.binning='uniform linear bins from another range',
    r=>r.counts_encoding='uint32 little-endian',r=>r.raw_bytes=32,r=>r.output_bytes=64,r=>r.counts_sum++,
    r=>r.dtype='float64',r=>r.image.dtype='float64',r=>r.image.data_type_code=12,r=>r.image.is_unsigned=false,
    r=>r.axis_mode='source_intensity_units',r=>r.axis_calibration_is_bin_left_edge=true,
    r=>r.image.calibration_complete=true,r=>r.image.calibration[0].scale=2,r=>r.image.calibration[0].origin=1,
    r=>r.source_intensity_calibration.scale=Infinity,r=>r.source_intensity_calibration.unit='',
    r=>r.intensity_calibration_applied=true,r=>r.intensity_semantics='electrons',r=>r.source_write_requested=true,
    r=>r.snapshot_atomic=true,r=>r.ownership='permanent',r=>r.candidate_probe=true,r=>r.qualification='NOT_QUALIFIED',
    r=>delete r.retention,r=>r.retention.creation_request_id='other-operation',r=>r.retention.token=0];
  for(const change of changes) {
    const result=histogramFixture(); change(result);
    assert.throws(()=>validateNativeHistogram(result,histogramArgs,'saved-histogram'),change.toString());
  }
  for(const bins of [0,1,4097,0xffffffff]) assert.throws(()=>validateNativeHistogram(histogramFixture(),[77,bins,...histogramArgs.slice(2)]));
  for(const args of [[77,8,-1,histogramArgs[3]],[77,8,'0',histogramArgs[3]],
    [77,8,histogramFloatBits(NaN),histogramArgs[3]],[77,8,histogramArgs[3],histogramArgs[2]]])
    assert.throws(()=>validateNativeHistogram(histogramFixture(),args));
});

test('HISTOGRAM refuses fractional, negative, nonfinite, oversized or noncanonical binary64 counts', () => {
  for(const value of [-1,0.5,NaN,Infinity,4294967296,5]) {
    const result=histogramFixture(),bytes=Buffer.from(result.values_base64,'base64'); bytes.writeDoubleLE(value,0);
    result.values_base64=bytes.toString('base64');
    assert.throws(()=>validateNativeHistogram(result,histogramArgs));
  }
  const result=histogramFixture(),alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const end=result.values_base64.indexOf('=')-1, chars=[...result.values_base64];
  chars[end]=alphabet[alphabet.indexOf(chars[end])+1]; result.values_base64=chars.join('');
  assert.deepEqual(Buffer.from(result.values_base64,'base64'),Buffer.from(histogramFixture().values_base64,'base64'));
  assert.throws(()=>validateNativeHistogram(result,histogramArgs),/canonical/);
});

test('rank-one SHOW cannot drop its descriptor or mislabel native uint32 counts as float64 samples', () => {
  const image=histogramFixture().image;
  const delivery=()=>({backend:'digitalmicrograph-native',image_id:99,delivery:'visible_dm_document',document_visible:true,
    operator:'ImageGetOrCreateImageDocument + ImageDocumentShow',rank:1,display_family:'native_1d_image_document',
    display_class:'host_selected',retained_operation:'HISTOGRAM',one_dimensional_display:structuredClone(image),
    ownership:'host document holds image; plugin result reference released at normal STOP/cleanup',
    source_write_requested:false,snapshot_atomic:false,file_saved:false,model_visual_verification:false});
  validateNativeShow(delivery(),99);
  for(const change of [r=>delete r.one_dimensional_display,r=>r.retained_operation='PROFILE',r=>r.image=r.one_dimensional_display,
    r=>r.one_dimensional_display.dtype='float64',r=>r.one_dimensional_display.native_mean_supported=true,
    r=>r.one_dimensional_display.calibration[0].origin=NaN,r=>r.one_dimensional_display.calibration[0].scale=Infinity,
    r=>r.one_dimensional_display.calibration[0].usable=true,r=>r.one_dimensional_display.calibration[0].issue=null]) {
    const result=delivery(); change(result); assert.throws(()=>validateNativeShow(result,99),change.toString());
  }
});
