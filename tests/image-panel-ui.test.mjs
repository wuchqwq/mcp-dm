// Execute the actual UI event handlers with a deterministic DOM/canvas/API shim.
// No browser timing, DM, private data, or worker/backend qualification is implied.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import * as coordinates from '../ui/image-panel/coordinates.mjs';
import * as userWorkflow from '../ui/image-panel/user-workflow.mjs';
import * as viewerState from '../ui/image-panel/viewer-state.mjs';
import * as viewerRender from '../ui/image-panel/viewer-render.mjs';
import * as annotationPresentation from '../ui/image-panel/annotation-presentation.mjs';
import * as figureExport from '../ui/image-panel/figure-export.mjs';
import {DataProbes as ProviderDataProbes} from '../ui/image-panel/data-probes.mjs';
import {MeasurementWorkspace as ProviderMeasurementWorkspace,requiresMeasurementJump} from '../ui/image-panel/measurement-workspace.mjs';
import {performance} from 'node:perf_hooks';
import {randomUUID} from 'node:crypto';

const source=readFileSync(process.env.PANEL_UI_UNDER_TEST??new URL('../ui/image-panel/app.mjs',import.meta.url),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const sourceId='a'.repeat(32),viewId='b'.repeat(32);
const panel={domain:'spatial_pixels',source_object_id:sourceId,source_rect_xyxy:[20,12,148,108],image_rect_xyxy:[0,0,128,96]};
function fixture(){return {object:{object_id:viewId,kind:'view',panels:[copy(panel)],annotations:[],display:{gamma:1,display_range:[0,255]}},tools:[],png_base64:'synthetic',clean_png_base64:'synthetic-clean',render_base_id:viewId,selection:null,last_operation:null};}
function pixelBytes(w,h){return Uint8ClampedArray.from({length:w*h*4},(_,i)=>i%4===3?255:(i*17+31)%256);}
async function harness(initial=fixture()){
 const calls=[],draftCalls=[],getCalls=[],frames=new Map(),stats={pow:0,draws:0,uploads:0};let server=copy(initial),frameId=0,waitAction=null,nextActionResult=null,actionSequence=0,actionFailure=null,waitMeasurement=null,measurementResponse=null,recoveryResponse=null;
 const canvasContexts=[],probeCalls=[],probeTimers=new Map();let probeTimerId=0;
 class Context{
  constructor(canvas){this.canvas=canvas;this.lastPixels=null;canvasContexts.push(this);}
  drawImage(image){stats.draws++;this.lastPixels=image.context?.lastPixels??null;}
  getImageData(x,y,w,h){return {data:pixelBytes(w,h),width:w,height:h};}
  putImageData(value){stats.uploads++;this.lastPixels={data:new Uint8ClampedArray(value.data),width:value.width,height:value.height};}
  clearRect(){} fillText(){} strokeRect(){} setLineDash(){} beginPath(){} arc(){} stroke(){} moveTo(){} lineTo(){} closePath(){} save(){} restore(){} fill(){}
 }
 class Element{
  constructor(id){this.id=id;this.value='';this.style={};this.dataset={};this.attributes={};this.children=[];this.listeners={};this.classList={toggle(){}};this.textContent='';this.width=128;this.height=96;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  replaceChildren(...children){this.children=children;this.value=children[0]?.value??'';}
  append(...children){this.children.push(...children);}
  setAttribute(name,value){this.attributes[name]=value;}
  querySelector(){return null;}
  getContext(){return this.context??=new Context(this);}
  getBoundingClientRect(){return {left:0,top:0,width:this.width,height:this.height};}
  setPointerCapture(){}
 }
 const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
 $('zoom').value='1';$('mode').value='line';$('status').value='hypothesized';$('fft-window').value='hann';$('fft-mean').checked=true;
 const math=Object.create(Math);math.pow=(a,b)=>{stats.pow++;return Math.pow(a,b);};
 const sandbox={...userWorkflow,...coordinates,...viewerState,...viewerRender,...annotationPresentation,...figureExport,requiresMeasurementJump,console,Math:math,Uint8ClampedArray,performance,crypto:{randomUUID},
  MeasurementWorkspace:class extends ProviderMeasurementWorkspace{constructor(options){super({...options,document:sandbox.document});}},
  DataProbes:class extends ProviderDataProbes{constructor(options){super({...options,document:sandbox.document,setTimer:(fn,delay)=>{const id=++probeTimerId;probeTimers.set(id,{fn,delay});return id;},clearTimer:id=>probeTimers.delete(id)});}},
  document:{getElementById:$,createElement:tag=>new Element(tag),querySelectorAll:()=>[],addEventListener(){}},
  sessionStorage:{getItem:()=> 'synthetic-token',setItem(){}},location:{hash:'',pathname:'/'},history:{replaceState(){}},
  Option:class{constructor(text,value){this.text=text;this.value=value;}},
  Image:class{constructor(){this.width=128;this.height=96;}async decode(){}},
  ImageData:class{constructor(data,width,height){this.data=data;this.width=width;this.height=height;}},
  requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
  fetch:async(url,options)=>{
   if(!options.body){getCalls.push(url);if(url.startsWith('/api/measurements?'))return {ok:true,json:async()=>({current:{...copy(server.object),object_id:server.object.object_id},entries:copy(server.measurement_entries??[]),truncated:false})};if(url==='/api/revision')return {ok:true,json:async()=>({state_revision:server.state_revision,object_id:server.object.object_id,pending_result:server.pending_result})};}
   if(options.body){const body=JSON.parse(options.body);
    if(url==='/api/probe'){probeCalls.push(body);return {ok:true,json:async()=>({object_id:body.expected_object_id,kind:'probe',component:body.component,coordinate_space:body.coordinate_space,samples:[{point:body.coordinates,array_index_xy:body.coordinates,value:17}]})};}
    if(body.action==='draft'){draftCalls.push(body);if(body.params.selection)server.selection=copy(body.params.selection);server.edit_state={...copy(body.params),base_object_id:server.object.object_id};return {ok:true,json:async()=>body.lightweight?{object_id:server.object.object_id,edit_state:copy(server.edit_state)}:copy(server)};}
    calls.push(body);assert.equal(body.expected_object_id,server.object.object_id);if(waitAction)await waitAction;if(body.action==='measure'&&waitMeasurement)await waitMeasurement;
    if(actionFailure){const error=actionFailure;actionFailure=null;return {ok:false,json:async()=>({error})};}
    if(['edit','edit-layout'].includes(body.action)&&body.params.auto_commit){
     const result=nextActionResult?copy(nextActionResult):copy(server);nextActionResult=null;
     for(const update of body.params.updates){const mark=result.object.annotations.find(m=>m.annotation_id===update.annotation_id);assert.ok(mark,'autosave must update an existing stable mark');for(const [field,value]of Object.entries(update)){if(field==='coordinates')mark.anchor.coordinates=copy(value);else if(!['annotation_id','presentation_replace'].includes(field))mark[field]=copy(value);}}
     if(result.object.object_id===server.object.object_id)result.object.object_id=(++actionSequence).toString(16).padStart(32,'0');
     result.state_revision=(server.state_revision??0)+1;result.edit_state=copy(server.edit_state);result.auto_edit_committed=true;server=result;
    }else if(nextActionResult){server=copy(nextActionResult);nextActionResult=null;}
    if(body.action==='mark'){const {panel:selectionPanel,...anchor}=body.params.selection;server.object.annotations.push({annotation_id:body.params.annotation_id,kind:anchor.kind,anchor:copy(anchor),text:body.params.text,color:body.params.color,status:body.params.status});server.object.object_id=(++actionSequence).toString(16).padStart(32,'0');server.state_revision=(server.state_revision??0)+1;server.selection=copy(body.params.selection);}
    if(body.action==='measure'||body.action==='select')server.selection=copy(body.params.selection);
    const measured=body.action==='measure'&&measurementResponse?(typeof measurementResponse==='function'?measurementResponse(body):copy(measurementResponse)):{};
    server.last_operation=body.action==='recover'&&recoveryResponse?copy(recoveryResponse):{...(body.action==='measure'?{kind:'measure',coordinate_space:body.params.selection.coordinate_space,points:[body.params.selection.coordinates.slice(0,2),body.params.selection.coordinates.slice(2)]}:{}),...measured,action:body.action,...(body.action==='mark'?{annotation_ids:[body.params.annotation_id]}:{})};
   }
   return {ok:true,json:async()=>copy(server)};
  }
 };
 const renderSource=readFileSync(new URL('../ui/image-panel/viewer-render.mjs',import.meta.url),'utf8').replace(/^export /gm,'');
 const script=renderSource+'\n'+source.replace(/^import .*from '\.\/[^']+\.mjs';\r?\n/gm,'')
  .replace('refresh().then(','globalThis.ready=refresh().then(')
  +'\nglobalThis.pollUI=pollRevision;globalThis.finishSaves=async()=>{do{if(autoSaving)await autoSaving;await Promise.resolve();}while(autoSaving);};globalThis.inspect=()=>({draft,drag,editCoordinates,state,pending,dirty:dirty(),view,draftRevision:historyDraft.revision,queuedEdits:[...queuedEdits],autoFailed,busy});';
 vm.runInNewContext(script,sandbox,{filename:'ui/image-panel/app.mjs'});await sandbox.ready;
 const flush=()=>{for(const [id,callback] of [...frames]){frames.delete(id);callback();}};
 const event=(type,x=10,y=10,extra={})=>{$('canvas').listeners[type]?.({clientX:x,clientY:y,pointerId:1,button:0,...extra});};
 const click=async id=>{await $(id).onclick();flush();};
 const draw=(kind='line')=>{$('mode').value=kind;event('pointerdown',10,10);event('pointermove',40,35);event('pointerup',40,35);flush();};
 return {$,calls,draftCalls,getCalls,probeCalls,stats,frames,flush,event,click,draw,flushProbes:async()=>{const timers=[...probeTimers];probeTimers.clear();for(const [_id,timer]of timers)timer.fn();for(let i=0;i<8;i++)await Promise.resolve();},poll:()=>sandbox.pollUI(),inspect:()=>copy(sandbox.inspect()),contexts:canvasContexts,
  settle:async()=>{for(let i=0;i<80;i++)await Promise.resolve();flush();},finish:async()=>{await sandbox.finishSaves();flush();},
  delayAction(promise){waitAction=promise;},
  failAction(message='Synthetic save failure; query original request'){actionFailure=message;},
  actionResult(value){nextActionResult=copy(value);},
  measureResponse(value){measurementResponse=typeof value==='function'?value:copy(value);},delayMeasurement(promise){waitMeasurement=promise;},
  recoverResponse(value){recoveryResponse=copy(value);},
  setServer(value){server=copy(value);},server:()=>copy(server)};
}

test('measure then hand off uses the same anchored selection without redrawing',async()=>{
 const h=await harness();h.draw();const selection=h.inspect().draft;
 await h.click('measure');assert.deepEqual(h.inspect().draft.coordinates,selection.coordinates);
 await h.click('share');assert.equal(h.calls.at(-1).action,'select');assert.deepEqual(h.calls.map(call=>call.action),['mark','measure','select']);
 assert.deepEqual(h.calls[2].params.selection.coordinates,selection.coordinates);
 assert.equal(h.calls[2].params.selection.source_object_id,sourceId);
 assert.equal(h.calls[1].params.annotation_id,h.calls[0].params.annotation_id,'measurement is bound to the newly saved scientific mark');
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

test('same scientific grid display revision preserves the exact local selection despite its new object ID',async()=>{
 const initial=fixture();initial.object.scientific_grid_identity={array_sha256:'same-scientific-array',source_rect_xyxy:[20,12,148,108]};
 const h=await harness(initial);h.draw();const selected=h.inspect().draft;
 const next=copy(initial);next.object.object_id='c'.repeat(32);next.object.display.gamma=1.7;h.setServer(next);
 await h.click('reload');assert.deepEqual(h.inspect().draft,selected);
 await h.click('share');assert.equal(h.calls.at(-1).expected_object_id,next.object.object_id);assert.deepEqual(h.calls.at(-1).params.selection.coordinates,selected.coordinates);assert.equal(h.calls.at(-1).params.selection.source_object_id,sourceId);
});

test('unrelated scientific image does not inherit a local selection from the older image',async()=>{
 const h=await harness();h.draw();const next=fixture();next.object.object_id='c'.repeat(32);next.object.panels[0].source_object_id='d'.repeat(32);h.setServer(next);
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
 assert.deepEqual(h.calls.map(call=>call.action),['mark','measure','select']);
 assert.deepEqual(h.calls[2].params.selection.coordinates,before.coordinates);
 assert.equal(h.calls[2].params.selection.coordinate_space,'frequency_cycles_per_pixel');
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

test('Shift and Ctrl constrain a new ROI on the source grid using the final pointerup modifier',async()=>{
 for(const modifier of ['shiftKey','ctrlKey']){
  const f=fixture();f.object.panels[0].source_rect_xyxy=[20,12,276,108];const h=await harness(f);h.$('mode').value='rectangle';
  h.event('pointerdown',10.2,10.3);h.event('pointermove',30,15);h.event('pointerup',40,20,{[modifier]:true});h.flush();
  assert.deepEqual(h.inspect().draft.coordinates,[40,22,100,82]);assert.deepEqual(coordinates.selectionRectangle(h.inspect().draft),[40,22,100,82]);
 }
 const h=await harness();h.$('mode').value='rectangle';h.event('pointerdown',10,10);h.event('pointermove',40,20,{shiftKey:true});
 assert.deepEqual(h.inspect().drag.end,[40,40]);h.event('pointerup',40,20);h.flush();assert.deepEqual(h.inspect().draft.coordinates,[30,22,60,32]);
});

test('new line and arrow constrain their final source coordinates without a final pointermove',async()=>{
 for(const [kind,modifier,end,expected]of [['line','shiftKey',[50,20],[30,22,70,22]],['arrow','ctrlKey',[15,65],[30,22,30,77]]]){
  const h=await harness();h.$('mode').value=kind;h.event('pointerdown',10,10);h.event('pointerup',...end,{[modifier]:true});h.flush();assert.deepEqual(h.inspect().draft.coordinates,expected);
 }
});

function annotated(){const s=fixture();s.object.annotations=[{annotation_id:'line-a',kind:'line',text:'candidate',color:'cyan',status:'hypothesized',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates:[30,22,60,52]}}];return s;}
async function editHarness(){const h=await harness(annotated());h.$('existing').value='line-a';h.$('existing').onchange();return h;}

test('edit uses pointerup position even with no final pointermove event',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointermove',12,13);h.event('pointerup',18,19);h.flush();
 await h.settle();assert.equal(h.calls.length,1);assert.equal(h.calls[0].params.auto_commit,true);assert.deepEqual(h.calls[0].params.updates[0].coordinates,[38,31,60,52]);
 assert.equal(h.calls[0].params.updates[0].status,undefined,'geometry edit must not resubmit confirmation state');
 assert.equal(h.server().object.annotations[0].status,'hypothesized');
 assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[38,31,60,52]);assert.notEqual(h.inspect().state.object.object_id,viewId);
});

test('Shift and Ctrl do not constrain existing annotation geometry drags',async()=>{
 for(const modifier of ['shiftKey','ctrlKey']){const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19,{[modifier]:true});h.flush();await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[38,31,60,52]);}
});

test('pointercancel and lost capture roll back the current gesture without saving',async()=>{
 for(const ending of ['pointercancel','lostpointercapture']){
  const h=await editHarness();h.event('pointerdown',10,10);h.event('pointermove',20,20);h.event(ending);h.flush();
  assert.equal(h.inspect().drag,null);assert.equal(h.inspect().editCoordinates,null);assert.equal(h.calls.length,0);
 }
});

test('a second drag starts from the queued edit; cancellation preserves it and the latest edit eventually saves',async()=>{
 const h=await editHarness();let done;h.delayAction(new Promise(resolve=>{done=resolve;}));h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 const first=h.inspect().queuedEdits[0][1].update.coordinates;assert.deepEqual(first,[38,31,60,52]);
 h.event('pointerdown',18,19);h.event('pointermove',21,22);h.event('pointercancel');h.flush();
 assert.equal(h.inspect().editCoordinates,null);assert.deepEqual(h.inspect().queuedEdits[0][1].update.coordinates,first);
 h.event('pointerdown',18,19);h.event('pointerup',22,23);h.flush();
 assert.deepEqual(h.inspect().queuedEdits[0][1].update.coordinates,[42,35,60,52]);done();await h.settle();
 assert.equal(h.calls.length,2);assert.deepEqual(h.calls.at(-1).params.updates[0].coordinates,[42,35,60,52]);assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[42,35,60,52]);assert.equal(h.inspect().dirty,false);
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
 await h.settle();assert.deepEqual(h.calls.at(-1).params.updates[0].coordinates,[38,31,60,52]);assert.equal(h.inspect().queuedEdits.length,0);
});

