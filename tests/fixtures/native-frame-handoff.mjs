// Hand-written transport evidence only; no DM/native qualification.
import {imageMetadata} from './native-operations.mjs';

export function frameHandoffFixture({index=1, imageId=77, shape=[7,9], unknownUnits=false}={}) {
  const image=imageMetadata(imageId,{shape});
  if(unknownUnits) {
    image.calibration.forEach(axis=>Object.assign(axis,{unit:null,usable:false,issue:'unknown_units'}));
    image.calibration_complete=false;
  }
  const source={...structuredClone(image),id:31,name:'synthetic uint16 sequence',ndim:3,dtype:'uint16',data_type_code:10,
    is_integer:true,is_unsigned:true,shape:[3,...shape],dm_dimensions:[shape[1],shape[0],3],pixels:3*shape[0]*shape[1],
    native_mean_supported:false,native_summary_supported:false,
    calibration:[...image.calibration.map(axis=>({...axis,numpy_axis:axis.numpy_axis+1})),
      {dm_dimension:2,numpy_axis:0,size:3,origin:2,calibrated_value_at_pixel_zero:1.5,scale:-.75,
        unit:null,usable:false,issue:'unknown_units'}],calibration_complete:false};
  const result={backend:'digitalmicrograph-native',operation:'FRAME',source_image_id:31,image_id:imageId,frame_index:index,
    frame_axis:{dm_dimension:2,numpy_axis:0,index_base:0,role:'unspecified_sequence',count:3,
      calibrated_value:1.5-index*.75,unit:null,usable:false},source,image,
    operator:'GMS::Image::GetSubSliceAsImage + GMSImageProcessing::ImageConvert',
    computation:'DM native frame copy and explicit uint16-to-float32 conversion',
    output_bytes:image.pixels*4,validation_peak_new_image_bytes:image.pixels*6,
    dtype_conversion:{input_dtype:'uint16',input_data_type_code:10,output_dtype:'float32',output_data_type_code:2,
      lossless_values:true,operator:'GMSImageProcessing::ImageConvert'},
    intensity_calibration_source:{origin:0,scale:1,unit:'raw'},intensity_calibration_output:{origin:0,scale:1,unit:'raw'},
    intensity_calibration_applied:false,intensity_semantics:'raw pixel intensity',source_write_requested:false,
    snapshot_atomic:false,visible_dm_document:false,ownership:'plugin retained strong reference until normal native STOP/cleanup'};
  const ancestry={schema_version:1,status:'tracked_frame',request_id:'original-frame',normalized_args:[31,index],result,
    scope:'original frame identity only; current values and coordinates follow current operation metadata'};
  const provenance={operation:'FRAME',request_id:'original-frame',source_image_ids:[31],semantics:'DM native independent frame copy'};
  return {result,ancestry,provenance};
}
