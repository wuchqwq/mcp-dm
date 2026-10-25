import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeHistogram, validateNativeShow} from '../lib/native_bridge.mjs';
import {histogramArgs,histogramFixture,histogramFloatBits,histogramIntensityFixture,histogramIndexAxisFixture,histogramShowFixture} from './fixtures/native-histogram.mjs';

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

test('identity-intensity histogram axis binds exact native origin, local float32 roundtrip and quarter-bin budget',()=>{
  const result=histogramIntensityFixture();validateNativeHistogram(result,histogramArgs,'saved-histogram');
  assert.equal(result.image.calibration[0].origin,4);assert.equal(result.image.calibration[0].calibrated_value_at_pixel_zero,-4);
  assert.equal(result.axis_roundtrip_bound,2**-20);assert.equal(result.axis_max_coordinate_error,2**-20);
  validateNativeShow(histogramShowFixture(result),99);
  for(const change of [r=>r.source_intensity_calibration.origin=7.5,r=>r.source_intensity_calibration.scale=-2,
    r=>r.source_intensity_calibration.unit=null,r=>r.image.calibration[0].origin=-4,
    r=>r.axis_zero_requested=0,r=>r.axis_zero_observed=0,r=>r.axis_scale_observed=2,
    r=>r.axis_roundtrip_error=1e-13,r=>r.axis_roundtrip_bound=1,r=>r.axis_max_coordinate_error=1,
    r=>r.axis_tolerance='binary32 1000 ulp',r=>r.axis_unavailable_reason='not_needed',
    r=>{r.image.calibration[0].calibrated_value_at_pixel_zero+=2**-22;r.axis_zero_observed=r.image.calibration[0].calibrated_value_at_pixel_zero;r.axis_roundtrip_error=2**-22;}]) {
    const bad=histogramIntensityFixture();change(bad);
    assert.throws(()=>validateNativeHistogram(bad,histogramArgs,'saved-histogram'),change.toString());
    assert.throws(()=>validateNativeShow(histogramShowFixture(bad),99),change.toString());
  }
});

test('histogram SHOW closes arbitrary complete/index axes but retains historical index receipts',()=>{
  const old=histogramShowFixture();delete old.histogram_axis_context;validateNativeShow(old,99);
  const complete=histogramShowFixture(histogramIntensityFixture());delete complete.histogram_axis_context;
  assert.throws(()=>validateNativeShow(complete,99),/creation axis context/);
  for(const [key,value] of [['origin',2],['calibrated_value_at_pixel_zero',2],['scale',2]]) {
    const bad=structuredClone(old);bad.one_dimensional_display.calibration[0][key]=value;
    assert.throws(()=>validateNativeShow(bad,99),key);
  }
  const changed=histogramShowFixture(histogramIntensityFixture());changed.histogram_axis_context.requested_range=[-3,5];
  assert.throws(()=>validateNativeShow(changed,99));
});

test('histogram optional style receipts distinguish observed bars, default reasons and historical absence',()=>{
  const scope='host line-plot presentation only; no scientific claim; reversible in the DM UI';
  const bar={...histogramShowFixture(),display_style:'histogram',display_style_scope:scope};validateNativeShow(bar,99);
  const fallback={...histogramShowFixture(),display_style:'default',display_style_scope:scope,display_style_reason:'style_entrypoints_unavailable'};
  validateNativeShow(fallback,99);
  for(const change of [r=>r.display_style='bars',r=>r.display_style_scope='scientific histogram',r=>r.display_style_reason='unknown',
    r=>delete r.display_style_scope,r=>r.retained_operation='PROFILE']) {
    const bad=structuredClone(bar);change(bad);assert.throws(()=>validateNativeShow(bad,99),change.toString());
  }
  for(const change of [r=>delete r.display_style_reason,r=>r.display_style_reason='unknown']) {
    const bad=structuredClone(fallback);change(bad);assert.throws(()=>validateNativeShow(bad,99),change.toString());
  }
});

