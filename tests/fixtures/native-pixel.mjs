// Metadata-only fixtures: no host, native operation or scientific qualification.
import {fourierFixture,operationFixture,imageMetadata,readFixture} from './native-operations.mjs';

export function unknownPixelUnits(image) {
  image.calibration_complete=false;
  for (const axis of image.calibration) {axis.unit=null;axis.usable=false;axis.issue='unknown_units';}
  return image;
}
export function pixelFourierFixture(operation='FFT_PIXEL',{unknownUnits=true,spatial=false}={}) {
  const base=operation.replace(/_PIXEL$/,''),result=fourierFixture(base,77,{spatial});
  result.operation=operation;result.coordinate_mode='pixel';
  if (unknownUnits) {unknownPixelUnits(result.source);unknownPixelUnits(result.image);}
  if (result.frequency_grid) {
    result.frequency_grid.coordinate_mode='pixel';
    result.frequency_grid.axes.forEach((axis,index)=>{
      axis.physical_frequency_step=null;axis.unit='cycles_per_pixel';axis.frequency_at_index_zero=-.5;
      axis.native_calibration_scale=result.image.calibration[index].scale;
      axis.native_calibration_unit=result.image.calibration[index].unit;
      axis.coordinate_rule='f(i)=(i-dc_index)*cycles_per_pixel_step';
    });
  }
  return result;
}
export function pixelFilterFixture(kind=1,{unknownUnits=true}={}) {
  const result=operationFixture('FILTER',[77,kind]);result.operation='FILTER_PIXEL';result.coordinate_mode='pixel';
  if (unknownUnits) {unknownPixelUnits(result.source);unknownPixelUnits(result.image);}
  return result;
}
export function pixelCropFixture({unknownUnits=true}={}) {
  const source=imageMetadata(77,{shape:[8,8]}),image=imageMetadata(99,{shape:[4,4]});
  const origin=[5,5],scale=[-.25,.5],outOrigin=[4,3],sourceZero=[1.25,-2.5],outputZero=[1,-1.5];
  for (let axis=0;axis<2;axis++) {
    Object.assign(source.calibration[axis],{origin:origin[axis],scale:scale[axis],calibrated_value_at_pixel_zero:sourceZero[axis]});
    Object.assign(image.calibration[axis],{origin:outOrigin[axis],scale:scale[axis],calibrated_value_at_pixel_zero:outputZero[axis]});
  }
  if (unknownUnits) {unknownPixelUnits(source);unknownPixelUnits(image);}
  return {backend:'digitalmicrograph-native',coordinate_mode:'pixel',source_image_id:77,image_id:99,source,image,
    requested_rect:[1,2,5,6],effective_rect:[1,2,5,6],rect_convention:'zero-based half-open [x0,y0,x1,y1]',
    operator:'GMS::Image::GetSubSliceAsImage',computation:'DM native independent pixel copy',output_bytes:64,
    ownership:'plugin retained strong reference until normal native STOP/cleanup',visible_dm_document:false,
    source_write_requested:false,snapshot_atomic:false,
    calibration_zero_verification:[{dm_dimension:0,expected:1,absolute_error:0,tolerance:3*2**-24+2**-53},
      {dm_dimension:1,expected:-1.5,absolute_error:0,tolerance:2**-22+2**-53}],
    calibration_tolerance_rule:'propagated binary32 half-ULPs of source zero, shifted index origin and output zero'};
}
export function pixelReadFixture({spatial=false}={}) {
  const producer=pixelFourierFixture('REAL_PIXEL',{spatial}),args=[99,2,1,6,3];
  const result=readFixture(args,{source:structuredClone(producer.image),provenance:{operation:'REAL_PIXEL',request_id:'pixel-real',source_image_ids:[77],semantics:'synthetic context only'}});
  result.scientific_context={schema_version:1,status:'tracked_fourier',original_operation:'REAL_PIXEL',request_id:'pixel-real',
    normalized_args:[77],result_version:2,result:producer,source_offset_xy:[0,0],postprocessing:[]};
  return {result,args};
}
