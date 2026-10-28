import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createImagePanel,StdioImageClient} from '../tools/image_panel.mjs';
import {makeFigureRecipe,figureDisplayParameters,recipeIdentity} from '../ui/image-panel/figure-export.mjs';

const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32),D='d'.repeat(32),F='f'.repeat(32);
const clone=value=>structuredClone(value);
const reversedKeys=value=>Array.isArray(value)?value.map(reversedKeys):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).reverse().map(([key,item])=>[key,reversedKeys(item)])):value;
const grid={domain:'spatial_pixels',source_object_id:F,source_rect_xyxy:[0,0,32,32],image_rect_xyxy:[0,0,32,32]};
const scientificGrid={source_grid_object_id:F,shape_yx:[32,32],array_sha256:'1'.repeat(64),coordinate_space:'source_pixels'};
const presentation={marker_shape:'circle',marker_radius:5,category:'A',layer:'experimental',label:{text:'g₁',offset:[12,-8],font_size:12,leader:true}};
const mark={annotation_id:'first',kind:'point',status:'user_confirmed',text:'original science statement',presentation,
 anchor:{coordinate_space:'source_pixels',source_object_id:F,coordinates:[7,9]}};
const selection={kind:'point',...mark.anchor,panel:grid};
// The helper verifies format signature and stored digest; PNG decoding belongs
// to the real-browser fixture, not this controlled transport boundary test.
const cleanBytes=Buffer.from('89504e470d0a1a0a00000000','hex');
const cleanHash=createHash('sha256').update(cleanBytes).digest('hex');
const scaleBar={visible:true,label:'0.1 nm',length_pixels:5};

async function fixture(run,{calibrated=false,spectral=false,changedGrid=false,lostReply=null,reorderedKeys=false}={}){
 const workspace=mkdtempSync(path.join(tmpdir(),'dm-presentation-transport-')),calls=[];
 const panelGrid=spectral?{domain:'frequency',source_object_id:F,fft_shape_yx:[32,32],image_rect_xyxy:[0,0,32,32]}:grid;
 const initialMark=spectral?{...clone(mark),anchor:{coordinate_space:'frequency_cycles_per_pixel',source_object_id:F,coordinates:[.125,.125]}}:clone(mark);
 const base={kind:'view',parent_object_id:F,panels:[panelGrid],scientific_grid_identity:scientificGrid,shape_yx:[32,32],display:{gamma:1,display_range:[0,255],max_size:32,upscale:false,interpolation:'lanczos',...(spectral?{representation:'log_amplitude',frequency_rect:[0,0,32,32],spectrum_axes:false,spectrum_filter:null}:{scale_bar:false})},annotations:[initialMark],
  ...(calibrated?{xy_calibration:{status:'active',coordinate_domain:'real_space'}}:{})};
 const records=new Map([[A,{...clone(base),object_id:A}],[F,{kind:'frame',object_id:F,frame_index:0,source_object_id:'e'.repeat(32)}]]);
 let panel,failed=false,previewSequence=0;
 const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_preview','image_result','image_annotate'].map(name=>({name,inputSchema:{}}))}:{}};},
  async tool(name,args){
   calls.push({name,args:clone(args)});
   if(name==='image_info'||name==='image_result'){
    const id=name==='image_info'?args.object_id:([...records.values()].find(record=>record.request_id===args.request_id)?.object_id);
    assert.ok(records.has(id));return {data:clone(records.get(id)),png:cleanBytes.toString('base64')};
   }
   // Save-before-dispatch is still true for the new display-only operation.
   const request=JSON.parse(readFileSync(path.join(panel.journal,`${args.request_id}.request.json`),'utf8'));
   assert.equal(request.name,name);assert.deepEqual(request.arguments,args);
   if(name==='image_annotate'){
    const annotations=args.annotations??[...clone(records.get(args.object_id).annotations)];
    for(const update of args.updates??[]){const current=annotations.find(value=>value.annotation_id===update.annotation_id);Object.assign(current,update);}
    const data={...clone(base),object_id:D,parent_object_id:args.object_id,request_id:args.request_id,kind:'annotate',annotations};
    if(reorderedKeys){data.panels=reversedKeys(data.panels);data.scientific_grid_identity=reversedKeys(data.scientific_grid_identity);}
    records.set(D,data);return {data:clone(data),png:cleanBytes.toString('base64')};
   }
   assert.equal(name,'image_preview');
   const scaled=args.scale_bar===true,id=scaled?C:(++previewSequence===1?B:previewSequence.toString(16).padStart(32,'0'));
   const parent=records.get(args.object_id),controls=Object.fromEntries(Object.entries(args).filter(([key])=>!['request_id','object_id'].includes(key)));
   const data={...clone(base),object_id:id,parent_object_id:args.object_id,request_id:args.request_id,display:{...clone(parent.display),...controls},annotations:args.gamma!==undefined?clone(parent.annotations):[],scale_bar:scaled?scaleBar:{visible:false}};
   if(reorderedKeys)data.panels=reversedKeys(data.panels);
   if(changedGrid&&!scaled)data.panels=[{...panelGrid,image_rect_xyxy:[0,0,31,32]}];
   if(!scaled){
    const directory=path.join(workspace,'objects',id);mkdirSync(directory,{recursive:true});writeFileSync(path.join(directory,'preview.png'),cleanBytes);
    data.files_sha256={'preview.png':cleanHash};
   }
   records.set(id,data);
   if(lostReply===(scaled?'scale':'clean')&&!failed){failed=true;throw new Error('Controlled reply loss after saved render');}
   return {data:clone(data),png:cleanBytes.toString('base64')};
  },async close(){}};
 panel=await createImagePanel({workspace,python:path.resolve('unused-python'),object_id:A,client});
 const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
 const act=async(action,params={},extra={})=>{const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params,...extra})});return {status:response.status,data:await response.json()};};
 try{await run({panel,act,calls,origin,initialMark,panelGrid});}finally{await panel.close();rmSync(workspace,{recursive:true,force:true});}
}

