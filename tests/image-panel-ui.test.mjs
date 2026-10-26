// Execute the actual UI event handlers with a deterministic DOM/canvas/API shim.
// No browser timing, DM, private data, or worker/backend qualification is implied.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import * as coordinates from '../ui/image-panel/coordinates.mjs';
import * as viewerState from '../ui/image-panel/viewer-state.mjs';
import * as viewerRender from '../ui/image-panel/viewer-render.mjs';
import {performance} from 'node:perf_hooks';
import {randomUUID} from 'node:crypto';

const source=readFileSync(process.env.PANEL_UI_UNDER_TEST??new URL('../ui/image-panel/app.mjs',import.meta.url),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const sourceId='a'.repeat(32),viewId='b'.repeat(32);
const panel={domain:'spatial_pixels',source_object_id:sourceId,source_rect_xyxy:[20,12,148,108],image_rect_xyxy:[0,0,128,96]};
function fixture(){return {object:{object_id:viewId,kind:'view',panels:[copy(panel)],annotations:[],display:{gamma:1,display_range:[0,255]}},tools:[],png_base64:'synthetic',clean_png_base64:'synthetic-clean',render_base_id:viewId,selection:null,last_operation:null};}
function pixelBytes(w,h){return Uint8ClampedArray.from({length:w*h*4},(_,i)=>i%4===3?255:(i*17+31)%256);}
async function harness(initial=fixture()){
 const calls=[],draftCalls=[],getCalls=[],frames=new Map(),stats={pow:0,draws:0,uploads:0};let server=copy(initial),frameId=0,waitAction=null,nextActionResult=null;
 const canvasContexts=[];
 class Context{
  constructor(canvas){this.canvas=canvas;this.lastPixels=null;canvasContexts.push(this);}
  drawImage(image){stats.draws++;this.lastPixels=image.context?.lastPixels??null;}
  getImageData(x,y,w,h){return {data:pixelBytes(w,h),width:w,height:h};}
  putImageData(value){stats.uploads++;this.lastPixels={data:new Uint8ClampedArray(value.data),width:value.width,height:value.height};}
  clearRect(){} fillText(){} strokeRect(){} setLineDash(){} beginPath(){} arc(){} stroke(){} moveTo(){} lineTo(){} closePath(){} save(){} restore(){} fill(){}
 }
 class Element{
  constructor(id){this.id=id;this.value='';this.style={};this.children=[];this.listeners={};this.classList={toggle(){}};this.textContent='';this.width=128;this.height=96;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  replaceChildren(...children){this.children=children;this.value=children[0]?.value??'';}
  append(child){this.children.push(child);}
  getContext(){return this.context??=new Context(this);}
  getBoundingClientRect(){return {left:0,top:0,width:this.width,height:this.height};}
  setPointerCapture(){}
 }
 const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
 $('zoom').value='1';$('mode').value='line';$('status').value='hypothesized';$('fft-window').value='hann';$('fft-mean').checked=true;
 const math=Object.create(Math);math.pow=(a,b)=>{stats.pow++;return Math.pow(a,b);};
 const sandbox={...coordinates,...viewerState,...viewerRender,console,Math:math,Uint8ClampedArray,performance,crypto:{randomUUID},
  document:{getElementById:$,createElement:tag=>new Element(tag),querySelectorAll:()=>[],addEventListener(){}},
  sessionStorage:{getItem:()=> 'synthetic-token',setItem(){}},location:{hash:'',pathname:'/'},history:{replaceState(){}},
  Option:class{constructor(text,value){this.text=text;this.value=value;}},
  Image:class{constructor(){this.width=128;this.height=96;}async decode(){}},
  ImageData:class{constructor(data,width,height){this.data=data;this.width=width;this.height=height;}},
  requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
  fetch:async(url,options)=>{
   if(!options.body){getCalls.push(url);if(url==='/api/revision')return {ok:true,json:async()=>({state_revision:server.state_revision,object_id:server.object.object_id,pending_result:server.pending_result})};}
   if(options.body){const body=JSON.parse(options.body);
    if(body.action==='draft'){draftCalls.push(body);if(body.params.selection)server.selection=copy(body.params.selection);return {ok:true,json:async()=>copy(server)};}
    calls.push(body);assert.equal(body.expected_object_id,server.object.object_id);if(waitAction)await waitAction;
    if(nextActionResult){server=copy(nextActionResult);nextActionResult=null;}
    if(body.action==='measure'||body.action==='select')server.selection=copy(body.params.selection);
    server.last_operation={action:body.action};
   }
   return {ok:true,json:async()=>copy(server)};
  }
 };
 const renderSource=readFileSync(new URL('../ui/image-panel/viewer-render.mjs',import.meta.url),'utf8').replace(/^export /gm,'');
 const script=renderSource+'\n'+source.replace(/^import .*from '\.\/[^']+\.mjs';\r?\n/gm,'')
  .replace('refresh().then(','globalThis.ready=refresh().then(')
  +'\nglobalThis.pollUI=pollRevision;globalThis.inspect=()=>({draft,drag,editCoordinates,state,pending,dirty:dirty(),view,draftRevision:historyDraft.revision});';
 vm.runInNewContext(script,sandbox,{filename:'ui/image-panel/app.mjs'});await sandbox.ready;
 const flush=()=>{for(const [id,callback] of [...frames]){frames.delete(id);callback();}};
 const event=(type,x=10,y=10,extra={})=>{$('canvas').listeners[type]?.({clientX:x,clientY:y,pointerId:1,button:0,...extra});};
 const click=async id=>{await $(id).onclick();flush();};
 const draw=(kind='line')=>{$('mode').value=kind;event('pointerdown',10,10);event('pointermove',40,35);event('pointerup',40,35);flush();};
 return {$,calls,draftCalls,getCalls,stats,frames,flush,event,click,draw,poll:()=>sandbox.pollUI(),inspect:()=>copy(sandbox.inspect()),contexts:canvasContexts,
  settle:async()=>{for(let i=0;i<20;i++)await Promise.resolve();},
  delayAction(promise){waitAction=promise;},
  actionResult(value){nextActionResult=copy(value);},
  setServer(value){server=copy(value);},server:()=>copy(server)};
}

test('measure then hand off uses the same anchored selection without redrawing',async()=>{
 const h=await harness();h.draw();const selection=h.inspect().draft;
 await h.click('measure');assert.deepEqual(h.inspect().draft.coordinates,selection.coordinates);
 await h.click('share');assert.equal(h.calls.at(-1).action,'select');assert.equal(h.calls.length,2);
 assert.deepEqual(h.calls[1].params.selection.coordinates,selection.coordinates);
 assert.equal(h.calls[1].params.selection.source_object_id,sourceId);
 assert.match(h.$('message').textContent,/选择已交接/);
});

test('export and same-object refresh retain the current locally drawn selection',async()=>{
 const h=await harness();h.draw('rectangle');const selection=h.inspect().draft;
 await h.click('export');assert.deepEqual(h.inspect().draft,selection);
 await h.click('reload');assert.deepEqual(h.inspect().draft,selection);
 assert.equal(h.calls.length,1);
});

test('fresh load restores an explicitly saved server selection using its panel map',async()=>{
 const s=fixture();s.selection={kind:'point',coordinate_space:'source_pixels',source_object_id:sourceId,coordinates:[40,30],panel:copy(panel)};
 const h=await harness(s);assert.deepEqual(h.inspect().draft.rendered,[20,18]);
 await h.click('share');assert.deepEqual(h.calls[0].params.selection.coordinates,[40,30]);
});

test('an older server selection does not replace a newer unsent local selection on export',async()=>{
 const h=await harness();h.draw();await h.click('share');const first=h.inspect().draft.coordinates;
 h.event('pointerdown',50,40);h.event('pointerup',90,60);h.flush();const current=h.inspect().draft.coordinates;
 assert.notDeepEqual(current,first);await h.click('export');assert.deepEqual(h.inspect().draft.coordinates,current);
 await h.click('share');assert.deepEqual(h.calls.at(-1).params.selection.coordinates,current);
});

test('changed object never inherits a local selection from an older revision',async()=>{
 const h=await harness();h.draw();const next=fixture();next.object.object_id='c'.repeat(32);h.setServer(next);
 await h.click('reload');assert.equal(h.inspect().draft,null);
 await h.click('share');assert.equal(h.calls.length,0);
});

test('foreign source or changed grid cannot restore a stale server selection',async()=>{
 for(const mutate of [s=>{s.selection.source_object_id='f'.repeat(32);},s=>{s.object.panels[0].source_rect_xyxy=[0,0,128,96];}]){
  const s=fixture();s.selection={kind:'point',coordinate_space:'source_pixels',source_object_id:sourceId,coordinates:[40,30],panel:copy(panel)};mutate(s);
  const h=await harness(s);assert.equal(h.inspect().draft,null);await h.click('share');assert.equal(h.calls.length,0);
 }
});

test('odd FFT selection retains its original signed frequencies through measure and share',async()=>{
 const s=fixture(),p={domain:'frequency',source_object_id:sourceId,fft_shape_yx:[55,95],fft_rect_xyxy:[38,22,58,34],image_rect_xyxy:[0,0,128,96]};
 s.object.panels=[p];s.object.kind='fft_view';const h=await harness(s);h.draw('point');const before=h.inspect().draft;
 await h.click('measure');await h.click('share');
 assert.deepEqual(h.calls[1].params.selection.coordinates,before.coordinates);
 assert.equal(h.calls[1].params.selection.coordinate_space,'frequency_cycles_per_pixel');
});

test('pointer moves coalesce into one animation frame and reuse the tone bitmap',async()=>{
 const h=await harness();const beforePow=h.stats.pow,beforeUploads=h.stats.uploads,beforeDraws=h.stats.draws;
 h.event('pointerdown');for(let i=0;i<50;i++)h.event('pointermove',20+i,25);
 assert.equal(h.frames.size,1);assert.equal(h.stats.draws,beforeDraws);
 h.flush();assert.equal(h.stats.pow,beforePow);assert.equal(h.stats.uploads,beforeUploads);
 assert.equal(h.stats.draws,beforeDraws);assert.equal(h.calls.length,0); // Separate overlay never copies the full image.
 h.event('pointerup',69,25);assert.equal(h.frames.size,0);
});

test('tone draft lookup keeps former RGB arithmetic and alpha bytes exactly',async()=>{
 const h=await harness();h.$('gamma').value='0.65';h.$('low').value='23';h.$('high').value='190';
 h.$('gamma').oninput();h.flush();
 const expected=pixelBytes(128,96);
 for(let i=0;i<expected.length;i+=4)for(let c=0;c<3;c++){
  const normalized=Math.max(0,Math.min(1,(Math.pow(expected[i+c]/255,1)*255-23)/(190-23)));
  expected[i+c]=255*Math.pow(normalized,1/.65);
 }
 const shown=h.$('base-canvas').context.lastPixels;
 assert.deepEqual(shown.data,expected);
 const before=h.stats.pow;h.event('pointerdown');h.event('pointermove',20,30);h.flush();
 assert.equal(h.stats.pow,before);
});

test('a real tone change invalidates the cache once, not on every overlay move',async()=>{
 const h=await harness(),before=h.stats.pow;h.$('gamma').value='2';h.$('gamma').oninput();h.flush();
 assert.ok(h.stats.pow>before);assert.ok(h.stats.pow-before<=512);
 const adjusted=h.stats.pow;h.draw();assert.equal(h.stats.pow,adjusted);
});

function annotated(){const s=fixture();s.object.annotations=[{annotation_id:'line-a',kind:'line',text:'candidate',color:'cyan',status:'hypothesized',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates:[30,22,60,52]}}];return s;}
async function editHarness(){const h=await harness(annotated());h.$('existing').value='line-a';h.$('existing').onchange();return h;}

test('edit uses pointerup position even with no final pointermove event',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointermove',12,13);h.event('pointerup',18,19);h.flush();
 await h.click('save-mark');assert.deepEqual(h.calls[0].params.updates[0].coordinates,[38,31,60,52]);
 assert.equal(h.calls[0].params.updates[0].status,'hypothesized');
});

