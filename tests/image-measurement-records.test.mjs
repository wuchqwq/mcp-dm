// Actual existing external image provider records; no browser/DM/model claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {readImageMeasurements,writeMeasurementLink} from '../lib/image_measurement_records.mjs';
import {ImageWorkspace} from '../lib/image_workspace.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
function fixture(){
 const dir=mkdtempSync(path.join(tmpdir(),'image-measurement-records-'));
 const script=String.raw`
import json,sys
from pathlib import Path
import numpy as np,tifffile
from tools.image_workspace import execute
root=Path(sys.argv[1]); workspace=root/'workspace'; counter=0
def call(action,**kw):
 global counter
 counter+=1
 result=execute(dict(workspace=str(workspace),action=action,request_id='fixture-'+str(counter),**kw))
 if not result['ok']: raise RuntimeError(result)
 return result['result']
source=root/'synthetic.tiff'
tifffile.imwrite(source,np.arange(2*16*24,dtype=np.uint16).reshape(2,16,24),photometric='minisblack')
opened=call('open',source_path=str(source)); frame=call('frame',object_id=opened['object_id'],frame_index=0)
cal=call('calibrate',object_id=frame['object_id'],scope='sequence',xy_scale=dict(x=.02,y=-.04,unit='nm'),source_text='Explicit synthetic fixture, not experiment')
fft=call('fft',object_id=cal['object_id'],rect=[2,2,18,14],window='none',subtract_mean=True)
pts=[[.125,0],[0,.125],[.125,.125]]
marks=[dict(annotation_id='peak-'+str(i),kind='point',coordinate_space='frequency_cycles_per_pixel',source_object_id=fft['object_id'],coordinates=p,status='hypothesized',text='g'+str(i+1)) for i,p in enumerate(pts)]
annotated=call('annotate',object_id=fft['object_id'],annotations=marks)
measurements=[call('measure',object_id=annotated['object_id'],points=[[0,0],p]) for p in pts]
gamma=call('view',object_id=annotated['object_id'],gamma=2)
edit=call('annotate',object_id=gamma['object_id'],updates=[dict(annotation_id='peak-0',coordinates=[.1875,0])])
label_only=call('annotate',object_id=edit['object_id'],updates=[dict(annotation_id='peak-1',presentation=dict(label=dict(offset=[20,30])))])
moved_other=call('annotate',object_id=edit['object_id'],updates=[dict(annotation_id='peak-1',coordinates=[0,.25])])
revised=call('remeasure',object_id=edit['object_id'],measurement_object_id=measurements[0]['object_id'],points=[[0,0],[.1875,0]],source_text='Synthetic fixture endpoint correction')
scale=call('calibrate',object_id=edit['object_id'],scope='sequence',xy_scale=dict(x=.03,y=-.06,unit='nm'),source_text='Explicit revised synthetic sampling')
view=call('view',object_id=scale['object_id'])
remeasured=call('remeasure',object_id=view['object_id'],measurement_object_id=revised['object_id'])
next_frame=call('frame',object_id=opened['object_id'],frame_index=1)
next_view=call('view',object_id=next_frame['object_id'])
other=root/'other.tiff';tifffile.imwrite(other,np.zeros((16,24),dtype=np.uint16))
other_source=call('open',source_path=str(other));other_frame=call('frame',object_id=other_source['object_id'],frame_index=0)
other_measure=call('measure',object_id=other_frame['object_id'],points=[[0,0],[3,4]])
other_fft=call('fft',object_id=other_frame['object_id'],window='none',subtract_mean=False)
other_fft_measure=call('measure',object_id=other_fft['object_id'],points=[[0,0],[.125,0]])
print(json.dumps(dict(dir=str(root),workspace=str(workspace),source=str(source),opened=opened,frame=frame,fft=fft,annotated=annotated,measurements=measurements,gamma=gamma,edit=edit,label_only=label_only,moved_other=moved_other,revised=revised,scale=scale,view=view,remeasured=remeasured,next_view=next_view,other_frame=other_frame,other_measure=other_measure,other_fft=other_fft,other_fft_measure=other_fft_measure)))
`;
 const p=spawnSync(python,['-c',script,dir],{cwd:root,encoding:'utf8'});
 assert.equal(p.status,0,p.stderr||p.stdout);return JSON.parse(p.stdout);
}
function link(f,i,record=f.measurements[i],input=f.annotated){return writeMeasurementLink(f.workspace,{schema_version:1,measurement_object_id:record.object_id,input_object_id:input.object_id,annotation_id:'peak-'+i,name:'g'+(i+1),measurement_kind:'dc_to_peak',previous_measurement_object_id:record.remeasurement?.previous_measurement_object_id??null});}
function result(f,object){return readImageMeasurements({workspace:f.workspace,objectId:object.object_id});}