test('spatial measurements bind the selected saved view or annotation without intermediate context or calibration writes',async()=>{
 for(const kind of ['view','annotate']){
  const workspace=mkdtempSync(path.join(tmpdir(),'dm-bound-spatial-measure-')),calls=[];
  const selected={kind:'line',coordinate_space:'source_pixels',source_object_id:F,coordinates:[3,4,13,4],panel:grid};
  const current={object_id:A,kind,parent_object_id:F,display:{gamma:1},panels:[grid],annotations:[],
   user_context:{data_meaning:'synthetic_demo',source_text:'Explicit routing test'},
   xy_calibration:{calibration_id:C,status:'active',coordinate_domain:'real_space',xy_scale:{x:.02,y:.02,unit:'nm'}}};
  let panel;
  const client={async rpc(method){return {result:method==='tools/list'?{tools:['image_info','image_context','image_calibrate','image_measure'].map(name=>({name,inputSchema:{}}))}:{}};},
   async tool(name,args){
    calls.push({name,args:clone(args)});
    if(name==='image_info')return {data:clone(args.object_id===A?current:{object_id:F,kind:'frame',frame_index:0,source_object_id:B}),png:cleanBytes.toString('base64')};
    assert.equal(name,'image_measure','measurement must not recreate context or calibration');
    const request=JSON.parse(readFileSync(path.join(panel.journal,`${args.request_id}.request.json`),'utf8'));
    assert.equal(request.name,'image_measure');assert.deepEqual(request.arguments,args);
    assert.equal(args.object_id,A);assert.deepEqual(args.points,[[3,4],[13,4]]);assert.equal(args.coordinate_space,'source_pixels');
    return {data:{object_id:D,kind:'measure',request_id:args.request_id,parent_object_id:A,points:clone(args.points),coordinate_space:args.coordinate_space,physical_distance:.2,physical_unit:'nm'}};
   },async close(){}};
  try{
   panel=await createImagePanel({workspace,python:path.resolve('unused-python'),object_id:A,client});
   const origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
   const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:A,draft_revision:0,action:'measure',params:{selection:selected}})}),result=await response.json();
   assert.equal(response.status,200,JSON.stringify(result));assert.equal(result.object.object_id,A);assert.deepEqual(result.selection,selected);
   assert.equal(result.last_operation.parent_object_id,A);assert.equal(result.last_operation.physical_distance,.2);
   assert.equal(calls.filter(call=>call.name==='image_measure').length,1);
   assert.equal(calls.filter(call=>['image_context','image_calibrate'].includes(call.name)).length,0);
  }finally{await panel?.close();rmSync(workspace,{recursive:true,force:true});}
 }
});