test('new marks get safe IDs automatically, independent of user text and scientific status',async()=>{
 const h=await harness();assert.match(h.$('mark-id').value,/^mark-[a-f0-9]{24}$/);h.draw('arrow');
 h.$('mark-text').value='same candidate';h.$('mark-text').oninput();await h.click('save-mark');
 assert.match(h.calls.at(-1).params.annotation_id,/^mark-[a-f0-9]{24}$/);assert.equal(h.calls.at(-1).params.status,'hypothesized');
});

test('undo and redo of an autosaved annotation create compensating versions instead of pretending to delete history',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 const moved=copy(h.server().object.annotations[0].anchor.coordinates),firstId=h.server().object.object_id;
 await h.click('undo');await h.settle();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[30,22,60,52]);assert.notEqual(h.server().object.object_id,firstId);
 await h.click('redo');await h.settle();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,moved);
 assert.equal(h.calls.length,3);assert.ok(h.calls.every(c=>c.action==='edit'&&c.params.auto_commit));
});

test('refresh and read-only measurement never erase unsaved display or mark drafts',async()=>{
 const h=await editHarness();h.draw('line');h.$('gamma').value='1.5';h.$('gamma').oninput();h.flush();
 const local=h.inspect();await h.click('reload');assert.deepEqual(h.inspect().editCoordinates,local.editCoordinates);assert.equal(h.$('gamma').value,'1.5');
 h.$('mode').value='line';h.event('pointerdown',60,20);h.event('pointerup',90,30);h.flush();await h.click('measure');
 assert.deepEqual(h.inspect().editCoordinates,local.editCoordinates);assert.equal(Number(h.$('gamma').value),1.5);assert.equal(h.inspect().dirty,true);
});

