// Actual loopback Panel -> original stdio MCP -> independent image Python.
// HTTP actions exercise the GUI contract; this is not browser/human/DM evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync,readdirSync,rmSync,existsSync} from 'node:fs';
import {createImagePanel,StdioImageClient} from '../tools/image_panel.mjs';
import {exportMeasurementTable} from '../ui/image-panel/measurement-workspace.mjs';

const enabled=process.env.DM_INSPECTOR_PANEL_REAL_TEST==='1';
const almost=(actual,expected)=>assert.ok(Math.abs(actual-expected)<=1e-12*Math.max(1,Math.abs(expected)),`${actual} != ${expected}`);

test('actual provider table retains three reflections, versions, scale and lost-response recovery across new Panel instances',{skip:!enabled,timeout:180000},async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'data-inspector-panel-')),workspace=path.join(directory,'workspace'),source=path.join(directory,'public-synthetic.tiff');let setup,panel;
 try{
  const pythonCommand=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python';
  const created=spawnSync(pythonCommand,['-c',String.raw`import sys,numpy as np,tifffile
y,x=np.mgrid[:32,:48]
a=np.rint(30000+4000*np.cos(2*np.pi*x/8)+3000*np.cos(2*np.pi*y/8)+2000*np.cos(2*np.pi*(x-y)/8)).astype(np.uint16)
tifffile.imwrite(sys.argv[1],np.stack([a,a+5]),photometric='minisblack',metadata=None)
print(sys.executable)`,source],{encoding:'utf8'});assert.equal(created.status,0,created.stderr);const python=created.stdout.trim(),original=readFileSync(source);
  setup=new StdioImageClient({workspace,python});await setup.rpc('initialize',{});
  const opened=(await setup.tool('image_open',{source_path:source,request_id:'inspector-open'})).data;
  const frame=(await setup.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'inspector-frame'})).data;
  await setup.close();setup=null;
  const delegate=new StdioImageClient({workspace,python});let dropNext=false,dropped=null,measureSubmissions=0;
  const client={rpc:(...args)=>delegate.rpc(...args),close:()=>delegate.close(),async tool(name,args){
   const result=await delegate.tool(name,args);
   if(name==='image_measure'){measureSubmissions++;if(dropNext){dropNext=false;dropped={request_id:args.request_id,object_id:result.data.object_id};throw new Error('Controlled reply loss after actual scientific commit');}}
   return result;
  }};
  panel=await createImagePanel({workspace,python,object_id:frame.object_id,client});let origin;
  const headers=()=>({'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'});
  const send=async(action,params={},status=200)=>{origin=panel.url.split('/#')[0];const response=await fetch(origin+'/api/action',{method:'POST',headers:headers(),body:JSON.stringify({expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params})}),data=await response.json();assert.equal(response.status,status,JSON.stringify(data));return data;};
  const inspect=async(query='object_id='+panel.state().object.object_id,status=200)=>{origin=panel.url.split('/#')[0];const response=await fetch(origin+'/api/measurements?'+query,{headers:headers()}),data=await response.json();assert.equal(response.status,status,JSON.stringify(data));return data;};
  const selection=(kind,coordinates)=>{const p=panel.state().object.panels[0];return {kind,coordinates,panel:p,source_object_id:p.source_object_id,coordinate_space:p.domain==='frequency'?'frequency_cycles_per_pixel':'source_pixels'};};
  await send('calibrate',{scope:'sequence',xy_scale:{x:.02,y:-.04,unit:'nm'},source_text:'Independent synthetic fixture sampling; not an experimental calibration'});
  await send('fft',{selection:selection('rectangle',[8,8,40,24]),window:'none',subtract_mean:true});
  const spectrum=panel.state().object.object_id,spectrumFile=path.join(workspace,'objects',spectrum,'data.npy'),fftBytes=readFileSync(spectrumFile);
  const points=[[.125,0],[0,.125],[-.125,.125]],ids=['g1','g2','g3'],first=[];
  for(let i=0;i<3;i++)await send('mark',{selection:selection('point',points[i]),annotation_id:ids[i],text:ids[i],status:'hypothesized'});
  // Lose exactly one real accepted measurement reply. Its immutable creation
  // input provides an unambiguous association even though no link was written.
  dropNext=true;await send('measure',{selection:selection('point',points[0]),annotation_id:ids[0]},400);
  assert.ok(dropped);assert.equal(existsSync(path.join(workspace,'measurement-links',dropped.object_id+'.json')),false);
  const recovered=await send('recover');assert.equal(recovered.last_operation.object_id,dropped.object_id);assert.equal(recovered.last_operation.request_id,dropped.request_id);assert.equal(measureSubmissions,1);
  first.push(dropped.object_id);
  for(let i=1;i<3;i++){const state=await send('measure',{selection:selection('point',points[i]),annotation_id:ids[i]});first.push(state.last_operation.object_id);}
  let records=await inspect();assert.equal(records.entries.length,3);assert.equal(records.current.dtype,'complex128');assert.deepEqual(records.current.shape_yx,[16,32]);assert.deepEqual(records.current.source_rect_xyxy,[8,8,40,24]);assert.equal(records.current.frame_index,0);
  for(let i=0;i<3;i++){const entry=records.entries.find(value=>value.object_id===first[i]);assert.equal(entry.annotation_id,ids[i]);assert.equal(entry.status,'current');assert.deepEqual(entry.points,[[0,0],points[i]]);almost(entry.d_spacing,1/Math.hypot(points[i][0]/.02,points[i][1]/-.04));const actual=JSON.parse(readFileSync(path.join(workspace,'objects',entry.object_id,'object.json')));assert.equal(entry.d_spacing,actual.d_spacing);assert.equal(entry.request_id,actual.request_id);}
  const previousOther=records.entries.filter(x=>x.annotation_id!=='g1').map(x=>[x.object_id,x.points,x.d_spacing]).sort();
  points[0]=[.1875,0];await send('edit',{updates:[{annotation_id:'g1',coordinates:points[0]}],auto_commit:true});
  records=await inspect();assert.equal(records.entries.find(x=>x.object_id===first[0]).status,'needs_remeasurement');
  const revised=(await send('measure',{selection:selection('point',points[0]),annotation_id:'g1',measurement_object_id:first[0]})).last_operation;
  records=await inspect();assert.equal(records.entries.find(x=>x.object_id===first[0]).status,'historical');assert.equal(records.entries.find(x=>x.object_id===revised.object_id).status,'current');
  assert.deepEqual(records.entries.filter(x=>x.annotation_id!=='g1').map(x=>[x.object_id,x.points,x.d_spacing]).sort(),previousOther);
  const beforeGamma=records.entries.map(x=>[x.object_id,x.points,x.d_spacing,x.status]).sort();
  await send('preview',{gamma:1.7});records=await inspect();assert.deepEqual(records.entries.map(x=>[x.object_id,x.points,x.d_spacing,x.status]).sort(),beforeGamma);
  await send('edit-layout',{updates:[{annotation_id:'g2',presentation:{label:{text:'g2 label only',offset:[18,-10],font_size:14}}}]});
  records=await inspect();assert.deepEqual(records.entries.map(x=>[x.object_id,x.points,x.d_spacing,x.status]).sort(),beforeGamma,'label layout does not create or alter a measurement');
  await send('calibrate',{scope:'sequence',xy_scale:{x:.03,y:-.06,unit:'nm'},source_text:'Independent revised synthetic sampling, not changed experimental scale'});
  records=await inspect();assert.equal(records.entries.filter(x=>x.status==='needs_remeasurement').length,3);
  const latest=[revised.object_id,first[1],first[2]],current=[];
  for(let i=0;i<3;i++){const state=await send('measure',{selection:selection('point',points[i]),annotation_id:ids[i],measurement_object_id:latest[i]});current.push(state.last_operation.object_id);}
  records=await inspect();assert.equal(records.entries.length,7);assert.equal(records.entries.filter(x=>x.status==='current').length,3);
  for(let i=0;i<3;i++){const entry=records.entries.find(x=>x.object_id===current[i]);almost(entry.d_spacing,1/Math.hypot(points[i][0]/.03,points[i][1]/-.06));assert.equal(entry.measurement_kind,'dc_to_peak');}
  const beforeReads=readdirSync(path.join(workspace,'requests')).sort();await inspect('object_id='+'f'.repeat(32),409);await inspect('object_id=../../outside',409);await inspect('object_id='+panel.state().object.object_id+'&workspace=elsewhere',409);assert.deepEqual(readdirSync(path.join(workspace,'requests')).sort(),beforeReads,'bounded read refusals do not submit science');
  const csv=exportMeasurementTable(records.entries.filter(x=>x.status==='current')),csvFile=path.join(directory,'measurements.csv');writeFileSync(csvFile,csv);
  const independentlyRead=spawnSync(python,['-c',String.raw`import csv,math,sys
rows=list(csv.DictReader(open(sys.argv[1],newline='',encoding='utf-8')))
assert len(rows)==3
for r in rows:
 x,y=float(r['point_1_x']),float(r['point_1_y'])
 assert math.isclose(float(r['d_spacing']),1/math.hypot(x/.03,y/-.06),rel_tol=1e-12,abs_tol=1e-12)
 assert r['d_spacing_unit']=='nm' and r['frequency_unit']=='cycles/nm'
 assert r['status']=='当前' and r['result_object_id'] and r['request_id']
print('csv independent numeric check PASS')`,csvFile],{encoding:'utf8'});assert.equal(independentlyRead.status,0,independentlyRead.stderr);
  const savedView=panel.state().object.object_id;await panel.close();panel=null;
  panel=await createImagePanel({workspace,python,object_id:savedView});const reopened=await inspect();assert.deepEqual(reopened.entries,records.entries);assert.deepEqual(readdirSync(path.join(workspace,'requests')).sort(),beforeReads,'new Panel reads existing saved results without another FFT/view');
  const requests=readdirSync(path.join(workspace,'requests')).map(file=>JSON.parse(readFileSync(path.join(workspace,'requests',file))));assert.equal(requests.filter(record=>record.parameters.action==='fft').length,1);assert.deepEqual(readFileSync(spectrumFile),fftBytes);assert.deepEqual(readFileSync(source),original);
 }finally{await setup?.close();await panel?.close();rmSync(directory,{recursive:true,force:true});}
});