test('fresh source display is restricted to the current frame and never dispatches FFT',async()=>fixture(async({act,calls})=>{
 const before=calls.length;assert.equal((await act('show',{object_id:A,source_view:true})).status,409);assert.equal(calls.length,before);
 assert.equal((await act('show',{object_id:F,source_view:false})).status,400);assert.equal(calls.length,before);
 const reply=await act('show',{object_id:F,source_view:true});assert.equal(reply.status,200);
 assert.deepEqual(calls.slice(before).filter(c=>c.name!=='image_info').map(c=>({name:c.name,object_id:c.args.object_id})),[{name:'image_preview',object_id:F}]);
}));

test('presentation draft and sparse save retain the scientific anchor and confirmation',async()=>fixture(async({panel,act,calls,initialMark})=>{
 const changed={...clone(presentation),label:{...presentation.label,text:'display label',offset:[30,12]}};
 const draft=await act('draft',{draft_revision:1,dirty:true,gesture_active:true,selection,annotation_edit:{annotation_id:'first',presentation:changed}},{lightweight:true});
 assert.equal(draft.status,200);assert.deepEqual(draft.data.edit_state.annotation_edit.presentation,changed);
 assert.deepEqual(panel.state().object.annotations[0],initialMark);
 await act('draft',{draft_revision:2,dirty:true,gesture_active:false},{lightweight:true});
 const saved=await act('edit',{updates:[{annotation_id:'first',presentation:changed}],auto_commit:true});
 assert.equal(saved.status,200);assert.equal(saved.data.auto_edit_committed,true);
 assert.deepEqual(saved.data.object.annotations[0].anchor,initialMark.anchor);
 assert.equal(saved.data.object.annotations[0].status,'user_confirmed');assert.equal(saved.data.object.annotations[0].text,initialMark.text);
 const sent=calls.filter(value=>value.name==='image_annotate').at(-1).args.updates[0];
 assert.deepEqual(sent,{annotation_id:'first',presentation:changed});
}));

test('new mark replacement preserves existing presentation and rejects unbounded metadata before dispatch',async()=>fixture(async({act,calls})=>{
 for(const value of [{status:'user_confirmed'},{label:{href:'javascript:bad'}},{label:{offset:[4097,0]}},{line_width:4},{marker_shape:'script'}]){
  const result=await act('draft',{draft_revision:1,dirty:true,gesture_active:false,annotation_edit:{annotation_id:'first',presentation:value}},{lightweight:true});
  assert.equal(result.status,400);
 }
 assert.equal(calls.filter(value=>value.name==='image_annotate').length,0);
 const result=await act('mark',{selection,annotation_id:'new-mark',presentation:{category:'unexplained',label:{text:'g₂'}}});
 assert.equal(result.status,200);
 const sent=calls.find(value=>value.name==='image_annotate').args.annotations;
 assert.deepEqual(sent[0].presentation,presentation);assert.equal(sent[0].status,'user_confirmed');assert.deepEqual(sent[0].coordinates,mark.anchor.coordinates);
 assert.equal(sent[1].status,'hypothesized');assert.equal(sent[1].presentation.category,'unexplained');
}));