test('a late save cannot erase a newer drag and observation remains enabled while waiting',async()=>{
 const h=await editHarness();let done;h.delayAction(new Promise(resolve=>{done=resolve;}));h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 assert.equal(h.inspect().busy,true);h.event('pointerdown',18,19);h.event('pointermove',22,23);h.flush();const newer=h.inspect().editCoordinates;
 assert.deepEqual(newer,[42,35,60,52]);done();await h.settle();assert.deepEqual(h.inspect().editCoordinates,newer);assert.ok(h.inspect().drag);
 h.event('pointerup',22,23);h.flush();await h.settle();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,newer);assert.equal(h.inspect().dirty,false);
});

test('saving one mark preserves a separate unsaved display draft',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();h.$('gamma').value='1.7';h.$('gamma').oninput();h.flush();
 await h.click('save-mark');await h.settle();assert.equal(Number(h.$('gamma').value),1.7);assert.equal(h.inspect().editCoordinates,null);assert.equal(h.inspect().dirty,true);
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
 assert.deepEqual(h.getCalls.slice(before),['/api/revision','/api/revision','/api/state','/api/measurements?object_id='+next.object.object_id]);assert.equal(h.inspect().state.object.object_id,next.object.object_id);
});

test('Agent result notice never overwrites an unsaved local display draft',async()=>{
 const h=await harness();h.$('gamma').value='1.9';h.$('gamma').oninput();h.flush();const next=fixture();next.object.object_id='c'.repeat(32);next.state_revision=2;h.setServer(next);
 await h.poll();assert.equal(h.inspect().state.object.object_id,viewId);assert.equal(h.$('gamma').value,'1.9');assert.equal(h.inspect().pending.object.object_id,next.object.object_id);
});

