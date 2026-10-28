import {selectionFromDrag,selectionRectangle,transformCoordinates,panelAt,coordinateSpace} from './coordinates.mjs';
import {zoomAt,panBy,hitMark,DraftHistory,internalMarkId,relatedViewport} from './viewer-state.mjs';
import {tonePixels,drawMark} from './viewer-render.mjs';
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d'),baseCanvas=$('base-canvas'),baseContext=baseCanvas.getContext('2d',{willReadFrequently:true}),marksCanvas=$('marks-canvas'),marksContext=marksCanvas.getContext('2d'),stage=$('image-stage'),viewport=$('viewport');
const key='mcp-dm-panel-token',hash=location.hash.slice(1);if(hash){sessionStorage.setItem(key,hash);history.replaceState(null,'',location.pathname);}const token=sessionStorage.getItem(key);
let state,image,basePixels,draft=null,drag=null,editCoordinates=null,busy=false,cleanBase=false,selectedId='',spaceDown=false,pending=null,orphanedDraft=false;
let view={scale:1,x:0,y:0},toneCacheKey=null,paintFrame=null,marksDirty=true,loading=0,fieldDirty=false,displayBaseline='',draftPublisher=Promise.resolve();
let draftPending=null,draftSending=false,draftError=null,autoFailed=false,autoSequence=0,autoTimer=null,fieldBefore=null,autoSaving=null,measuredMarkId='';
const queuedEdits=new Map(),editUndo=[],editRedo=[];
const historyDraft=new DraftHistory({}),perf={frames:0,tone_count:0,overlay_count:0,tone_last_ms:0,overlay_last_ms:0,draw_last_ms:0,action_last_ms:0};
const now=()=>performance.now(),message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
const displayDraft=()=>({gamma:Number($('gamma').value),low:$('low').value,high:$('high').value,axes:$('axes').checked,scale:$('scale').checked});
const dirty=()=>Boolean(orphanedDraft||queuedEdits.size||editCoordinates||fieldDirty||JSON.stringify(displayDraft())!==displayBaseline);
function diagnostics(){const status=autoFailed?'保存失败 · 草稿保留':busy?'正在保存':queuedEdits.size?'等待保存':dirty()?'本地草稿':draft?'选择已就绪':'已保存 · 原图只读';$('performance-data').textContent=JSON.stringify({...perf,dirty:dirty(),gesture_active:Boolean(drag),draft_revision:historyDraft.revision,object_id:state?.object.object_id,scale:view.scale,busy,queued_edits:queuedEdits.size});$('draft-status').textContent=status;$('autosave-status').textContent=status;$('undo').disabled=!editUndo.length&&!historyDraft.undoStack.length;$('redo').disabled=!editRedo.length&&!historyDraft.redoStack.length;$('undo').title=editUndo.length?'撤销标注：保存一个新版本，旧版本仍保留':'撤销未保存草稿';$('redo').title=editRedo.length?'恢复标注：保存一个新版本':'恢复草稿';}
async function api(url,body){const response=await fetch(url,{method:body?'POST':'GET',headers:{'X-Panel-Token':token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const result=await response.json();if(!response.ok)throw new Error(result.error??'本地服务失败');return result;}
function selection(){if(!draft)throw new Error('先在图中选择位置或区域');const {rendered,...s}=draft;return s;}
function annotationEditDraft(){
 if(selectedId&&queuedEdits.has(selectedId)&&!editCoordinates&&!fieldDirty)return {...queuedEdits.get(selectedId).update};
 if(!selectedId||!editCoordinates&&!fieldDirty){
  const prior=orphanedDraft?state.edit_state?.annotation_edit:null;
  return prior?Object.fromEntries(['annotation_id','coordinates','text','color','status'].filter(k=>prior[k]!==undefined).map(k=>[k,prior[k]])):null;
 }
 return {annotation_id:selectedId,...(editCoordinates?{coordinates:[...editCoordinates]}:{}),...(fieldDirty?{text:$('mark-text').value,color:$('color').value,status:$('status').value}:{})};
}
function publishDraft({gesture_active=Boolean(drag),includeSelection=false,urgent=false}={}){
 if(!state)return Promise.resolve();const object_id=state.object.object_id,params={draft_revision:historyDraft.revision,dirty:dirty()||gesture_active,gesture_active,annotation_edit:annotationEditDraft(),...(includeSelection&&draft?{selection:selection()}:{})};
 draftPending={expected_object_id:object_id,action:'draft',lightweight:true,params,urgent:urgent||gesture_active};
 if(!draftSending){draftSending=true;draftPublisher=(async()=>{try{while(draftPending){if(!draftPending.urgent&&typeof setTimeout==='function')await new Promise(r=>setTimeout(r,70));const body=draftPending;draftPending=null;delete body.urgent;try{await api('/api/action',body);draftError=null;}catch(e){draftError=e;message('草稿交接未确认：'+e.message,true);}}}finally{draftSending=false;}})();}
 return draftPublisher;
}
function effectiveEdit(id){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===id);if(!mark)return null;return {annotation_id:id,coordinates:[...mark.anchor.coordinates],text:mark.text??'',color:mark.color,status:mark.status,...(queuedEdits.get(id)?.update??{})};}
function queueEdit(update,before=null,{undo=true}={}){
 const prior=before??effectiveEdit(update.annotation_id);if(!prior)return;
 const after={...effectiveEdit(update.annotation_id),...update};
 if(JSON.stringify(prior)===JSON.stringify(after)){if(queuedEdits.has(update.annotation_id))Promise.resolve().then(flushEdits);return;}
 if(undo&&JSON.stringify(prior)!==JSON.stringify(after)){editUndo.push({before:prior,after});if(editUndo.length>40)editUndo.shift();editRedo.length=0;}
 queuedEdits.set(update.annotation_id,{update:after,sequence:++autoSequence,geometryChanged:JSON.stringify(prior.coordinates)!==JSON.stringify(after.coordinates)});marksDirty=true;record();schedulePaint();publishDraft({urgent:true});Promise.resolve().then(flushEdits);
}
function captureSelected(){if(!selectedId||!editCoordinates&&!fieldDirty)return false;const before=fieldBefore??effectiveEdit(selectedId),update={annotation_id:selectedId,text:$('mark-text').value,color:$('color').value,status:$('status').value,...(editCoordinates?{coordinates:[...editCoordinates]}:{})};editCoordinates=null;fieldDirty=false;fieldBefore=null;queueEdit(update,before);return true;}
function flushEdits(){
 if(autoSaving)return autoSaving;
 if(busy||drag||autoFailed||!queuedEdits.size)return Promise.resolve();
 autoSaving=saveFirstEdit().finally(()=>{autoSaving=null;if(!autoFailed&&queuedEdits.size&&!drag)Promise.resolve().then(flushEdits);});return autoSaving;
}
async function saveFirstEdit(){
 const [id,sent]=queuedEdits.entries().next().value;busy=true;diagnostics();
 try{
  await publishDraft({urgent:true});if(draftError)throw draftError;
  const r=await api('/api/action',{expected_object_id:state.object.object_id,draft_revision:historyDraft.revision,action:'edit',params:{updates:[sent.update],auto_commit:true}});
  if(!r.auto_edit_committed)throw new Error('未能安全接续自动保存；草稿保留，请查询原请求');
  if(queuedEdits.get(id)===sent){queuedEdits.delete(id);if(selectedId===id&&!drag&&!fieldDirty&&JSON.stringify(editCoordinates)===JSON.stringify(sent.update.coordinates))editCoordinates=null;}
  // Annotation-only adoption uses identical provider panel mappings. Keep the
  // current gesture/camera/local edits; no decode or full bitmap work here.
  state=r;marksDirty=true;showPending();schedulePaint();message('标注已自动保存；旧版本保留。');
 }catch(e){autoFailed=true;message('自动保存失败，编辑仍保留。请查询原请求，勿重复提交：'+e.message,true);}
 finally{busy=false;diagnostics();await publishDraft({includeSelection:true,urgent:true});if(!autoFailed&&sent.geometryChanged&&measuredMarkId===id&&!queuedEdits.size&&!drag)await act('measure',{selection:selection()});}
}
function autoFields(){if(!selectedId)return;if(autoTimer!==null&&typeof clearTimeout==='function')clearTimeout(autoTimer);if(typeof setTimeout==='function')autoTimer=setTimeout(()=>{autoTimer=null;captureSelected();},350);}
function snapshot(){return {draft,editCoordinates,selectedId,fieldDirty,display:displayDraft(),fields:{id:$('mark-id').value,text:$('mark-text').value,color:$('color').value,status:$('status').value}};}
function record(){historyDraft.replace(snapshot());diagnostics();}
function restoreSnapshot(value){draft=value.draft??null;editCoordinates=value.editCoordinates??null;selectedId=value.selectedId??'';fieldDirty=value.fieldDirty??false;$('existing').value=selectedId;if(value.display){$('gamma').value=value.display.gamma;$('low').value=value.display.low;$('high').value=value.display.high;$('axes').checked=value.display.axes;$('scale').checked=value.display.scale;$('gamma-label').textContent=$('gamma').value;}if(value.fields)for(const [id,field]of [['mark-id','id'],['mark-text','text'],['color','color'],['status','status']])$(id).value=value.fields[field];marksDirty=true;showDraft();schedulePaint();publishDraft({includeSelection:true});}
function schedulePaint(){if(paintFrame===null)paintFrame=requestAnimationFrame(()=>{paintFrame=null;paint();});}
function restoredSelection(value,panels){if(!value)return null;const panel=panels.find(p=>p.source_object_id===value.source_object_id&&coordinateSpace(p)===value.coordinate_space&&JSON.stringify(p)===JSON.stringify(value.panel));if(!panel)return null;try{return {...value,panel,rendered:transformCoordinates(value.coordinates,panel,{edges:['rectangle','polygon'].includes(value.kind),inverse:true})};}catch{return null;}}
function markPanel(mark){const matches=(state.object.panels??[]).filter(p=>p.source_object_id===mark.anchor?.source_object_id&&coordinateSpace(p)===mark.anchor.coordinate_space);if(matches.length!==1)throw new Error('标注面板映射不唯一；请在明确的单一视图中编辑');return matches[0];}
function showPending(){$('pending-result').hidden=!pending&&!state?.pending_result;$('pending-message').textContent='有新结果等待查看。查看会切换到该结果的保存版本，当前已保存版本仍保留；请先保存、撤销或明确放弃未保存草稿。';}
async function act(action,params={}){
 if(['frame','roi','fft','export','preview','select'].includes(action)&&selectedId&&(editCoordinates||fieldDirty))captureSelected();
 if(busy){message('上一项保存仍在等待；可继续观察、缩放和平移。');return;}if(pending&&action!=='research-observation'){message('请先处理待查看结果；当前草稿仍保留。',true);return;}
 if(dirty()&&['frame','roi','fft','calibrate','accept-result'].includes(action)){message('先保存或撤销当前草稿，再切换科学视图；缩放、平移和选择仍可继续。',true);return;}
 const sentRevision=historyDraft.revision,start=now(),local=snapshot(),keepDisplay=dirty()&&['edit','mark'].includes(action)&&JSON.stringify(displayDraft())!==displayBaseline,keepMark=action==='preview'&&(editCoordinates||fieldDirty);busy=true;diagnostics();
 try{await draftPublisher;const r=await api('/api/action',{expected_object_id:state.object.object_id,draft_revision:sentRevision,action,params});
  if(action==='research-observation'||action==='recover'&&r.last_operation?.action==='research-observation'){
   state={...state,research_observation:r.research_observation,last_operation:r.last_operation,state_revision:r.state_revision};renderMeasurement();renderObservation();
   message('观察已保存；当前图、选区与未保存草稿保持原样。对 Agent 说“继续”以修订解释。');return r;
  }
  if(r.pending_result&&r.object.object_id===state.object.object_id){state={...state,pending_result:r.pending_result,state_revision:r.state_revision};showPending();message('计算完成；新结果等待查看，期间的新草稿保持原样。');return r;}
  if(historyDraft.revision!==sentRevision||drag){pending=r;showPending();message('保存完成；较新的草稿保持原样，结果等待接续。');return r;}
  if(r.object.object_id===state.object.object_id&&['select','measure','export'].includes(action)){state={...state,last_operation:r.last_operation,selection:r.selection,state_revision:r.state_revision};renderMeasurement();}
  else await load(r,{keepDisplay:keepDisplay?local.display:null,keepMark:keepMark?local:null});
  message(({select:'选择已交接；可继续使用当前选区。',measure:'测量完成；当前选区已保留。',export:'已导出；当前选区已保留。'})[action]??'已保存新版本；原像素与旧版本保留。');return r;
 }catch(e){message(e.message,true);}finally{busy=false;perf.action_last_ms=now()-start;diagnostics();if(queuedEdits.size)Promise.resolve().then(flushEdits);}
}
async function refresh(){const next=await api('/api/state');if(state&&(dirty()||drag)){if(next.object.object_id!==state.object.object_id)pending=next;else state={...state,pending_result:next.pending_result,state_revision:next.state_revision,research_observation:next.research_observation};renderObservation();showPending();message('已检查最新状态；本地草稿保持原样。');return;}if(next.pending_result&&state){state.pending_result=next.pending_result;state.research_observation=next.research_observation;renderObservation();showPending();return;}await load(next);}
function renderObservation(){
 const observation=state.research_observation;
 $('research-feedback').hidden=!state.tools.some(t=>t.name==='image_context');
 $('observation-summary').textContent=observation?`${observation.authority==='synthetic_fixture'?'合成演示（非真人确认）':'研究者声明'}：${observation.source_text} · 确认范围仅为存在孪晶；具体孪晶关系、取向和 HKL 仍待检验。${observation.current_view_relation==='different_saved_view_review_scope'?' 当前视图已变化；Agent 必须复核原观察绑定的图像范围。':''}`:'尚未提交孪晶观察。';
}
function humanCalibration(o){const c=o.xy_calibration??o.calibration_record??o.calibration;if(!c)return 'XY 物理标尺未知；像素域操作可继续';const xy=c.xy_scale??c;return xy.x!==undefined?`XY：${xy.x} / ${xy.y} ${xy.unit??''}/px · ${c.status??c.source_type??'版本化标定'}`:'XY：已保留标定记录；详情见高级信息';}
function renderMeasurement(){const m=state.last_operation;$('operation').textContent=m?JSON.stringify(m,null,2):'';const finite=value=>typeof value==='number'&&Number.isFinite(value);
 $('measurement-summary').textContent=finite(m?.physical_distance)?`距离 ${m.physical_distance} ${m.physical_unit??''}`:
 finite(m?.distance_physical)?`距离 ${m.distance_physical} ${m.physical_unit??''}`:
 finite(m?.d_spacing)?`晶面间距（几何） ${m.d_spacing} ${m.d_spacing_unit??''}`:
 finite(m?.period)?`倒空间差向量周期 ${m.period} ${m.period_unit??''}`:
 finite(m?.distance_pixels)?`图像坐标距离 ${m.distance_pixels} px`:
 finite(m?.frequency_distance_cycles_per_pixel)?`频率差 ${m.frequency_distance_cycles_per_pixel} cycles/pixel`:
 '选线段或已知中心的倒空间峰后可测量；候选标记不等于物相确认';}
async function load(next,{keepDisplay=null,keepMark=null}={}){
 const ticket=++loading,revision=historyDraft.revision,sameObject=state?.object.object_id===next.object.object_id,rect=viewport.getBoundingClientRect(),continued=relatedViewport(view,state,next,[rect.width,rect.height]),savedSelection=(sameObject||continued)&&draft?draft:next.selection;let decoded=null;
 if(next.clean_png_base64||next.png_base64){decoded=new Image();decoded.src='data:image/png;base64,'+(next.clean_png_base64??next.png_base64);await decoded.decode();if(ticket!==loading)return;if(state&&(historyDraft.revision!==revision||drag)){pending=next;showPending();return;}}
 if(!state&&next.edit_state?.dirty)orphanedDraft=true;
 state=next;draft=restoredSelection(savedSelection,next.object.panels??[]);drag=null;editCoordinates=null;fieldDirty=false;toneCacheKey=null;marksDirty=true;const o=state.object,previous=selectedId;
 $('identity').textContent=`${state.frame_identity?`第 ${state.frame_identity.frame_index+1} 帧 · `:''}${o.panels?.some(p=>p.domain==='frequency')?'FFT / 倒空间':'科学图像'} · 原图只读`;$('calibration-summary').textContent=humanCalibration(o);$('source-badge').textContent=state.source_identity?.label??'来源待核对';$('source-name').textContent=state.source_identity?.filename??'';
 $('existing').replaceChildren(new Option('新增标记',''));for(const mark of o.annotations??[])if(mark.annotation_id)$('existing').append(new Option(`${mark.text||mark.annotation_id} · ${{hypothesized:'候选',user_confirmed:'用户确认',retracted:'撤回'}[mark.status]??mark.status}`,mark.annotation_id));selectedId=(o.annotations??[]).some(m=>m.annotation_id===previous)?previous:'';$('existing').value=selectedId;
 const d=state.effective_display??o.display??{};$('gamma').value=d.gamma??1;$('gamma-label').textContent=$('gamma').value;$('low').value=d.display_range?.[0]??'';$('high').value=d.display_range?.[1]??'';$('axes').checked=d.spectrum_axes??false;$('scale').checked=d.scale_bar??false;displayBaseline=JSON.stringify(displayDraft());if(state.frame_identity)$('frame').value=state.frame_identity.frame_index+1;
 const calibrationRecord=o.xy_calibration;
 if(calibrationRecord?.xy_scale){const xy=calibrationRecord.xy_scale;$('scale-x').value=xy.x;$('scale-y').value=xy.y;
  $('unit').value=({'angstrom':'Å','1/angstrom':'1/Å'})[xy.unit]??xy.unit;$('scope').value=calibrationRecord.scope;}
 $('calibration').hidden=!state.tools.some(t=>t.name==='image_calibrate');$('metadata').textContent=JSON.stringify({object_id:o.object_id,frame_identity:state.frame_identity,calibration:o.xy_calibration??o.calibration_record??o.calibration,effective_display:d,render_base_id:state.render_base_id,display_source_object_id:state.display_source_object_id},null,2);
 renderMeasurement();renderObservation();
 image=decoded;cleanBase=Boolean(next.clean_png_base64);for(const c of [canvas,baseCanvas,marksCanvas]){c.width=image?.width??640;c.height=image?.height??160;}stage.style.width=canvas.width+'px';stage.style.height=canvas.height+'px';
 if(image){baseContext.drawImage(image,0,0);basePixels=baseContext.getImageData(0,0,canvas.width,canvas.height);if(!sameObject&&!continued)fitView();else{if(!sameObject)view=continued;resize();}}else{basePixels=null;baseContext.clearRect(0,0,640,160);baseContext.fillStyle='#d4e4ef';baseContext.fillText('序列已打开。请选择一个帧。',20,40);}
 syncMarkFields(false);
 if(keepDisplay){$('gamma').value=keepDisplay.gamma;$('low').value=keepDisplay.low;$('high').value=keepDisplay.high;$('axes').checked=keepDisplay.axes;$('scale').checked=keepDisplay.scale;$('gamma-label').textContent=$('gamma').value;}
 if(keepMark){selectedId=keepMark.selectedId;editCoordinates=keepMark.editCoordinates;fieldDirty=keepMark.fieldDirty;$('existing').value=selectedId;for(const [id,field]of [['mark-id','id'],['mark-text','text'],['color','color'],['status','status']])$(id).value=keepMark.fields[field];}
 // A reconnect must continue the shared monotonically increasing lease; a
 // fresh browser's local counter must never erase a newer panel draft.
 historyDraft.revision=Math.max(historyDraft.revision,state.edit_state?.draft_revision??0);
 historyDraft.reset(snapshot());showDraft();paint();showPending();await publishDraft({includeSelection:true});
}
function resize(){stage.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;$('zoom').value=view.scale;$('zoom-label').textContent=Math.round(view.scale*100)+'%';schedulePaint();}
function fitView(){const r=viewport.getBoundingClientRect(),scale=Math.max(.1,Math.min(2,(r.width-48)/canvas.width,(r.height-48)/canvas.height));view={scale,x:(r.width-canvas.width*scale)/2,y:(r.height-canvas.height*scale)/2};resize();}
function renderedMarks(){return (state?.object.annotations??[]).map(original=>{const queued=queuedEdits.get(original.annotation_id)?.update,mark={...original,...(queued??{})};if(!mark.anchor)return mark;let p;try{p=markPanel(mark);}catch{return {...mark,visibility:'outside_view'};}const edges=['rectangle','polygon'].includes(mark.kind),coords=mark.annotation_id===selectedId&&editCoordinates?editCoordinates:queued?.coordinates??mark.anchor.coordinates,changed=mark.annotation_id===selectedId&&fieldDirty;return {...mark,coordinates:transformCoordinates(coords,p,{edges,inverse:true}),...(queued||mark.annotation_id===selectedId&&editCoordinates?{arrow_render_coordinates:undefined}:{}),...(changed?{text:$('mark-text').value,color:$('color').value,status:$('status').value}:{})};});}
function paint(){
 if(paintFrame!==null){cancelAnimationFrame(paintFrame);paintFrame=null;}if(!basePixels){diagnostics();return;}const start=now(),display=state.effective_display??state.object.display??{},oldGamma=display.gamma??1,gamma=Number($('gamma').value),range=display.display_range,low=$('low').value===''?NaN:Number($('low').value),high=$('high').value===''?NaN:Number($('high').value),cache=JSON.stringify([state.render_base_id,oldGamma,gamma,range,low,high]);
 if(cache!==toneCacheKey){const t=now(),pixels=tonePixels(basePixels.data,{oldGamma,gamma,range,low,high});baseContext.putImageData(new ImageData(pixels,basePixels.width,basePixels.height),0,0);toneCacheKey=cache;perf.tone_last_ms=now()-t;perf.tone_count++;}
 const overlayStart=now(),marks=renderedMarks();if(marksDirty){marksContext.clearRect(0,0,canvas.width,canvas.height);if(cleanBase)for(const m of marks)if(m.annotation_id!==selectedId||!editCoordinates&&!fieldDirty)drawMark(marksContext,m);marksDirty=false;}
 ctx.clearRect(0,0,canvas.width,canvas.height);const edited=marks.find(m=>m.annotation_id===selectedId);if(edited)drawMark(ctx,edited,{selected:true,scale:view.scale,draft:Boolean(editCoordinates)});
 const coords=drag?.kind==='edit'||drag?.kind==='pan'?null:drag?(drag.kind==='point'?drag.start:[...drag.start,...drag.end]):draft?.rendered;
 if(coords){const kind=drag?.kind??draft.kind,c=kind==='rectangle'?[Math.min(coords[0],coords[2]),Math.min(coords[1],coords[3]),Math.max(coords[0],coords[2]),Math.max(coords[1],coords[3])]:coords;drawMark(ctx,{kind,coordinates:c,color:'cyan',line_width:2,arrowhead_size:6,status:'hypothesized'},{scale:view.scale,draft:true});}
 perf.frames++;perf.overlay_count++;perf.overlay_last_ms=now()-overlayStart;perf.draw_last_ms=now()-start;diagnostics();
}
function xy(event){const rect=canvas.getBoundingClientRect();return [(event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height];}
function showDraft(){if(!draft){$('selection').textContent='在图中圈区域、点选峰，或直接拖动已有标注。';return;}let rect;try{if(draft.kind==='rectangle')rect=selectionRectangle(draft);}catch(e){message(e.message,true);}const coords=(rect??draft.coordinates).map(v=>Number(v.toPrecision(6)));$('selection').textContent=`${{point:'点',line:'线段',arrow:'箭头',rectangle:'ROI'}[draft.kind]??draft.kind} · ${coords.join(', ')} · ${draft.coordinate_space==='frequency_cycles_per_pixel'?'cycles/px':'源像素坐标'}${rect?'（向外取整边界）':''}`;}
function syncMarkFields(changeMode=true){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===selectedId);$('existing').value=selectedId;editCoordinates=null;fieldDirty=false;if(mark){$('mark-id').value=mark.annotation_id;$('mark-text').value=mark.text??'';$('color').value=mark.color;$('status').value=mark.status;if(changeMode)$('mode').value='edit';}else{$('mark-id').value=internalMarkId(()=>crypto.randomUUID());$('mark-text').value='';$('color').value='cyan';$('status').value='hypothesized';if(changeMode)$('mode').value='arrow';}marksDirty=true;}
function chooseMark(next){
 if(next===selectedId)return true;
 if(editCoordinates||fieldDirty)captureSelected();
 selectedId=next;syncMarkFields();const saved=effectiveEdit(next);if(saved){$('mark-text').value=saved.text;$('color').value=saved.color;$('status').value=saved.status;editCoordinates=queuedEdits.get(next)?.update.coordinates??null;}
 document.body?.classList.add('properties-open');return true;
}
canvas.addEventListener('pointerdown',event=>{
 if(!image||drag||![0,1].includes(event.button))return;const start=xy(event);if(event.button===1||spaceDown||$('mode').value==='pan'){drag={kind:'pan',pointerId:event.pointerId,startClient:[event.clientX,event.clientY],originalView:{...view}};canvas.setPointerCapture(event.pointerId);return;}
 let kind=$('mode').value;try{const hit=hitMark(renderedMarks(),start,{scale:view.scale});if(kind==='select'){if(hit){if(!chooseMark(hit.mark.annotation_id))return;kind='edit';}else kind='rectangle';}else if(kind==='edit'&&hit&&!chooseMark(hit.mark.annotation_id))return;
  panelAt(state.object.panels??[],...start,{edges:kind==='rectangle'});
  if(kind==='edit'){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===selectedId);if(!mark?.anchor)throw new Error('先点击一条带科学锚点的标注');const p=markPanel(mark),edges=['rectangle','polygon'].includes(mark.kind),original=editCoordinates??effectiveEdit(selectedId).coordinates,rendered=transformCoordinates(original,p,{edges,inverse:true}),distances=[];for(let i=0;i<rendered.length;i+=2)distances.push(Math.hypot(start[0]-rendered[i],start[1]-rendered[i+1]));const nearest=Math.min(...distances),handle=nearest<9/view.scale?distances.indexOf(nearest):-1;drag={kind,start,end:start,mark,p,edges,handle,original,before:effectiveEdit(selectedId),previousEdit:editCoordinates};editCoordinates=[...drag.original];draft={kind:mark.kind,...mark.anchor,coordinates:[...original],panel:p,rendered};marksDirty=true;}
  else drag={kind,start,end:start};drag.pointerId=event.pointerId;canvas.setPointerCapture(event.pointerId);publishDraft({gesture_active:true});schedulePaint();
 }catch(e){message(e.message,true);}
});
function updateDrag(event){if(drag.kind==='pan'){view=panBy(drag.originalView,event.clientX-drag.startClient[0],event.clientY-drag.startClient[1]);resize();return;}drag.end=xy(event);if(drag.kind==='edit'){const from=transformCoordinates(drag.start,drag.p,{edges:drag.edges}),to=transformCoordinates(drag.end,drag.p,{edges:drag.edges}),delta=to.map((v,i)=>v-from[i]);editCoordinates=drag.original.map((v,i)=>drag.handle<0||Math.floor(i/2)===drag.handle?v+delta[i%2]:v);}}
canvas.addEventListener('pointermove',event=>{if(!drag||event.pointerId!==drag.pointerId)return;updateDrag(event);schedulePaint();});
function cancelDrag(event){if(!drag||event.pointerId!==drag.pointerId)return;if(drag.kind==='edit')editCoordinates=drag.previousEdit;if(drag.kind==='pan'){view=drag.originalView;resize();}drag=null;marksDirty=true;schedulePaint();publishDraft();message('已取消本次拖动；尚未提交任何修改。');}
canvas.addEventListener('pointercancel',cancelDrag);canvas.addEventListener('lostpointercapture',cancelDrag);
canvas.addEventListener('pointerup',event=>{if(!drag||event.pointerId!==drag.pointerId)return;const kind=drag.kind,before=drag.before;try{updateDrag(event);if(kind==='pan')return;if(kind==='edit'){const update={annotation_id:selectedId,coordinates:[...editCoordinates],text:$('mark-text').value,color:$('color').value,status:$('status').value};draft={...draft,coordinates:[...editCoordinates],rendered:transformCoordinates(editCoordinates,drag.p,{edges:drag.edges,inverse:true})};editCoordinates=null;fieldDirty=false;queueEdit(update,before);return;}const selected=selectionFromDrag(state.object.panels??[],drag.start,drag.end,{kind});draft={...selected,rendered:transformCoordinates(selected.coordinates,selected.panel,{edges:kind==='rectangle',inverse:true})};showDraft();message('选择已定位；可直接测量或交给 Agent。');}catch(e){message(e.message,true);}finally{drag=null;if(kind!=='pan')record();paint();publishDraft({includeSelection:true,urgent:true});Promise.resolve().then(flushEdits);}});
viewport.addEventListener('wheel',event=>{if(!image)return;event.preventDefault();const r=viewport.getBoundingClientRect();view=zoomAt(view,[event.clientX-r.left,event.clientY-r.top],Math.exp(-event.deltaY*.0015));resize();},{passive:false});
document.addEventListener('keydown',event=>{if(/INPUT|TEXTAREA|SELECT/.test(event.target?.tagName??''))return;if(event.code==='Space'){spaceDown=true;event.preventDefault();}if(!event.ctrlKey&&!event.metaKey){const mode={v:'select',r:'rectangle',p:'point',l:'line',a:'arrow',h:'pan'}[event.key.toLowerCase()];if(mode)setMode(mode);if(event.key.toLowerCase()==='f')fitView();}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();if(event.shiftKey)$('redo').onclick();else $('undo').onclick();}if(event.key==='Escape'&&drag)cancelDrag({pointerId:drag.pointerId});});document.addEventListener('keyup',event=>{if(event.code==='Space')spaceDown=false;});
function guarded(fn){return async()=>{try{await fn();}catch(e){message(e.message,true);}};}
for(const [id,action]of [['apply-roi','roi'],['measure','measure'],['share','select']])$(id).onclick=guarded(()=>{if(action==='measure')measuredMarkId=selectedId;return act(action,{selection:selection()});});
$('fft').onclick=guarded(()=>act('fft',{selection:selection(),window:$('fft-window').value,subtract_mean:$('fft-mean').checked}));
$('reload').onclick=guarded(refresh);$('zoom').oninput=()=>{const r=viewport.getBoundingClientRect();view=zoomAt(view,[r.width/2,r.height/2],Number($('zoom').value)/view.scale);resize();};$('fit').onclick=fitView;
for(const id of ['gamma','low','high','axes','scale'])$(id).oninput=()=>{$('gamma-label').textContent=$('gamma').value;record();schedulePaint();publishDraft();message('显示草稿即时反馈；保存后从原科学数组重绘，不重算 FFT。');};
$('apply-display').onclick=guarded(()=>{const frequency=state.object.panels?.some(p=>p.domain==='frequency');return act('preview',{gamma:Number($('gamma').value),display_range:$('low').value===''||$('high').value===''?null:[Number($('low').value),Number($('high').value)],...(frequency?{spectrum_axes:$('axes').checked}:{scale_bar:$('scale').checked})});});
$('set-frame').onclick=guarded(()=>act('frame',{frame_index:Number($('frame').value)-1}));$('previous-frame').onclick=guarded(()=>act('frame',{frame_index:Math.max(0,Number($('frame').value)-2)}));$('next-frame').onclick=guarded(()=>act('frame',{frame_index:Number($('frame').value)}));$('full').onclick=guarded(()=>act('preview',{frequency_rect:null}));$('export').onclick=guarded(()=>{if(dirty())throw new Error('请先保存或撤销草稿，再导出已保存视图。');return act('export');});$('recover').onclick=guarded(()=>act('recover'));
$('existing').onchange=()=>{if(!chooseMark($('existing').value))return;record();paint();publishDraft();};
for(const id of ['mark-text','color','status'])$(id).oninput=()=>{if(!fieldBefore&&selectedId)fieldBefore=effectiveEdit(selectedId);fieldDirty=true;marksDirty=true;record();schedulePaint();publishDraft();autoFields();};
$('save-mark').onclick=guarded(async()=>{if(selectedId){captureSelected();return flushEdits();}const fields={text:$('mark-text').value,color:$('color').value,status:$('status').value};return act('mark',{selection:selection(),annotation_id:$('mark-id').value,...fields});});
$('undo').onclick=()=>{if(editUndo.length){const item=editUndo.pop();editRedo.push(item);queueEdit(item.before,null,{undo:false});message('正在保存撤销修订；先前科学版本仍保留。');}else if(historyDraft.undo())restoreSnapshot(historyDraft.current);};$('redo').onclick=()=>{if(editRedo.length){const item=editRedo.pop();editUndo.push(item);queueEdit(item.after,null,{undo:false});message('正在保存恢复修订。');}else if(historyDraft.redo())restoreSnapshot(historyDraft.current);};
$('discard-local').onclick=guarded(async()=>{if(busy)throw new Error('原请求仍在保存，先查询其结果；本地编辑保留。');drag=null;queuedEdits.clear();autoFailed=false;orphanedDraft=false;await load(await api('/api/state'));message('本地草稿已撤回；保存过的科学版本仍保留。');});
$('discard-draft').onclick=guarded(async()=>{orphanedDraft=false;if(pending){const next=pending;pending=null;await load(next);}else{editCoordinates=null;fieldDirty=false;const current=await api('/api/state');await load(current);await act('accept-result');}message('已查看保存版本；旧科学版本仍保留。');});
$('accept-agent-result').onclick=guarded(async()=>{if(dirty()||drag)throw new Error('先保存、撤销或明确放弃草稿，再查看 Agent 结果');return act('accept-result');});
const calibrate=withdraw=>act('calibrate',{coordinate_domain:state.object.xy_calibration?.coordinate_domain??'real_space',scope:$('scope').value,xy_scale:withdraw?null:{x:Number($('scale-x').value),y:Number($('scale-y').value),unit:$('unit').value},source_text:$('source').value});$('calibrate').onclick=guarded(()=>calibrate(false));$('withdraw').onclick=guarded(()=>calibrate(true));
$('submit-observation').onclick=guarded(()=>act('research-observation',{source_text:$('observation-text').value,authority:$('observation-authority').value}));
const revisionKey=value=>JSON.stringify([value.state_revision,value.object_id??value.object?.object_id,value.pending_result?.object_id,value.pending_result?.request_id]);
function setMode(mode){$('mode').value=mode;for(const button of document.querySelectorAll('[data-mode]'))button.setAttribute('aria-pressed',String(button.dataset.mode===mode));}
for(const button of document.querySelectorAll('[data-mode]'))button.onclick=()=>setMode(button.dataset.mode);
$('toggle-properties').onclick=()=>document.body.classList.toggle('properties-open');$('close-properties').onclick=()=>document.body.classList.remove('properties-open');
$('toggle-settings').onclick=()=>{document.body.classList.add('properties-open');$('settings-panel').open=true;};
$('frame').onkeydown=event=>{if(event.key==='Enter')$('set-frame').onclick();};
async function pollRevision(){
 try{if(state&&!document.hidden&&!busy&&!drag){const next=await api('/api/revision');if(revisionKey(next)!==revisionKey(state))await refresh();}}
 catch{/* A closed panel is not restarted and no scientific operation is retried. */}
 finally{if(typeof setTimeout==='function')setTimeout(pollRevision,1500);}
}
globalThis.addEventListener?.('beforeunload',event=>{if(dirty()||drag){event.preventDefault();event.returnValue='';}});
refresh().then(()=>{if(image)fitView();message(orphanedDraft?'检测到先前未保存的草稿记录；请明确撤回草稿后继续。':'滚轮缩放 · 空格拖动 · 移动标注松手即保存');if(typeof setTimeout==='function')setTimeout(pollRevision,1500);}).catch(e=>message(e.message,true));
