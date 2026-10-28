import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImagePanel} from '../tools/image_panel.mjs';

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
 const base={kind:'view',parent_object_id:F,panels:[panelGrid],scientific_grid_identity:scientificGrid,shape_yx:[32,32],display:{gamma:1},annotations:[initialMark],
  ...(calibrated?{xy_calibration:{status:'active',coordinate_domain:'real_space'}}:{})};
 const records=new Map([[A,{...clone(base),object_id:A}],[F,{kind:'frame',object_id:F,frame_index:0}]]);
 let panel,failed=false;
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
   const scaled=args.scale_bar===true,id=scaled?C:B;
   const data={...clone(base),object_id:id,parent_object_id:args.object_id,request_id:args.request_id,annotations:[],scale_bar:scaled?scaleBar:{visible:false}};
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