test('recover multiple saved measurements, exact metadata, frame/grid visibility and linked history',()=>{
 const f=fixture();try{
  const recoveredWithoutLink=result(f,f.moved_other).entries.find(x=>x.object_id===f.measurements[1].object_id);
  assert.equal(recoveredWithoutLink.annotation_id,'peak-1');assert.equal(recoveredWithoutLink.name,'g2');assert.equal(recoveredWithoutLink.status,'needs_remeasurement');
  const before=readFileSync(f.source);for(let i=0;i<3;i++)link(f,i);link(f,0,f.revised,f.edit);link(f,0,f.remeasured,f.view);
  const data=result(f,f.annotated);
  assert.equal(data.entries.length,5);assert.equal(data.current.dtype,'complex128');assert.deepEqual(data.current.shape_yx,[12,16]);
  assert.equal(data.current.frame_index,0);assert.equal(data.current.source_identity.path,f.source);
  assert.deepEqual(data.current.source_rect_xyxy,[2,2,18,14]);assert.equal(data.current.source_kind,'tiff');
  for(const expected of f.measurements){const entry=data.entries.find(x=>x.object_id===expected.object_id);assert.deepEqual(entry.points,expected.points);assert.equal(entry.period,expected.period);assert.equal(entry.d_spacing,expected.d_spacing);assert.equal(entry.parent_object_id,expected.parent_object_id);}
  assert.equal(data.entries.find(x=>x.object_id===f.measurements[0].object_id).status,'historical');
  assert.equal(data.entries.find(x=>x.object_id===f.measurements[1].object_id).status,'current');
  assert.equal(data.entries.find(x=>x.object_id===f.measurements[1].object_id).annotation_id,'peak-1');
  const gamma=result(f,f.gamma);assert.equal(gamma.entries.find(x=>x.object_id===f.measurements[1].object_id).status,'current');
  assert.deepEqual(gamma.entries.find(x=>x.object_id===f.measurements[1].object_id).points,f.measurements[1].points);
  const edited=result(f,f.edit);assert.equal(edited.entries.find(x=>x.object_id===f.measurements[1].object_id).status,'current');
  assert.equal(edited.entries.find(x=>x.object_id===f.revised.object_id).annotation_matches_current,true);
  assert.equal(result(f,f.label_only).entries.find(x=>x.object_id===f.measurements[1].object_id).status,'current');
  const moved=result(f,f.moved_other);assert.equal(moved.entries.find(x=>x.object_id===f.measurements[1].object_id).status,'needs_remeasurement');assert.equal(moved.entries.find(x=>x.object_id===f.measurements[2].object_id).status,'current');
  const scale=result(f,f.view);assert.equal(scale.entries.find(x=>x.object_id===f.measurements[1].object_id).status,'needs_remeasurement');
  assert.deepEqual(scale.current.source_rect_xyxy,[2,2,18,14]);assert.deepEqual(scale.entries[0].source.source_rect_xyxy,[2,2,18,14]);
  assert.equal(scale.entries.find(x=>x.object_id===f.remeasured.object_id).status,'current');
  const next=result(f,f.next_view);assert.equal(next.entries.length,5);assert.ok(next.entries.every(x=>!x.same_frame&&!x.same_grid&&!x.visible_in_current_view&&x.status==='historical'));
  const reopened=readImageMeasurements({workspace:f.workspace,objectId:f.view.object_id});assert.deepEqual(reopened,scale);
  const workspace=new ImageWorkspace({workspace:f.workspace,spawnProcess:()=>assert.fail('Metadata inspection must not launch a scientific worker')});assert.deepEqual(workspace.inspectMeasurements({objectId:f.view.object_id}),scale);
  const limited=readImageMeasurements({workspace:f.workspace,objectId:f.view.object_id,limit:3});assert.equal(limited.total_count,5);assert.equal(limited.entries.length,3);assert.equal(limited.truncated,true);
  const uncalibrated=result(f,f.other_frame),pixel=uncalibrated.entries.find(x=>x.object_id===f.other_measure.object_id);assert.equal(uncalibrated.entries.length,2);assert.equal(pixel.distance_pixels,5);assert.equal(pixel.physical_distance,null);assert.equal(pixel.physical_unit,null);assert.equal(uncalibrated.current.xy_calibration,null);
  const pixelFrequency=result(f,f.other_fft).entries.find(x=>x.object_id===f.other_fft_measure.object_id);assert.equal(pixelFrequency.frequency_distance_cycles_per_pixel,.125);assert.equal(pixelFrequency.pixel_period,8);assert.equal(pixelFrequency.period,null);assert.equal(pixelFrequency.d_spacing,null);assert.equal(pixelFrequency.physical_frequency_unit,null);
  assert.deepEqual(readFileSync(f.source),before);
 }finally{rmSync(f.dir,{recursive:true,force:true});}
});