test('pointercancel and lost capture roll back the current gesture without saving',async()=>{
 for(const ending of ['pointercancel','lostpointercapture']){
  const h=await editHarness();h.event('pointerdown',10,10);h.event('pointermove',20,20);h.event(ending);h.flush();
  assert.equal(h.inspect().drag,null);assert.equal(h.inspect().editCoordinates,null);assert.equal(h.calls.length,0);
 }
});

test('a second drag starts from the unsaved edited coordinates; cancellation preserves that draft',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();
 const first=h.inspect().editCoordinates;
 h.event('pointerdown',18,19);h.event('pointermove',21,22);h.event('pointercancel');h.flush();
 assert.deepEqual(h.inspect().editCoordinates,first);
 h.event('pointerdown',18,19);h.event('pointerup',22,23);h.flush();
 await h.click('save-mark');assert.deepEqual(h.calls[0].params.updates[0].coordinates,[42,35,60,52]);
});

test('another pointer cannot take over an in-progress gesture',async()=>{
 const h=await harness();h.event('pointerdown',10,10);h.event('pointermove',120,80,{pointerId:2});h.event('pointerup',120,80,{pointerId:2});
 assert.equal(h.inspect().drag.pointerId,1);h.event('pointerup',30,25);h.flush();
 assert.deepEqual(h.inspect().draft.coordinates,[30,22,50,37]);
});