test('reopening a panel with an outstanding dirty lease requires an explicit discard',async()=>{
 const s=fixture();s.edit_state={draft_revision:18,dirty:true,gesture_active:false};const h=await harness(s);assert.equal(h.inspect().dirty,true);
 assert.equal(h.draftCalls.at(-1).params.dirty,true);assert.match(h.$('message').textContent,/先前未保存.*明确撤回/);await h.click('discard-local');assert.equal(h.inspect().dirty,false);
});

test('gesture start publishes a blocking lease while pointer moves stay local and pointerup commits exact coordinates',async()=>{
 const h=await editHarness();h.event('pointerdown',10,10);h.event('pointermove',18,19);h.flush();await h.settle();
 assert.deepEqual(h.draftCalls.at(-1).params.annotation_edit,{annotation_id:'line-a',coordinates:[30,22,60,52]});
 assert.deepEqual(h.inspect().editCoordinates,[38,31,60,52]);
 assert.equal(h.draftCalls.at(-1).params.gesture_active,true);assert.equal(h.calls.length,0);
 h.event('pointerup',18,19);h.flush();await h.settle();assert.equal(h.draftCalls.at(-1).params.annotation_edit,null);assert.equal(h.inspect().dirty,false);assert.equal(h.calls.length,1);
});

test('text/color/status are returned as unsaved edits without committing a scientific object',async()=>{
 const h=await editHarness();h.$('mark-text').value='a revised candidate';h.$('color').value='orange';h.$('status').value='retracted';h.$('mark-text').oninput();await h.settle();
 assert.deepEqual(h.draftCalls.at(-1).params.annotation_edit,{annotation_id:'line-a',text:'a revised candidate',color:'orange',status:'retracted'});assert.equal(h.calls.length,0);
});

test('choosing another mark queues the prior edit and preserves both edits while a save waits',async()=>{
 const s=annotated();s.object.annotations.push({...copy(s.object.annotations[0]),annotation_id:'line-b',anchor:{...copy(s.object.annotations[0].anchor),coordinates:[90,22,120,52]}});
 const h=await harness(s);let done;h.delayAction(new Promise(resolve=>{done=resolve;}));h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 h.$('existing').value='line-b';h.$('existing').onchange();assert.equal(h.$('existing').value,'line-b');assert.deepEqual(h.inspect().queuedEdits[0][1].update.coordinates,[38,31,60,52]);
 h.$('mode').value='select';h.event('pointerdown',70,10);h.event('pointerup',80,20);h.flush();assert.equal(h.$('existing').value,'line-b');assert.equal(h.inspect().queuedEdits.length,2);
 done();await h.settle();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[38,31,60,52]);assert.deepEqual(h.server().object.annotations[1].anchor.coordinates,[100,32,120,52]);assert.equal(h.inspect().dirty,false);
});

test('failed autosave retains its latest local edit and does not silently replay',async()=>{
 const h=await editHarness();h.failAction();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
 assert.equal(h.inspect().autoFailed,true);assert.equal(h.inspect().dirty,true);assert.deepEqual(h.inspect().queuedEdits[0][1].update.coordinates,[38,31,60,52]);assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[30,22,60,52]);
 await h.settle();assert.equal(h.calls.length,1);assert.match(h.$('message').textContent,/失败|保留/);
});

test('saving a mark advances the visible identity even when a separate Agent result remains queued',async()=>{
 const initial=annotated();initial.pending_result={object_id:'d'.repeat(32),request_id:'agent-result'};
 const h=await harness(initial);h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();
 const committed=annotated();committed.object.object_id='c'.repeat(32);committed.pending_result=copy(initial.pending_result);committed.object.annotations[0].anchor.coordinates=[38,31,60,52];h.actionResult(committed);await h.click('save-mark');
 assert.equal(h.inspect().state.object.object_id,committed.object.object_id);assert.equal(h.inspect().editCoordinates,null);
 assert.equal(h.inspect().state.pending_result.object_id,'d'.repeat(32));assert.equal(h.$('pending-result').hidden,false);
 assert.equal(h.draftCalls.at(-1).expected_object_id,committed.object.object_id);
});

test('measurement summary prefers valid physical lengths and never prints null as a distance',async()=>{
 const f=fixture();f.last_operation={physical_distance:2.5,physical_unit:'nm',distance_pixels:10};
 const h=await harness(f);assert.match(h.$('measurement-summary').textContent,/2.5 nm/);
 f.last_operation={physical_distance:null,period:null,d_spacing:null,distance_pixels:10};h.setServer(f);await h.click('reload');
 assert.match(h.$('measurement-summary').textContent,/10 px/);assert.doesNotMatch(h.$('measurement-summary').textContent,/null/);
 f.last_operation={physical_distance:null,period:2.5,period_unit:'nm',d_spacing:2.5,d_spacing_unit:'nm',distance_pixels:10};h.setServer(f);await h.click('reload');
 assert.match(h.$('measurement-summary').textContent,/晶面间距.*2.5 nm/);
});

test('reciprocal calibration form uses the current domain and signed scale, not a real-space default',async()=>{
 const f=fixture();f.tools=[{name:'image_calibrate'}];f.object.xy_calibration={status:'active',scope:'image',coordinate_domain:'reciprocal_space',xy_scale:{x:.2,y:-.4,unit:'1/nm'}};
 const h=await harness(f);assert.equal(Number(h.$('scale-x').value),.2);assert.equal(Number(h.$('scale-y').value),-.4);assert.equal(h.$('unit').value,'1/nm');assert.equal(h.$('scope').value,'image');
 h.$('source').value='Explicit synthetic calibration correction';await h.click('calibrate');
 assert.equal(h.calls.at(-1).params.coordinate_domain,'reciprocal_space');assert.deepEqual(h.calls.at(-1).params.xy_scale,{x:.2,y:-.4,unit:'1/nm'});
});