test('layout batch saves one presentation-only revision while retaining selection, anchors and authority',async()=>fixture(async({panel,act,calls})=>{
 assert.equal((await act('mark',{selection,annotation_id:'new-mark',presentation:{label:{text:'g₂'}}})).status,200);
 const selected={...selection,coordinates:[11,12]};await act('select',{selection:selected});
 const before=clone(panel.state()),writes=calls.filter(value=>value.name==='image_annotate').length;
 const updates=[{annotation_id:'first',presentation:{label:{offset:[20,-8]}},presentation_replace:true},{annotation_id:'new-mark',presentation:{category:'unexplained',label:{offset:[-12,18]}}}];
 const result=await act('edit-layout',{updates,auto_commit:true});
 assert.equal(result.status,200);assert.equal(result.data.auto_edit_committed,true);assert.deepEqual(result.data.selection,selected);
 assert.equal(calls.filter(value=>value.name==='image_annotate').length,writes+1);
 assert.deepEqual(calls.filter(value=>value.name==='image_annotate').at(-1).args.updates,updates);
 for(let i=0;i<before.object.annotations.length;i++)for(const key of ['anchor','status','text'])assert.deepEqual(result.data.object.annotations[i][key],before.object.annotations[i][key]);
 const count=calls.filter(value=>value.name==='image_annotate').length;
 assert.equal((await act('edit-layout',{updates:[{annotation_id:'first',coordinates:[8,9],presentation:{}}]})).status,400);
 assert.equal((await act('edit-layout',{updates:[{annotation_id:'first',presentation:{}},{annotation_id:'first',presentation:{}}]})).status,400);
 assert.equal((await act('edit-layout',{updates:[]})).status,400);
 assert.equal((await act('edit',{updates:[{annotation_id:'first',presentation_replace:true}]})).status,400);
 assert.equal((await act('draft',{draft_revision:1,dirty:true,gesture_active:false,annotation_edit:{annotation_id:'first',presentation:{},presentation_replace:true}},{lightweight:true})).status,400);
 assert.equal((await act('edit',{updates})).status,400);
 assert.equal(calls.filter(value=>value.name==='image_annotate').length,count);
}));

test('figure base returns verified clean assets and sourced bar without adopting a new view or consuming a draft',async()=>fixture(async({panel,act,calls,origin})=>{
 await act('draft',{draft_revision:1,dirty:true,gesture_active:true,selection,annotation_edit:{annotation_id:'first',presentation:{label:{offset:[15,-6]}}}},{lightweight:true});
 const before=panel.state(),result=await act('figure-base');assert.equal(result.status,200);
 assert.equal(result.data.object.object_id,A);assert.equal(panel.state().object.object_id,A);assert.equal(result.data.state_revision,before.state_revision);
 assert.deepEqual(result.data.edit_state,before.edit_state);assert.deepEqual(result.data.selection,before.selection);
 assert.deepEqual(result.data.figure_base,{object_id:B,request_id:calls.filter(value=>value.name==='image_preview').at(-1).args.request_id,
  clean_png_base64:cleanBytes.toString('base64'),clean_png_sha256:cleanHash,scale_bar:scaleBar,panels:[grid]});
 const previews=calls.filter(value=>value.name==='image_preview');
 assert.deepEqual(previews.map(value=>value.args.scale_bar),[true,false]);assert.ok(previews.every(value=>value.args.object_id===A&&value.args.spectrum_axes===undefined));
 assert.ok(calls.every(value=>value.name!=='image_fft'));
 for(const resource of ['annotation-presentation.mjs','figure-export.mjs'])assert.equal((await fetch(origin+'/'+resource)).status,200);
 const csp=(await fetch(origin+'/')).headers.get('content-security-policy');assert.match(csp,/img-src 'self' data: blob:/);assert.doesNotMatch(csp,/unsafe-inline/);
},{calibrated:true}));

test('FFT figure base only revises display and refuses changed render mapping',async()=>{
 await fixture(async({panel,act,calls})=>{const result=await act('figure-base');assert.equal(result.status,200);assert.equal(panel.state().object.object_id,A);
  const args=calls.find(value=>value.name==='image_preview').args;assert.equal(args.spectrum_axes,false);assert.equal(args.scale_bar,undefined);},{spectral:true});
 await fixture(async({panel,act})=>{const result=await act('figure-base');assert.equal(result.status,409);assert.match(result.data.error,/exact current source\/render mapping/);assert.equal(panel.state().object.object_id,A);assert.ok(panel.state().last_operation.request_id);},{changedGrid:true});
});

test('dictionary key order does not alter panel or grid identity while coordinate array values remain exact',async()=>fixture(async({panel,act})=>{
 const selected={...selection,panel:reversedKeys(grid)};
 assert.equal((await act('select',{selection:selected})).status,200);
 const asset=await act('figure-base');assert.equal(asset.status,200);assert.equal(panel.state().object.object_id,A);
 assert.deepEqual(asset.data.figure_base.panels,[grid]);
 const saved=await act('edit-layout',{updates:[{annotation_id:'first',presentation:{label:{offset:[20,-8]}}}],auto_commit:true});
 assert.equal(saved.status,200);assert.equal(saved.data.auto_edit_committed,true);assert.deepEqual(saved.data.selection,selected);
 const changed={...selected,panel:{...selected.panel,source_rect_xyxy:[0,0,31,32]}};
 assert.equal((await act('select',{selection:changed})).status,400);
 const reorderedArray={...selected,panel:{...selected.panel,source_rect_xyxy:[0,32,32,0]}};
 assert.equal((await act('select',{selection:reorderedArray})).status,400);
},{calibrated:true,reorderedKeys:true}));