test('completed gestures publish the exact scientific selection without a model wake or manual handoff',async()=>{
 const h=await harness();h.draw('rectangle');await h.settle();const final=h.draftCalls.at(-1);
 assert.equal(final.action,'draft');assert.equal(final.params.gesture_active,false);assert.equal(final.params.dirty,false);
 assert.deepEqual(final.params.selection.coordinates,h.inspect().draft.coordinates);assert.equal(h.calls.length,0);
 assert.equal(final.params.selection.source_object_id,sourceId);
});

test('default select mode directly finds and drags an anchored mark with no ID entry',async()=>{
 const h=await harness(annotated());h.$('mode').value='select';h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();
 assert.equal(h.$('existing').value,'line-a');assert.equal(h.$('mark-id').value,'line-a');
 await h.click('save-mark');assert.deepEqual(h.calls.at(-1).params.updates[0].coordinates,[38,31,60,52]);
});

test('new marks get safe IDs automatically, independent of user text and scientific status',async()=>{
 const h=await harness();assert.match(h.$('mark-id').value,/^mark-[a-f0-9]{24}$/);h.draw('arrow');
 h.$('mark-text').value='same candidate';h.$('mark-text').oninput();await h.click('save-mark');
 assert.match(h.calls.at(-1).params.annotation_id,/^mark-[a-f0-9]{24}$/);assert.equal(h.calls.at(-1).params.status,'hypothesized');
});