test('dragging an independently positioned label saves presentation only and preserves the confirmed scientific anchor',async()=>{
 const f=fixture();f.object.annotations=[{annotation_id:'indexed-peak',kind:'point',text:'(1 -1 0)',color:'white',status:'user_confirmed',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates:[60,52]},presentation:{category:'A',label:{text:'g₁',offset:[15,12],pinned:true}}}];
 const h=await harness(f),original=copy(f.object.annotations[0]);h.$('mode').value='select';h.flush();
 h.event('pointerdown',57,54);assert.equal(h.inspect().drag.kind,'label');h.event('pointermove',67,62);h.flush();
 assert.deepEqual(h.inspect().state.object.annotations[0].anchor,original.anchor);assert.equal(h.calls.length,0);
 h.event('pointerup',67,62);h.flush();await h.settle();
 assert.equal(h.calls.length,1);const update=h.calls[0].params.updates[0];assert.deepEqual(Object.keys(update).sort(),['annotation_id','presentation','presentation_replace']);assert.equal(update.presentation_replace,true);
 assert.deepEqual(update.presentation.label.offset,[25,20]);assert.equal(update.presentation.label.pinned,true);
 const saved=h.server().object.annotations[0];assert.deepEqual(saved.anchor,original.anchor);assert.equal(saved.status,'user_confirmed');assert.equal(saved.text,original.text);assert.equal(saved.presentation.label.text,original.presentation.label.text);
});

test('moving a measured endpoint hides its stale numeric label until a new measurement record supplies valid units',async()=>{
 for(const result of [{object_id:'new-distance-record',physical_distance:3.2,physical_unit:'nm'},{object_id:'pixel-only-record',physical_distance:null,physical_unit:null,distance_pixels:30}]){
  const f=annotated();f.object.annotations[0].status='user_confirmed';f.object.annotations[0].text='d = 2.5 nm';f.object.annotations[0].presentation={label:{text:'d = 2.5 nm',offset:[40,5],pinned:true,visible:true,measurement_object_id:'old-distance-record',measurement_kind:'distance'}};
  const h=await harness(f);let measured;h.delayMeasurement(new Promise(resolve=>{measured=resolve;}));h.measureResponse(result);
  h.$('existing').value='line-a';h.$('existing').onchange();h.event('pointerdown',10,10);h.event('pointerup',18,19);h.flush();await h.settle();
  const moved=h.server().object.annotations[0];assert.deepEqual(moved.anchor.coordinates,[38,31,60,52]);assert.equal(moved.status,'user_confirmed');assert.equal(moved.presentation.label.visible,false);assert.equal(moved.presentation.label.measurement_object_id,'old-distance-record');
  assert.doesNotMatch(h.$('annotation-layer').innerHTML,/data-part="label"/);
  assert.equal(h.calls[0].action,'edit');assert.equal(h.calls[0].params.updates[0].status,undefined);assert.equal(h.calls[1].action,'measure');assert.deepEqual(h.calls[1].params.selection.coordinates,[38,31,60,52]);
  measured();await h.settle();const saved=h.server().object.annotations[0];assert.equal(saved.status,'user_confirmed');assert.deepEqual(saved.anchor.coordinates,[38,31,60,52]);
  if(result.physical_unit){assert.equal(h.calls.length,3);assert.equal(saved.presentation.label.visible,true);assert.equal(saved.presentation.label.measurement_object_id,'new-distance-record');assert.equal(saved.presentation.label.text,'d = 3.2 nm');assert.match(saved.note,/new-distance-record/);}
  else {assert.equal(h.calls.length,2);assert.equal(saved.presentation.label.visible,false);assert.equal(saved.presentation.label.measurement_object_id,'old-distance-record');assert.match(h.$('message').textContent,/没有可信物理单位/);}
 }
});

test('figure mode locks scientific geometry and new selections while leaving the original anchor available',async()=>{
 const f=annotated();f.object.annotations[0].presentation={label:{visible:false}};const h=await harness(f);await h.click('figure-mode');assert.equal(h.$('figure-mode').textContent,'出图模式');
 h.$('mode').value='select';h.event('pointerdown',10,10);h.event('pointermove',18,19);h.event('pointerup',18,19);h.flush();await h.settle();
 assert.equal(h.inspect().drag,null);assert.equal(h.inspect().editCoordinates,null);assert.equal(h.calls.length,0);assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[30,22,60,52]);
 h.$('mode').value='rectangle';h.event('pointerdown',80,60);h.event('pointermove',110,80);h.event('pointerup',110,80);h.flush();await h.settle();
 assert.equal(h.inspect().draft,null);assert.equal(h.inspect().dirty,false);assert.equal(h.calls.length,0);assert.doesNotMatch(h.$('annotation-layer').innerHTML,/data-part="handles"/);
});

function twoMeasuredLines(){const f=fixture();f.object.annotations=[['A',[25,30,75,30],'1'],['B',[21,70,146,70],'2.5']].map(([annotation_id,coordinates,value])=>({annotation_id,kind:'line',text:`d = ${value} nm`,color:'white',status:'user_confirmed',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates},presentation:{label:{text:`d = ${value} nm`,offset:[8,20],visible:true,measurement_object_id:annotation_id.toLowerCase().repeat(32),measurement_kind:'distance'}}}));return f;}
function selectLine(h,id){h.$('existing').value=id;h.$('existing').onchange();}
function measuredFromSelection(body){const c=body.params.selection.coordinates;return {object_id:(c[1]===30?'c':'d').repeat(32),physical_distance:Math.hypot(c[2]-c[0],c[3]-c[1])*.02,physical_unit:'nm'};}
test('P0: saving A then selecting B remeasures saved A, never the global B selection',async()=>{
 const f=twoMeasuredLines(),h=await harness(f),originalB=copy(f.object.annotations[1]);let release;h.delayAction(new Promise(r=>{release=r;}));h.measureResponse(measuredFromSelection);
 selectLine(h,'A');h.event('pointerdown',55,18);h.event('pointerup',65,18);h.flush();await h.settle();assert.equal(h.calls[0].action,'edit');
 selectLine(h,'B');h.event('pointerdown',126,58);h.event('pointerup',126,58);h.flush();assert.deepEqual(h.inspect().draft.coordinates,originalB.anchor.coordinates);
 release();await h.settle();const saved=h.server().object.annotations;
 assert.deepEqual(h.calls.find(c=>c.action==='measure').params.selection.coordinates,[25,30,85,30]);
 assert.equal(saved[0].presentation.label.text,'d = 1.2 nm');assert.deepEqual(saved[1],originalB);assert.deepEqual(h.inspect().draft.coordinates,originalB.anchor.coordinates);
});

