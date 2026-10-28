import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createImagePanel,StdioImageClient} from '../tools/image_panel.mjs';
import {transformCoordinates,selectionFromDrag,selectionRectangle,panelAt} from '../ui/image-panel/coordinates.mjs';

const python=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python';
const spatial={domain:'spatial_pixels',source_object_id:'a'.repeat(32),source_rect_xyxy:[20,12,140,84],image_rect_xyxy:[0,0,60,36]};
const frequency={domain:'frequency',source_object_id:'b'.repeat(32),fft_shape_yx:[55,95],fft_rect_xyxy:[38,22,58,34],image_rect_xyxy:[60,20,260,140]};
test('panel transforms independently preserve spatial centres/edges and odd signed original FFT bins',()=>{
 assert.deepEqual(transformCoordinates([9.75,8.75,39.75,26.75],spatial),[40,30,100,66]);
 assert.deepEqual(transformCoordinates([0,0,60,36],spatial,{edges:true}),[20,12,140,84]);
 for(const edges of [false,true])for(const p of [spatial,frequency]){
  const input=[p.image_rect_xyxy[0]+3,p.image_rect_xyxy[1]+4,p.image_rect_xyxy[2]-5,p.image_rect_xyxy[3]-6];
  const round=transformCoordinates(transformCoordinates(input,p,{edges}),p,{edges,inverse:true});round.forEach((v,i)=>assert.ok(Math.abs(v-input[i])<1e-12));
 }
 const dc=transformCoordinates([0,0],frequency,{inverse:true});assert.deepEqual(transformCoordinates(dc,frequency),[0,0]);
 assert.deepEqual(selectionRectangle(selectionFromDrag([frequency],[60,20],[260,140],{kind:'rectangle'})),[38,22,58,34]);
 assert.throws(()=>panelAt([spatial],100,10),/单一数据区域.*避开坐标轴和图外空白/);
 assert.throws(()=>selectionFromDrag([spatial,{...spatial,image_rect_xyxy:[70,0,130,36]}],[5,5],[75,5],{kind:'line'}),/one source/);
});

function fakeClient(){const id='a'.repeat(32);let number=0;const calls=[];const object={object_id:id,kind:'view',panels:[spatial],annotations:[],display:{gamma:1,display_range:[0,1]}};
 return {calls,async rpc(method){return method==='tools/list'?{result:{tools:['image_info','image_preview','image_annotate','image_export','image_result'].map(name=>({name,inputSchema:{}}))}}:{result:{}};},async tool(name,args){calls.push({name,args});return {data:name==='image_info'?object:{...object,object_id:(++number).toString(16).padStart(32,'0'),request_id:args.request_id},png:'iVBORw0KGgo='};},async close(){}};
}
test('loopback panel rejects missing token, other origins, arbitrary tools/fields and stale competing edits before dispatch',async()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'dm-panel-security-')),client=fakeClient();let panel;
 try{panel=await createImagePanel({workspace:dir,python:path.resolve(python),object_id:'a'.repeat(32),client});const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
  assert.equal((await fetch(origin+'/api/state')).status,403);
  assert.equal((await fetch(origin+'/api/state',{headers:{...headers,Origin:'http://evil.example'}})).status,403);
  assert.equal((await fetch(origin+'/server.mjs',{headers})).status,404);
  let r=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:'a'.repeat(32),action:'run_script',params:{script:'unsafe'}})});assert.equal(r.status,400);
  r=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:'a'.repeat(32),action:'preview',params:{source_path:'outside'}})});assert.equal(r.status,400);assert.equal(client.calls.length,1);
  for(const selection of [
   {kind:'point',coordinate_space:'source_pixels',source_object_id:'f'.repeat(32),coordinates:[25,20],panel:spatial},
   {kind:'point',coordinate_space:'frequency_cycles_per_pixel',source_object_id:spatial.source_object_id,coordinates:[25,20],panel:spatial},
   {kind:'point',coordinate_space:'source_pixels',source_object_id:spatial.source_object_id,coordinates:[2000,20],panel:spatial},
   {kind:'point',coordinate_space:'source_pixels',source_object_id:spatial.source_object_id,coordinates:[25,20,30],panel:spatial}
  ]){r=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:'a'.repeat(32),action:'select',params:{selection}})});assert.equal(r.status,400);assert.equal(client.calls.length,1);}
  const call=()=>fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:'a'.repeat(32),action:'preview',params:{gamma:2}})});
  const responses=await Promise.all([call(),call()]);assert.deepEqual(responses.map(r=>r.status).sort(),[200,409]);assert.equal(client.calls.filter(c=>c.name==='image_preview').length,1);
  const files=readdirSync(panel.journal);assert.equal(files.filter(f=>f.endsWith('.request.json')).length,1);const record=JSON.parse(readFileSync(path.join(panel.journal,files.find(f=>f.endsWith('.request.json')))));assert.equal(record.name,'image_preview');assert.equal(record.arguments.request_id,client.calls.at(-1).args.request_id);
 }finally{await panel?.close();rmSync(dir,{recursive:true,force:true});}
});