test('lost figure replies query the original render without resubmission or accidental view adoption',async()=>{
 await fixture(async({panel,act,calls})=>{const failed=await act('figure-base');assert.equal(failed.status,400);assert.match(failed.data.error,/Original request_id=/);
  const original=panel.state().last_operation.request_id,result=await act('recover');assert.equal(result.status,200);assert.equal(result.data.figure_base.object_id,B);assert.equal(panel.state().object.object_id,A);
  assert.equal(calls.filter(value=>value.name==='image_preview').length,1);assert.equal(calls.find(value=>value.name==='image_result').args.request_id,original);
 },{lostReply:'clean'});
 await fixture(async({panel,act,calls})=>{assert.equal((await act('figure-base')).status,400);const result=await act('recover');assert.equal(result.status,200);
  assert.equal(result.data.figure_base,undefined);assert.equal(result.data.figure_base_recovery.state,'scale_render_saved_clean_render_not_submitted');
  assert.equal(calls.filter(value=>value.name==='image_preview').length,1);assert.equal(panel.state().object.object_id,A);
 },{calibrated:true,lostReply:'scale'});
});

const figurePreferences={preset:'real-space',mode:'figure',columns:'single',fontPt:8,layers:{experimental:true,simulation_A:false,simulation_B:false},legend:false,scaleBar:false,letter:'a'};

test('figure display restore replays explicit gamma/range and rejects missing or unbound recipes before writing',async()=>fixture(async({panel,act,calls})=>{
 const before=clone(panel.state()),recipe=makeFigureRecipe(before,figurePreferences);
 assert.equal((await act('preview',{gamma:2,display_range:[20,200]})).status,200);
 assert.equal(panel.state().effective_display.gamma,2);
 const restored=await act('restore-figure-display',{recipe});assert.equal(restored.status,200,JSON.stringify(restored.data));
 assert.equal(restored.data.effective_display.gamma,1);assert.deepEqual(restored.data.effective_display.display_range,[0,255]);
 assert.deepEqual(restored.data.object.annotations,before.object.annotations);assert.deepEqual(recipeIdentity(restored.data),recipe.source);
 const sent=calls.filter(v=>v.name==='image_preview').at(-1).args;
 for(const [key,value]of Object.entries(figureDisplayParameters(recipe.display_recipe,recipe.source.panels)))assert.deepEqual(sent[key],value);
 const count=calls.filter(v=>v.name==='image_preview').length;
 for(const mutate of [r=>delete r.display_recipe,r=>delete r.display_recipe.gamma,r=>{r.display_recipe.gamma=3;},r=>{r.source.panels[0].source_object_id=C;},r=>{r.source.calibration={calibration_id:C};},r=>{r.source.grid.array_sha256='2'.repeat(64);},r=>{r.source.anchors[0].status='hypothesized';}]){
  const bad=clone(recipe);mutate(bad);const result=await act('restore-figure-display',{recipe:bad});assert.ok([400,409].includes(result.status),JSON.stringify(result));
 }
 assert.equal(calls.filter(v=>v.name==='image_preview').length,count);assert.ok(calls.every(v=>v.name!=='image_fft'));
}));

test('uncertain figure display restoration queries the exact original saved render without re-execution',async()=>fixture(async({panel,act,calls})=>{
 const recipe=makeFigureRecipe(panel.state(),figurePreferences),before=clone(panel.state().object);
 const failed=await act('restore-figure-display',{recipe});assert.equal(failed.status,400);assert.match(failed.data.error,/Original request_id=/);
 const original=panel.state().last_operation.request_id;assert.deepEqual(panel.state().object,before);
 const recovered=await act('recover');assert.equal(recovered.status,200,JSON.stringify(recovered.data));
 assert.equal(recovered.data.effective_display.gamma,1);assert.deepEqual(recovered.data.object.annotations,before.annotations);
 assert.equal(calls.filter(v=>v.name==='image_preview').length,1);assert.equal(calls.filter(v=>v.name==='image_result').at(-1).args.request_id,original);
 assert.equal(JSON.parse(readFileSync(path.join(panel.journal,`${original}.request.json`),'utf8')).name,'image_preview');
},{lostReply:'clean'}));