test('P0: a delayed measurement cannot write an older A revision after A moves again',async()=>{
 const h=await harness(twoMeasuredLines());let release;h.delayMeasurement(new Promise(r=>{release=r;}));h.measureResponse(measuredFromSelection);
 selectLine(h,'A');h.event('pointerdown',55,18);h.event('pointerup',65,18);h.flush();await h.settle();assert.equal(h.calls.filter(c=>c.action==='measure').length,1);
 h.event('pointerdown',65,18);h.event('pointerup',75,18);h.flush();await h.settle();assert.equal(h.server().object.annotations[0].presentation.label.visible,false);
 release();await h.finish();const mark=h.server().object.annotations[0];assert.equal(h.inspect().autoFailed,false,JSON.stringify({calls:h.calls,ui:h.inspect(),message:h.$('message').textContent}));assert.equal(h.inspect().busy,false,JSON.stringify({calls:h.calls,queue:h.inspect().queuedEdits,message:h.$('message').textContent}));assert.deepEqual(mark.anchor.coordinates,[25,30,95,30]);assert.equal(mark.presentation.label.text,'d = 1.4 nm');assert.equal(mark.status,'user_confirmed');
 assert.deepEqual(h.calls.filter(c=>c.action==='measure').map(c=>c.params.selection.coordinates),[[25,30,85,30],[25,30,95,30]]);
 assert.ok(!h.calls.some(c=>c.action==='edit'&&c.params.updates.some(u=>u.text==='d = 1.2 nm')),'stale numeric result must never be persisted');
});

test('P0: consecutive A/B edits each remeasure their own saved anchor; label drag keeps that measurement ID',async()=>{
 const h=await harness(twoMeasuredLines());let release;h.delayMeasurement(new Promise(r=>{release=r;}));h.measureResponse(measuredFromSelection);
 selectLine(h,'A');h.event('pointerdown',55,18);h.event('pointerup',65,18);h.flush();await h.settle();
 selectLine(h,'B');h.event('pointerdown',1,58);h.event('pointerup',11,58);h.flush();release();await h.finish();
 const [a,b]=h.server().object.annotations;assert.equal(a.presentation.label.text,'d = 1.2 nm');assert.equal(b.presentation.label.text,'d = 2.3 nm');assert.deepEqual(b.anchor.coordinates,[31,70,146,70]);
 assert.deepEqual(h.calls.filter(c=>c.action==='measure').map(c=>c.params.selection.coordinates),[[25,30,85,30],[31,70,146,70]]);
 const count=h.calls.filter(c=>c.action==='measure').length,id=a.presentation.label.measurement_object_id,anchor=copy(a.anchor);
 h.$('mode').value='select';h.event('pointerdown',20,45);h.event('pointerup',30,49);h.flush();await h.finish();
 const again=h.server().object.annotations[0];assert.deepEqual(again.anchor,anchor);assert.equal(again.presentation.label.measurement_object_id,id);assert.equal(h.calls.filter(c=>c.action==='measure').length,count);
});

test('P0: unknown measurement response retains drafts and only queries its original request on recovery',async()=>{
 const h=await harness(twoMeasuredLines());let release;h.delayMeasurement(new Promise(r=>{release=r;}));h.measureResponse(measuredFromSelection);
 selectLine(h,'A');h.event('pointerdown',55,18);h.event('pointerup',65,18);h.flush();await h.settle();
 selectLine(h,'B');h.event('pointerdown',1,58);h.event('pointerup',11,58);h.flush();h.failAction('Synthetic response lost. Original request_id=measure-original-42; query it');release();await h.settle();
 assert.equal(h.inspect().autoFailed,true);assert.equal(h.inspect().dirty,true);assert.equal(h.server().object.annotations[0].presentation.label.visible,false);const requests=h.calls.length;
 await h.settle();assert.equal(h.calls.length,requests,'unknown measurement is never automatically replayed');
 h.recoverResponse({kind:'measure',request_id:'measure-original-42',object_id:'e'.repeat(32),coordinate_space:'source_pixels',points:[[25,30],[85,30]],physical_distance:1.2,physical_unit:'nm'});
 await h.click('recover');await h.finish();assert.equal(h.calls.find(c=>c.action==='recover').params.request_id,'measure-original-42');assert.equal(h.inspect().autoFailed,false);
 assert.equal(h.server().object.annotations[0].presentation.label.text,'d = 1.2 nm');assert.equal(h.server().object.annotations[1].presentation.label.text,'d = 2.3 nm');assert.equal(h.calls.filter(c=>c.action==='measure'&&c.params.selection.coordinates[1]===30).length,1);
});

function figureImportFixture(){
 const saved=annotated();saved.object.display={gamma:1,display_range:[0,255],max_size:128,upscale:false,interpolation:'nearest',scale_bar:false};
 saved.object.annotations[0].status='user_confirmed';saved.object.annotations[0].presentation={marker_shape:'circle',label:{offset:[8,-8],text:'saved label',measurement_object_id:'e'.repeat(32),measurement_kind:'distance'}};
 const recipe=figureExport.makeFigureRecipe(saved,{preset:'real-space',mode:'figure',columns:'single',fontPt:8,layers:{experimental:true,simulation_A:false,simulation_B:false},legend:false,scaleBar:false,letter:'a'}),current=copy(saved);
 current.object.display.gamma=2;current.object.display.display_range=[20,220];current.object.annotations[0].presentation={marker_shape:'diamond',label:{offset:[28,18],text:'later label'}};
 const restored=copy(current);restored.object.object_id='c'.repeat(32);restored.object.display=copy(saved.object.display);restored.render_base_id=restored.object.object_id;
 return {saved,current,restored,recipe};
}

test('P0: paste and file imports await restored display before saving exact presentation replacements',async()=>{
 for(const route of ['paste','file']){
  const {saved,current,restored,recipe}=figureImportFixture(),h=await harness(current);let release;h.delayAction(new Promise(resolve=>{release=resolve;}));h.actionResult(restored);
  const text=JSON.stringify(recipe);let imported;
  if(route==='paste'){h.$('recipe-text').value=text;imported=h.click('load-recipe-text');}
  else{h.$('import-figure').files=[{size:text.length,text:async()=>text}];imported=h.$('import-figure').onchange();}
  await h.settle();assert.equal(h.calls.length,1);assert.equal(h.calls[0].action,'restore-figure-display');assert.deepEqual(h.calls[0].params.recipe,recipe);assert.equal(h.inspect().queuedEdits.length,0);assert.deepEqual(h.server().object.annotations[0].presentation,current.object.annotations[0].presentation);
  release();await imported;await h.finish();
  const edit=h.calls.find(c=>c.action==='edit');assert.ok(edit,'presentation saves only after display adoption');assert.equal(edit.expected_object_id,restored.object.object_id);assert.equal(edit.params.updates[0].presentation_replace,true);assert.deepEqual(edit.params.updates[0].presentation,saved.object.annotations[0].presentation);
  assert.equal(h.inspect().state.object.display.gamma,1);assert.deepEqual(h.inspect().state.object.display.display_range,[0,255]);assert.deepEqual(h.server().object.annotations[0].anchor,saved.object.annotations[0].anchor);assert.equal(h.server().object.annotations[0].status,'user_confirmed');assert.equal(h.server().object.annotations[0].presentation.label.measurement_object_id,'e'.repeat(32));assert.equal(h.$('figure-mode').textContent,'出图模式');assert.match(h.$('figure-export-status').textContent,/已恢复底图显示/);
 }
});