test('uncertain panel request is flushed before dispatch, never automatically repeated, and recover queries that original ID',async()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'dm-panel-recovery-')),client=fakeClient(),baseTool=client.tool.bind(client);let panel,acceptedId,previews=0;
 client.tool=async(name,args)=>{
  if(name==='image_preview'){
   previews++;acceptedId=args.request_id;const request=JSON.parse(readFileSync(path.join(panel.journal,`${acceptedId}.request.json`)));assert.equal(request.arguments.request_id,acceptedId);throw new Error('Simulated uncertain wait after acceptance');
  }
  if(name==='image_result'){assert.equal(args.request_id,acceptedId);const r=await baseTool('image_info',{});return {...r,data:{...r.data,object_id:'c'.repeat(32),request_id:acceptedId}};}
  return baseTool(name,args);
 };
 try{panel=await createImagePanel({workspace:dir,python:path.resolve(python),object_id:'a'.repeat(32),client});const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'},send=(action,params)=>fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:panel.state().object.object_id,action,params})});
  let response=await send('preview',{gamma:2});assert.equal(response.status,400);assert.match((await response.json()).error,new RegExp(acceptedId));assert.equal(previews,1);
  const pending=JSON.parse(readFileSync(path.join(panel.journal,'current-selection.json')));assert.equal(pending.last_operation.state,'submitted');assert.equal(pending.last_operation.request_id,acceptedId);
  response=await send('recover',{});assert.equal(response.status,200);assert.equal((await response.json()).object.object_id,'c'.repeat(32));assert.equal(previews,1);
 }finally{await panel?.close();rmSync(dir,{recursive:true,force:true});}
});