test('undo and redo restore draft scientific geometry without backend writes',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();const moved=h.inspect().editCoordinates;
 await h.click('undo');assert.equal(h.inspect().editCoordinates,null);await h.click('redo');assert.deepEqual(h.inspect().editCoordinates,moved);
 assert.equal(h.calls.length,0);
});

test('refresh and read-only measurement never erase unsaved display or mark drafts',async()=>{
 const h=await editHarness();h.draw('line');h.$('gamma').value='1.5';h.$('gamma').oninput();h.flush();
 const local=h.inspect();await h.click('reload');assert.deepEqual(h.inspect().editCoordinates,local.editCoordinates);assert.equal(h.$('gamma').value,'1.5');
 h.$('mode').value='line';h.event('pointerdown',60,20);h.event('pointerup',90,30);h.flush();await h.click('measure');
 assert.deepEqual(h.inspect().editCoordinates,local.editCoordinates);assert.equal(h.$('gamma').value,'1.5');assert.equal(h.inspect().dirty,true);
});

test('a late save cannot erase a newer drag and observation remains enabled while waiting',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();let done;
 h.delayAction(new Promise(resolve=>{done=resolve;}));const saving=h.click('save-mark');await h.settle();
 h.event('pointerdown',18,19);h.event('pointerup',22,23);h.flush();const newer=h.inspect().editCoordinates;
 assert.deepEqual(newer,[42,35,60,52]);done();await saving;assert.deepEqual(h.inspect().editCoordinates,newer);
 assert.equal(h.inspect().dirty,true);assert.ok(h.inspect().pending);assert.equal(h.$('pending-result').hidden,false);
});

test('saving one mark preserves a separate unsaved display draft',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();h.$('gamma').value='1.7';h.$('gamma').oninput();h.flush();
 await h.click('save-mark');assert.equal(h.$('gamma').value,1.7);assert.equal(h.inspect().editCoordinates,null);assert.equal(h.inspect().dirty,true);
});

test('FFT scientific settings are visible choices and forwarded rather than silently fixed',async()=>{
 const h=await harness();h.draw('rectangle');h.$('fft-window').value='none';h.$('fft-mean').checked=false;await h.click('fft');
 assert.equal(h.calls.at(-1).params.window,'none');assert.equal(h.calls.at(-1).params.subtract_mean,false);
});

test('ambiguous repeated-source comparison panels reject mark edit without choosing the first panel',async()=>{
 const s=annotated();s.object.panels.push({...copy(panel),image_rect_xyxy:[150,0,278,96]});const h=await harness(s);
 h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',20,20);h.flush();
 assert.equal(h.inspect().editCoordinates,null);assert.match(h.$('message').textContent,/不唯一/);assert.equal(h.calls.length,0);
});

