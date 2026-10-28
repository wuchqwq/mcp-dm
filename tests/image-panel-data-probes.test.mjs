// Actual Panel HTTP -> original MCP server -> scientific arrays. No browser,
// human pointer-performance or DM claim is made by this endpoint regression.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync,readdirSync,rmSync} from 'node:fs';
import {createImagePanel,StdioImageClient} from '../tools/image_panel.mjs';
import {exportProfileCSV} from '../ui/image-panel/data-probes.mjs';

const enabled=process.env.DM_PROBES_PANEL_REAL_TEST==='1';
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<=1e-11*Math.max(1,Math.abs(expected)),`${actual} != ${expected}`);

test('actual array probes, population ROI statistics, nearest profile and explicit complex components remain sourced and frame scoped',{skip:!enabled,timeout:180000},async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'scientific-data-probes-')),workspace=path.join(directory,'workspace'),source=path.join(directory,'public-asymmetric.tiff');let setup,panel,releaseProbe;
 try{
  const command=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python';
  const fixture=spawnSync(command,['-c',String.raw`import sys,numpy as np,tifffile
y,x=np.mgrid[:3,:5]
a=(1000+10*y+x*x).astype(np.uint16)
tifffile.imwrite(sys.argv[1],np.stack([a,a+100]),photometric='minisblack',metadata=None)
print(sys.executable)`,source],{encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);
  const python=fixture.stdout.trim(),original=readFileSync(source);
  setup=new StdioImageClient({workspace,python});await setup.rpc('initialize',{});
  const opened=(await setup.tool('image_open',{source_path:source,request_id:'probe-open'})).data;
  const frame=(await setup.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'probe-frame'})).data;await setup.close();setup=null;
  const actual=new StdioImageClient({workspace,python});let delayNext=false,probeStarted;
  const wrapped={rpc:actual.rpc.bind(actual),close:actual.close.bind(actual),async tool(name,args){const result=await actual.tool(name,args);if(name==='image_probe'&&delayNext){delayNext=false;probeStarted();await new Promise(resolve=>releaseProbe=resolve);}return result;}};
  panel=await createImagePanel({workspace,python,object_id:frame.object_id,client:wrapped});const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
  const send=async(action,params,status=200)=>{const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params})}),value=await response.json();assert.equal(response.status,status,JSON.stringify(value));return value;};
  const select=(kind,coordinates)=>{const p=panel.state().object.panels[0];return {kind,coordinates,panel:p,source_object_id:p.source_object_id,coordinate_space:p.domain==='frequency'?'frequency_cycles_per_pixel':'source_pixels'};};
  const probeBody=(coordinates,component='raw')=>{const selected=select('point',coordinates);return {expected_object_id:panel.state().object.object_id,source_object_id:selected.source_object_id,coordinate_space:selected.coordinate_space,coordinates,component};};
  const probe=async(body,status=200)=>{const response=await fetch(origin+'/api/probe',{method:'POST',headers,body:JSON.stringify(body)}),value=await response.json();assert.equal(response.status,status,JSON.stringify(value));return value;};
  const snapshot=()=>({objects:readdirSync(path.join(workspace,'objects')).sort(),requests:readdirSync(path.join(workspace,'requests')).sort()});
  await send('calibrate',{scope:'sequence',xy_scale:{x:.2,y:-.3,unit:'nm'},source_text:'Independent asymmetric synthetic calibration; not experimental'});
  const beforeProbe=snapshot();let result=await probe(probeBody([2,1]));assert.equal(result.samples[0].value,1014);assert.equal(result.component,'raw');assert.equal(result.dtype,'uint16');assert.deepEqual(result.samples[0].array_index_xy,[2,1]);assert.equal(result.dm_called,false);
  for(const point of [[0,0],[4,2],[2,1]])await probe(probeBody(point));
  assert.deepEqual(snapshot(),beforeProbe,'pointer reads do not publish requests or scientific result objects');
  await probe({...probeBody([2,1]),expected_object_id:'f'.repeat(32)},409);
  await probe({...probeBody([2,1]),source_object_id:'f'.repeat(32)},400);
  await probe({...probeBody([2,1]),source_path:'../../outside'},400);
  assert.deepEqual(snapshot(),beforeProbe,'invalid scoped reads also create no scientific records');
  await send('preview',{gamma:2.2,display_range:[1000,1036],max_size:320,upscale:true});result=await probe(probeBody([2,1]));assert.equal(result.samples[0].value,1014,'gamma/PNG scaling never replaces stored uint16');

  const view=panel.state().object.object_id;
  const stats=(await send('statistics',{selection:select('rectangle',[1,0,4,2]),component:'raw'})).last_operation;
  assert.equal(panel.state().object.object_id,view,'statistics do not replace the visible image');assert.equal(stats.kind,'statistics');assert.equal(stats.statistics.sample_count,6);assert.equal(stats.statistics.minimum,1001);assert.equal(stats.statistics.maximum,1019);near(stats.statistics.mean,1000+58/6);near(stats.statistics.stddev,Math.sqrt(776/6-(58/6)**2));assert.deepEqual(stats.source_rect_xyxy,[1,0,4,2]);assert.match(stats.standard_deviation,/ddof=0/);
  const profile=(await send('profile',{selection:select('line',[0,0,4,2]),component:'raw',sample_count:5})).last_operation;
  assert.equal(panel.state().object.object_id,view,'profile does not replace the visible image');assert.equal(profile.sampling.interpolation,'nearest');assert.equal(profile.sampling.line_width,1);assert.deepEqual(profile.samples.indices_xy,[[0,0],[1,1],[2,1],[3,2],[4,2]]);assert.deepEqual(profile.samples.value,[1000,1011,1014,1029,1036]);assert.deepEqual(profile.samples.coordinates_xy,[[0,0],[1,.5],[2,1],[3,1.5],[4,2]]);near(profile.samples.distance.at(-1),Math.sqrt(20));assert.equal(profile.distance_unit,'pixel');near(profile.samples.physical_distance.at(-1),1);assert.equal(profile.physical_distance_unit,'nm');
  const csv=exportProfileCSV(profile),csvFile=path.join(directory,'profile.csv');writeFileSync(csvFile,csv);
  const checked=spawnSync(python,['-c',String.raw`import csv,math,numpy as np,sys
rows=list(csv.DictReader(open(sys.argv[1],encoding='utf8',newline='')))
assert [int(float(r['value'])) for r in rows]==[1000,1011,1014,1029,1036]
assert math.isclose(float(rows[-1]['physical_distance']),1.0,rel_tol=1e-12)
assert all(r['physical_distance_unit']=='nm' and r['interpolation']=='nearest' and r['line_width']=='1' for r in rows)
saved=np.load(sys.argv[2],allow_pickle=False)
assert saved.dtype==np.dtype('uint16') and saved.tolist()==[1000,1011,1014,1029,1036]
print('independent profile CSV/NPY PASS')`,csvFile,path.join(workspace,'objects',profile.object_id,'profile.npy')],{encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);
  const recovery=(await panel.client.tool('image_result',{request_id:profile.request_id})).data;assert.equal(recovery.object_id,profile.object_id);assert.deepEqual(recovery.samples.value,profile.samples.value);
  const beforeRecovery=snapshot(),guiRecovery=await send('recover',{request_id:profile.request_id});assert.equal(guiRecovery.object.object_id,view);assert.equal(guiRecovery.last_operation.object_id,profile.object_id);assert.deepEqual(guiRecovery.last_operation.samples.value,profile.samples.value);assert.deepEqual(snapshot(),beforeRecovery,'GUI recovery queries the original numeric result without another profile or preview');

  // Hold only an actual completed raw response; other actual stdio calls remain
  // live. A later frame must not adopt the old probe value after release.
  const started=new Promise(resolve=>probeStarted=resolve);delayNext=true;const oldProbe=probe(probeBody([2,1]),409);await started;
  await send('frame',{frame_index:1});releaseProbe();releaseProbe=null;await oldProbe;assert.equal(panel.state().frame_identity.frame_index,1);result=await probe(probeBody([2,1]));assert.equal(result.samples[0].value,1114);

  await send('frame',{frame_index:0});await send('fft',{selection:select('rectangle',[0,0,5,3]),window:'none',subtract_mean:false});
  const fftId=panel.state().object.object_id,fftFile=path.join(workspace,'objects',fftId,'data.npy'),fftBefore=readFileSync(fftFile),beforeComplex=snapshot();
  await probe(probeBody([0,0],'raw'),400);
  for(const [component,expected]of [['real',15240],['imag',0],['amplitude',15240],['power',232257600]]){result=await probe(probeBody([0,0],component));near(result.samples[0].value,expected);assert.equal(result.component,component);assert.equal(result.dtype,'complex128');assert.deepEqual(result.samples[0].array_index_xy,[2,1]);}
  assert.deepEqual(snapshot(),beforeComplex,'explicit complex read components are read-only');
  const dcEdges=[-.5/5,-.5/3,.5/5,.5/3];
  const dcStats=(await send('statistics',{selection:select('rectangle',dcEdges),component:'real'})).last_operation;
  assert.deepEqual(dcStats.frequency_rect,[2,1,3,2]);assert.equal(dcStats.statistics.sample_count,1);near(dcStats.statistics.mean,15240);assert.equal(dcStats.statistics.stddev,0);
  const fftProfile=(await send('profile',{selection:select('line',[0,0,.2,0]),component:'amplitude',sample_count:2})).last_operation;
  assert.equal(fftProfile.distance_unit,'cycles/pixel');assert.equal(fftProfile.physical_distance_unit,'cycles/nm');near(fftProfile.samples.physical_distance.at(-1),1);near(fftProfile.samples.value[0],15240);
  let expectedReal=0,expectedImag=0;for(let x=0;x<5;x++){const angle=-2*Math.PI*x/5,coefficient=3*x*x;expectedReal+=coefficient*Math.cos(angle);expectedImag+=coefficient*Math.sin(angle);}near(fftProfile.samples.value[1],Math.hypot(expectedReal,expectedImag));
  assert.deepEqual(readFileSync(fftFile),fftBefore);assert.deepEqual(readFileSync(source),original);
  const ledgers=readdirSync(path.join(workspace,'requests')).map(name=>JSON.parse(readFileSync(path.join(workspace,'requests',name))));assert.equal(ledgers.filter(record=>record.parameters.action==='fft').length,1);assert.ok(ledgers.every(record=>record.parameters.action!=='probe'));
 }finally{releaseProbe?.();await setup?.close();await panel?.close();rmSync(directory,{recursive:true,force:true});}
});
