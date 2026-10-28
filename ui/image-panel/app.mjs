import {selectionFromDrag,selectionRectangle,transformCoordinates,panelAt,coordinateSpace,constrainSelectionDrag} from './coordinates.mjs';
import {zoomAt,panBy,hitMark,DraftHistory,internalMarkId,relatedViewport,equalRecords} from './viewer-state.mjs';
import {tonePixels,drawMark} from './viewer-render.mjs';
import {layoutAnnotations,renderAnnotationsSVG} from './annotation-presentation.mjs';
import {buildFigureBundle,downloadBlob,makeFigureRecipe,readFigureRecipe,figureScaleBar} from './figure-export.mjs';
import {MeasurementWorkspace,requiresMeasurementJump} from './measurement-workspace.mjs';
import {DataProbes} from './data-probes.mjs';
import {UserActionHistory,SavedViewHistory,workflowScope,selectionActionReason,measurementLabel} from './user-workflow.mjs';
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d'),baseCanvas=$('base-canvas'),baseContext=baseCanvas.getContext('2d',{willReadFrequently:true}),marksCanvas=$('marks-canvas'),marksContext=marksCanvas.getContext('2d'),stage=$('image-stage'),viewport=$('viewport');
const key='mcp-dm-panel-token',hash=location.hash.slice(1);if(hash){sessionStorage.setItem(key,hash);history.replaceState(null,'',location.pathname);}const token=sessionStorage.getItem(key);
let state,image,basePixels,draft=null,drag=null,editCoordinates=null,busy=false,cleanBase=false,selectedId='',spaceDown=false,pending=null,orphanedDraft=false;
let view={scale:1,x:0,y:0},toneCacheKey=null,paintFrame=null,marksDirty=true,loading=0,fieldDirty=false,displayBaseline='',draftPublisher=Promise.resolve();
let draftPending=null,draftSending=false,draftError=null,autoFailed=false,autoSequence=0,autoTimer=null,fieldBefore=null,autoSaving=null,measuredMarkId='';
let labelDraft=null,annotationLayout=null,hoverId='';
let labelTimer=null;
let figurePrefs={preset:'real-space',mode:'analysis',layers:{experimental:true,simulation_A:false,simulation_B:false},columns:'single',fontPt:8,legend:true,scaleBar:true,letter:''};
const queuedEdits=new Map(),userHistory=new UserActionHistory(),savedViews=new SavedViewHistory();
let lastUserDisplay=null;
const geometryRevisions=new Map(),remeasuringMarks=new Map();let failedMeasurement=null;
const historyDraft=new DraftHistory({}),perf={frames:0,tone_count:0,overlay_count:0,tone_last_ms:0,overlay_last_ms:0,draw_last_ms:0,action_last_ms:0};
const now=()=>performance.now(),message=(text,error=false)=>{$('message').textContent=text;$('message').classList.toggle('error',error);};
const measurementWorkspace=new MeasurementWorkspace({getState:()=>state,api,onSelect:selectMeasurement,onJump:jumpMeasurement,onUpdate:updateMeasurement,onError:e=>message('结果读取未完成：'+e.message,true)});
const dataProbes=new DataProbes({getState:dataProbeState,api,onError:e=>message('原数组读取未完成：'+e.message,true)});
function dataProbeState(){const current=measurementWorkspace.current;return state&&current?.object_id===state.object.object_id?{...state,object:{...state.object,scientific_grid_identity:current.scientific_grid_identity,dtype:current.dtype,xy_calibration:current.xy_calibration}}:state;}
async function refreshMeasurements(){const ok=await measurementWorkspace.refresh();if(ok){renderMeasurement();dataProbes.refreshCurrent();dataProbes.restoreSavedResults(state.numeric_results??{});if(['statistics','profile'].includes(state.last_operation?.kind))dataProbes.renderResult(state.last_operation);}return ok;}
function selectMeasurement(entry){
 if(!entry)return;
 if(requiresMeasurementJump(entry)){message('这条结果属于另一帧、视野外或旧版峰位；请点“跳到结果原视图”明确查看。');return;}
 const mark=state.object.annotations?.find(value=>value.annotation_id===entry.annotation_id);
 if(mark){chooseMark(mark.annotation_id);const panel=markPanel(mark);draft={kind:mark.kind,...mark.anchor,panel,rendered:transformCoordinates(mark.anchor.coordinates,panel,{inverse:true})};}
 else{message('当前视图没有这条结果的保存标记；可显式跳到其原视图。');return;}
 measurementWorkspace.select(entry.object_id,{notify:false});marksDirty=true;showDraft();schedulePaint();
}
async function jumpMeasurement(entry){if(!entry)return;const r=await act('measurement-jump',{measurement_object_id:entry.object_id});if(r)measurementWorkspace.select(entry.object_id);}
async function updateMeasurement(entry){
 if(!entry)return;if(!entry.same_grid||!entry.visible_in_current_view)throw new Error('先显式跳到结果原视图，再更新该测量');
 const mark=state.object.annotations?.find(value=>value.annotation_id===entry.annotation_id);
 if(!mark)throw new Error('当前视图缺少原标记，请先跳到结果原视图');
 const panel=markPanel(mark);return act('measure',{selection:{...mark.anchor,kind:mark.kind,panel},annotation_id:mark.annotation_id,measurement_object_id:entry.object_id});
}
const displayDraft=()=>({gamma:Number($('gamma').value),low:$('low').value,high:$('high').value,axes:$('axes').checked,scale:$('scale').checked});
const dirty=()=>Boolean(orphanedDraft||queuedEdits.size||editCoordinates||labelDraft||fieldDirty||remeasuringMarks.size||failedMeasurement||JSON.stringify(displayDraft())!==displayBaseline);
function diagnostics(){
 const status=autoFailed?'保存失败 · 草稿保留':busy?'正在保存':queuedEdits.size?'等待保存':dirty()?'本地草稿':draft?'选择已就绪':'已保存 · 原图只读';
 $('performance-data').textContent=JSON.stringify({...perf,dirty:dirty(),gesture_active:Boolean(drag),draft_revision:historyDraft.revision,object_id:state?.object.object_id,scale:view.scale,busy,queued_edits:queuedEdits.size});$('draft-status').textContent=status;$('autosave-status').textContent=status;
 const undo=userHistory.peek('undo'),redo=userHistory.peek('redo');
 $('undo').disabled=!undo&&!labelDraft&&!fieldDirty;$('redo').disabled=!redo;
 $('undo').title=undo?'撤销：'+undo.label:'没有可撤销操作';$('redo').title=redo?'恢复：'+redo.label:'没有可恢复操作';
 for(const [id,action]of [['apply-roi','roi'],['fft','fft'],['measure','measure'],['share','select'],['full','full'],['roi-statistics','statistics'],['line-profile','profile']]){
  const button=$(id);if(!button)continue;if(id==='roi-statistics')button.hidden=draft?.kind!=='rectangle';if(id==='line-profile')button.hidden=!['line','arrow'].includes(draft?.kind);const reason=selectionActionReason(action,draft,state?.object??{});button.disabled=Boolean(reason)||busy||Boolean(drag);button.title=reason||({roi:'查看选定区域',fft:'计算当前实空间 ROI 的 FFT',measure:'保存测量结果',select:'可选：把当前选择交给 Agent',full:'仅恢复完整频谱，不返回原图',statistics:'读取保存科学数组的 ROI 统计',profile:'读取当前线的原数组剖面'})[action];
 }
 for(const [id,target]of [['view-back',savedViews.target(-1)],['view-forward',savedViews.target(1)],['view-original',savedViews.original(state)]])if($(id))$(id).disabled=!target||busy||Boolean(drag)||target.id===state?.object?.object_id;
 const sourceTarget=savedViews.original(state);$('view-original').textContent=sourceTarget?.freshSourceView?'全帧（新显示）':'原图';$('view-original').title=sourceTarget?.freshSourceView?'没有已保存的原图显示配方；使用当前标定新建全帧预览，不重算 FFT':'打开本帧已保存的原图视图';
 if($('view-current'))$('view-current').textContent=savedViews.entries[savedViews.index]?.role??'当前视图';
}
function setResultsTab(tab,{expand=true}={}){
 if(!['measurements','statistics','profile'].includes(tab))return;
 for(const name of ['measurements','statistics','profile']){const button=$('results-tab-'+name),panel=$('results-'+name);if(button){button.setAttribute('aria-selected',String(name===tab));button.tabIndex=name===tab?0:-1;}if(panel)panel.hidden=name!==tab;}
 if($('numeric-data'))$('numeric-data').open=tab!=='measurements';
 if(expand&&$('measurement-workspace'))$('measurement-workspace').open=true;
}
function rememberSelection(before,after){userHistory.push({kind:'selection',label:'更改选区',scope:workflowScope(state),before,after});}
function setDisplayDraft(value){$('gamma').value=value.gamma;$('low').value=value.low;$('high').value=value.high;$('axes').checked=value.axes;$('scale').checked=value.scale;$('gamma-label').textContent=String(value.gamma);lastUserDisplay=displayDraft();}
function recordDisplayInput(id){
 commitLabelDraft();captureSelected();const before=lastUserDisplay??JSON.parse(displayBaseline),after=displayDraft();
 userHistory.push({kind:'display',label:id==='gamma'?'调整 Gamma':id==='low'||id==='high'?'调整显示范围':'调整显示辅助',scope:workflowScope(state),before,after},{group:'display:'+id});lastUserDisplay=after;
}
function applyUserHistory(direction){
 if(drag||autoFailed){message('先结束手势或恢复未确认的原请求，再撤销。',true);return;}
 commitLabelDraft();captureSelected();userHistory.endGroup();const item=userHistory.peek(direction);if(!item)return;
 if(item.scope!==workflowScope(state)){message('此操作属于另一科学视图；未修改当前数据。',true);return;}
 const undo=direction==='undo',value=undo?item.before:item.after,expected=undo?item.after:item.before;
 if(item.kind==='annotation'){
  const current=effectiveEdit(value.annotation_id);if(!current||Object.entries(expected).some(([k,v])=>k!=='annotation_id'&&!equalRecords(current[k],v))){message('标记已被后续操作修改；没有用旧操作覆盖它。',true);return;}
  queueEdit(value,null,{undo:false});
 }else if(item.kind==='display'){setDisplayDraft(value);record();schedulePaint();publishDraft({urgent:true});}
 else if(item.kind==='selection'){
  const restored=value?.draft?restoredSelection(value.draft,state.object.panels??[]):null;
  if(value?.draft&&!restored){message('选区不属于当前科学网格；未恢复旧坐标。',true);return;}
  selectedId=(state.object.annotations??[]).some(m=>m.annotation_id===value?.selectedId)?value.selectedId:'';syncMarkFields(false);draft=restored;record();showDraft();schedulePaint();publishDraft({includeSelection:true,urgent:true});
 }
 userHistory.finish(direction,item);diagnostics();message((undo?'已撤销：':'已恢复：')+item.label+(item.kind==='annotation'?'；保存补偿版本，历史记录保留。':item.kind==='display'?'；当前为显示草稿，保存显示后可导出。':''));
}
async function navigateSavedView(target){
 if(!target)return;if(dirty()||busy||drag){message('先保存或撤销草稿，再切换保存视图。',true);return;}
 await act('show',{object_id:target.id,...(target.freshSourceView?{source_view:true}:{})});
}
async function api(url,body){const response=await fetch(url,{method:body?'POST':'GET',headers:{'X-Panel-Token':token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});const result=await response.json();if(!response.ok)throw new Error(result.error??'本地服务失败');return result;}
function selection(){if(!draft)throw new Error('先在图中选择位置或区域');const {rendered,...s}=draft;return s;}
function annotationEditDraft(){
 if(selectedId&&labelDraft)return {annotation_id:selectedId,presentation:labelDraft};
 if(selectedId&&queuedEdits.has(selectedId)&&!editCoordinates&&!fieldDirty){const {note,presentation_replace,...edit}=queuedEdits.get(selectedId).update;return edit;}
 if(!selectedId||!editCoordinates&&!fieldDirty){
  const prior=orphanedDraft?state.edit_state?.annotation_edit:null;
  return prior?Object.fromEntries(['annotation_id','coordinates','text','color','status'].filter(k=>prior[k]!==undefined).map(k=>[k,prior[k]])):null;
 }
 return {annotation_id:selectedId,...(editCoordinates?{coordinates:[...editCoordinates]}:{}),...(fieldDirty?{text:$('mark-text').value,color:$('color').value,status:$('status').value}:{})};
}
function publishDraft({gesture_active=Boolean(drag),includeSelection=false,urgent=false}={}){
 if(!state)return Promise.resolve();const object_id=state.object.object_id,params={draft_revision:historyDraft.revision,dirty:dirty()||gesture_active,gesture_active,annotation_edit:annotationEditDraft(),...(includeSelection?{selection:draft?selection():null}:{})};
 draftPending={expected_object_id:object_id,action:'draft',lightweight:true,params,urgent:urgent||gesture_active};
 if(!draftSending){draftSending=true;draftPublisher=(async()=>{try{while(draftPending){if(!draftPending.urgent&&typeof setTimeout==='function')await new Promise(r=>setTimeout(r,70));const body=draftPending;draftPending=null;delete body.urgent;try{await api('/api/action',body);draftError=null;}catch(e){draftError=e;message('草稿交接未确认：'+e.message,true);}}}finally{draftSending=false;}})();}
 return draftPublisher;
}
function effectiveEdit(id){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===id);if(!mark?.anchor)return null;return {annotation_id:id,coordinates:[...mark.anchor.coordinates],text:mark.text??'',color:mark.color,status:mark.status,presentation:JSON.parse(JSON.stringify(mark.presentation??{})),...(queuedEdits.get(id)?.update??{})};}
function queueEdit(update,before=null,{undo=true}={}){
 const prior=before??effectiveEdit(update.annotation_id);if(!prior)return;
 const after={...effectiveEdit(update.annotation_id),...update},changedGeometry=JSON.stringify(prior.coordinates)!==JSON.stringify(after.coordinates),numericLabel=queuedEdits.get(update.annotation_id)?.numericLabel??(changedGeometry&&prior.presentation?.label?.measurement_object_id?remeasuringMarks.get(update.annotation_id)?.numericLabel??prior.presentation.label:null);
 if(update.presentation&&!equalRecords(prior.presentation,after.presentation))after.presentation_replace=true;
 if(changedGeometry&&numericLabel)after.presentation={...after.presentation,label:{...after.presentation.label,visible:false}};
 if(JSON.stringify(prior)===JSON.stringify(after)){if(queuedEdits.has(update.annotation_id))Promise.resolve().then(flushEdits);return;}
 if(undo){const keys=Object.keys(update).filter(k=>!['annotation_id','presentation_replace','note'].includes(k)&&!equalRecords(prior[k],update[k]));if(keys.length){const project=value=>({annotation_id:update.annotation_id,...Object.fromEntries(keys.map(k=>[k,value[k]]))});userHistory.push({kind:'annotation',label:changedGeometry?'移动科学标记':'调整标注',scope:workflowScope(state),before:project(prior),after:project(after)});}}
 if(changedGeometry)geometryRevisions.set(update.annotation_id,(geometryRevisions.get(update.annotation_id)??0)+1);
 queuedEdits.set(update.annotation_id,{update:after,sequence:++autoSequence,geometryRevision:geometryRevisions.get(update.annotation_id)??0,geometryChanged:queuedEdits.get(update.annotation_id)?.geometryChanged||changedGeometry,numericLabel});marksDirty=true;record();schedulePaint();publishDraft({urgent:true});Promise.resolve().then(flushEdits);
}
function captureSelected(){if(!selectedId||!editCoordinates&&!fieldDirty)return false;const before=fieldBefore??effectiveEdit(selectedId),update={annotation_id:selectedId,text:$('mark-text').value,color:$('color').value,status:$('status').value,...(editCoordinates?{coordinates:[...editCoordinates]}:{})};editCoordinates=null;fieldDirty=false;fieldBefore=null;queueEdit(update,before);return true;}
function flushEdits(){
 if(autoSaving)return autoSaving;
 if(busy||drag||autoFailed||!queuedEdits.size)return Promise.resolve();
 autoSaving=saveFirstEdit().finally(()=>{autoSaving=null;if(!autoFailed&&queuedEdits.size&&!drag)Promise.resolve().then(flushEdits);});return autoSaving;
}
function editWire(id,sent){const saved=(state.object.annotations??[]).find(m=>m.annotation_id===id),wire={annotation_id:id};for(const [field,value]of Object.entries(sent.update)){if(field==='annotation_id')continue;const old=field==='coordinates'?saved.anchor.coordinates:field==='presentation'?saved.presentation??{}:saved[field]??(field==='text'?'':undefined);if(!equalRecords(value,old))wire[field]=value;}if(wire.presentation_replace)wire.presentation=sent.update.presentation;return wire;}
async function saveFirstEdit(){
 const [id,sent]=queuedEdits.entries().next().value,submittedObject=state.object.object_id;let measurementTarget=null;busy=true;diagnostics();
 try{
  await publishDraft({urgent:true});if(draftError)throw draftError;
  const wire=editWire(id,sent),layoutOnly=w=>Object.keys(w).every(k=>['annotation_id','presentation','presentation_replace'].includes(k)),batch=layoutOnly(wire)?[...queuedEdits].filter(([key,value])=>layoutOnly(editWire(key,value))).slice(0,100):[[id,sent]];
  if(Object.keys(wire).length===1){if(queuedEdits.get(id)===sent)queuedEdits.delete(id);return;}
  const updates=batch.map(([key,value])=>editWire(key,value)).filter(w=>Object.keys(w).length>1);
  const r=await api('/api/action',{expected_object_id:submittedObject,draft_revision:historyDraft.revision,action:batch.length>1?'edit-layout':'edit',params:{updates,auto_commit:true}});
  if(!r.auto_edit_committed)throw new Error('未能安全接续自动保存；草稿保留，请查询原请求');
  for(const [key,value]of batch)if(queuedEdits.get(key)===value){queuedEdits.delete(key);if(selectedId===key&&!drag&&!fieldDirty&&JSON.stringify(editCoordinates)===JSON.stringify(value.update.coordinates))editCoordinates=null;}
  // Annotation-only adoption uses identical provider panel mappings. Keep the
  // current gesture/camera/local edits; no decode or full bitmap work here.
 state=r;savedViews.remember(state,{replace:true});for(const [key]of batch){const saved=state.object.annotations.find(m=>m.annotation_id===key),option=[...($('existing').options??$('existing').children)].find(o=>o.value===key);if(option)option.textContent=`${saved.text??''} · ${{hypothesized:'候选',user_confirmed:'用户确认',retracted:'撤回'}[saved.status]??''}`;}if(batch.some(([key])=>key===selectedId)&&!drag&&!fieldDirty&&!labelDraft){const mark=state.object.annotations.find(m=>m.annotation_id===selectedId);$('mark-text').value=mark.text??'';const option=$('existing').selectedOptions?.[0];if(option)option.textContent=`${mark.text??''} · ${{hypothesized:'候选',user_confirmed:'用户确认',retracted:'撤回'}[mark.status]??''}`;syncPresentationFields();}marksDirty=true;showDraft();showPending();schedulePaint();message(sent.geometryChanged?'科学锚点已修订；旧版本保留。':'标签／样式已保存；科学锚点未改变。');
  if(wire.coordinates!==undefined&&(measurementWorkspace.hasAnnotation(id)||measuredMarkId===id||sent.numericLabel)){const mark=r.object.annotations.find(m=>m.annotation_id===id),panels=r.object.panels.filter(p=>p.source_object_id===mark.anchor.source_object_id&&coordinateSpace(p)===mark.anchor.coordinate_space);if(panels.length===1)measurementTarget={previousMeasurement:measurementWorkspace.latestForAnnotation(id)?.object_id,id,submittedObject,savedObject:r.object.object_id,sequence:sent.sequence,geometryRevision:sent.geometryRevision,anchor:JSON.parse(JSON.stringify(mark.anchor)),kind:mark.kind,status:mark.status,panel:JSON.parse(JSON.stringify(panels[0])),calibration:r.object.xy_calibration??null,numericLabel:sent.numericLabel};}
 }catch(e){autoFailed=true;message('自动保存失败，编辑仍保留。请查询原请求，勿重复提交：'+e.message,true);}
 finally{busy=false;diagnostics();await publishDraft({includeSelection:true,urgent:true});if(!autoFailed&&measurementTarget)await remeasureSavedEdit(measurementTarget);}
}
function currentMeasurementTarget(target){const latest=effectiveEdit(target.id),mark=state.object.annotations.find(m=>m.annotation_id===target.id);return Boolean(latest&&mark?.status===target.status&&(geometryRevisions.get(target.id)??0)===target.geometryRevision&&equalRecords(latest.coordinates,target.anchor.coordinates)&&equalRecords(state.object.xy_calibration??null,target.calibration)&&state.object.panels.some(p=>equalRecords(p,target.panel))&&!(selectedId===target.id&&editCoordinates&&!equalRecords(editCoordinates,target.anchor.coordinates))&&(!target.numericLabel||latest.presentation.label?.measurement_object_id===target.numericLabel.measurement_object_id));}
function applyBoundMeasurement(target,m){
 if(!currentMeasurementTarget(target))return false;
 const points=target.kind==='point'?m?.points?.[1]:m?.points?.flat();
 if(!m?.object_id||m.kind!=='measure'||m.coordinate_space!==target.anchor.coordinate_space||!equalRecords(points,target.anchor.coordinates))throw new Error('测量返回的科学锚点与已保存标注不一致；旧标签保持隐藏');
 state={...state,last_operation:{...m,annotation_id:target.id}};renderMeasurement();
 if(target.numericLabel){const period=target.numericLabel.measurement_kind==='period',value=period?m.d_spacing:m.physical_distance,unit=period?m.d_spacing_unit:m.physical_unit;if(Number.isFinite(value)&&typeof unit==='string'&&unit){const label=`d = ${Number(value.toPrecision(4))} ${unit}`,p=effectiveEdit(target.id).presentation;queueEdit({annotation_id:target.id,text:label,note:`Measured by image_measure record ${m.object_id}`,presentation:{...p,label:{...p.label,text:label,visible:target.numericLabel.visible!==false,measurement_object_id:m.object_id,measurement_kind:period?'period':'distance'}}},null,{undo:false});}else message('锚点已更新；新测量没有可信物理单位，旧数值标签保持隐藏。',true);}
 return true;
}
async function remeasureSavedEdit(target){
 if(!currentMeasurementTarget(target))return;
 const boundSelection={...target.anchor,kind:target.kind,panel:target.panel};busy=true;remeasuringMarks.set(target.id,target);schedulePaint();diagnostics();
 try{await publishDraft({urgent:true});if(draftError)throw draftError;const r=await api('/api/action',{expected_object_id:target.savedObject,draft_revision:historyDraft.revision,action:'measure',params:{selection:boundSelection,annotation_id:target.id,...(target.previousMeasurement?{measurement_object_id:target.previousMeasurement}:{})}});if(r.object.object_id!==target.savedObject){pending=r;showPending();return;}applyBoundMeasurement(target,r.last_operation);remeasuringMarks.delete(target.id);}
 catch(e){failedMeasurement={...target,request_id:e.message.match(/Original request_id=([A-Za-z0-9_-]{1,64})/)?.[1]??null};autoFailed=true;message('重新测量未确认；锚点与草稿保留。请查询原请求，勿重复提交：'+e.message,true);}
 finally{busy=false;marksDirty=true;schedulePaint();diagnostics();await refreshMeasurements();if(selectedId===target.id&&currentMeasurementTarget(target))measurementWorkspace.selectAnnotation(target.id);await publishDraft({includeSelection:true,urgent:true});}
}
function autoFields(){if(!selectedId)return;if(autoTimer!==null&&typeof clearTimeout==='function')clearTimeout(autoTimer);if(typeof setTimeout==='function')autoTimer=setTimeout(()=>{autoTimer=null;captureSelected();},350);}
function snapshot(){return {draft,editCoordinates,labelDraft,selectedId,fieldDirty,display:displayDraft(),fields:{id:$('mark-id').value,text:$('mark-text').value,color:$('color').value,status:$('status').value}};}
function record(){historyDraft.replace(snapshot());diagnostics();}
function restoreSnapshot(value){draft=value.draft??null;editCoordinates=value.editCoordinates??null;labelDraft=value.labelDraft??null;selectedId=value.selectedId??'';fieldDirty=value.fieldDirty??false;$('existing').value=selectedId;if(value.display){$('gamma').value=value.display.gamma;$('low').value=value.display.low;$('high').value=value.display.high;$('axes').checked=value.display.axes;$('scale').checked=value.display.scale;$('gamma-label').textContent=$('gamma').value;}if(value.fields)for(const [id,field]of [['mark-id','id'],['mark-text','text'],['color','color'],['status','status']])$(id).value=value.fields[field];syncPresentationFields();marksDirty=true;showDraft();schedulePaint();publishDraft({includeSelection:true});}
function schedulePaint(){if(paintFrame===null)paintFrame=requestAnimationFrame(()=>{paintFrame=null;paint();});}
function restoredSelection(value,panels){if(!value)return null;const panel=panels.find(p=>p.source_object_id===value.source_object_id&&coordinateSpace(p)===value.coordinate_space&&equalRecords(p,value.panel));if(!panel)return null;try{return {...value,panel,rendered:transformCoordinates(value.coordinates,panel,{edges:['rectangle','polygon'].includes(value.kind),inverse:true})};}catch{return null;}}
function markPanel(mark){const matches=(state.object.panels??[]).filter(p=>p.source_object_id===mark.anchor?.source_object_id&&coordinateSpace(p)===mark.anchor.coordinate_space);if(matches.length!==1)throw new Error('标注面板映射不唯一；请在明确的单一视图中编辑');return matches[0];}
function showPending(){$('pending-result').hidden=!pending&&!state?.pending_result;$('pending-message').textContent='有新结果等待查看。查看会切换到该结果的保存版本，当前已保存版本仍保留；请先保存、撤销或明确放弃未保存草稿。';}
async function act(action,params={}){
 if(['frame','roi','fft','export','preview','select'].includes(action)&&selectedId&&(editCoordinates||fieldDirty))captureSelected();
 if(busy){message('上一项保存仍在等待；可继续观察、缩放和平移。');return;}if(pending&&!['research-observation','accept-result','recover'].includes(action)){message('请先处理待查看结果；当前草稿仍保留。',true);return;}
 if(dirty()&&['frame','roi','fft','calibrate','accept-result','show','measurement-jump'].includes(action)){message('先保存或撤销当前草稿，再切换科学视图；缩放、平移和选择仍可继续。',true);return;}
 const sentRevision=historyDraft.revision,start=now(),local=snapshot(),keepDisplay=dirty()&&['edit','mark'].includes(action)&&JSON.stringify(displayDraft())!==displayBaseline,keepMark=action==='preview'&&(editCoordinates||fieldDirty);busy=true;diagnostics();
 try{await draftPublisher;const r=await api('/api/action',{expected_object_id:state.object.object_id,draft_revision:sentRevision,action,params});
  if(action==='recover'&&failedMeasurement){const target=failedMeasurement,m=r.last_operation;if(m?.kind!=='measure'||target.request_id&&m.request_id!==target.request_id)throw new Error('原测量请求仍未确认；保留隐藏标签与本地草稿');applyBoundMeasurement(target,m);failedMeasurement=null;remeasuringMarks.delete(target.id);autoFailed=false;message('原测量请求已核对；仅接续仍有效的标注版本。');return r;}
  if(action==='research-observation'||action==='recover'&&r.last_operation?.action==='research-observation'){
   state={...state,research_observation:r.research_observation,last_operation:r.last_operation,state_revision:r.state_revision};renderMeasurement();renderObservation();
   message('观察已保存；当前图、选区与未保存草稿保持原样。对 Agent 说“继续”以修订解释。');return r;
  }
  if(r.pending_result&&r.object.object_id===state.object.object_id){state={...state,pending_result:r.pending_result,state_revision:r.state_revision};showPending();message('计算完成；新结果等待查看，期间的新草稿保持原样。');return r;}
  if(historyDraft.revision!==sentRevision||drag){pending=r;showPending();message('保存完成；较新的草稿保持原样，结果等待接续。');return r;}
  if(r.object.object_id===state.object.object_id&&['select','measure','export','statistics','profile'].includes(action)){state={...state,last_operation:r.last_operation,selection:r.selection,state_revision:r.state_revision};renderMeasurement();if(['statistics','profile'].includes(action))dataProbes.renderResult(r.last_operation);}
  else await load(r,{keepDisplay:keepDisplay?local.display:null,keepMark:keepMark?local:null,role:action==='roi'?'ROI':action==='fft'?'FFT':action==='frame'?'原图':action==='show'&&params.source_view?'全帧（新显示）':null});
  if(['measure','statistics','profile'].includes(action))setResultsTab(action==='measure'?'measurements':action);
  message(action==='show'&&params.source_view?'已按当前标定新建全帧显示；未恢复未知的旧显示配方，未重算 FFT。':action==='export'?`科学数据已保存到 ${r.last_operation?.output_dir??'工作区 exports 目录'}（不是浏览器图片下载）`:({select:'选择已交接；可继续使用当前选区。',measure:'测量完成；当前选区已保留。',show:'已打开保存视图；未重算 FFT。'})[action]??'已保存新版本；原像素与旧版本保留。');return r;
 }catch(e){message(e.message,true);}finally{busy=false;perf.action_last_ms=now()-start;diagnostics();await refreshMeasurements();if(queuedEdits.size)Promise.resolve().then(flushEdits);}
}
async function refresh(){const next=await api('/api/state');if(state&&(dirty()||drag)){if(next.object.object_id!==state.object.object_id)pending=next;else state={...state,pending_result:next.pending_result,state_revision:next.state_revision,research_observation:next.research_observation};renderObservation();showPending();message('已检查最新状态；本地草稿保持原样。');return;}if(next.pending_result&&state){state.pending_result=next.pending_result;state.research_observation=next.research_observation;renderObservation();showPending();return;}await load(next);}
function renderObservation(){
 const observation=state.research_observation;
 $('research-feedback').hidden=!state.tools.some(t=>t.name==='image_context');
 $('observation-summary').textContent=observation?`${observation.authority==='synthetic_fixture'?'合成演示（非真人确认）':'研究者声明'}：${observation.source_text} · 确认范围仅为存在孪晶；具体孪晶关系、取向和 HKL 仍待检验。${observation.current_view_relation==='different_saved_view_review_scope'?' 当前视图已变化；Agent 必须复核原观察绑定的图像范围。':''}`:'尚未提交孪晶观察。';
}
function humanCalibration(o){const c=o.xy_calibration??o.calibration_record??o.calibration;if(!c)return 'XY 物理标尺未知；像素域操作可继续';const xy=c.xy_scale??c;return xy.x!==undefined?`XY：${xy.x} / ${xy.y} ${xy.unit??''}/px · ${c.status??c.source_type??'版本化标定'}`:'XY：已保留标定记录；详情见高级信息';}
function renderMeasurement(){const last=state.last_operation,entry=selectedId?measurementWorkspace.latestForAnnotation(selectedId):null,m=entry??(last?.annotation_id&&selectedId&&last.annotation_id!==selectedId?null:last);$('operation').textContent=last?JSON.stringify(last,null,2):'';const finite=value=>typeof value==='number'&&Number.isFinite(value);
 $('measurement-summary').textContent=finite(m?.physical_distance)?`距离 ${m.physical_distance} ${m.physical_unit??''}`:
 finite(m?.distance_physical)?`距离 ${m.distance_physical} ${m.physical_unit??''}`:
 finite(m?.d_spacing)?`晶面间距（几何） ${m.d_spacing} ${m.d_spacing_unit??''}`:
 finite(m?.period)?`倒空间差向量周期 ${m.period} ${m.period_unit??''}`:
 finite(m?.distance_pixels)?`图像坐标距离 ${m.distance_pixels} px`:
 finite(m?.frequency_distance_cycles_per_pixel)?`频率差 ${m.frequency_distance_cycles_per_pixel} cycles/pixel`:
 '选线段或已知中心的倒空间峰后可测量；候选标记不等于物相确认';if(entry&&entry.status!=='current')$('measurement-summary').textContent='旧版数值（待重测或历史）：'+$('measurement-summary').textContent;}