test('uncalibrated actual FFT table stays in cycles/pixel and frame switching does not project old measurements',{skip:!enabled,timeout:90000},async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'data-inspector-pixel-')),workspace=path.join(directory,'workspace'),source=path.join(directory,'pixel-only.tiff');let client,panel;
 try{
  const command=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python',fixture=spawnSync(command,['-c',"import sys,numpy as np,tifffile; print(sys.executable); a=np.arange(16*24,dtype=np.uint16).reshape(16,24); tifffile.imwrite(sys.argv[1],np.stack([a,a+10]),photometric='minisblack',metadata=None)",source],{encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);const python=fixture.stdout.trim(),before=readFileSync(source);
  client=new StdioImageClient({workspace,python});await client.rpc('initialize',{});const opened=(await client.tool('image_open',{source_path:source,request_id:'pixel-open'})).data,frame=(await client.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'pixel-frame'})).data;await client.close();client=null;
  panel=await createImagePanel({workspace,python,object_id:frame.object_id});const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
  const send=async(action,params)=>{const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:panel.state().object.object_id,action,params})}),value=await response.json();assert.equal(response.status,200,JSON.stringify(value));return value;};
  const pick=(kind,coordinates)=>{const p=panel.state().object.panels[0];return {kind,coordinates,panel:p,source_object_id:p.source_object_id,coordinate_space:p.domain==='frequency'?'frequency_cycles_per_pixel':'source_pixels'};};
  await send('fft',{selection:pick('rectangle',[0,0,24,16]),window:'none',subtract_mean:true});
  await send('mark',{selection:pick('point',[.125,0]),annotation_id:'pixel-peak',text:'g1'});
  const dc=(await send('measure',{selection:pick('point',[.125,0]),annotation_id:'pixel-peak'})).last_operation;
  const difference=(await send('measure',{selection:pick('line',[.125,0,0,.125])})).last_operation;
  const inspect=async()=>{const response=await fetch(origin+'/api/measurements?object_id='+panel.state().object.object_id,{headers});assert.equal(response.status,200);return response.json();};
  let records=await inspect();assert.equal(records.current.xy_calibration,null);assert.equal(records.entries.length,2);
  almost(dc.frequency_distance_cycles_per_pixel,.125);almost(dc.pixel_period,8);
  // The legacy last_operation projection intentionally omits the endpoint
  // flag. The new table reads it from actual immutable provider records.
  assert.equal(records.entries.find(entry=>entry.object_id===dc.object_id).dc_reference_point_index,0);
  assert.equal(records.entries.find(entry=>entry.object_id===difference.object_id).dc_reference_point_index,null);
  for(const entry of records.entries){assert.equal(entry.period,null);assert.equal(entry.d_spacing,null);assert.equal(entry.physical_frequency_unit,null);assert.equal(entry.physical_frequency_magnitude,null);assert.equal(entry.status,'current');}
  const csv=exportMeasurementTable(records.entries);assert.match(csv,/cycles_per_pixel/);assert.ok(!csv.includes(',nm,'));
  await send('frame',{frame_index:1});records=await inspect();assert.equal(records.current.frame_index,1);assert.equal(records.entries.length,2);assert.ok(records.entries.every(entry=>entry.status==='historical'&&!entry.same_frame&&!entry.same_grid&&!entry.visible_in_current_view));assert.deepEqual(readFileSync(source),before);
 }finally{await client?.close();await panel?.close();rmSync(directory,{recursive:true,force:true});}
});