test('P0: a local display draft arriving during figure restoration remains intact and blocks label replay',async()=>{
 const {current,restored,recipe}=figureImportFixture(),h=await harness(current);let release;h.delayAction(new Promise(resolve=>{release=resolve;}));h.actionResult(restored);h.$('recipe-text').value=JSON.stringify(recipe);
 const imported=h.click('load-recipe-text');await h.settle();assert.equal(h.calls[0].action,'restore-figure-display');
 h.$('gamma').value='.7';h.$('gamma').oninput();h.flush();const revision=h.inspect().draftRevision;
 release();await imported;await h.finish();
 assert.equal(h.calls.length,1);assert.equal(h.inspect().state.object.object_id,current.object.object_id);assert.equal(h.inspect().pending.object.object_id,restored.object.object_id);assert.equal(h.inspect().draftRevision,revision);assert.equal(Number(h.$('gamma').value),.7);assert.equal(h.inspect().dirty,true);assert.equal(h.inspect().queuedEdits.length,0);assert.deepEqual(h.inspect().state.object.annotations[0].presentation,current.object.annotations[0].presentation);assert.equal(h.$('figure-mode').textContent,'分析模式');assert.match(h.$('figure-export-status').textContent,/尚未安全接续/);
});

test('P0: a provider pending display result cannot apply imported labels or figure preferences',async()=>{
 const {current,restored,recipe}=figureImportFixture(),h=await harness(current),queued=copy(current);queued.pending_result={object_id:restored.object.object_id,request_id:'display-restore-original',reason:'unsaved_draft'};h.actionResult(queued);h.$('recipe-text').value=JSON.stringify(recipe);
 await h.click('load-recipe-text');await h.finish();
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].action,'restore-figure-display');assert.equal(h.inspect().state.object.object_id,current.object.object_id);assert.equal(h.inspect().state.pending_result.request_id,'display-restore-original');assert.equal(h.$('pending-result').hidden,false);assert.equal(h.inspect().queuedEdits.length,0);assert.equal(Number(h.$('gamma').value),2);assert.deepEqual(h.inspect().state.object.annotations[0].presentation,current.object.annotations[0].presentation);assert.equal(h.$('figure-mode').textContent,'分析模式');assert.match(h.$('figure-export-status').textContent,/尚未安全接续/);
});


test('P0: recipe layout batch refreshes the selected inspector even when another mark is first',async()=>{
 const {saved,current,restored}=figureImportFixture();
 for(const s of [saved,current,restored])s.object.annotations.push({...copy(s.object.annotations[0]),annotation_id:'line-b'});
 saved.object.annotations[1].presentation.label.font_size=12;current.object.annotations[1].presentation.label.font_size=16;restored.object.annotations[1].presentation.label.font_size=16;
 const recipe=figureExport.makeFigureRecipe(saved,{preset:'real-space',mode:'figure',layers:{experimental:true},fontPt:8}),h=await harness(current);
 h.$('existing').value='line-b';h.$('existing').onchange();assert.equal(h.$('label-size').value,16);
 h.actionResult(restored);h.$('recipe-text').value=JSON.stringify(recipe);await h.click('load-recipe-text');await h.finish();
 assert.ok(h.calls.some(c=>c.action==='edit-layout'));assert.equal(h.$('label-size').value,12);assert.equal(h.$('marker-shape').value,'circle');assert.deepEqual(h.server().object.annotations[1].anchor,saved.object.annotations[1].anchor);
});

test('pointer probe uses the exact source coordinate request and creates no scientific action',async()=>{
 const h=await harness();h.event('pointermove',25,26);await h.flushProbes();assert.equal(h.probeCalls.length,0,'closed numerical inspector performs no backend read');h.$('numeric-data').open=true;h.event('pointermove',25,26);h.event('pointermove',30,28);assert.equal(h.probeCalls.length,0);await h.flushProbes();assert.equal(h.probeCalls.length,1);assert.deepEqual(h.probeCalls[0].coordinates,[50,40]);assert.equal(h.probeCalls[0].source_object_id,sourceId);assert.equal(h.probeCalls[0].component,'raw');assert.equal(h.calls.length,0);assert.match(h.$('probe-value').textContent,/原始数值 17/);h.event('pointermove',40,38);h.event('pointerleave');await h.flushProbes();assert.equal(h.probeCalls.length,1);assert.match(h.$('probe-value').textContent,/尚未读取/);
});

