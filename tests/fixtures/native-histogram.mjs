import {imageMetadata} from './native-operations.mjs';

// Independently enumerated protocol fixtures, never a DM operator or proof of
// vendor edge behavior. More bins than source pixels is deliberately valid.
export function histogramFloatBits(value) {
  const bytes=Buffer.alloc(4); bytes.writeFloatLE(value); return bytes.readUInt32LE();
}
export const histogramArgs=[77,8,histogramFloatBits(-4),histogramFloatBits(4)];
export function histogramFixture(args=histogramArgs,requestId='saved-histogram',options={}) {
  const [sourceId,bins,minBits,maxBits]=args;
  const f32=bits=>{const bytes=Buffer.alloc(4);bytes.writeUInt32LE(bits);return bytes.readFloatLE();};
  const minimum=f32(minBits),maximum=f32(maxBits),source=imageMetadata(sourceId,{shape:options.shape??[2,2]});
  const counts=options.counts??Array.from({length:bins},(_,i)=>[0,2,5,7].includes(i)?1:0);
  const bytes=Buffer.alloc(counts.length*8);counts.forEach((value,i)=>bytes.writeDoubleLE(value,i*8));
  const axis={dm_dimension:0,numpy_axis:0,size:bins,origin:0,calibrated_value_at_pixel_zero:0,
    scale:1,unit:null,usable:false,issue:'missing_unit'};
  const image={id:99,name:'native histogram protocol fixture',ndim:1,data_type_code:11,dtype:'uint32',
    is_integer:true,is_unsigned:true,packing_style:1,shape:[bins],dm_dimensions:[bins],pixels:bins,
    shape_order:'one-dimensional native histogram bins',calibration:[axis],calibration_complete:false,
    native_mean_supported:false,native_summary_supported:false,
    coordinate_rule:'physical(i)=calibrated_value_at_pixel_zero+i*scale'};
  return {backend:'digitalmicrograph-native',operation:'HISTOGRAM',source_image_id:sourceId,image_id:99,
    source,image,source_min:minimum,source_max:maximum,source_pixels:source.pixels,
    requested_range:[minimum,maximum],range_covers_source:true,bins,bin_width:(maximum-minimum)/bins,
    binning:'uniform linear bins over the caller range; the range must cover the complete native source minimum/maximum',
    bin_edge_rule:'left edge at range_min, width = (max-min)/bins',counts_sum:source.pixels,counts_complete:true,
    shape:[bins],dtype:'uint32',axes:['intensity_bin'],counts_encoding:'exact uint32 counts little-endian binary64 payload',
    values_base64:bytes.toString('base64'),raw_bytes:bins*8,output_bytes:bins*4,axis_mode:'bin_index',
    axis_calibration_is_bin_left_edge:false,bin_left_edge:minimum,
    source_intensity_calibration:{origin:7.5,scale:-2,unit:'arb'},operator:'GMSImageProcessing::CalcHistogram',computation:'DM native',
    intensity_calibration_applied:false,intensity_semantics:'raw pixel intensity counts per bin',source_write_requested:false,snapshot_atomic:false,
    ownership:'plugin retained strong reference until normal native STOP/cleanup; shown document may retain image',
    retention:{token:1,creation_request_id:requestId,state_at_creation:'plugin_retained',
      identity_scope:'bridge token in this native session, not a host image ID'}};
}
export function savedHistogramFixture(args=histogramArgs,requestId='saved-histogram',options={}) {
  return {...histogramFixture(args,requestId,options),native_receipt:{protocol:'NB2',session:'a'.repeat(32),id:requestId,
    request_id:requestId,state:'completed',host_pid:301,exec_tid:303,worker_tid:302,timings_us:{queue:1,execute:2},
    original_operation:'HISTOGRAM',normalized_args:args,result_type:'native_histogram',result_version:1}};
}