test('real stdio panel selection, FFT, sparse edit, new-client recovery and export preserve synthetic TIFF bytes',async()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'dm-panel-mcp-')),source=path.join(dir,'synthetic.tiff'),workspace=path.join(dir,'workspace');let panel,setup;
 try{const fixture=spawnSync(python,['-c',"import numpy as np,tifffile,sys; a=np.arange(32*48,dtype=np.uint16).reshape(32,48);tifffile.imwrite(sys.argv[1],np.stack([a,a+9]),photometric='minisblack',metadata=None)",source],{encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);const original=readFileSync(source);
  setup=new StdioImageClient({workspace,python});await setup.rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'panel-test',version:'1'}});const opened=(await setup.tool('image_open',{source_path:source,request_id:'panel-fixture-open'})).data;await setup.close();setup=null;
  const executable=spawnSync(python,['-c','import sys; print(sys.executable)'],{encoding:'utf8'});assert.equal(executable.status,0,executable.stderr);
  panel=await createImagePanel({workspace,python:executable.stdout.trim(),object_id:opened.object_id});let origin=panel.url.split('/#')[0];
  const send=async(action,params={})=>{const expected_object_id=panel.state().object.object_id,r=await fetch(origin+'/api/action',{method:'POST',headers:{'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({expected_object_id,action,params})});const value=await r.json();assert.equal(r.status,200,JSON.stringify(value));return value;};
  let state=panel.state();assert.equal(state.object.kind,'tiff_source');assert.equal(state.png_base64,null);
  state=await send('calibrate',{scope:'sequence',xy_scale:{x:.2,y:-.4,unit:'nm'},source_text:'Independent synthetic fixture scale, not experimental metadata'});const calibrationId=state.object.xy_calibration.calibration_id;assert.equal(state.png_base64,null);
  state=await send('frame',{frame_index:0});assert.ok(state.png_base64);assert.equal(Buffer.from(state.png_base64,'base64').subarray(0,8).toString('hex'),'89504e470d0a1a0a');assert.ok(state.object.scale_bar);
  state=await send('frame',{frame_index:1});assert.equal(state.object.xy_calibration.calibration_id,calibrationId);assert.equal(state.object.panels.length,1);assert.equal(state.frame_identity.frame_index,1);
  let selected=selectionFromDrag(state.object.panels,[4,4],[24,24],{kind:'rectangle'});await send('select',{selection:selected});const record=JSON.parse(readFileSync(path.join(panel.journal,'current-selection.json')));assert.equal(record.selection.source_object_id,state.object.panels[0].source_object_id);
  state=await send('fft',{selection:selected});assert.equal(state.object.kind,'fft');const spectrum=state.object.object_id,fp=state.object.panels[0];selected=selectionFromDrag([fp],[7,7],[12,12],{kind:'arrow'});state=await send('mark',{selection:selected,annotation_id:'peak-a',text:'candidate',status:'hypothesized'});const anchor=state.object.annotations[0].anchor;
  state=await send('edit',{updates:[{annotation_id:'peak-a',text:'user moved label',color:'orange'}]});assert.deepEqual(state.object.annotations[0].anchor,anchor);assert.equal(state.object.annotations[0].status,'hypothesized');assert.equal(state.object.annotations[0].color,'orange');
  state=await send('preview',{gamma:.8,max_size:320,upscale:true,spectrum_axes:true,display_range:[0,15]});assert.equal(state.object.fft_recomputed,false);assert.deepEqual(state.object.annotations[0].anchor,anchor);const renderBase=state.object.object_id,recipe=state.object.display;
  state=await send('edit',{updates:[{annotation_id:'peak-a',text:'saved annotated view retains visible recipe'}]});const request=state.object.request_id,object=state.object.object_id;assert.equal(state.object.display,undefined);assert.deepEqual(state.effective_display,recipe);assert.equal(state.display_source_object_id,renderBase);
  await panel.close();panel=await createImagePanel({workspace,python:executable.stdout.trim(),object_id:object});origin=panel.url.split('/#')[0];state=panel.state();assert.equal(state.object.object_id,object);assert.equal(state.object.xy_calibration.calibration_id,calibrationId);assert.deepEqual(state.effective_display,recipe);assert.equal(state.effective_display.gamma,.8);assert.equal(state.effective_display.spectrum_axes,true);assert.deepEqual(state.effective_display.display_range,[0,15]);assert.equal(state.display_source_object_id,renderBase);
  const [left,top,right,bottom]=state.object.panels[0].image_rect_xyxy,where=[left+.7*(right-left),top+.7*(bottom-top)],peak=selectionFromDrag(state.object.panels,where,where,{kind:'point'});state=await send('measure',{selection:peak});const q=Math.hypot(peak.coordinates[0]/.2,peak.coordinates[1]/-.4);assert.ok(Math.abs(state.last_operation.physical_frequency_magnitude-q)<1e-12);assert.ok(Math.abs(state.last_operation.period-1/q)<1e-12);assert.equal(state.last_operation.calibration_dependency.calibration_id,calibrationId);assert.equal(state.object.object_id,object);
  const reopened=new StdioImageClient({workspace,python});try{await reopened.rpc('initialize',{});const recovered=await reopened.tool('image_result',{request_id:request});assert.equal(recovered.data.object_id,object);assert.ok(recovered.png);}finally{await reopened.close();}
  state=await send('export');const out=state.last_operation.output_dir;assert.ok(readFileSync(path.join(out,'preview.png')).length>20);assert.equal(JSON.parse(readFileSync(path.join(out,'manifest.json'))).display_object.annotations[0].anchor.source_object_id,spectrum);assert.deepEqual(readFileSync(source),original);
 }finally{await setup?.close();await panel?.close();rmSync(dir,{recursive:true,force:true});}
});