async function load(next,{keepDisplay=null,keepMark=null,role=null}={}){
 const priorScope=state?workflowScope(state):null;
 const ticket=++loading,revision=historyDraft.revision,sameObject=state?.object.object_id===next.object.object_id,rect=viewport.getBoundingClientRect(),continued=relatedViewport(view,state,next,[rect.width,rect.height]),savedSelection=(sameObject||continued)&&draft?draft:next.selection;let decoded=null;
 if(next.clean_png_base64||next.png_base64){decoded=new Image();decoded.src='data:image/png;base64,'+(next.clean_png_base64??next.png_base64);await decoded.decode();if(ticket!==loading)return;if(state&&(historyDraft.revision!==revision||drag)){pending=next;showPending();return;}}
 if(!state&&next.edit_state?.dirty)orphanedDraft=true;
 state=next;draft=restoredSelection(savedSelection,next.object.panels??[]);drag=null;editCoordinates=null;labelDraft=null;fieldDirty=false;toneCacheKey=null;marksDirty=true;const o=state.object,previous=selectedId;
 if(!sameObject&&!continued){figurePrefs.preset=o.annotations?.some(m=>['A','B','shared','unexplained'].includes(m.presentation?.category))?'multi-domain':o.panels?.some(p=>p.domain==='frequency')?'diffraction':'real-space';figurePrefs.legend=figurePrefs.preset!=='real-space';figurePrefs.layers={experimental:true,simulation_A:figurePrefs.preset!=='real-space',simulation_B:figurePrefs.preset!=='real-space'};}syncFigureControls();
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
 syncMarkFields(false);void refreshMeasurements();
 if(keepDisplay){$('gamma').value=keepDisplay.gamma;$('low').value=keepDisplay.low;$('high').value=keepDisplay.high;$('axes').checked=keepDisplay.axes;$('scale').checked=keepDisplay.scale;$('gamma-label').textContent=$('gamma').value;}
 if(keepMark){selectedId=keepMark.selectedId;editCoordinates=keepMark.editCoordinates;fieldDirty=keepMark.fieldDirty;$('existing').value=selectedId;for(const [id,field]of [['mark-id','id'],['mark-text','text'],['color','color'],['status','status']])$(id).value=keepMark.fields[field];}
 // A reconnect must continue the shared monotonically increasing lease; a
 // fresh browser's local counter must never erase a newer panel draft.
 historyDraft.revision=Math.max(historyDraft.revision,state.edit_state?.draft_revision??0);
 historyDraft.reset(snapshot());lastUserDisplay=displayDraft();if(priorScope!==workflowScope(state))userHistory.reset();savedViews.remember(state,{replace:Boolean(continued),role});showDraft();paint();showPending();await publishDraft({includeSelection:true});
}
function resize(){stage.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;$('zoom').value=view.scale;$('zoom-label').textContent=Math.round(view.scale*100)+'%';schedulePaint();}
function fitView(){const r=viewport.getBoundingClientRect(),scale=Math.max(.1,Math.min(2,(r.width-48)/canvas.width,(r.height-48)/canvas.height));view={scale,x:(r.width-canvas.width*scale)/2,y:(r.height-canvas.height*scale)/2};resize();}
function renderedMarks(){return (state?.object.annotations??[]).map(original=>{const queued=queuedEdits.get(original.annotation_id)?.update,mark={...original,...(queued??{}),...(original.annotation_id===selectedId&&labelDraft?{presentation:labelDraft}:{})};if(!mark.anchor)return mark;let p;try{p=markPanel(mark);}catch{return {...mark,visibility:'outside_view'};}const edges=['rectangle','polygon'].includes(mark.kind),coords=mark.annotation_id===selectedId&&editCoordinates?editCoordinates:queued?.coordinates??mark.anchor.coordinates,changed=mark.annotation_id===selectedId&&fieldDirty;return {...mark,coordinates:transformCoordinates(coords,p,{edges,inverse:true}),...(queued||mark.annotation_id===selectedId&&editCoordinates?{arrow_render_coordinates:undefined}:{}),...(changed?{text:$('mark-text').value,color:$('color').value,status:$('status').value}:{})};});}
function paint(){
 if(paintFrame!==null){cancelAnimationFrame(paintFrame);paintFrame=null;}if(!basePixels){diagnostics();return;}const start=now(),display=state.effective_display??state.object.display??{},oldGamma=display.gamma??1,gamma=Number($('gamma').value),range=display.display_range,low=$('low').value===''?NaN:Number($('low').value),high=$('high').value===''?NaN:Number($('high').value),cache=JSON.stringify([state.render_base_id,oldGamma,gamma,range,low,high]);
 if(cache!==toneCacheKey){const t=now(),pixels=tonePixels(basePixels.data,{oldGamma,gamma,range,low,high});baseContext.putImageData(new ImageData(pixels,basePixels.width,basePixels.height),0,0);toneCacheKey=cache;perf.tone_last_ms=now()-t;perf.tone_count++;}
 const overlayStart=now(),marks=renderedMarks().map(m=>(remeasuringMarks.has(m.annotation_id)||m.annotation_id===selectedId&&editCoordinates)&&m.presentation?.label?.measurement_object_id?{...m,presentation:{...m.presentation,label:{...m.presentation.label,visible:false}}}:m);if(marksDirty){marksContext.clearRect(0,0,canvas.width,canvas.height);marksDirty=false;}
 annotationLayout=layoutAnnotations(marks,{...figurePrefs,width:canvas.width,height:canvas.height,scale:view.scale,selectedId,hoverId});
 $('annotation-layer').innerHTML=cleanBase?renderAnnotationsSVG(annotationLayout,{width:canvas.width,height:canvas.height,interactive:true,figureLayout:{legend:figurePrefs.legend,letter:figurePrefs.letter,scaleBar:figurePrefs.scaleBar?figureScaleBar(state.object.scale_bar):null}}):'';
 ctx.clearRect(0,0,canvas.width,canvas.height);
 const coords=drag?.kind==='edit'||drag?.kind==='pan'?null:drag?(drag.kind==='point'?drag.start:[...drag.start,...drag.end]):draft?.rendered;
 if(coords&&figurePrefs.mode==='analysis'&&drag?.kind!=='label'){const kind=drag?.kind??draft.kind,c=kind==='rectangle'?[Math.min(coords[0],coords[2]),Math.min(coords[1],coords[3]),Math.max(coords[0],coords[2]),Math.max(coords[1],coords[3])]:coords;drawMark(ctx,{kind,coordinates:c,color:'cyan',line_width:2/view.scale,arrowhead_size:6/view.scale,status:'hypothesized'},{scale:view.scale,draft:true});}
 perf.frames++;perf.overlay_count++;perf.overlay_last_ms=now()-overlayStart;perf.draw_last_ms=now()-start;diagnostics();
}
function xy(event){const rect=canvas.getBoundingClientRect();return [(event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height];}
function showDraft(){if(!draft){$('selection').textContent='在图中圈区域、点选峰，或直接拖动已有标注。';return;}let rect;try{if(draft.kind==='rectangle')rect=selectionRectangle(draft);}catch(e){message(e.message,true);}const coords=(rect??draft.coordinates).map(v=>Number(v.toPrecision(6)));$('selection').textContent=`${{point:'点',line:'线段',arrow:'箭头',rectangle:'ROI'}[draft.kind]??draft.kind} · ${coords.join(', ')} · ${draft.coordinate_space==='frequency_cycles_per_pixel'?'cycles/px':'源像素坐标'}${rect?'（向外取整边界）':''}`;}
function syncMarkFields(changeMode=true){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===selectedId);$('existing').value=selectedId;editCoordinates=null;labelDraft=null;fieldDirty=false;if(mark){$('mark-id').value=mark.annotation_id;$('mark-text').value=mark.text??'';$('color').value=mark.color;$('status').value=mark.status;if(changeMode)setMode('select');}else{$('mark-id').value=internalMarkId(()=>crypto.randomUUID());$('mark-text').value='';$('color').value='cyan';$('status').value='hypothesized';if(changeMode)setMode('select');}syncPresentationFields();marksDirty=true;}
function syncFigureControls(){$('annotation-preset').value=figurePrefs.preset;$('figure-mode').textContent=figurePrefs.mode==='figure'?'出图模式':'分析模式';$('figure-mode').setAttribute?.('aria-pressed',String(figurePrefs.mode==='figure'));document.body?.classList.toggle('figure-mode',figurePrefs.mode==='figure');const l=figurePrefs.layers,v=l.experimental?(l.simulation_A&&l.simulation_B?'all':'experimental'):l.simulation_A&&l.simulation_B?'simulation':l.simulation_A?'A':'B';$('layer-view').value=v;$('layer-summary').textContent=({all:'实验与候选叠加',experimental:'只看实验',simulation:'全部模拟 + 未解释峰',A:'候选 A + 未解释峰',B:'候选 B + 未解释峰'})[v];$('figure-columns').value=figurePrefs.columns;$('figure-font').value=figurePrefs.fontPt;$('figure-legend').checked=figurePrefs.legend;$('figure-scale').checked=figurePrefs.scaleBar;$('figure-letter').value=figurePrefs.letter;}
function syncPresentationFields(){const m=effectiveEdit(selectedId),p=labelDraft??m?.presentation??{},l=p.label??{};$('label-text').value=l.text??m?.text??'';$('label-size').value=l.font_size??12;$('marker-shape').value=p.marker_shape??(p.category==='B'?'square':p.category==='shared'?'double_circle':p.category==='unexplained'?'diamond':'circle');$('label-visible').checked=l.visible!==false;$('geometry-visible').checked=p.geometry_visible!==false;$('label-leader').checked=l.leader!==false;$('label-pinned').checked=l.pinned??false;}
function commitLabelDraft(){if(!selectedId||!labelDraft)return;const update={annotation_id:selectedId,presentation:labelDraft};labelDraft=null;queueEdit(update);}
function editPresentation(event){if(!selectedId)return;const p=labelDraft??effectiveEdit(selectedId).presentation;labelDraft={...p,marker_shape:$('marker-shape').value,geometry_visible:$('geometry-visible').checked,label:{...p.label,text:$('label-text').value,font_size:Number($('label-size').value),visible:$('label-visible').checked,leader:$('label-leader').checked,pinned:$('label-pinned').checked}};if(event?.target?.id==='label-text'&&labelDraft.label.text!==p.label?.text){delete labelDraft.label.measurement_object_id;delete labelDraft.label.measurement_kind;}record();schedulePaint();publishDraft();if(labelTimer!==null)clearTimeout(labelTimer);labelTimer=setTimeout(()=>{labelTimer=null;commitLabelDraft();},350);}
function chooseMark(next){
 if(next===selectedId)return true;
 if(labelDraft)commitLabelDraft();
 if(editCoordinates||fieldDirty)captureSelected();
 selectedId=next;syncMarkFields();const saved=effectiveEdit(next);if(saved){$('mark-text').value=saved.text;$('color').value=saved.color;$('status').value=saved.status;editCoordinates=queuedEdits.get(next)?.update.coordinates??null;}
 document.body?.classList.add('properties-open');measurementWorkspace.selectAnnotation(next);renderMeasurement();return true;
}
canvas.addEventListener('pointerdown',event=>{
 if(!image||drag||![0,1].includes(event.button))return;const start=xy(event);if(event.button===1||spaceDown||$('mode').value==='pan'){drag={kind:'pan',pointerId:event.pointerId,startClient:[event.clientX,event.clientY],originalView:{...view}};canvas.setPointerCapture(event.pointerId);return;}
 let kind=$('mode').value==='edit'?'select':$('mode').value;const selectionBefore={draft:draft?JSON.parse(JSON.stringify(draft)):null,selectedId};let blankSelect=false;try{
  if(kind==='select'&&selectedId){const selectedMark=state.object.annotations?.find(mark=>mark.annotation_id===selectedId);if(selectedMark?.anchor)markPanel(selectedMark);}
  const handleHit=figurePrefs.mode==='analysis'?hitMark(annotationLayout?.items.filter(i=>i.geometryVisible).map(i=>i.mark)??[],start,{scale:view.scale,radius:6}):null;
  const label=(!handleHit||handleHit.handle<0)&&(['select','edit'].includes(kind)||figurePrefs.mode==='figure')?annotationLayout?.items.findLast(item=>item.label?.visible&&start[0]>=item.label.x&&start[0]<=item.label.x+item.label.width&&start[1]>=item.label.y&&start[1]<=item.label.y+item.label.height):null;
  if(label?.id){if(!chooseMark(label.id))return;const current=effectiveEdit(label.id);drag={kind:'label',pointerId:event.pointerId,start,end:start,before:current,originalOffset:[...label.label.offset],labelSize:[label.label.width,label.label.height],anchor:label.anchor};labelDraft={...current.presentation,label:{...current.presentation.label,offset:[...label.label.offset],pinned:true}};canvas.setPointerCapture(event.pointerId);publishDraft({gesture_active:true});schedulePaint();message('拖动文字仅调整排版；科学锚点与测量保持原样。');return;}
  if(figurePrefs.mode==='figure')return;
  const visible=annotationLayout?.items.filter(item=>item.geometryVisible).map(item=>item.mark)??renderedMarks(),hit=hitMark(visible,start,{scale:view.scale});if(kind==='select'){if(hit){if(!chooseMark(hit.mark.annotation_id))return;kind='edit';}else{chooseMark('');draft=null;blankSelect=true;kind='rectangle';}}
  const drawingPanel=panelAt(state.object.panels??[],...start,{edges:kind==='rectangle'});
  if(kind==='edit'){const mark=(state.object.annotations??[]).find(m=>m.annotation_id===selectedId);if(!mark?.anchor)throw new Error('先点击一条带科学锚点的标注');const p=markPanel(mark),edges=['rectangle','polygon'].includes(mark.kind),original=editCoordinates??effectiveEdit(selectedId).coordinates,rendered=transformCoordinates(original,p,{edges,inverse:true}),distances=[];for(let i=0;i<rendered.length;i+=2)distances.push(Math.hypot(start[0]-rendered[i],start[1]-rendered[i+1]));const nearest=Math.min(...distances),handle=nearest<9/view.scale?distances.indexOf(nearest):-1;drag={kind,start,end:start,mark,p,edges,handle,original,before:effectiveEdit(selectedId),previousEdit:editCoordinates};editCoordinates=[...drag.original];draft={kind:mark.kind,...mark.anchor,coordinates:[...original],panel:p,rendered};marksDirty=true;}
  else drag={kind,start,end:start,originalStart:start,p:drawingPanel,selectionBefore,blankSelect};drag.pointerId=event.pointerId;canvas.setPointerCapture(event.pointerId);publishDraft({gesture_active:true});schedulePaint();
 }catch(e){message(e.message,true);}
});
function updateDrag(event){if(drag.kind==='pan'){view=panBy(drag.originalView,event.clientX-drag.startClient[0],event.clientY-drag.startClient[1]);resize();return;}drag.end=xy(event);if(['rectangle','line','arrow'].includes(drag.kind))Object.assign(drag,constrainSelectionDrag(drag.p,drag.originalStart,drag.end,{kind:drag.kind,constrained:Boolean(event.shiftKey||event.ctrlKey)}));if(drag.kind==='label'){const offset=drag.originalOffset.map((v,i)=>Math.max(-drag.anchor[i],Math.min((i?canvas.height:canvas.width)-drag.anchor[i]-drag.labelSize[i],v+drag.end[i]-drag.start[i])));labelDraft={...labelDraft,label:{...labelDraft.label,offset,pinned:true}};return;}if(drag.kind==='edit'){const from=transformCoordinates(drag.start,drag.p,{edges:drag.edges}),to=transformCoordinates(drag.end,drag.p,{edges:drag.edges}),delta=to.map((v,i)=>v-from[i]);editCoordinates=drag.original.map((v,i)=>drag.handle<0||Math.floor(i/2)===drag.handle?v+delta[i%2]:v);}}
canvas.addEventListener('pointermove',event=>{if(!drag){if($('numeric-data').open)try{const p=xy(event);dataProbes.observe(selectionFromDrag(state.object.panels??[],p,p,{kind:'point'}));}catch{dataProbes.clear();}if(figurePrefs.mode==='analysis'){const p=xy(event),hit=hitMark(annotationLayout?.items.filter(i=>i.geometryVisible).map(i=>i.mark)??[],p,{scale:view.scale}),next=hit?.mark.annotation_id??'';if(next!==hoverId){hoverId=next;schedulePaint();}}return;}if(event.pointerId!==drag.pointerId)return;updateDrag(event);schedulePaint();});
canvas.addEventListener('pointerleave',()=>dataProbes.clear());
function cancelDrag(event){if(!drag||event.pointerId!==drag.pointerId)return;if(drag.kind==='label')labelDraft=null;if(drag.kind==='edit')editCoordinates=drag.previousEdit;if(drag.kind==='pan'){view=drag.originalView;resize();}drag=null;marksDirty=true;schedulePaint();publishDraft();message('已取消本次拖动；尚未提交任何修改。');}
canvas.addEventListener('pointercancel',cancelDrag);canvas.addEventListener('lostpointercapture',cancelDrag);
canvas.addEventListener('pointerup',event=>{if(!drag||event.pointerId!==drag.pointerId)return;const kind=drag.kind,before=drag.before;try{updateDrag(event);if(kind==='pan')return;if(drag.blankSelect&&Math.hypot(drag.end[0]-drag.start[0],drag.end[1]-drag.start[1])*view.scale<3){draft=null;rememberSelection(drag.selectionBefore,{draft:null,selectedId:''});showDraft();return;}if(kind==='label'){const update={annotation_id:selectedId,presentation:labelDraft};labelDraft=null;queueEdit(update,before);syncPresentationFields();return;}if(kind==='edit'){const update={annotation_id:selectedId,coordinates:[...editCoordinates],text:$('mark-text').value,color:$('color').value,status:$('status').value};draft={...draft,coordinates:[...editCoordinates],rendered:transformCoordinates(editCoordinates,drag.p,{edges:drag.edges,inverse:true})};editCoordinates=null;fieldDirty=false;queueEdit(update,before);return;}const selected=selectionFromDrag(state.object.panels??[],drag.start,drag.end,{kind});draft={...selected,rendered:transformCoordinates(selected.coordinates,selected.panel,{edges:kind==='rectangle',inverse:true})};rememberSelection(drag.selectionBefore??{draft:null,selectedId:''},{draft:JSON.parse(JSON.stringify(draft)),selectedId});showDraft();message('选择已定位；可直接测量或交给 Agent。');}catch(e){message(e.message,true);}finally{drag=null;if(kind!=='pan')record();paint();publishDraft({includeSelection:true,urgent:true});Promise.resolve().then(flushEdits);}});
viewport.addEventListener('wheel',event=>{if(!image)return;event.preventDefault();const r=viewport.getBoundingClientRect();view=zoomAt(view,[event.clientX-r.left,event.clientY-r.top],Math.exp(-event.deltaY*.0015));resize();},{passive:false});
document.addEventListener('keydown',event=>{if(/INPUT|TEXTAREA|SELECT/.test(event.target?.tagName??''))return;if(event.code==='Space'){spaceDown=true;event.preventDefault();}if(!event.ctrlKey&&!event.metaKey){const mode={v:'select',r:'rectangle',p:'point',l:'line',a:'arrow',h:'pan'}[event.key.toLowerCase()];if(mode)setMode(mode);if(event.key.toLowerCase()==='f')fitView();}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();if(event.shiftKey)$('redo').onclick();else $('undo').onclick();}if(event.key==='Escape'&&drag)cancelDrag({pointerId:drag.pointerId});});document.addEventListener('keyup',event=>{if(event.code==='Space')spaceDown=false;});
function guarded(fn){return async()=>{try{await fn();}catch(e){message(e.message,true);}};}
for(const [id,action]of [['apply-roi','roi'],['share','select']])$(id).onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason(action,picked,state.object);if(reason)throw new Error(reason);return act(action,{selection:picked});});
$('measure').onclick=guarded(async()=>{
 const picked=selection(),reason=selectionActionReason('measure',picked,state.object);if(reason)throw new Error(reason);let mark=state.object.annotations?.find(m=>m.annotation_id===selectedId&&m.kind===picked.kind&&equalRecords(m.anchor?.coordinates,picked.coordinates));
 if(!mark){
  const r=await act('mark',{selection:picked,annotation_id:internalMarkId(()=>crypto.randomUUID()),text:measurementLabel(picked,(state.object.annotations?.length??0)+1),color:'cyan',status:'hypothesized'});
  if(!r||pending||state.pending_result)return;
  const id=r.last_operation?.annotation_ids?.[0];mark=r.object.annotations?.find(m=>m.annotation_id===id);if(!mark)throw new Error('标记保存未确认；请查询原请求');chooseMark(id);
 }
 measuredMarkId=mark.annotation_id;
 const panel=markPanel(mark),previous=measurementWorkspace.latestForAnnotation(mark.annotation_id);
 return act('measure',{selection:{...mark.anchor,kind:mark.kind,panel},annotation_id:mark.annotation_id,...(previous?{measurement_object_id:previous.object_id}:{})});
});
$('fft').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('fft',picked,state.object);if(reason)throw new Error(reason);return act('fft',{selection:picked,window:$('fft-window').value,subtract_mean:$('fft-mean').checked});});
$('roi-statistics').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('statistics',picked,state.object);if(reason)throw new Error(reason);return act('statistics',{selection:picked,component:$('probe-component').value});});
$('line-profile').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('profile',picked,state.object);if(reason)throw new Error(reason);return act('profile',{selection:picked,component:$('probe-component').value,sample_count:Number($('profile-count').value)});});
$('reload').onclick=guarded(refresh);$('zoom').oninput=()=>{const r=viewport.getBoundingClientRect();view=zoomAt(view,[r.width/2,r.height/2],Number($('zoom').value)/view.scale);resize();};$('fit').onclick=fitView;
for(const id of ['gamma','low','high','axes','scale']){$(id).oninput=()=>{recordDisplayInput(id);$('gamma-label').textContent=$('gamma').value;record();schedulePaint();publishDraft();message('显示草稿即时反馈；保存后从原科学数组重绘，不重算 FFT。');};$(id).onchange=()=>userHistory.endGroup();}
$('apply-display').onclick=guarded(()=>{const frequency=state.object.panels?.some(p=>p.domain==='frequency');return act('preview',{gamma:Number($('gamma').value),display_range:$('low').value===''||$('high').value===''?null:[Number($('low').value),Number($('high').value)],...(frequency?{spectrum_axes:$('axes').checked}:{scale_bar:$('scale').checked})});});
$('set-frame').onclick=guarded(()=>act('frame',{frame_index:Number($('frame').value)-1}));$('previous-frame').onclick=guarded(()=>act('frame',{frame_index:Math.max(0,Number($('frame').value)-2)}));$('next-frame').onclick=guarded(()=>act('frame',{frame_index:Number($('frame').value)}));$('full').onclick=guarded(()=>act('preview',{frequency_rect:null}));$('export').onclick=guarded(()=>{if(dirty())throw new Error('请先保存或撤销草稿，再导出已保存视图。');return act('export');});$('recover').onclick=guarded(()=>act('recover',failedMeasurement?.request_id?{request_id:failedMeasurement.request_id}:{}));
$('existing').onchange=()=>{if(!chooseMark($('existing').value))return;record();paint();publishDraft();};
for(const id of ['mark-text','color','status'])$(id).oninput=()=>{if(!fieldBefore&&selectedId)fieldBefore=effectiveEdit(selectedId);fieldDirty=true;marksDirty=true;record();schedulePaint();publishDraft();autoFields();};
$('save-mark').onclick=guarded(async()=>{if(selectedId){commitLabelDraft();captureSelected();return flushEdits();}const fields={text:$('mark-text').value,color:$('color').value,status:$('status').value};return act('mark',{selection:selection(),annotation_id:$('mark-id').value,...fields});});
$('undo').onclick=()=>applyUserHistory('undo');$('redo').onclick=()=>applyUserHistory('redo');
$('discard-local').onclick=guarded(async()=>{if(busy)throw new Error('原请求仍在保存，先查询其结果；本地编辑保留。');drag=null;queuedEdits.clear();autoFailed=false;failedMeasurement=null;remeasuringMarks.clear();orphanedDraft=false;pending=null;await load(await api('/api/state'));message('本地草稿已撤回；保存过的科学版本仍保留。');});
$('discard-draft').onclick=guarded(async()=>{orphanedDraft=false;if(pending){const next=pending;pending=null;await load(next);}else{editCoordinates=null;fieldDirty=false;const current=await api('/api/state');await load(current);await act('accept-result');}message('已查看保存版本；旧科学版本仍保留。');});
$('accept-agent-result').onclick=guarded(async()=>{if(dirty()||drag)throw new Error('先保存、撤销或明确放弃草稿，再查看 Agent 结果');if(pending){pending=null;await load(await api('/api/state'));}return act('accept-result');});
const calibrate=withdraw=>act('calibrate',{coordinate_domain:state.object.xy_calibration?.coordinate_domain??'real_space',scope:$('scope').value,xy_scale:withdraw?null:{x:Number($('scale-x').value),y:Number($('scale-y').value),unit:$('unit').value},source_text:$('source').value});$('calibrate').onclick=guarded(()=>calibrate(false));$('withdraw').onclick=guarded(()=>calibrate(true));
$('submit-observation').onclick=guarded(()=>act('research-observation',{source_text:$('observation-text').value,authority:$('observation-authority').value}));
const revisionKey=value=>JSON.stringify([value.state_revision,value.object_id??value.object?.object_id,value.pending_result?.object_id,value.pending_result?.request_id]);
function setMode(mode){mode=mode==='edit'?'select':mode;$('mode').value=mode;canvas.style.cursor=mode==='pan'?'grab':mode==='select'?'default':'crosshair';for(const button of document.querySelectorAll('[data-mode]'))button.setAttribute('aria-pressed',String(button.dataset.mode===mode));}
for(const button of document.querySelectorAll('[data-mode]'))button.onclick=()=>setMode(button.dataset.mode);
$('toggle-properties').onclick=()=>document.body.classList.toggle('properties-open');$('close-properties').onclick=()=>document.body.classList.remove('properties-open');
$('toggle-settings').onclick=()=>{document.body.classList.add('properties-open');$('settings-panel').open=true;};
for(const id of ['label-text','label-size','marker-shape','label-visible','geometry-visible','label-leader','label-pinned'])$(id).oninput=editPresentation;
$('annotation-preset').onchange=()=>{figurePrefs.preset=$('annotation-preset').value;syncFigureControls();schedulePaint();message('仅切换标注显示预设；科学坐标与确认状态保持原样。');};
$('figure-mode').onclick=()=>{figurePrefs.mode=figurePrefs.mode==='figure'?'analysis':'figure';syncFigureControls();schedulePaint();message(figurePrefs.mode==='figure'?'出图模式：可继续拖动文字；科学锚点已锁定。':'分析模式：圆圈移动改变科学点位，文字移动只改变排版。');};
$('layer-view').onchange=()=>{const v=$('layer-view').value;figurePrefs.layers={experimental:v==='all'||v==='experimental',simulation_A:['all','A','simulation'].includes(v),simulation_B:['all','B','simulation'].includes(v)};$('layer-summary').textContent=$('layer-view').selectedOptions?.[0]?.textContent??v;schedulePaint();};
$('arrange-labels').onclick=()=>{commitLabelDraft();const arranged=layoutAnnotations(renderedMarks(),{...figurePrefs,width:canvas.width,height:canvas.height,scale:view.scale,arrange:true});for(const update of arranged.suggestedUpdates??[])queueEdit({annotation_id:update.id??update.annotation_id,presentation:update.presentation});schedulePaint();message('已整理未固定标签；手工固定位置与科学锚点保留。');};
$('figure-options').onclick=()=>{$('figure-columns').value=figurePrefs.columns;$('figure-font').value=figurePrefs.fontPt;$('figure-legend').checked=figurePrefs.legend;$('figure-scale').checked=figurePrefs.scaleBar;$('figure-letter').value=figurePrefs.letter;$('figure-dialog').showModal();};
function figureOptions(){return {...figurePrefs,columns:$('figure-columns').value,fontPt:Math.max(7,Math.min(12,Number($('figure-font').value)||8)),legend:$('figure-legend').checked,scaleBar:$('figure-scale').checked,letter:$('figure-letter').value};}
for(const id of ['figure-columns','figure-font','figure-legend','figure-scale','figure-letter'])$(id).oninput=()=>{figurePrefs=figureOptions();schedulePaint();};
$('export-figure').onclick=guarded(async()=>{
 commitLabelDraft();captureSelected();while(queuedEdits.size||autoSaving){if(autoFailed)throw new Error('标签保存失败；本地编辑保留，请先查询原请求');if(busy&&!autoSaving)throw new Error('保存仍在进行，请稍后导出');await flushEdits();}
 if(dirty()||drag||busy)throw new Error('先保存显示草稿并结束手势，再导出图面');const revision=historyDraft.revision,id=state.object.object_id,marks=renderedMarks(),preferences=figureOptions();$('figure-export-status').textContent='正在从保存数组生成干净底图与矢量图层…';busy=true;diagnostics();
 try{await draftPublisher;const base=await api('/api/action',{expected_object_id:id,draft_revision:revision,action:'figure-base',params:{}});if(historyDraft.revision!==revision||state.object.object_id!==id||drag)throw new Error('导出期间图面已变化；新编辑已保留，请结束后重新导出');const bundle=await buildFigureBundle({state:{...state,figure_base:base.figure_base},marks,preferences,base64:base.figure_base.clean_png_base64,scaleBar:base.figure_base.scale_bar});if(historyDraft.revision!==revision||state.object.object_id!==id||drag)throw new Error('导出期间图面已变化；新编辑已保留，请结束后重新导出');downloadBlob(bundle.blob,'microscopy-figure.zip');$('figure-export-status').textContent='已下载 clean.png、annotations.svg、annotated.png 和 figure.json。保留原工作区后可载入配方继续编辑。';message('图面已导出；科学像素、锚点与旧版本保持原样。');}
 catch(e){$('figure-export-status').textContent='导出未完成：'+e.message;throw e;}finally{busy=false;diagnostics();}
});
async function importRecipeText(text){try{if(text.length>512000)throw new Error('图面配方超过大小上限');if(dirty()||busy||drag)throw new Error('先结束手势并保存草稿，再载入配方');const recipe=JSON.parse(text),updates=readFigureRecipe(recipe,state);const restored=await act('restore-figure-display',{recipe});if(!restored||pending||state.pending_result||drag||dirty()||state.object.object_id!==restored.object.object_id)throw new Error('显示恢复尚未安全接续；当前草稿保留，请处理待查看结果后重试');for(const update of updates)queueEdit(update);figurePrefs={...figurePrefs,...recipe.preferences,layers:{experimental:recipe.preferences.layers?.experimental!==false,simulation_A:recipe.preferences.layers?.simulation_A===true,simulation_B:recipe.preferences.layers?.simulation_B===true},letter:String(recipe.preferences.letter??'').slice(0,8)};syncFigureControls();schedulePaint();$('figure-export-status').textContent='已恢复底图显示、标签与样式；科学锚点和确认状态已逐项校验并保留。';}catch(e){$('figure-export-status').textContent='载入未完成：'+e.message;throw e;}}
$('import-figure').onchange=guarded(async()=>{const file=$('import-figure').files?.[0];if(!file)return;if(file.size>512000)throw new Error('图面配方超过大小上限');await importRecipeText(await file.text());});
$('load-recipe-text').onclick=guarded(()=>importRecipeText($('recipe-text').value));
$('frame').onkeydown=event=>{if(event.key==='Enter')$('set-frame').onclick();};
$('view-back').onclick=guarded(()=>navigateSavedView(savedViews.target(-1)));
$('view-forward').onclick=guarded(()=>navigateSavedView(savedViews.target(1)));
$('view-original').onclick=guarded(()=>navigateSavedView(savedViews.original(state)));
for(const tab of ['measurements','statistics','profile']){
 const button=$('results-tab-'+tab);if(button){button.onclick=()=>setResultsTab(tab);button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const names=['measurements','statistics','profile'],i=names.indexOf(tab),next=event.key==='Home'?0:event.key==='End'?2:(i+(event.key==='ArrowRight'?1:2))%3;setResultsTab(names[next]);$('results-tab-'+names[next])?.focus?.();};}
}
setResultsTab('measurements',{expand:false});