test('historical moved or missing marks expose the same explicit jump requested by selection',async()=>{
 for(const missing of [false,true]){
  const initial=annotated(),saved=copy(initial),oldId='e'.repeat(32),currentId='f'.repeat(32),savedView='d'.repeat(32);
  saved.object.object_id=savedView;saved.object.annotations[0].anchor.coordinates=[30,22,55,50];
  if(missing)initial.object.annotations=[];
  const old={object_id:oldId,kind:'measure',annotation_id:'line-a',name:'old A',status:'historical',points:[[30,22],[55,50]],coordinate_space:'source_pixels',input_object_id:savedView,same_grid:true,visible_in_current_view:true,annotation_matches_current:false};
  const current={...copy(old),object_id:currentId,name:'current A',status:'current',points:[[30,22],[60,52]],input_object_id:viewId,annotation_matches_current:!missing};
  initial.measurement_entries=[old,current];const h=await harness(initial);await h.settle();
  h.$('measurement-history').checked=true;h.$('measurement-history').onchange();
  const row=id=>h.$('measurement-rows').children.find(value=>value.dataset.measurementId===id);
  row(oldId).onclick();await h.settle();
  assert.match(h.$('message').textContent,/跳到结果原视图/);
  assert.equal(h.$('measurement-jump').hidden,false,missing?'missing annotation must allow original-view navigation':'moved annotation must allow original-view navigation');
  assert.equal(h.calls.length,0,'viewing the old result cannot remeasure or switch views');
  assert.equal(h.inspect().state.object.object_id,viewId);assert.deepEqual(h.inspect().state.object.annotations,initial.object.annotations);
  const restored=copy(saved);restored.measurement_entries=[{...copy(old),annotation_matches_current:true},{...copy(current),annotation_matches_current:false}];
  h.actionResult(restored);await h.click('measurement-jump');await h.settle();
  assert.deepEqual(h.calls.map(value=>value.action),['measurement-jump']);assert.equal(h.calls[0].params.measurement_object_id,oldId);
  assert.equal(h.inspect().state.object.object_id,savedView);assert.deepEqual(h.inspect().state.object.annotations,saved.object.annotations);
  assert.equal(row(oldId).attributes['aria-selected'],'true','the old row remains selected, not the newer measurement of that annotation');
  assert.equal(h.$('measurement-jump').hidden,true,'the exact original mark now matches');
  assert.deepEqual(h.server().measurement_entries.map(value=>({object_id:value.object_id,points:value.points})),initial.measurement_entries.map(value=>({object_id:value.object_id,points:value.points})));
 }
 for(const flags of [{same_grid:true,visible_in_current_view:true,annotation_matches_current:true},{same_grid:false,visible_in_current_view:false,annotation_matches_current:false},{same_grid:true,visible_in_current_view:false,annotation_matches_current:true}]){
  const initial=annotated();initial.measurement_entries=[{object_id:'e'.repeat(32),kind:'measure',annotation_id:'line-a',status:'current',points:[[30,22],[60,52]],coordinate_space:'source_pixels',...flags}];
  const h=await harness(initial);await h.settle();h.$('measurement-rows').children[0].onclick();await h.settle();
  assert.equal(h.$('measurement-jump').hidden,!requiresMeasurementJump(initial.measurement_entries[0]));assert.equal(h.calls.length,0);
 }
 assert.equal(requiresMeasurementJump(null),false);
});


// Human workflow regressions: actual app handlers with this file's existing DOM/API shim.
function humanPointFixture(){const s=fixture();s.object.annotations=[{annotation_id:'human-A',kind:'point',text:'A',color:'cyan',status:'hypothesized',anchor:{source_object_id:sourceId,coordinate_space:'source_pixels',coordinates:[60,50]}}];return s;}
test('human workflow: choosing a mark never leaves a sticky edit mode; blank drag cannot move it',async()=>{
 const h=await harness(humanPointFixture());h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',40,38);await h.finish();
 assert.equal(h.$('mode').value,'select');const before=copy(h.server().object.annotations[0].anchor);
 h.event('pointerdown',90,70);h.event('pointermove',105,85);h.event('pointerup',105,85);await h.finish();
 assert.equal(h.inspect().draft.kind,'rectangle');assert.deepEqual(h.server().object.annotations[0].anchor,before);assert.equal(h.calls.filter(c=>c.action==='edit').length,0);
 h.event('pointerdown',100,75);h.event('pointerup',100,75);await h.finish();assert.equal(h.inspect().draft,null);
});
test('human workflow: undo newer Gamma before older science geometry; redo follows the same chronological order',async()=>{
 const h=await harness(humanPointFixture());h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',50,38);await h.finish();
 const moved=copy(h.server().object.annotations[0].anchor.coordinates);assert.deepEqual(moved,[70,50]);
 h.$('gamma').value='2';h.$('gamma').oninput();await h.click('undo');await h.finish();
 assert.equal(Number(h.$('gamma').value),1);assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,moved);
 await h.click('undo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[60,50]);
 await h.click('redo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,moved);
 await h.click('redo');assert.equal(Number(h.$('gamma').value),2);
});
test('human workflow: a newer marker move is undone before an earlier unsaved Gamma change',async()=>{
 const h=await harness(humanPointFixture());h.$('gamma').value='2';h.$('gamma').oninput();h.$('mode').value='select';h.event('pointerdown',40,38);h.event('pointerup',50,38);await h.finish();
 await h.click('undo');await h.finish();assert.deepEqual(h.server().object.annotations[0].anchor.coordinates,[60,50]);assert.equal(Number(h.$('gamma').value),2);
 await h.click('undo');assert.equal(Number(h.$('gamma').value),1);
});
test('human workflow: a rectangle measurement is refused before creating a scientific mark',async()=>{
 const h=await harness();h.draw('rectangle');await h.click('measure');assert.equal(h.calls.length,0);assert.equal(h.server().object.annotations.length,0);assert.match(h.$('message').textContent,/线段|ROI/);
});
test('human workflow: saved-view back opens the stored object and never resubmits FFT',async()=>{
 const first=fixture(),h=await harness(first);h.draw('rectangle');const fft=copy(first);fft.object.object_id='c'.repeat(32);fft.object.kind='fft';fft.object.panels=[{domain:'frequency',source_object_id:'d'.repeat(32),fft_shape_yx:[96,128],image_rect_xyxy:[0,0,128,96]}];h.actionResult(fft);await h.click('fft');
 assert.equal(h.$('view-back').disabled,false);h.actionResult(first);await h.click('view-back');assert.equal(h.calls.at(-1).action,'show');assert.equal(h.calls.at(-1).params.object_id,viewId);assert.equal(h.calls.filter(c=>c.action==='fft').length,1);assert.equal(h.inspect().state.object.object_id,viewId);
});
test('directly reopened ROI explicitly requests a fresh full-frame display instead of claiming a saved recipe',async()=>{
 const initial=fixture();initial.frame_identity={frame_object_id:sourceId,frame_index:0};const h=await harness(initial);
 assert.equal(h.$('view-current').textContent,'保存视图');assert.equal(h.$('view-original').textContent,'全帧（新显示）');assert.match(h.$('view-original').title,/没有已保存/);
 const full=copy(initial);full.object.object_id='c'.repeat(32);full.object.panels[0].source_rect_xyxy=[0,0,128,96];h.actionResult(full);await h.click('view-original');
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].action,'show');assert.deepEqual(h.calls[0].params,{object_id:sourceId,source_view:true});assert.match(h.$('message').textContent,/未恢复未知的旧显示配方/);assert.equal(h.$('view-original').disabled,true);
});

test('human workflow: result tabs expose one result type without changing the scientific object',async()=>{
 const h=await harness();await h.click('results-tab-profile');assert.equal(h.$('results-profile').hidden,false);assert.equal(h.$('results-measurements').hidden,true);assert.equal(h.$('numeric-data').open,true);await h.click('results-tab-measurements');assert.equal(h.$('numeric-data').open,false);assert.equal(h.calls.length,0);
});