test('explicit recovery retains the original journaled request identity after later operations',async()=>fixture(async({panel,act,calls})=>{
 assert.equal((await act('preview',{gamma:2})).status,200);const original=panel.state().object.request_id;
 assert.equal((await act('preview',{gamma:3})).status,200);assert.notEqual(panel.state().last_operation.request_id,original);
 const previews=calls.filter(v=>v.name==='image_preview').length,recovered=await act('recover',{request_id:original});assert.equal(recovered.status,200);
 assert.equal(calls.filter(v=>v.name==='image_result').at(-1).args.request_id,original);assert.equal(recovered.data.object.request_id,original);assert.equal(recovered.data.effective_display.gamma,2);assert.equal(calls.filter(v=>v.name==='image_preview').length,previews);
 const queries=calls.filter(v=>v.name==='image_result').length;
 assert.equal((await act('recover',{request_id:'../foreign'})).status,400);assert.equal((await act('recover',{request_id:'not-journaled'})).status,404);assert.equal((await act('recover',{request_id:null})).status,400);assert.equal(calls.filter(v=>v.name==='image_result').length,queries);
}));

// Opt in explicitly for bounded backend acceptance; ordinary lightweight CI
// keeps the controlled transport contracts and needs no analysis environment.
test('real MCP restores gamma, range and exact clean PNG pixels over spatial and saved FFT arrays',{skip:process.env.DM_PANEL_REAL_RECIPE_TEST!=='1'},async()=>{
 const python=process.env.DM_IMAGE_PYTHON??process.env.DM_TEST_PYTHON??'python',dir=mkdtempSync(path.join(tmpdir(),'dm-figure-display-mcp-')),source=path.join(dir,'synthetic.tiff');let setup,panel;
 try{
  const fixture=spawnSync(python,['-c',"import numpy as np,tifffile,sys; y,x=np.indices((32,48)); tifffile.imwrite(sys.argv[1],((x*197+y*357)%4096).astype(np.uint16),photometric='minisblack',metadata=None); print(sys.executable)",source],{encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);const executable=fixture.stdout.trim(),sourceBytes=readFileSync(source);
  const pixelDigest=base64=>{const r=spawnSync(executable,['-c',"from PIL import Image; import io,hashlib,sys; im=Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGBA'); print(str(im.size)+hashlib.sha256(im.tobytes()).hexdigest())"],{input:Buffer.from(base64,'base64'),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
  for(const spectral of [false,true]){
   const workspace=path.join(dir,spectral?'frequency':'spatial');setup=new StdioImageClient({workspace,python:executable});await setup.rpc('initialize',{});let sequence=0;
   const tool=async(name,args)=>(await setup.tool(name,{...args,request_id:`display-fixture-${++sequence}`})).data;
   const opened=await tool('image_open',{source_path:source}),frame=await tool('image_frame',{object_id:opened.object_id,frame_index:0}),calibrated=await tool('image_calibrate',{object_id:frame.object_id,scope:'image',xy_scale:{x:.02,y:.02,unit:'nm'},source_text:'Synthetic display-restore calibration; not experimental metrology'});
   let scientific=calibrated;
   if(spectral)scientific=await tool('image_fft',{object_id:calibrated.object_id,rect:[0,0,48,32],window:'none',subtract_mean:false});
   const view=await tool('image_preview',{object_id:scientific.object_id,gamma:1,display_range:spectral?[0,18]:[0,4095],max_size:96,upscale:true,interpolation:'nearest',...(spectral?{representation:'log_amplitude',spectrum_axes:false,spectrum_filter:null,frequency_rect:[4,2,44,30]}:{scale_bar:false})}),space=spectral?'frequency_cycles_per_pixel':'source_pixels',points=spectral?[[0,0],[.125,.125]]:[[3,4],[13,4]],measurement=await tool('image_measure',{object_id:view.object_id,points,coordinate_space:space});
   const annotated=await tool('image_annotate',{object_id:view.object_id,annotations:[{annotation_id:'measured',kind:'line',coordinates:points.flat(),coordinate_space:space,source_object_id:view.panels[0].source_object_id,text:'saved numeric label',status:'user_confirmed',presentation:{marker_shape:'circle',label:{offset:[8,-8],text:spectral?'d = measured':'d = 0.2 nm',measurement_object_id:measurement.object_id,measurement_kind:spectral?'period':'distance'}}}]});
   await setup.close();setup=null;
   const worker=new StdioImageClient({workspace,python:executable}),calls=[];let loseRestoreReply=false,failed=false;
   const audited={rpc:(...args)=>worker.rpc(...args),async tool(name,args){calls.push({name,args:clone(args)});const result=await worker.tool(name,args);if(loseRestoreReply&&name==='image_preview'&&!failed){failed=true;throw new Error('Controlled lost real MCP display response');}return result;},close:()=>worker.close()};
   panel=await createImagePanel({workspace,python:executable,object_id:annotated.object_id,client:audited});const origin=panel.url.split('/#')[0];
   const act=async(action,params={},expected=200)=>{const r=await fetch(origin+'/api/action',{method:'POST',headers:{'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({expected_object_id:panel.state().object.object_id,draft_revision:panel.state().edit_state.draft_revision,action,params})}),data=await r.json();assert.equal(r.status,expected,JSON.stringify(data));return data;};
   const initial=clone(panel.state()),recipe=makeFigureRecipe(initial,{...figurePreferences,preset:spectral?'diffraction':'real-space'}),originalArray=readFileSync(path.join(workspace,'objects',view.object_id,'data.npy')),clean=await act('figure-base'),cleanPixels=pixelDigest(clean.figure_base.clean_png_base64);
   await act('preview',{gamma:2});assert.equal(panel.state().effective_display.gamma,2);assert.notEqual(pixelDigest(panel.state().png_base64),pixelDigest(initial.png_base64));
   await act('restore-figure-display',{recipe});assert.equal(panel.state().effective_display.gamma,1);assert.equal(pixelDigest(panel.state().png_base64),pixelDigest(initial.png_base64));
   await act('preview',{display_range:spectral?[2,15]:[500,3500]});assert.notDeepEqual(panel.state().effective_display.display_range,recipe.display_recipe.display_range);
   await act('edit-layout',{updates:[{annotation_id:'measured',presentation:{marker_shape:'diamond',label:{offset:[20,6]}}}],auto_commit:true});
   const count=calls.filter(v=>v.name==='image_preview').length;loseRestoreReply=true;
   const uncertain=await act('restore-figure-display',{recipe},400);assert.match(uncertain.error,/Original request_id=/);const originalRequest=panel.state().last_operation.request_id;
   await act('recover');assert.equal(calls.filter(v=>v.name==='image_preview').length,count+1);assert.equal(calls.filter(v=>v.name==='image_result').at(-1).args.request_id,originalRequest);
   assert.deepEqual(figureDisplayParameters(panel.state().effective_display,panel.state().object.panels),figureDisplayParameters(recipe.display_recipe,recipe.source.panels));
   await act('edit-layout',{updates:recipe.annotations.map(v=>({...v,presentation_replace:true})),auto_commit:true});
   const final=panel.state(),finalClean=await act('figure-base');assert.deepEqual(recipeIdentity(final),recipe.source);assert.deepEqual(final.object.annotations[0].presentation,initial.object.annotations[0].presentation);assert.equal(final.object.annotations[0].presentation.label.measurement_object_id,measurement.object_id);
   assert.equal(pixelDigest(finalClean.figure_base.clean_png_base64),cleanPixels);assert.equal(pixelDigest(final.png_base64),pixelDigest(initial.png_base64));
   assert.deepEqual(readFileSync(path.join(workspace,'objects',final.render_base_id,'data.npy')),originalArray);assert.deepEqual(readFileSync(source),sourceBytes);assert.ok(calls.every(v=>v.name!=='image_fft'));if(spectral)assert.equal(final.object.fft_recomputed??false,false);
   const replayed=makeFigureRecipe(final,recipe.preferences);assert.deepEqual(replayed.source,recipe.source);assert.deepEqual(figureDisplayParameters(replayed.display_recipe,replayed.source.panels),figureDisplayParameters(recipe.display_recipe,recipe.source.panels));
   await panel.close();panel=null;
  }
 }finally{await panel?.close();await setup?.close();rmSync(dir,{recursive:true,force:true});}
});