test('fresh browser draft revision advances the existing shared lease instead of restarting at one',async()=>{
 const s=fixture();s.edit_state={draft_revision:77,dirty:false,gesture_active:false};const h=await harness(s);
 assert.ok(h.draftCalls[0].params.draft_revision>77);h.draw('point');await h.settle();assert.ok(h.draftCalls.at(-1).params.draft_revision>78);
});

test('revision polling uses small metadata and automatically presents a new clean result',async()=>{
 const h=await harness(),before=h.getCalls.length;await h.poll();assert.deepEqual(h.getCalls.slice(before),['/api/revision']);
 const next=fixture();next.object.object_id='c'.repeat(32);next.state_revision=2;h.setServer(next);await h.poll();
 assert.deepEqual(h.getCalls.slice(before),['/api/revision','/api/revision','/api/state']);assert.equal(h.inspect().state.object.object_id,next.object.object_id);
});

test('Agent result notice never overwrites an unsaved local display draft',async()=>{
 const h=await harness();h.$('gamma').value='1.9';h.$('gamma').oninput();h.flush();const next=fixture();next.object.object_id='c'.repeat(32);next.state_revision=2;h.setServer(next);
 await h.poll();assert.equal(h.inspect().state.object.object_id,viewId);assert.equal(h.$('gamma').value,'1.9');assert.equal(h.inspect().pending.object.object_id,next.object.object_id);
});

test('reopening a panel with an outstanding dirty lease requires an explicit discard',async()=>{
 const s=fixture();s.edit_state={draft_revision:18,dirty:true,gesture_active:false};const h=await harness(s);assert.equal(h.inspect().dirty,true);
 assert.equal(h.draftCalls.at(-1).params.dirty,true);assert.match(h.$('message').textContent,/无法恢复/);await h.click('discard-local');assert.equal(h.inspect().dirty,false);
});

test('drag publishes the exact unsaved annotation edit and undo explicitly clears it',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 const edit=h.draftCalls.at(-1).params.annotation_edit;
 assert.deepEqual(edit,{annotation_id:'line-a',coordinates:[38,31,60,52]});
 assert.equal(h.draftCalls.at(-1).params.dirty,true);
 await h.click('undo');await h.settle();assert.equal(h.draftCalls.at(-1).params.annotation_edit,null);
});

test('text/color/status are returned as unsaved edits without committing a scientific object',async()=>{
 const h=await editHarness();h.$('mark-text').value='a revised candidate';h.$('color').value='orange';h.$('status').value='retracted';h.$('mark-text').oninput();await h.settle();
 assert.deepEqual(h.draftCalls.at(-1).params.annotation_edit,{annotation_id:'line-a',text:'a revised candidate',color:'orange',status:'retracted'});assert.equal(h.calls.length,0);
});

test('choosing a different mark cannot silently drop an unsaved edit',async()=>{
 const s=annotated();s.object.annotations.push({...copy(s.object.annotations[0]),annotation_id:'line-b',anchor:{...copy(s.object.annotations[0].anchor),coordinates:[90,22,120,52]}});
 const h=await harness(s);h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();const edit=h.inspect().editCoordinates;
 h.$('existing').value='line-b';h.$('existing').onchange();assert.equal(h.$('existing').value,'line-a');assert.deepEqual(h.inspect().editCoordinates,edit);assert.match(h.$('message').textContent,/未保存/);
 h.$('mode').value='select';h.event('pointerdown',70,10);h.event('pointerup',80,20);h.flush();assert.equal(h.$('existing').value,'line-a');assert.deepEqual(h.inspect().editCoordinates,edit);assert.equal(h.inspect().drag,null);
 h.$('existing').value='';h.$('existing').onchange();assert.equal(h.$('existing').value,'line-a');assert.deepEqual(h.inspect().editCoordinates,edit);
});

test('saving a mark advances the visible identity even when a separate Agent result remains queued',async()=>{
 const initial=annotated();initial.pending_result={object_id:'d'.repeat(32),request_id:'agent-result'};
 const h=await harness(initial);h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();
 const committed=annotated();committed.object.object_id='c'.repeat(32);committed.pending_result=copy(initial.pending_result);committed.object.annotations[0].anchor.coordinates=[38,31,60,52];h.actionResult(committed);await h.click('save-mark');
 assert.equal(h.inspect().state.object.object_id,committed.object.object_id);assert.equal(h.inspect().editCoordinates,null);
 assert.equal(h.inspect().state.pending_result.object_id,'d'.repeat(32));assert.equal(h.$('pending-result').hidden,false);
 assert.equal(h.draftCalls.at(-1).expected_object_id,committed.object.object_id);
});
