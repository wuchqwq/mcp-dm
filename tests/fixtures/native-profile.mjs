import {imageMetadata} from './native-operations.mjs';
import {normalizedGuiMapping} from './native-rois.mjs';

// Independently chosen protocol data; no vendor calls or qualification.
export const profileArgs = [77,31,9,4,2,1,5,1,1];
export function profileFixture(args = profileArgs, requestId = 'saved-profile', {unsigned=false,shape=[8,12]}={}) {
  const [sourceId,document_id,display_id,roi_id,x0,y0,x1,y1] = args;
  const n = Math.abs(x1-x0)+Math.abs(y1-y0)+1;
  const source = imageMetadata(sourceId,{shape,unsigned});
  source.calibration[1].scale = source.calibration[0].scale;
  const axis = {dm_dimension:0,numpy_axis:0,size:n,origin:0,calibrated_value_at_pixel_zero:0,
    scale:-0.25,unit:'nm',usable:true,issue:null};
  const image = {id:99,name:'native profile protocol fixture',ndim:1,data_type_code:12,dtype:'float64',packing_style:1,
    shape:[n],dm_dimensions:[n],pixels:n,shape_order:'one-dimensional native profile samples',calibration:[axis],
    calibration_complete:true,native_mean_supported:false,native_summary_supported:false,
    coordinate_rule:'physical(i)=calibrated_value_at_pixel_zero+i*scale'};
  const bytes = Buffer.alloc(n*8);
  for (let i=0;i<n;++i) bytes.writeDoubleLE([-2.5,0.1,16777217,4294967295][i%4],i*8);
  return {backend:'digitalmicrograph-native',operation:'PROFILE',source_image_id:sourceId,image_id:99,source,image,
    source_gui_line:{document_id,display_id,roi_id,raw_line:{x0,y0,x1,y1},effective_line:[x0,y0,x1,y1],rotation_degrees:0,
      source_layout:'direct_image_canonical_xy',slice_ids:[0],coordinate_mapping:normalizedGuiMapping(source.shape)},
    width:1,shape:[n],dtype:'float64',axes:['native_profile_axis'],byte_order:'little',array_order:'C',data_encoding:'base64',
    sample_count:n,raw_bytes:n*8,output_bytes:n*8,values_base64:bytes.toString('base64'),
    source_sample_start_xy:[x0,y0],source_sample_end_xy:[x1,y1],source_sample_step_xy:[(x1-x0)/(n-1),(y1-y0)/(n-1)],
    distance_zero:0,distance_step:0.25,distance_unit:'nm',calibration_complete:true,
    source_intensity_calibration:{origin:2.5,scale:-3,unit:null},intensity_calibration:{origin:2.5,scale:-3,unit:null},
    operator:'LiveProfile_ExtractLineProfile',computation:'DM native',snapshot_atomic:false,source_write_requested:false,
    intensity_calibration_applied:false,intensity_semantics:'raw pixel intensity',
    ownership:'plugin retained strong reference until normal native STOP/cleanup; shown document may retain image',
    retention:{token:1,creation_request_id:requestId,state_at_creation:'plugin_retained',identity_scope:'bridge token in this native session, not a host image ID'}};
}

export function savedProfileFixture(args = profileArgs, requestId = 'saved-profile') {
  return {...profileFixture(args,requestId),native_receipt:{protocol:'NB2',session:'a'.repeat(32),id:requestId,request_id:requestId,
    state:'completed',host_pid:301,exec_tid:303,worker_tid:302,timings_us:{queue:1,execute:2},original_operation:'PROFILE',
    normalized_args:args,result_type:'native_line_profile',result_version:1}};
}