test('underflow or coarse index origin cannot be legitimized by a large axis tolerance',()=>{
  for(const [minimum,maximum] of [[0,2**-126],[2**-149,1],[-(2**24),Math.fround(-(2**24)+2)]]) {
    const args=[77,4096,histogramFloatBits(minimum),histogramFloatBits(maximum)],counts=Array(4096).fill(0);counts[0]=4;
    const result=histogramFixture(args,'saved-histogram',{counts});
    Object.assign(result,{axis_mode:'source_intensity_units',axis_calibration_is_bin_left_edge:true,
      source_intensity_calibration:{origin:0,scale:1,unit:'arb'},axis_zero_requested:minimum,axis_zero_observed:minimum,
      axis_scale_observed:Math.fround(result.bin_width),axis_roundtrip_error:0,axis_roundtrip_bound:0,
      axis_max_coordinate_error:0,axis_tolerance:'binary32_local_ulp_v1',axis_unavailable_reason:null});
    result.image.calibration_complete=true;
    Object.assign(result.image.calibration[0],{origin:-minimum/result.bin_width,calibrated_value_at_pixel_zero:minimum,
      scale:Math.fround(result.bin_width),unit:'arb',usable:true,issue:null});
    assert.throws(()=>validateNativeHistogram(result,args,'saved-histogram'));
    assert.throws(()=>validateNativeShow(histogramShowFixture(result),99));
  }
});

test('current index-axis fallback preserves explicit null observations and a reason consistent with source calibration',()=>{
  const result=histogramIndexAxisFixture();validateNativeHistogram(result,histogramArgs,'saved-histogram');
  validateNativeShow(histogramShowFixture(result),99);
  for(const change of [r=>r.axis_unavailable_reason='unknown',r=>r.axis_unavailable_reason='source_intensity_units_unavailable',
    r=>r.axis_unavailable_reason='axis_entrypoint_unavailable',r=>r.axis_unavailable_reason='binary32_axis_not_resolved',
    r=>r.axis_zero_observed=0,r=>r.axis_tolerance='binary32 unrestricted',r=>delete r.axis_max_coordinate_error]) {
    const bad=histogramIndexAxisFixture();change(bad);assert.throws(()=>validateNativeHistogram(bad,histogramArgs,'saved-histogram'));
    assert.throws(()=>validateNativeShow(histogramShowFixture(bad),99));
  }
  result.source_intensity_calibration={origin:0,scale:1,unit:'arb'};result.axis_unavailable_reason='axis_entrypoint_unavailable';
  validateNativeHistogram(result,histogramArgs,'saved-histogram');validateNativeShow(histogramShowFixture(result),99);
});

test('historical bin-index zero placeholders remain queryable without qualifying their superseded physical-axis tolerance',()=>{
  const result=histogramFixture();Object.assign(result,{axis_zero_requested:0,axis_zero_observed:0,axis_scale_observed:0,
    axis_roundtrip_error:0,axis_tolerance:'binary32 divide/multiply round trip: 8 ulp of max(|origin|,|scale|,1)'});
  validateNativeHistogram(result,histogramArgs,'saved-histogram');validateNativeShow(histogramShowFixture(result),99);
  const calibrated=histogramIntensityFixture();calibrated.axis_tolerance=result.axis_tolerance;
  assert.throws(()=>validateNativeHistogram(calibrated,histogramArgs,'saved-histogram'));
  for(const change of [r=>r.axis_zero_observed=1,r=>r.axis_roundtrip_bound=1,r=>r.axis_tolerance='binary32 anything']) {
    const bad=structuredClone(result);change(bad);assert.throws(()=>validateNativeHistogram(bad,histogramArgs,'saved-histogram'));
  }
});

test('non-power-of-two bin widths preserve native float32 scale and separately bound accumulated coordinate drift',()=>{
  // L=-1, W=f32(2/3), q=-1.5, r=-1, all four counts hand-enumerated.
  const args=[77,3,histogramFloatBits(-1),histogramFloatBits(1)],result=histogramFixture(args,'saved-histogram',{counts:[1,2,1]});
  Object.assign(result,{axis_mode:'source_intensity_units',axis_calibration_is_bin_left_edge:true,
    source_intensity_calibration:{origin:0,scale:1,unit:'arb'},axis_zero_requested:-1,axis_zero_observed:-1,
    axis_scale_observed:0.6666666865348816,axis_roundtrip_error:0,axis_roundtrip_bound:1.9868215161977787e-7,
    axis_max_coordinate_error:2.3841858154405315e-7,axis_tolerance:'binary32_local_ulp_v1',axis_unavailable_reason:null});
  result.image.calibration_complete=true;
  Object.assign(result.image.calibration[0],{origin:1.5,calibrated_value_at_pixel_zero:-1,
    scale:0.6666666865348816,unit:'arb',usable:true,issue:null});
  validateNativeHistogram(result,args,'saved-histogram');validateNativeShow(histogramShowFixture(result),99);
  result.axis_max_coordinate_error=result.axis_roundtrip_bound;
  assert.throws(()=>validateNativeHistogram(result,args,'saved-histogram'));
});