test('duplicate original anchors stay unassociated without an explicit validated link',()=>{
 const f=fixture();try{
  const p=spawnSync(python,['-c',String.raw`
import json,sys
from tools.image_workspace import execute
workspace,fft=sys.argv[1:]
def call(action,request_id,**kw):
 result=execute(dict(workspace=workspace,action=action,request_id=request_id,**kw))
 if not result['ok']: raise RuntimeError(result)
 return result['result']
marks=[dict(annotation_id='duplicate-'+name,kind='point',coordinate_space='frequency_cycles_per_pixel',source_object_id=fft,coordinates=[.125,0],status='hypothesized',text=name) for name in ['a','b']]
saved=call('annotate','duplicate-input',object_id=fft,annotations=marks)
measure=call('measure','duplicate-measure',object_id=saved['object_id'],points=[[0,0],[.125,0]])
current=call('annotate','duplicate-current',object_id=saved['object_id'],annotations=marks[:1])
print(json.dumps(dict(saved=saved,measure=measure,current=current)))
`,f.workspace,f.fft.object_id],{cwd:root,encoding:'utf8'});
  assert.equal(p.status,0,p.stderr||p.stdout);const data=JSON.parse(p.stdout);
  const row=result(f,data.current).entries.find(x=>x.object_id===data.measure.object_id);
  assert.equal(row.annotation_id,null);assert.equal(row.name,null);assert.equal(row.annotation_matches_current,false);
  writeMeasurementLink(f.workspace,{measurement_object_id:data.measure.object_id,input_object_id:data.saved.object_id,annotation_id:'duplicate-a',name:'Explicit A selection',measurement_kind:'dc_to_peak'});
  const linked=result(f,data.current).entries.find(x=>x.object_id===data.measure.object_id);assert.equal(linked.annotation_id,'duplicate-a');assert.equal(linked.annotation_matches_current,true);
 }finally{rmSync(f.dir,{recursive:true,force:true});}
});

test('reject forged metadata, foreign source links, altered links and invalid scope without writes',()=>{
 const f=fixture();try{
  assert.throws(()=>readImageMeasurements({workspace:f.workspace,objectId:'../../foreign'}),/Explicit saved/);
  assert.throws(()=>readImageMeasurements({workspace:f.workspace,objectId:f.view.object_id,limit:513}),/1..512/);
  assert.throws(()=>writeMeasurementLink(f.workspace,{measurement_object_id:f.measurements[0].object_id,input_object_id:f.other_measure.parent_object_id,annotation_id:'peak-0',name:'bad',measurement_kind:'dc_to_peak'}),/input differs/);
  assert.throws(()=>writeMeasurementLink(f.workspace,{measurement_object_id:f.measurements[0].object_id,input_object_id:f.annotated.object_id,annotation_id:'peak-1',name:'bad',measurement_kind:'dc_to_peak'}),/anchors/);
  const saved=link(f,0);assert.deepEqual(link(f,0),saved);
  assert.throws(()=>writeMeasurementLink(f.workspace,{measurement_object_id:f.measurements[0].object_id,input_object_id:f.annotated.object_id,annotation_id:'peak-0',name:'changed',measurement_kind:'dc_to_peak'}),/conflicts/);
  const linkFile=path.join(f.workspace,'measurement-links',f.measurements[0].object_id+'.json');
  writeFileSync(linkFile,JSON.stringify({...saved,measurement_manifest_sha256:'0'.repeat(64)}));
  assert.throws(()=>result(f,f.annotated),/convenience link/);
  writeFileSync(linkFile,JSON.stringify(saved));
  const objectFile=f.measurements[1].manifest_path,metadata=JSON.parse(readFileSync(objectFile));metadata.d_spacing=999;
  writeFileSync(objectFile,JSON.stringify(metadata));assert.throws(()=>result(f,f.annotated),/changed scientific object manifest/);
 }finally{rmSync(f.dir,{recursive:true,force:true});}
});
