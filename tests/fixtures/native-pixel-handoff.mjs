// Independent, hand-built metadata controls only. No native operator executes.
import {fourierFixture,readFixture} from './native-operations.mjs';
import {frameHandoffFixture} from './native-frame-handoff.mjs';

export function pixelReadFixture({operation='REAL_PIXEL',spatial=false,crop=false,frame=false,unknownUnits=true}={}) {
  const base=operation.slice(0,-6);
  if(!['REAL','IMAG','VENDOR_ARG','VENDOR_NORM'].includes(base))throw Error('Explicit scalar pixel Fourier fixture required');
  const producer=fourierFixture(base,88,{spatial,shape:[4,8]});
  producer.operation=operation;producer.coordinate_mode='pixel';
  if(unknownUnits)for(const metadata of [producer.source,producer.image]) {
    metadata.calibration.forEach(axis=>Object.assign(axis,{unit:null,usable:false,issue:'unknown_units'}));
    metadata.calibration_complete=false;
  }
  if(producer.frequency_grid) {
    producer.frequency_grid.coordinate_mode='pixel';
    producer.frequency_grid.axes.forEach((axis,index)=>Object.assign(axis,{
      physical_frequency_step:null,unit:'cycles_per_pixel',frequency_at_index_zero:-.5,
      native_calibration_scale:producer.image.calibration[index].scale,
      native_calibration_unit:producer.image.calibration[index].unit,
      coordinate_rule:'f(i)=(i-dc_index)*cycles_per_pixel_step'}));
  }
  const source=structuredClone(producer.image),offset=crop?[1,1]:[0,0];
  let provenance={operation,request_id:'pixel-original',source_image_ids:[88],semantics:'synthetic pixel scalar result'};
  if(crop) {
    source.id=101;source.shape=[3,6];source.dm_dimensions=[6,3];source.pixels=18;
    source.calibration.forEach((axis,index)=>{axis.size=source.dm_dimensions[index];axis.origin-=offset[index];axis.calibrated_value_at_pixel_zero+=offset[index]*axis.scale;});
    provenance={operation:'CROP_PIXEL',request_id:'pixel-crop',source_image_ids:[99],semantics:'synthetic pixel crop'};
  }
  const args=[source.id,1,0,4,2],read=readFixture(args,{source,provenance});
  read.scientific_context={schema_version:1,status:'tracked_fourier',original_operation:operation,
    request_id:'pixel-original',normalized_args:[88],result_version:2,result:producer,source_offset_xy:offset,postprocessing:[]};
  if(base==='VENDOR_NORM') {
    const bytes=Buffer.alloc(read.raw_bytes);for(let n=0;n<read.sample_count;n++)bytes.writeFloatLE(n+.25,n*4);
    read.values_base64=bytes.toString('base64');
  }
  if(frame)read.frame_ancestry=frameHandoffFixture({shape:[4,8],unknownUnits}).ancestry;
  return {read,args,producer};
}