async function pollRevision(){
 try{if(state&&!document.hidden&&!busy&&!drag){const next=await api('/api/revision');if(revisionKey(next)!==revisionKey(state))await refresh();}}
 catch{/* A closed panel is not restarted and no scientific operation is retried. */}
 finally{if(typeof setTimeout==='function')setTimeout(pollRevision,1500);}
}
globalThis.addEventListener?.('beforeunload',event=>{if(dirty()||drag){event.preventDefault();event.returnValue='';}});
const resizer=$('results-resizer');
if(resizer){let resizing=null;resizer.onpointerdown=event=>{resizing={y:event.clientY,height:document.querySelector('.measurement-content').getBoundingClientRect().height};resizer.setPointerCapture(event.pointerId);};resizer.onpointermove=event=>{if(resizing)document.querySelector('.measurement-content').style.height=Math.max(130,Math.min(innerHeight*.55,resizing.height+resizing.y-event.clientY))+'px';};resizer.onpointerup=()=>{resizing=null;};resizer.onpointercancel=()=>{resizing=null;};resizer.onkeydown=event=>{if(['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();const content=document.querySelector('.measurement-content');content.style.height=Math.max(130,content.getBoundingClientRect().height+(event.key==='ArrowUp'?20:-20))+'px';}};}
refresh().then(()=>{if(image)fitView();message(orphanedDraft?'检测到先前未保存的草稿记录；请明确撤回草稿后继续。':'滚轮缩放 · 空格拖动 · 移动标注松手即保存');if(typeof setTimeout==='function')setTimeout(pollRevision,1500);}).catch(e=>message(e.message,true));
