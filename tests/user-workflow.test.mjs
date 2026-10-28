import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {UserActionHistory,SavedViewHistory,workflowScope,selectionActionReason,measurementLabel,framePreviewRecipe} from '../ui/image-panel/user-workflow.mjs';
import {profileTicks,profileReadout,nearestProfileSample,DataProbes} from '../ui/image-panel/data-probes.mjs';
const state=(id='a',domain='spatial_pixels')=>({frame_identity:{frame_object_id:'frame'},object:{object_id:id,panels:[{source_object_id:'frame',domain,source_rect_xyxy:[0,0,80,80]}]}});
test('history mixes geometry/display/selection in one chronological queue and groups only continuous slider input',()=>{
 const h=new UserActionHistory();h.push({kind:'annotation',before:{x:1},after:{x:2},scope:'one'});h.push({kind:'display',before:{gamma:1},after:{gamma:2},scope:'one'},{group:'gamma'});h.push({kind:'display',before:{gamma:2},after:{gamma:3},scope:'one'},{group:'gamma'});assert.equal(h.undoItems.length,2);assert.deepEqual(h.peek().before,{gamma:1});
 const d=h.peek();h.finish('undo',d);assert.equal(h.peek().kind,'annotation');const a=h.peek();h.finish('undo',a);assert.equal(h.peek('redo').kind,'annotation');h.finish('redo',a);assert.equal(h.peek('redo').kind,'display');
 h.push({kind:'selection',before:null,after:{x:3},scope:'one'});assert.equal(h.peek('redo'),null);
});
test('action availability rejects rectangles/real-space points before measure and frequency ROIs before FFT',()=>{
 const pick=(kind,domain)=>({kind,panel:{domain},coordinates:kind==='point'?[1,2]:[1,2,3,4]});
 assert.ok(selectionActionReason('measure',pick('rectangle','spatial_pixels')));assert.ok(selectionActionReason('measure',pick('point','spatial_pixels')));assert.equal(selectionActionReason('measure',pick('point','frequency')),'');assert.ok(selectionActionReason('fft',pick('rectangle','frequency')));assert.equal(selectionActionReason('statistics',pick('rectangle','frequency')),'');assert.equal(measurementLabel(pick('line','spatial_pixels'),1),'测距 1');
});
test('frequency gamma/range cannot be inherited by spatial frame navigation; spatial fixed range is preserved',()=>{
 const display={gamma:2,display_range:[2,15],max_size:600};assert.deepEqual(framePreviewRecipe(state('fft','frequency').object,display),{max_size:600});assert.deepEqual(framePreviewRecipe(state().object,display),display);assert.deepEqual(framePreviewRecipe({},display),{max_size:600});
 const backend=readFileSync(new URL('../tools/image_panel.mjs',import.meta.url),'utf8');assert.match(backend,/framePreviewRecipe\(current,effectiveDisplay\)/);
});
test('view references return to saved objects, update same-grid annotations in place and retain back/forward',()=>{
 const h=new SavedViewHistory();h.remember(state(),{role:'原图'});h.remember(state('b'),{replace:true});assert.equal(h.entries.length,1);h.remember(state('fft','frequency'),{role:'FFT'});assert.equal(h.target(-1).id,'b');h.remember(state('b'));assert.equal(h.target(1).id,'fft');assert.equal(h.original(state('fft','frequency')).id,'b');assert.notEqual(workflowScope(state()),workflowScope(state('fft','frequency')));
});
test('directly reopened ROI or FFT cannot impersonate a saved full-source display recipe',()=>{
 for(const domain of ['spatial_pixels','frequency']){
  const h=new SavedViewHistory(),saved=state('saved-'+domain,domain);
  h.remember(saved);assert.equal(h.entries[0].role,domain==='frequency'?'FFT':'保存视图');
  const original=h.original(saved);assert.equal(original.id,'frame');assert.equal(original.freshSourceView,true);assert.equal(original.role,'全帧（新显示）');assert.notEqual(original.id,saved.object.object_id);
  const full=state('known-full-source');h.remember(full,{role:'原图'});h.remember(state('edited-full-source'),{replace:true});
  assert.equal(h.original(saved).id,'edited-full-source');assert.equal(h.original(saved).freshSourceView,undefined);
 }
});
const profile={kind:'profile',object_id:'p',parent_object_id:'a',component:'raw',dtype:'uint16',distance_unit:'pixel',physical_distance_unit:'nm',samples:{coordinates_xy:[[0,0],[1,0],[2,0],[3,0],[4,0]],indices_xy:[[0,0],[1,0],[2,0],[3,0],[4,0]],sampled_coordinates_xy:[[0,0],[1,0],[2,0],[3,0],[4,0]],distance:[0,1,2,3,4],physical_distance:[0,.2,.4,.6,.8],value:[10,20,15,28,12]}};
test('profile ticks/readouts use saved physical or pixel axes and never invent interpolated measurements',()=>{
 assert.deepEqual(profileTicks(0,.8),[0,.2,.4,.6000000000000001,.8]);assert.deepEqual(profileTicks(5,5),[5]);const r=profileReadout(profile,2);assert.equal(r.x,.4);assert.equal(r.value,15);assert.equal(r.unit,'nm');assert.equal(nearestProfileSample(profile,.39),2);assert.deepEqual(profile.samples.value,[10,20,15,28,12]);
});
test('rendered profile has both numeric axes, a quantity title and keyboard/table-linked exact readout',()=>{
 class E{constructor(){this.children=[];this.attrs={};this.dataset={};this.textContent='';}replaceChildren(){this.children=[];}append(e){this.children.push(e);}setAttribute(k,v){this.attrs[k]=String(v);}getBoundingClientRect(){return {left:0,top:0,width:560,height:200};}}
 const els=new Map(['profile-values','profile-plot','profile-summary','profile-readout'].map(k=>[k,new E()]));const doc={getElementById:k=>els.get(k),createElement:()=>new E(),createElementNS:()=>new E()};const d=new DataProbes({document:doc,getState:()=>state(),api:()=>{throw new Error('Rendering must not call science');}});d.profile=profile;d.renderProfile();const labels=els.get('profile-plot').children.map(e=>e.textContent);assert.ok(labels.includes('0.8'));assert.ok(labels.includes('距离 (nm)'));assert.ok(labels.some(v=>v.includes('原始数值')));els.get('profile-plot').onkeydown({key:'End',preventDefault(){}});assert.match(els.get('profile-readout').textContent,/0.8 nm/);els.get('profile-values').children[2].onclick();assert.match(els.get('profile-readout').textContent,/采样 2.*0.4 nm.*15/);
});
