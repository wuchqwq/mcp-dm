import {selectionFromDrag,selectionRectangle,transformCoordinates,panelAt,coordinateSpace} from './coordinates.mjs';
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true});
const key='mcp-dm-panel-token',hash=location.hash.slice(1);if(hash){sessionStorage.setItem(key,hash);history.replaceState(null,'',location.pathname);}const token=sessionStorage.getItem(key);
let state,image,basePixels,draft=null,drag=null,editCoordinates=null,busy=false;
// Keep the expensive PNG tone draft separate from frequently redrawn gestures.
const toneCanvas=document.createElement('canvas'),toneContext=toneCanvas.getContext('2d');
let toneCacheKey=null,paintFrame=null;
function schedulePaint(){if(paintFrame===null)paintFrame=requestAnimationFrame(()=>{paintFrame=null;paint();});}
function restoredSelection(value,panels){
 if(!value)return null;
 const panel=panels.find(p=>p.source_object_id===value.source_object_id&&coordinateSpace(p)===value.coordinate_space&&JSON.stringify(p)===JSON.stringify(value.panel));
 if(!panel)return null; // Never carry a selection onto a changed view/grid.
 try{return {...value,panel,rendered:transformCoordinates(value.coordinates,panel,{edges:['rectangle','polygon'].includes(value.kind),inverse:true})};}
 catch{return null;}
}
const message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
async function api(url,body){const response=await fetch(url,{method:body?'POST':'GET',headers:{'X-Panel-Token':token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const result=await response.json();if(!response.ok)throw new Error(result.error??'本地服务失败');return result;}
async function act(action,params={}){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{const r=await api('/api/action',{expected_object_id:state.object.object_id,action,params});await load(r);message(({select:'选择已交接；可继续使用当前选区。',measure:'测量完成；当前选区已保留。',export:'已导出；当前选区已保留。'})[action]??'已保存新版本；原像素与旧版本保留。');return r;}catch(e){message(e.message,true);if(/Stale/.test(e.message))await refresh();}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
async function refresh(){await load(await api('/api/state'));}
async function load(next){
 const sameObject=state?.object.object_id===next.object.object_id;
 const savedSelection=sameObject&&draft?draft:next.selection;
 state=next;draft=restoredSelection(savedSelection,next.object.panels??[]);drag=null;editCoordinates=null;toneCacheKey=null;const o=state.object;
 $('identity').textContent=`${o.kind} · ${o.object_id}${state.frame_identity?` · 第 ${state.frame_identity.frame_index+1} 帧`:''} · 明确外部计算`;
 const previous=$('existing').value;$('existing').replaceChildren(new Option('新增标记',''));for(const mark of o.annotations??[]){if(mark.annotation_id)$('existing').append(new Option(`${mark.annotation_id} · ${mark.status}`,mark.annotation_id));}if([...(o.annotations??[])].some(m=>m.annotation_id===previous))$('existing').value=previous;
 const d=state.effective_display??o.display??{};$('gamma').value=d.gamma??1;$('gamma-label').textContent=$('gamma').value;$('low').value=d.display_range?.[0]??'';$('high').value=d.display_range?.[1]??'';$('axes').checked=d.spectrum_axes??false;$('scale').checked=d.scale_bar??false;if(state.frame_identity)$('frame').value=state.frame_identity.frame_index+1;
 $('calibration').hidden=!state.tools.some(t=>t.name==='image_calibrate');$('metadata').textContent=JSON.stringify({object_id:o.object_id,frame_identity:state.frame_identity,calibration:o.xy_calibration??o.calibration_record??o.calibration,effective_display:d,display_source_object_id:state.display_source_object_id},null,2);
 $('operation').textContent=state.last_operation?JSON.stringify(state.last_operation):'';
 if(next.png_base64){image=new Image();image.src='data:image/png;base64,'+next.png_base64;await image.decode();canvas.width=image.width;canvas.height=image.height;ctx.drawImage(image,0,0);basePixels=ctx.getImageData(0,0,canvas.width,canvas.height);resize();paint();}else{image=null;basePixels=null;canvas.width=640;canvas.height=160;ctx.clearRect(0,0,640,160);ctx.fillStyle='#d4e4ef';ctx.fillText('序列已打开。请选择一个帧。',20,40);}
 if(draft)showDraft();else $('selection').textContent='在图中点击或拖拽。矩形用于 ROI，线段可测量，点用于峰位。';
}
function resize(){const zoom=Number($('zoom').value);canvas.style.width=`${canvas.width*zoom}px`;canvas.style.height=`${canvas.height*zoom}px`;}
function paint(){
 if(paintFrame!==null){cancelAnimationFrame(paintFrame);paintFrame=null;}
 if(!basePixels)return;
 const display=state.effective_display??state.object.display??{},oldGamma=display.gamma??1,gamma=Number($('gamma').value),range=display.display_range,newLow=Number($('low').value),newHigh=Number($('high').value),adjustRange=Boolean(range&&$('low').value!==''&&$('high').value!==''&&newHigh>newLow);
 const key=JSON.stringify([oldGamma,gamma,range,newLow,newHigh,adjustRange]);
 if(toneCacheKey!==key){
  // Identical arithmetic/Uint8Clamped rounding to the former per-channel loop,
  // evaluated once per possible byte value, not once per pixel on every move.
  const lut=new Uint8ClampedArray(256);
  for(let value=0;value<256;value++){
   let normalized=Math.pow(value/255,oldGamma);
   if(adjustRange)normalized=Math.max(0,Math.min(1,(range[0]+normalized*(range[1]-range[0])-newLow)/(newHigh-newLow)));
   lut[value]=255*Math.pow(normalized,1/gamma);
  }
  const pixels=new ImageData(new Uint8ClampedArray(basePixels.data),basePixels.width,basePixels.height);
  for(let i=0;i<pixels.data.length;i+=4)for(let c=0;c<3;c++)pixels.data[i+c]=lut[pixels.data[i+c]];
  toneCanvas.width=pixels.width;toneCanvas.height=pixels.height;
  toneContext.putImageData(pixels,0,0);toneCacheKey=key;
 }
 ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(toneCanvas,0,0);
 const coords=drag?.kind==='edit'?null:drag?(drag.kind==='point'?drag.start:[...drag.start,...drag.end]):draft?.rendered;if(coords){ctx.strokeStyle='#45e8ff';ctx.fillStyle='#45e8ff';ctx.lineWidth=2;ctx.setLineDash([4,3]);if((drag?.kind??draft.kind)==='rectangle')ctx.strokeRect(coords[0],coords[1],coords[2]-coords[0],coords[3]-coords[1]);else if(coords.length===2){ctx.beginPath();ctx.arc(coords[0],coords[1],5,0,Math.PI*2);ctx.stroke();}else{ctx.beginPath();ctx.moveTo(...coords.slice(0,2));ctx.lineTo(...coords.slice(2,4));ctx.stroke();}ctx.setLineDash([]);}
 if(editCoordinates){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===$('existing').value),p=state.object.panels.find(p=>p.source_object_id===mark.anchor.source_object_id),edges=['rectangle','polygon'].includes(mark.kind),rendered=transformCoordinates(editCoordinates,p,{edges,inverse:true});ctx.strokeStyle='#ff903b';ctx.lineWidth=2;if(mark.kind==='rectangle')ctx.strokeRect(rendered[0],rendered[1],rendered[2]-rendered[0],rendered[3]-rendered[1]);else{ctx.beginPath();ctx.moveTo(...rendered.slice(0,2));for(let i=2;i<rendered.length;i+=2)ctx.lineTo(...rendered.slice(i,i+2));if(edges)ctx.closePath();ctx.stroke();}for(let i=0;i<rendered.length;i+=2)ctx.strokeRect(rendered[i]-3,rendered[i+1]-3,6,6);}
}
function xy(event){const rect=canvas.getBoundingClientRect();return [(event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height];}
function showDraft(){if(!draft)return;const {panel,rendered,...publicDraft}=draft;let rect;try{if(draft.kind==='rectangle')rect=selectionRectangle(draft);}catch(e){message(e.message,true);}$('selection').textContent=JSON.stringify({...publicDraft,...(rect?{submitted_integer_rect:rect,integer_rule:'outward bin/edge snapping; visible before submission'}:{})},null,2);}
canvas.addEventListener('pointerdown',event=>{if(busy||!image||drag||event.button!==0)return;const start=xy(event),kind=$('mode').value;try{panelAt(state.object.panels??[],...start,{edges:kind==='rectangle'});
 if(kind==='edit'){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===$('existing').value);if(!mark?.anchor)throw new Error('先在“已有标记”中选一条带科学锚点的标注');const p=state.object.panels.find(p=>p.source_object_id===mark.anchor.source_object_id);if(!p)throw new Error('标注不在当前数据面板');const edges=['rectangle','polygon'].includes(mark.kind),rendered=transformCoordinates(editCoordinates??mark.anchor.coordinates,p,{edges,inverse:true}),distances=[];for(let i=0;i<rendered.length;i+=2)distances.push(Math.hypot(start[0]-rendered[i],start[1]-rendered[i+1]));const nearest=Math.min(...distances),handle=nearest<12?distances.indexOf(nearest):-1;drag={kind,start,end:start,mark,p,edges,handle,original:editCoordinates??mark.anchor.coordinates,previousEdit:editCoordinates};editCoordinates=[...drag.original];}
 else drag={kind,start,end:start};drag.pointerId=event.pointerId;canvas.setPointerCapture(event.pointerId);schedulePaint();
 }catch(e){message(e.message,true);}});
function updateDrag(event){
 drag.end=xy(event);
 if(drag.kind==='edit'){
  const from=transformCoordinates(drag.start,drag.p,{edges:drag.edges}),to=transformCoordinates(drag.end,drag.p,{edges:drag.edges}),delta=to.map((v,i)=>v-from[i]);
  editCoordinates=drag.original.map((v,i)=>drag.handle<0||Math.floor(i/2)===drag.handle?v+delta[i%2]:v);
 }
}
canvas.addEventListener('pointermove',event=>{if(!drag||event.pointerId!==drag.pointerId)return;updateDrag(event);schedulePaint();});
function cancelDrag(event){
 if(!drag||event.pointerId!==drag.pointerId)return;
 if(drag.kind==='edit')editCoordinates=drag.previousEdit;
 drag=null;schedulePaint();
 message('已取消本次拖动；尚未提交任何修改。');
}
canvas.addEventListener('pointercancel',cancelDrag);
canvas.addEventListener('lostpointercapture',cancelDrag);
canvas.addEventListener('pointerup',event=>{if(!drag||event.pointerId!==drag.pointerId)return;try{updateDrag(event);if(drag.kind==='edit'){message('标注位置草稿已移动；点“保存这条标记”提交一个新版本。');return;}const selected=selectionFromDrag(state.object.panels??[],drag.start,drag.end,{kind:drag.kind});draft={...selected,rendered:selected.kind==='point'?drag.start:[...drag.start,...drag.end]};if(selected.kind==='rectangle')draft.rendered=[Math.min(...[drag.start[0],drag.end[0]]),Math.min(...[drag.start[1],drag.end[1]]),Math.max(...[drag.start[0],drag.end[0]]),Math.max(...[drag.start[1],drag.end[1]])];showDraft();message('选择已定位到原数据坐标。可继续提交选区、标记或交给 Agent。');}catch(e){message(e.message,true);}finally{drag=null;paint();}});
const selection=()=>{if(!draft)throw new Error('先在图中选择位置或区域');const {rendered,...s}=draft;return s;};
function guarded(fn){return async()=>{try{await fn();}catch(e){message(e.message,true);}};}
for(const [id,action]of [['apply-roi','roi'],['fft','fft'],['measure','measure'],['share','select']])$(id).onclick=guarded(()=>act(action,{selection:selection()}));
 $('reload').onclick=guarded(refresh);$('zoom').oninput=resize;for(const id of ['gamma','low','high'])$(id).oninput=()=>{$('gamma-label').textContent=$('gamma').value;schedulePaint();message('显示草稿：PNG 近似反馈，尚未保存；提交后从原科学数组重绘。');};
 $('apply-display').onclick=guarded(()=>{const low=Number($('low').value),high=Number($('high').value),frequency=state.object.panels?.some(p=>p.domain==='frequency');return act('preview',{gamma:Number($('gamma').value),display_range:$('low').value===''||$('high').value===''?null:[low,high],...(frequency?{spectrum_axes:$('axes').checked}:{scale_bar:$('scale').checked})});});
 $('set-frame').onclick=guarded(()=>act('frame',{frame_index:Number($('frame').value)-1}));$('full').onclick=guarded(()=>act('preview',{frequency_rect:null}));$('export').onclick=guarded(()=>act('export'));$('recover').onclick=guarded(()=>act('recover'));
 $('existing').onchange=()=>{const mark=(state.object.annotations??[]).find(m=>m.annotation_id===$('existing').value);editCoordinates=null;if(mark){draft=null;$('mark-id').value=mark.annotation_id;$('mark-text').value=mark.text??'';$('color').value=mark.color;$('status').value=mark.status;$('mode').value='edit';}else{$('mark-id').value='';$('mark-text').value='';$('color').value='cyan';$('status').value='hypothesized';$('mode').value='arrow';}paint();};
 $('save-mark').onclick=guarded(()=>{const existing=$('existing').value,fields={text:$('mark-text').value,color:$('color').value,status:$('status').value};if(existing)return act('edit',{updates:[{annotation_id:existing,...fields,...(editCoordinates?{coordinates:editCoordinates}:{})}]});return act('mark',{selection:selection(),annotation_id:$('mark-id').value,...fields});});
 const calibrate=withdraw=>{const xy_scale=withdraw?null:{x:Number($('scale-x').value),y:Number($('scale-y').value),unit:$('unit').value};return act('calibrate',{scope:$('scope').value,xy_scale,source_text:$('source').value});};$('calibrate').onclick=guarded(()=>calibrate(false));$('withdraw').onclick=guarded(()=>calibrate(true));
refresh().then(()=>message('本地工具已连接。所有保存操作创建新版本；原图只读。')).catch(e=>message(e.message,true));
