// Execute the actual UI event handlers with a deterministic DOM/canvas/API shim.
// No browser timing, DM, private data, or worker/backend qualification is implied.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import * as coordinates from '../ui/image-panel/coordinates.mjs';

const source=readFileSync(process.env.PANEL_UI_UNDER_TEST??new URL('../ui/image-panel/app.mjs',import.meta.url),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const sourceId='a'.repeat(32),viewId='b'.repeat(32);
const panel={domain:'spatial_pixels',source_object_id:sourceId,source_rect_xyxy:[20,12,148,108],image_rect_xyxy:[0,0,128,96]};
function fixture(){return {object:{object_id:viewId,kind:'view',panels:[copy(panel)],annotations:[],display:{gamma:1,display_range:[0,255]}},tools:[],png_base64:'synthetic',selection:null,last_operation:null};}
function pixelBytes(w,h){return Uint8ClampedArray.from({length:w*h*4},(_,i)=>i%4===3?255:(i*17+31)%256);}
async function harness(initial=fixture()){
 const calls=[],frames=new Map(),stats={pow:0,draws:0,uploads:0};let server=copy(initial),frameId=0;
 const canvasContexts=[];
 class Context{
  constructor(canvas){this.canvas=canvas;this.lastPixels=null;canvasContexts.push(this);}
  drawImage(image){stats.draws++;this.lastPixels=image.context?.lastPixels??null;}
  getImageData(x,y,w,h){return {data:pixelBytes(w,h),width:w,height:h};}
  putImageData(value){stats.uploads++;this.lastPixels={data:new Uint8ClampedArray(value.data),width:value.width,height:value.height};}
  clearRect(){} fillText(){} strokeRect(){} setLineDash(){} beginPath(){} arc(){} stroke(){} moveTo(){} lineTo(){} closePath(){}
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
 $('zoom').value='1';$('mode').value='line';$('status').value='hypothesized';
 const math=Object.create(Math);math.pow=(a,b)=>{stats.pow++;return Math.pow(a,b);};
 const sandbox={...coordinates,console,Math:math,Uint8ClampedArray,
  document:{getElementById:$,createElement:tag=>new Element(tag),querySelectorAll:()=>[]},
  sessionStorage:{getItem:()=> 'synthetic-token',setItem(){}},location:{hash:'',pathname:'/'},history:{replaceState(){}},
  Option:class{constructor(text,value){this.text=text;this.value=value;}},
  Image:class{constructor(){this.width=128;this.height=96;}async decode(){}},
  ImageData:class{constructor(data,width,height){this.data=data;this.width=width;this.height=height;}},
  requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
  fetch:async(url,options)=>{
   if(options.body){const body=JSON.parse(options.body);calls.push(body);
    assert.equal(body.expected_object_id,server.object.object_id);
    if(body.action==='measure'||body.action==='select')server.selection=copy(body.params.selection);
    server.last_operation={action:body.action};
   }
   return {ok:true,json:async()=>copy(server)};
  }
 };
 const script=source.replace(/^import .*from '\.\/coordinates\.mjs';\n/,'')
  .replace('refresh().then(','globalThis.ready=refresh().then(')
  +'\nglobalThis.inspect=()=>({draft,drag,editCoordinates,state});';
 vm.runInNewContext(script,sandbox,{filename:'ui/image-panel/app.mjs'});await sandbox.ready;
 const flush=()=>{for(const [id,callback] of [...frames]){frames.delete(id);callback();}};
 const event=(type,x=10,y=10,extra={})=>{$('canvas').listeners[type]?.({clientX:x,clientY:y,pointerId:1,button:0,...extra});};
 const click=async id=>{await $(id).onclick();flush();};
 const draw=(kind='line')=>{$('mode').value=kind;event('pointerdown',10,10);event('pointermove',40,35);event('pointerup',40,35);flush();};
 return {$,calls,stats,frames,flush,event,click,draw,inspect:()=>copy(sandbox.inspect()),contexts:canvasContexts,
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
 assert.equal(h.stats.draws,beforeDraws+1);assert.equal(h.calls.length,0);
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
 const shown=h.$('canvas').context.lastPixels;
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
