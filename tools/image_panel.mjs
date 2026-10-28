// Optional loopback gesture surface over the real image_* stdio MCP server.
// It owns no scientific state: every saved revision is an existing tool object.
import http from 'node:http';
import {spawn} from 'node:child_process';
import {randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {mkdirSync,writeFileSync,readFileSync,existsSync,openSync,fsyncSync,closeSync,renameSync,realpathSync,statSync,linkSync,unlinkSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {selectionRectangle} from '../ui/image-panel/coordinates.mjs';
import {annotationPresentation} from '../lib/image_workspace.mjs';
import {validate} from '../lib/runtime/schema.mjs';
import {figureDisplayParameters,readFigureRecipe,recipeIdentity} from '../ui/image-panel/figure-export.mjs';
import {readImageMeasurements,writeMeasurementLink} from '../lib/image_measurement_records.mjs';
import {framePreviewRecipe} from '../ui/image-panel/user-workflow.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const objectId=/^[a-f0-9]{32}$/;
const safeId=/^[A-Za-z0-9_-]{1,64}$/;
function fail(message,status=400){const e=new Error(message);e.status=status;throw e;}
function fields(value,allowed){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!allowed.includes(k)))fail('Unexpected action fields');}
function presentationUpdate(value){if(value.presentation!==undefined)validate(value.presentation,annotationPresentation,'presentation');if(value.presentation_replace!==undefined&&(typeof value.presentation_replace!=='boolean'||value.presentation===undefined))fail('presentation_replace requires an explicit boolean and presentation metadata');}
// Saved manifests and fresh worker replies may serialize dictionary keys in a
// different order. Compare their complete values; array order stays significant.
function sameRecord(left,right){const sorted=(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,value[key]])):value;return JSON.stringify(left,sorted)===JSON.stringify(right,sorted);}
function writeJournal(file,value){const fd=openSync(file,'wx');try{writeFileSync(fd,JSON.stringify(value,null,2));fsyncSync(fd);}finally{closeSync(fd);}}
function publicObject(value){
 const keys=['object_id','kind','request_id','parent_object_id','base_object_id','source_object_id','frame_index','page_count','pages','shape_yx','dtype','axes','display','panels','annotations','user_context','calibration','xy_calibration','calibration_record','calibration_status','active_calibration','calibration_dependency','calibration_review','display_calibration_id','frequency_axes','physical_frequency_axes','physical_frequency_magnitude','physical_frequency_unit','scale_bar','measurement','points','dx','dy','coordinate_space','coordinate_system','frequency_distance_cycles_per_pixel','pixel_period','image_coordinate_angle_degrees','physical_angle','physical_angle_degrees','physical_vector_xy','measurement_uncertainty','uncertainty_status','limitation','reciprocal_interpretation','distance_pixels','distance_physical','physical_distance','displacement_pixels','physical_displacement','physical_unit','period','period_unit','d_spacing','d_spacing_unit','fft_recomputed','scientific_data_changed','scientific_grid_identity','array_domain','scientific_semantics'];
 return Object.fromEntries(keys.filter(k=>value[k]!==undefined).map(k=>[k,value[k]]));
}
export class StdioImageClient {
 constructor({workspace,python,serverPath=path.join(root,'server.mjs')}){
  this.child=spawn(process.execPath,[serverPath],{env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python},stdio:['pipe','pipe','pipe'],windowsHide:true});
  this.next=1;this.pending=new Map();let buffer='';this.stderr='';
  this.child.stderr.on('data',c=>{this.stderr=(this.stderr+c).slice(-4000);});
  this.child.stdout.on('data',c=>{buffer+=c;let n;while((n=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,n);buffer=buffer.slice(n+1);try{const msg=JSON.parse(line),p=this.pending.get(msg.id);if(p){this.pending.delete(msg.id);clearTimeout(p.timer);p.resolve(msg);}}catch(e){this.rejectAll(e);}}});
  this.child.on('error',e=>this.rejectAll(e));this.child.on('exit',()=>this.rejectAll(new Error('MCP client exited '+this.stderr)));this.child.stdin.on('error',()=>{});
 }
 rejectAll(error){for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(error);}this.pending.clear();}
 rpc(method,params={}){return new Promise((resolve,reject)=>{const id=this.next++,timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('Stopped waiting; query the journaled original request_id. Do not resubmit automatically.'));},130000);this.pending.set(id,{resolve,reject,timer});this.child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});}
 async tool(name,args){const msg=await this.rpc('tools/call',{name,arguments:args});if(msg.error||msg.result?.isError)throw new Error(msg.error?.message??msg.result?.content?.find(c=>c.type==='text')?.text??'MCP operation failed');const data=JSON.parse(msg.result.content.find(c=>c.type==='text').text);const png=msg.result.content.find(c=>c.type==='image'&&c.mimeType==='image/png');return {data,png:png?.data};}
 async close(){if(this.child.exitCode===null)await new Promise(resolve=>{this.child.once('exit',resolve);this.child.stdin.end();});}
}
function originalMark(mark){if(!mark.anchor)fail('A legacy mark has no unique scientific anchor; replace it through MCP first');return {...Object.fromEntries(['annotation_id','kind','status','text','note','color','line_width','arrowhead_size','arrow_length','presentation'].filter(k=>mark[k]!==undefined).map(k=>[k,mark[k]])),...mark.anchor};}
export async function createImagePanel({workspace,python,object_id,port=0,panel_id=null,client:givenClient,journalDirectory}={}){
 if(!path.isAbsolute(workspace??'')||!path.isAbsolute(python??'')||!objectId.test(object_id??''))throw new Error('Explicit absolute workspace/python and existing object_id required');
 const token=randomBytes(24).toString('hex'),session=randomBytes(8).toString('hex');
 const journal=journalDirectory??path.join(workspace,'panel-journals',session);mkdirSync(journal,{recursive:true});
 const client=givenClient??new StdioImageClient({workspace,python});let tools,current,png,cleanPng=null,cleanHash=null,renderBaseId=null,sequence=0,selection=null,busy=Promise.resolve(),lastOperation=null,frameIdentity=null,effectiveDisplay=null,displaySourceObjectId=null,stateRevision=0,pendingResult=null,researchObservation=null,selectionTimer=null,selectionPersistenceError=null;
 const sources=new Map(),figureBars=new Map();
 const numericResults={statistics:null,profile:null};
 let editState={draft_revision:0,dirty:false,gesture_active:false,selection:null,annotation_edit:null,base_object_id:null};
 try{const init=await client.rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'mcp-dm-local-image-panel',version:'1'}});if(init.error)throw new Error(init.error.message);
 tools=(await client.rpc('tools/list')).result.tools;}catch(error){await client.close();throw error;}const names=new Set(tools.map(t=>t.name));
 const journalCall=async(name,args)=>{if(!names.has(name))fail('Tool unavailable: '+name);const write=name!=='image_info'&&name!=='image_result';if(write){args={...args,request_id:`panel-${session}-${++sequence}`};writeJournal(path.join(journal,`${args.request_id}.request.json`),{name,arguments:args});lastOperation={state:'submitted',tool:name,request_id:args.request_id,object_id:args.object_id};saveSelection();}try{const r=await client.tool(name,args);if(write)writeJournal(path.join(journal,`${args.request_id}.response.json`),{object_id:r.data.object_id,request_id:args.request_id,state:r.data.state});return r;}catch(error){if(write)error.message+=` Original request_id=${args.request_id}; query image_result with this ID. Do not automatically repeat the operation.`;throw error;}};
 const displayObject=async r=>{
  if(r.data.kind==='tiff_source'||r.png&&r.data.kind!=='calibration')return r;
  if(r.data.kind==='calibration'){
   let base=r.data;
   for(let i=0;i<64&&base.kind==='calibration';i++)base=(await journalCall('image_info',{object_id:base.base_object_id})).data;
   if(base.kind==='tiff_source')return {...r,png:null};
  }
  return journalCall('image_preview',{object_id:r.data.object_id});
 };
 // Prepare immutable render assets before committing the visible identity. A
 // draft can arrive while ancestry lookup/worker I/O is waiting.
 const prepareCurrent=async r=>{
  let value=r.data,display=null,displayId=null;const seen=new Set();
  for(let n=0;n<64;n++){
   if(seen.has(value.object_id))fail('Display ancestry contains a cycle');seen.add(value.object_id);
   if(value.display){display=structuredClone(value.display);displayId=value.object_id;break;}
   if(value.kind==='tiff_source')break;
   const next=value.render_base_object_id??value.base_object_id??value.parent_object_id;
   if(!objectId.test(next??''))break;
   value=(await journalCall('image_info',{object_id:next})).data;
   if(n===63)fail('Display ancestry exceeds 64 records');
  }
  let base=r.data;
  if(objectId.test(base.render_base_object_id??''))base=(await journalCall('image_info',{object_id:base.render_base_object_id})).data;
  let clean=null,digest=null;
  const file=base.files_sha256?.['unannotated.png']?'unannotated.png':!(base.annotations?.length)&&base.files_sha256?.['preview.png']?'preview.png':null;
  if(file&&r.png){
   if(!sameRecord(base.panels??[],r.data.panels??[]))fail('Clean render panel mapping differs from annotation revision');
   const directory=realpathSync(workspace),target=realpathSync(path.join(workspace,'objects',base.object_id,file)),relative=path.relative(directory,target);
   if(relative.startsWith('..')||path.isAbsolute(relative)||statSync(target).size>2*1024*1024)fail('Clean render lies outside bounded workspace');
   const bytes=readFileSync(target);digest=createHash('sha256').update(bytes).digest('hex');
   if(digest!==base.files_sha256[file]||bytes.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')fail('Clean PNG hash or format mismatch');
   clean=bytes.toString('base64');
  }else if(!r.data.annotations?.length){clean=r.png??null;digest=clean?createHash('sha256').update(Buffer.from(clean,'base64')).digest('hex'):null;}
  return {object:r.data,png:r.png??null,clean,digest,baseId:base.object_id,display,displayId};
 };
 const commitCurrent=(prepared,{annotationIds=[]}={})=>{
  current=prepared.object;png=prepared.png;cleanPng=prepared.clean;cleanHash=prepared.digest;renderBaseId=prepared.baseId;effectiveDisplay=prepared.display;displaySourceObjectId=prepared.displayId;selection=null;stateRevision++;
  // A saved drag is still the researcher's exact selection. Retain only the
  // explicitly edited mark; never infer a mark from array order or recency.
  if(annotationIds.length===1){
   const mark=current.annotations?.find(value=>value.annotation_id===annotationIds[0]);
   const matches=mark?.anchor?(current.panels??[]).filter(value=>value.source_object_id===mark.anchor.source_object_id&&({frequency:'frequency_cycles_per_pixel',spatial_pixels:'source_pixels',source_array_indices:'source_array_indices'}[value.domain])===mark.anchor.coordinate_space):[];
   if(mark?.status!=='retracted'&&mark?.kind!=='text'&&matches.length===1){
    try{selection=checkSelection({...mark.anchor,kind:mark.kind,panel:matches[0]});}
    catch{/* A valid saved mark outside this zoom is not a current selection. */}
   }
  }
  editState={draft_revision:editState.draft_revision,dirty:false,gesture_active:false,selection:null,annotation_edit:null,base_object_id:current.object_id};
 };
 const setCurrent=async r=>commitCurrent(await prepareCurrent(r));
 const describeSource=(value,declared)=>{
  if(['synthetic_demo','synthetic','合成演示'].includes(declared))return {kind:'synthetic',label:'合成演示',basis:'explicit user_context.data_meaning statement'};
  if(['digitalmicrograph','digitalmicrograph-native','saved digitalmicrograph-native READ numeric snapshot','saved digitalmicrograph-native PROFILE numeric snapshot','saved digitalmicrograph-native HISTOGRAM numeric snapshot'].includes(value.upstream_backend))return {kind:'dm_capture',label:'DM 捕获',basis:'validated imported capture backend'};
  if(value.source_identity?.path)return {kind:'tiff',label:'用户指定 TIFF',filename:path.win32.basename(path.basename(value.source_identity.path)),basis:'fixed source TIFF provenance'};
  return {kind:'unknown',label:'来源未声明',basis:'no supported explicit source declaration'};
 };
 const findFrameIdentity=async value=>{const original=value.object_id,declared=value.user_context?.data_meaning,visited=new Set();for(let n=0;n<64;n++){if(value.kind==='frame'){sources.set(original,describeSource(value,declared));return Number.isInteger(value.frame_index)?{frame_object_id:value.object_id,frame_index:value.frame_index,source_object_id:value.source_object_id}:null;}if(value.kind==='tiff_source'){sources.set(original,describeSource(value,declared));return null;}if(value.kind==='compare'||visited.has(value.object_id))return null;visited.add(value.object_id);const id=value.parent_object_id??value.base_object_id??value.source_object_id;if(!objectId.test(id??''))return null;value=(await journalCall('image_info',{object_id:id})).data;}return null;};
 try{await setCurrent(await displayObject(await journalCall('image_info',{object_id})));frameIdentity=await findFrameIdentity(current);}
 catch(error){await client.close();throw error;}
 const observationState=()=>researchObservation?{...structuredClone(researchObservation),current_view_relation:current.object_id===researchObservation.base_object_id?'same_saved_view':'different_saved_view_review_scope'}:null;
 const sourceIdentity=()=>sources.get(current.object_id)??describeSource(current,current.user_context?.data_meaning);
 const draftPersistence=()=>({pending:selectionTimer!==null,error:selectionPersistenceError});
 const draftAck=()=>({schema_version:1,panel_id,object_id:current.object_id,state_revision:stateRevision,edit_state:structuredClone(editState),selection,research_observation:observationState(),draft_persistence:draftPersistence()});
 const state=()=>({schema_version:1,panel_id,numeric_results:numericResults,backend:'external-image-workspace',state_revision:stateRevision,object:publicObject(current),source_identity:sourceIdentity(),effective_display:effectiveDisplay,display_source_object_id:displaySourceObjectId,render_base_id:renderBaseId,clean_png_base64:cleanPng,clean_png_sha256:cleanHash,frame_identity:frameIdentity,png_base64:png,tools:tools.map(t=>({name:t.name,inputSchema:t.inputSchema})),selection,last_operation:lastOperation,research_observation:observationState(),draft_persistence:draftPersistence(),edit_state:structuredClone(editState),pending_result:pendingResult?{object_id:pendingResult.prepared.object.object_id,request_id:pendingResult.request_id,reason:'unsaved_draft',scientific_operation_complete:true}:null});
 function writeSelection(){if(!current)return;const temp=path.join(journal,`.selection-${randomBytes(6).toString('hex')}.json`);writeJournal(temp,{schema_version:1,object_id:current.object_id,state_revision:stateRevision,frame_identity:frameIdentity,selection,edit_state:editState,pending_result:pendingResult?{object_id:pendingResult.prepared.object.object_id,request_id:pendingResult.request_id}:null,last_operation:lastOperation,research_observation:observationState(),updated_utc:new Date().toISOString()});renameSync(temp,path.join(journal,'current-selection.json'));selectionPersistenceError=null;}
 // Only the replaceable gesture handoff snapshot is coalesced. Scientific
 // request/response journals keep their original before-dispatch fsync path.
 function saveSelection({coalesce=false}={}){
  if(selectionTimer!==null){clearTimeout(selectionTimer);selectionTimer=null;}
  if(coalesce){selectionTimer=setTimeout(()=>{selectionTimer=null;try{writeSelection();}catch(error){selectionPersistenceError=error.message;}},100);selectionTimer.unref?.();}
  else writeSelection();
 }
 const figureAsset=async r=>{
  const prepared=await prepareCurrent(r);
  if(!sameRecord(prepared.object.panels??[],current.panels??[]))fail('Figure base must retain the exact current source/render mapping; disable FFT axes before exporting',409);
  if(!prepared.clean||!prepared.digest)fail('A verified clean figure base is unavailable');
  return {...state(),figure_base:{object_id:r.data.object_id,request_id:r.data.request_id,clean_png_base64:prepared.clean,
   clean_png_sha256:prepared.digest,scale_bar:figureBars.get(current.object_id)??null,panels:structuredClone(prepared.object.panels??[])}};
 };
 const annotationIdentity=value=>(value.annotations??[]).map(mark=>Object.fromEntries(['annotation_id','kind','anchor','status','text','note','presentation'].filter(key=>mark[key]!==undefined).map(key=>[key,mark[key]])));
 const verifyFigureDisplay=(prepared,nextFrame,restore)=>{
  if(!sameRecord(recipeIdentity({object:prepared.object,frame_identity:nextFrame}),restore.source)||!sameRecord(figureDisplayParameters(prepared.display,prepared.object.panels),restore.display)||!sameRecord(annotationIdentity(prepared.object),restore.annotations))fail('Restored figure display changed the scientific source, calibration, anchors, labels or exact render mapping; saved result was not adopted',409);
 };
 function saveResearchObservation(data,{baseObjectId=data.parent_object_id,baseRevision=stateRevision,baseFrameIdentity=null}={}){
  const observation=data.user_context?.research_observation;
  if(data.kind!=='context'||!objectId.test(data.object_id??'')||observation?.kind!=='twinning_present'||!['user_confirmed','synthetic_fixture'].includes(observation.authority)||data.research_observation_scope?.confirmation_scope!=='twinning_present_only'||data.research_observation_scope.source_object_id!==data.parent_object_id)fail('Research observation result is not a saved scoped context');
  researchObservation={object_id:data.object_id,request_id:data.request_id,...structuredClone(observation),scope:structuredClone(data.research_observation_scope??null),base_object_id:baseObjectId,base_state_revision:baseRevision,base_frame_identity:structuredClone(baseFrameIdentity)};
  lastOperation={action:'research-observation',object_id:data.object_id,request_id:data.request_id,state:'completed',confirmation_scope:'twinning_present_only'};
  stateRevision++;saveSelection();return state();
 }
 const sourceForFrame=async()=>{let value=current;const visited=new Set();for(let n=0;n<64;n++){if(value.kind==='tiff_source')return value.object_id;if(visited.has(value.object_id))break;visited.add(value.object_id);const next=value.parent_object_id??value.base_object_id??value.source_object_id;if(!objectId.test(next??''))break;value=(await journalCall('image_info',{object_id:next})).data;}fail('No explicit TIFF source ancestry; choose another object through the Agent');};
 const withCurrentContext=async(sourceId,{newFrame=false}={})=>{
  let target=sourceId;
  const context=Object.fromEntries(Object.entries(current.user_context??{}).filter(([key])=>['reconstruction_type','data_meaning','frame_meaning','xy_scale','value_unit','frame_scale','source_text'].includes(key)));
  if(Object.keys(context).length&&names.has('image_context'))target=(await journalCall('image_context',{object_id:target,metadata:context})).data.object_id;
  const calibration=current.xy_calibration;
  if(calibration?.calibration_id&&(!newFrame||calibration.scope==='sequence'))target=(await journalCall('image_calibrate',{object_id:target,calibration_object_id:calibration.calibration_id})).data.object_id;
  return target;
 };
 const checkSelection=value=>{fields(value,['kind','coordinate_space','source_object_id','coordinates','panel']);const lengths={point:2,line:4,arrow:4,rectangle:4,polygon:null},c=value.coordinates;if(!(value.kind in lengths)||!Array.isArray(c)||!c.every(Number.isFinite)||!objectId.test(value.source_object_id??'')||(value.kind==='polygon'?(c.length<6||c.length>64||c.length%2):c.length!==lengths[value.kind]))fail('Invalid scientific selection');const p=current.panels?.find(p=>p.source_object_id===value.source_object_id&&sameRecord(p,value.panel));if(!p)fail('Selection must use an exact current panel');const space={frequency:'frequency_cycles_per_pixel',spatial_pixels:'source_pixels',source_array_indices:'source_array_indices'}[p.domain];if(value.coordinate_space!==space)fail('Selection coordinate domain mismatch');const edges=['rectangle','polygon'].includes(value.kind);let bounds;if(p.domain==='frequency'){const [h,w]=p.fft_shape_yx,[x0,y0,x1,y1]=p.fft_rect_xyxy??[0,0,w,h],margin=edges?.5:0;bounds=[(x0-Math.floor(w/2)-margin)/w,(y0-Math.floor(h/2)-margin)/h,(x1-1-Math.floor(w/2)+margin)/w,(y1-1-Math.floor(h/2)+margin)/h];}else{const [x0,y0,x1,y1]=p.source_rect_xyxy;bounds=[x0,y0,edges?x1:x1-1,edges?y1:y1-1];}for(let i=0;i<c.length;i++)if(c[i]<bounds[i%2]-1e-12||c[i]>bounds[i%2+2]+1e-12)fail('Selection lies outside current source window');if(value.kind==='rectangle'&&(c[0]>=c[2]||c[1]>=c[3]))fail('Rectangle needs increasing nonempty edges');if(['line','arrow'].includes(value.kind)&&c[0]===c[2]&&c[1]===c[3])fail('Line needs distinct endpoints');return structuredClone(value);};
 const act=async body=>{
  fields(body,['expected_object_id','draft_revision','action','params','lightweight']);if(body.lightweight!==undefined&&(body.action!=='draft'||typeof body.lightweight!=='boolean'))fail('lightweight is an explicit boolean for draft acknowledgments only');if(body.expected_object_id!==current.object_id)fail('Stale object revision; reload before editing',409);const p=body.params??{},startedRevision=body.draft_revision??editState.draft_revision;let r,figureRestore=null;
  if(!Number.isSafeInteger(startedRevision)||startedRevision<0)fail('Invalid draft_revision');
  if(body.action==='draft'){const previousDraft=editState;fields(p,['draft_revision','dirty','gesture_active','selection','annotation_edit']);if(!Number.isSafeInteger(p.draft_revision)||p.draft_revision<editState.draft_revision||typeof p.dirty!=='boolean'||typeof p.gesture_active!=='boolean')fail('Invalid or stale draft revision',409);const picked=p.selection==null?null:checkSelection(p.selection);let annotationEdit=editState.annotation_edit??null;if(p.annotation_edit!==undefined){annotationEdit=null;if(p.annotation_edit!==null){const u=p.annotation_edit;fields(u,['annotation_id','coordinates','text','color','status','presentation']);if(u.presentation!==undefined)validate(u.presentation,annotationPresentation,'presentation');const mark=(current.annotations??[]).find(m=>m.annotation_id===u.annotation_id);if(!mark?.anchor)fail('Draft annotation must name an existing anchored mark');if(u.text!==undefined&&(typeof u.text!=='string'||u.text.length>256)||u.color!==undefined&&!['cyan','orange','white','amber','green'].includes(u.color)||u.status!==undefined&&!['hypothesized','user_confirmed','retracted'].includes(u.status))fail('Invalid annotation draft fields');const panels=(current.panels??[]).filter(p=>p.source_object_id===mark.anchor.source_object_id&&({frequency:'frequency_cycles_per_pixel',spatial_pixels:'source_pixels',source_array_indices:'source_array_indices'}[p.domain])===mark.anchor.coordinate_space);if(panels.length!==1)fail('Draft annotation requires one exact current panel');const anchor=checkSelection({...mark.anchor,kind:mark.kind,coordinates:u.coordinates??mark.anchor.coordinates,panel:panels[0]});annotationEdit={...structuredClone(u),kind:mark.kind,coordinate_space:anchor.coordinate_space,source_object_id:anchor.source_object_id,panel:anchor.panel};}}editState={draft_revision:p.draft_revision,dirty:p.dirty,gesture_active:p.gesture_active,selection:p.selection===undefined?editState.selection:picked,annotation_edit:annotationEdit,base_object_id:current.object_id};if(p.selection!==undefined)selection=picked;saveSelection({coalesce:previousDraft.gesture_active===editState.gesture_active&&previousDraft.dirty===editState.dirty});return body.lightweight?draftAck():state();}
  if(body.action==='accept-result'){fields(p,[]);if(editState.dirty||editState.gesture_active)fail('Save or explicitly discard draft before viewing pending result',409);if(pendingResult){const selected=selection;commitCurrent(pendingResult.prepared,{annotationIds:pendingResult.annotationIds});if(pendingResult.preserve_selection)selection=selected;frameIdentity=pendingResult.frameIdentity;lastOperation={action:'accept-result',object_id:current.object_id,request_id:pendingResult.request_id,...(pendingResult.annotationIds?.length?{annotation_ids:pendingResult.annotationIds}:{})};pendingResult=null;saveSelection();}return state();}
  if(body.action==='select'){fields(p,['selection']);selection=checkSelection(p.selection);saveSelection();return state();}
  if(body.action==='research-observation'){
   fields(p,['source_text','authority']);if(typeof p.source_text!=='string'||!p.source_text.trim()||p.source_text.length>1000||!['user_confirmed','synthetic_fixture'].includes(p.authority))fail('Provide a bounded observation statement and its explicit human or synthetic authority');
   const baseObjectId=current.object_id,baseRevision=stateRevision,baseFrameIdentity=structuredClone(frameIdentity);
   r=await journalCall('image_context',{object_id:baseObjectId,metadata:{research_observation:{kind:'twinning_present',source_text:p.source_text,authority:p.authority}}});
   // The provider object is the scientific record. Keep only its reference in
   // panel state; neither swap the saved image nor consume a local draft.
   return saveResearchObservation(r.data,{baseObjectId,baseRevision,baseFrameIdentity});
  }
  if(body.action==='preview'){fields(p,['gamma','display_range','max_size','upscale','interpolation','frequency_rect','spectrum_axes','scale_bar']);r=await journalCall('image_preview',{...p,object_id:current.object_id});}
  else if(body.action==='restore-figure-display'){
   fields(p,['recipe']);if(editState.dirty||editState.gesture_active||pendingResult)fail('Save or resolve the current draft/result before restoring a figure display',409);
   readFigureRecipe(p.recipe,state());
   const display=figureDisplayParameters(p.recipe.display_recipe,p.recipe.source.panels),saved=(await journalCall('image_info',{object_id:p.recipe.source_object_id})),savedDisplay=await prepareCurrent(saved),savedFrame=await findFrameIdentity(saved.data);
   if(!sameRecord(recipeIdentity({object:saved.data,frame_identity:savedFrame}),p.recipe.source)||!sameRecord(figureDisplayParameters(savedDisplay.display,saved.data.panels),display))fail('Figure recipe does not match its authoritative saved source/display version',409);
   const args={...display},existing=figureDisplayParameters(effectiveDisplay,current.panels);
   // Constant automatically ranged images have equal saved limits. The worker
   // admits those only through unchanged inherited range, never explicit limits.
   if(args.display_range[0]===args.display_range[1]){
    if(!sameRecord(existing.display_range,args.display_range)||existing.representation!==args.representation||!sameRecord(existing.spectrum_filter??null,args.spectrum_filter??null))fail('Cannot safely restore a constant display range from this current rendering; open the original display version',409);
    delete args.display_range;
   }
   figureRestore={source:structuredClone(p.recipe.source),display,annotations:structuredClone(annotationIdentity(current))};
   try{r=await journalCall('image_preview',{object_id:current.object_id,...args});lastOperation={...lastOperation,action:'restore-figure-display',figure_restore:figureRestore};saveSelection();}
   catch(error){lastOperation={...lastOperation,action:'restore-figure-display',figure_restore:figureRestore};saveSelection();throw error;}
  }
  else if(body.action==='frame'){fields(p,['frame_index']);r=await journalCall('image_frame',{object_id:await sourceForFrame(),frame_index:p.frame_index});const target=await withCurrentContext(r.data.object_id,{newFrame:true});r=await journalCall('image_preview',{object_id:target,...framePreviewRecipe(current,effectiveDisplay)});}
  else if(body.action==='roi'||body.action==='fft'){fields(p,body.action==='fft'?['selection','window','subtract_mean']:['selection']);if(body.action==='fft'&&(p.window!==undefined&&!['hann','none'].includes(p.window)||p.subtract_mean!==undefined&&typeof p.subtract_mean!=='boolean'))fail('Invalid explicit FFT preprocessing');const selected=checkSelection(p.selection),rect=selectionRectangle(selected);if(selected.panel.domain==='frequency'){if(body.action==='fft')fail('FFT needs a spatial ROI, not a frequency crop');r=await journalCall('image_preview',{object_id:current.object_id,frequency_rect:rect});}else {if(selected.panel.domain!=='spatial_pixels')fail('Imported frequency arrays have no spatial ROI mapping');const target=await withCurrentContext(selected.source_object_id),recipe=Object.fromEntries(['gamma','display_range','max_size','upscale','interpolation'].filter(key=>effectiveDisplay?.[key]!==undefined).map(key=>[key,effectiveDisplay[key]]));r=await journalCall(body.action==='fft'?'image_fft':'image_preview',{object_id:target,rect,...(body.action==='fft'?{window:p.window??'hann',subtract_mean:p.subtract_mean??true}:recipe)});}}
  else if(body.action==='mark'){fields(p,['selection','annotation_id','text','color','status','presentation']);if(p.presentation!==undefined)validate(p.presentation,annotationPresentation,'presentation');const selected=checkSelection(p.selection);if(p.annotation_id===undefined)p.annotation_id=`mark-${randomBytes(8).toString('hex')}`;if(!safeId.test(p.annotation_id))fail('Invalid annotation_id');const old=current.annotations??[];if(old.some(m=>m.annotation_id===p.annotation_id))fail('annotation_id already exists; choose it in the edit list');const {panel,...anchor}=selected;r=await journalCall('image_annotate',{object_id:current.object_id,annotations:[...old.map(originalMark),{...anchor,annotation_id:p.annotation_id,text:p.text??'',color:p.color??'cyan',status:p.status??'hypothesized',...(p.presentation!==undefined?{presentation:p.presentation}:{})}]});}
  else if(body.action==='edit'){fields(p,['updates','auto_commit']);if(p.auto_commit!==undefined&&typeof p.auto_commit!=='boolean')fail('auto_commit must be an explicit boolean');if(!Array.isArray(p.updates)||p.updates.length!==1)fail('Edit exactly one existing annotation per gesture');const u=p.updates[0];fields(u,['annotation_id','coordinates','text','color','status','note','presentation','presentation_replace']);presentationUpdate(u);if(!(current.annotations??[]).some(m=>m.annotation_id===u.annotation_id))fail('Unknown annotation_id');r=await journalCall('image_annotate',{object_id:current.object_id,updates:p.updates});}
  else if(body.action==='edit-layout'){
   fields(p,['updates','auto_commit']);if(p.auto_commit!==undefined&&typeof p.auto_commit!=='boolean')fail('auto_commit must be an explicit boolean');
   if(!Array.isArray(p.updates)||!p.updates.length||p.updates.length>100)fail('Layout edits require 1..100 existing annotations');
   const ids=new Set();
   for(const u of p.updates){fields(u,['annotation_id','presentation','presentation_replace']);if(u.presentation===undefined)fail('Layout edits require presentation metadata');presentationUpdate(u);
    if(!(current.annotations??[]).some(m=>m.annotation_id===u.annotation_id)||ids.has(u.annotation_id))fail('Layout edits require distinct existing annotation IDs');ids.add(u.annotation_id);}
   r=await journalCall('image_annotate',{object_id:current.object_id,updates:p.updates});
  }
  else if(body.action==='statistics'||body.action==='profile'){
   fields(p,body.action==='statistics'?['selection','component']:['selection','component','sample_count']);
   const selected=checkSelection(p.selection);
   if((current.panels??[]).length!==1)fail('Inspect one explicit scientific input, not a comparison composite');
   let args={object_id:current.object_id,component:p.component??'raw'};
   if(body.action==='statistics'){
    if(selected.kind!=='rectangle')fail('Draw an explicit ROI for array statistics');
    args={...args,[selected.panel.domain==='frequency'?'frequency_rect':'rect']:selectionRectangle(selected)};
   }else{
    if(!['line','arrow'].includes(selected.kind)||selected.coordinates.length!==4)fail('Draw a two-point line for an intensity profile');
    args={...args,points:[selected.coordinates.slice(0,2),selected.coordinates.slice(2)],coordinate_space:selected.coordinate_space,sample_count:p.sample_count??128,line_width:1,interpolation:'nearest'};
   }
   r=await journalCall(body.action==='statistics'?'image_statistics':'image_profile',args);
   numericResults[body.action]=r.data;lastOperation={...r.data};selection=selected;saveSelection();return state();
  }
  else if(body.action==='measurement-jump'){
   fields(p,['measurement_object_id']);
   const entry=readImageMeasurements({workspace,objectId:current.object_id}).entries.find(value=>value.object_id===p.measurement_object_id);
   if(!entry)fail('Measurement is not in this source workspace',404);
   if(editState.dirty||editState.gesture_active)fail('Save or discard drafts before explicitly jumping to a historical view',409);
   r=await displayObject(await journalCall('image_info',{object_id:entry.input_object_id}));
  }
  else if(body.action==='measure'){
   fields(p,['selection','annotation_id','measurement_object_id']);const selected=checkSelection(p.selection),domain=selected.panel.domain;
   const mark=p.annotation_id===undefined?null:(current.annotations??[]).find(value=>value.annotation_id===p.annotation_id);
   if(p.annotation_id!==undefined&&(!mark||mark.kind!==selected.kind||!sameRecord(mark.anchor?.coordinates,selected.coordinates)||mark.anchor?.source_object_id!==selected.source_object_id||mark.anchor?.coordinate_space!==selected.coordinate_space))fail('Measurement mark does not match the exact saved scientific selection',409);
   const spectral=domain==='frequency',scalar=domain==='source_array_indices',peak=selected.kind==='point';
   if(!['frequency','source_array_indices','spatial_pixels'].includes(domain))fail('Unsupported measurement domain');
   let dc=null;
   if(peak){
    if(spectral)dc=[0,0];
    else if(scalar){
     const record=current.xy_calibration;
     if(record?.status!=='active'||record.coordinate_domain!=='reciprocal_space'||
        !Array.isArray(record.dc_index_xy)||record.dc_index_xy.length!==2||!record.dc_index_xy.every(Number.isFinite))
       fail('A reciprocal peak requires an active calibration with an explicit DC; draw a two-point line for pixel geometry');
     dc=record.dc_index_xy;
    }else fail('Draw a two-point spatial line, or choose a reciprocal peak with an explicit DC');
   }else if(selected.coordinates.length!==4||!['line','arrow'].includes(selected.kind))fail('Draw a two-point line or select a reciprocal peak');
   // measurement_operand resolves the saved view/annotation and its selected
   // calibration. Measure that exact revision without intermediate writes.
   const target=current.object_id;
   const args={object_id:target,points:peak?[dc,selected.coordinates]:[selected.coordinates.slice(0,2),selected.coordinates.slice(2)],
    coordinate_space:spectral?'frequency_cycles_per_pixel':scalar?'source_array_indices':'source_pixels'};
   if(p.measurement_object_id!==undefined){
    const entry=readImageMeasurements({workspace,objectId:current.object_id}).entries.find(value=>value.object_id===p.measurement_object_id);
    if(!entry||p.annotation_id&&entry.annotation_id!==p.annotation_id)fail('Original measurement is not bound to this annotation/source',409);
    r=await journalCall('image_remeasure',{object_id:target,measurement_object_id:entry.object_id,points:args.points,source_text:'Researcher revised or remeasured this exact saved GUI selection; no phase confirmation.'});
   }else r=await journalCall('image_measure',args);
   if(mark)writeMeasurementLink(workspace,{measurement_object_id:r.data.object_id,input_object_id:target,annotation_id:mark.annotation_id,measurement_kind:Number.isInteger(r.data.dc_reference_point_index)?'dc_to_peak':'two_point',name:mark.text??'',...(p.measurement_object_id?{previous_measurement_object_id:p.measurement_object_id}:{})});
   lastOperation={...publicObject(r.data),...(mark?{annotation_id:mark.annotation_id}:{}),...(peak?{reference:spectral?'mathematical DC [0,0]; geometric period, not phase identification':'recorded calibrated DC; not an independently verified beam centre'}:{})};
   selection=selected;saveSelection();return state();
  }
  else if(body.action==='calibrate'){fields(p,['scope','xy_scale','source_text','coordinate_domain']);r=await displayObject(await journalCall('image_calibrate',{object_id:current.object_id,...p}));}
  else if(body.action==='figure-base'){
   fields(p,[]);
   const spectral=(current.panels??[]).some(panel=>panel.domain==='frequency');
   let step='scale';
   try{
    let bar=current.scale_bar?.visible?structuredClone(current.scale_bar):null;
    if(!spectral&&current.xy_calibration?.status==='active'&&current.xy_calibration.coordinate_domain==='real_space'&&!bar){
     const scaled=await journalCall('image_preview',{object_id:current.object_id,scale_bar:true});
     if(!sameRecord(scaled.data.panels??[],current.panels??[]))fail('Scale-bar source/render mapping changed',409);
     bar=scaled.data.scale_bar??null;
    }
    figureBars.set(current.object_id,bar);step='clean';
    r=await journalCall('image_preview',{object_id:current.object_id,...(spectral?{spectrum_axes:false}:{scale_bar:false})});
    lastOperation={action:'figure-base',figure_step:'clean',object_id:r.data.object_id,request_id:r.data.request_id,state:'completed'};
    const result=await figureAsset(r);saveSelection();return result;
   }catch(error){lastOperation={...lastOperation,action:'figure-base',figure_step:step};saveSelection();throw error;}
  }
  else if(body.action==='export'){fields(p,[]);mkdirSync(path.join(workspace,'exports'),{recursive:true});const output_dir=path.join(workspace,'exports',`panel-${session}-${sequence+1}`);r=await journalCall('image_export',{object_id:current.object_id,output_dir});lastOperation={...publicObject(r.data),output_dir};saveSelection();return state();}
  else if(body.action==='show'){
   fields(p,['object_id','source_view']);if(!objectId.test(p.object_id??''))fail('Explicit existing object_id required');if(p.source_view!==undefined&&p.source_view!==true)fail('source_view must be true when provided');
   if(p.source_view){if(p.object_id!==frameIdentity?.frame_object_id)fail('Source view must name this exact frame',409);const target=await withCurrentContext(p.object_id);r=await journalCall('image_preview',{object_id:target});}
   else r=await displayObject(await journalCall('image_info',{object_id:p.object_id}));
  }
  else if(body.action==='recover'){fields(p,['request_id']);if(p.request_id!==undefined&&(typeof p.request_id!=='string'||!safeId.test(p.request_id)))fail('Valid original request_id required');let operation=lastOperation;const original=p.request_id??operation?.request_id;if(!safeId.test(original??''))fail('No valid saved request to query');if(p.request_id!==undefined){if(!existsSync(path.join(journal,`${original}.request.json`)))fail('Original request is not journaled by this panel',404);if(operation?.request_id!==original)operation={request_id:original};}r=await journalCall('image_result',{request_id:original});if(!r.data.object_id)fail('Original request has not returned an image object');if(operation.action==='figure-base'){if(operation.figure_step==='scale'){figureBars.set(current.object_id,r.data.scale_bar??null);return {...state(),figure_base_recovery:{state:'scale_render_saved_clean_render_not_submitted',request_id:original,object_id:r.data.object_id}};}return figureAsset(r);}if(operation.action==='restore-figure-display')figureRestore=operation.figure_restore;if(r.data.kind==='context'&&r.data.user_context?.research_observation)return saveResearchObservation(r.data);if(['statistics','profile'].includes(r.data.kind)){numericResults[r.data.kind]=r.data;lastOperation=r.data;saveSelection();return state();}if(['measure','export'].includes(r.data.kind)){lastOperation=publicObject(r.data);saveSelection();return state();}r=await displayObject(r);}
  else fail('Unknown panel action');
  const prepared=await prepareCurrent(r),nextFrame=await findFrameIdentity(r.data);
  if(figureRestore)verifyFigureDisplay(prepared,nextFrame,figureRestore);
  const annotationIds=body.action==='mark'?[p.annotation_id]:['edit','edit-layout'].includes(body.action)?p.updates.map(value=>value.annotation_id):[];
  const affected={...(annotationIds.length?{annotation_ids:annotationIds}:{}),...(figureRestore?{figure_restore:figureRestore}:{})};
  const layoutEdit=body.action==='edit-layout',autoEdit=body.action==='edit'&&p.auto_commit===true||layoutEdit&&p.auto_commit!==false;
  if(layoutEdit||autoEdit){
   if(!sameRecord(prepared.object.panels??[],current.panels??[])||!sameRecord(prepared.object.scientific_grid_identity??null,current.scientific_grid_identity??null))fail('Automatic annotation adoption requires the exact same scientific grid and render mapping',409);
  }
  if(autoEdit){
   const newerDraft=editState.draft_revision!==startedRevision||editState.gesture_active,latestEdit=structuredClone(editState),latestSelection=selection;
   commitCurrent(prepared,{annotationIds});frameIdentity=nextFrame;
   if(layoutEdit)selection=latestSelection;
   if(newerDraft){editState={...latestEdit,base_object_id:current.object_id};selection=latestSelection;}
   lastOperation={action:body.action,object_id:current.object_id,request_id:current.request_id,...affected};
   saveSelection();return {...state(),auto_edit_committed:true};
  }
  if(editState.draft_revision!==startedRevision||editState.gesture_active){pendingResult={prepared,frameIdentity:nextFrame,request_id:r.data.request_id,annotationIds,...(layoutEdit?{preserve_selection:true}:{})};lastOperation={action:body.action,object_id:r.data.object_id,request_id:r.data.request_id,state:'completed_pending_view',...affected};}else{const selected=selection;commitCurrent(prepared,{annotationIds});if(layoutEdit)selection=selected;frameIdentity=nextFrame;lastOperation={action:body.action,object_id:current.object_id,request_id:current.request_id,...affected};}
  saveSelection();return state();
 };
 const presentationDirectory=path.join(journal,'presentations');mkdirSync(presentationDirectory,{recursive:true});
 const presentationReceipt=id=>{if(!safeId.test(id??''))fail('Valid original request_id required');const response=path.join(presentationDirectory,`${id}.response.json`);if(existsSync(response))return JSON.parse(readFileSync(response,'utf8'));if(existsSync(path.join(presentationDirectory,`${id}.request.json`)))return {presentation:{request_id:id,status:'pending',limitation:'query original ID; never automatically resubmit'}};fail('Presentation request not found',404);};
 const present=async body=>{
  fields(body,['object_id','expected_object_id','draft_revision','request_id']);
  if(!objectId.test(body.object_id??'')||!objectId.test(body.expected_object_id??'')||!safeId.test(body.request_id??'')||!Number.isSafeInteger(body.draft_revision)||body.draft_revision<0)fail('Explicit object, expected view, draft revision and original request ID required');
  const file=path.join(presentationDirectory,`${body.request_id}.request.json`);
  if(existsSync(file)){const prior=JSON.parse(readFileSync(file,'utf8'));if(['object_id','expected_object_id','draft_revision','request_id'].some(key=>prior[key]!==body[key]))fail('Presentation request ID parameter conflict',409);return presentationReceipt(body.request_id);}
  if(body.expected_object_id!==current.object_id)fail('Stale panel object; read current selection again',409);
  if(pendingResult)fail('Resolve pending result before presenting another result',409);
  writeJournal(file,body);
  try{
   const r=await displayObject(await journalCall('image_info',{object_id:body.object_id})),prepared=await prepareCurrent(r),nextFrame=await findFrameIdentity(r.data);
   const queued=editState.dirty||editState.gesture_active||editState.draft_revision!==body.draft_revision;
   if(queued)pendingResult={prepared,frameIdentity:nextFrame,request_id:body.request_id};else{commitCurrent(prepared);frameIdentity=nextFrame;}
   saveSelection();const response={...state(),presentation:{request_id:body.request_id,status:queued?'queued':'shown',object_id:r.data.object_id}};writeJournal(path.join(presentationDirectory,`${body.request_id}.response.json`),response);return response;
  }catch(error){writeJournal(path.join(presentationDirectory,`${body.request_id}.response.json`),{presentation:{request_id:body.request_id,status:'failed',error:error.message}});throw error;}
 };
 const staticFiles=new Map([['/',['index.html','text/html; charset=utf-8']],['/app.mjs',['app.mjs','text/javascript; charset=utf-8']],['/coordinates.mjs',['coordinates.mjs','text/javascript; charset=utf-8']],['/style.css',['style.css','text/css; charset=utf-8']],['/viewer-state.mjs',['viewer-state.mjs','text/javascript; charset=utf-8']],['/viewer-render.mjs',['viewer-render.mjs','text/javascript; charset=utf-8']],['/annotation-presentation.mjs',['annotation-presentation.mjs','text/javascript; charset=utf-8']],['/figure-export.mjs',['figure-export.mjs','text/javascript; charset=utf-8']],['/measurement-workspace.mjs',['measurement-workspace.mjs','text/javascript; charset=utf-8']],['/data-probes.mjs',['data-probes.mjs','text/javascript; charset=utf-8']],['/user-workflow.mjs',['user-workflow.mjs','text/javascript; charset=utf-8']]]);
 const server=http.createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
  try{
   const origin=`http://127.0.0.1:${server.address().port}`;if(req.headers.host!==`127.0.0.1:${server.address().port}`)fail('Invalid Host',403);const url=new URL(req.url,origin);
   if(req.method==='GET'&&staticFiles.has(url.pathname)){const [file,type]=staticFiles.get(url.pathname);res.setHeader('Content-Type',type);res.end(readFileSync(path.join(root,'ui','image-panel',file)));return;}
   const supplied=req.headers['x-panel-token'];if(typeof supplied!=='string'||Buffer.byteLength(supplied)!==Buffer.byteLength(token)||!timingSafeEqual(Buffer.from(supplied),Buffer.from(token)))fail('Panel token required',403);
   if(req.headers.origin&&req.headers.origin!==origin)fail('Cross-origin requests refused',403);
   res.setHeader('Content-Type','application/json');
   if(req.method==='GET'&&url.pathname==='/api/state'){res.end(JSON.stringify(state()));return;}
   if(req.method==='GET'&&url.pathname==='/api/measurements'){
    if([...url.searchParams.keys()].some(key=>key!=='object_id')||url.searchParams.get('object_id')!==current.object_id)fail('Measurement inspection requires the exact current object',409);
    const inspected=current.object_id,revision=stateRevision;
    const records=readImageMeasurements({workspace,objectId:inspected});
    res.end(JSON.stringify({...records,object_id:inspected,state_revision:revision}));return;
   }
   if(req.method==='GET'&&url.pathname==='/api/revision'){res.end(JSON.stringify({state_revision:stateRevision,object_id:current.object_id,pending_result:pendingResult?{object_id:pendingResult.prepared.object.object_id,request_id:pendingResult.request_id}:null,edit_state:{draft_revision:editState.draft_revision,dirty:editState.dirty,gesture_active:editState.gesture_active}}));return;}
   if(req.method==='GET'&&url.pathname==='/api/present'){res.end(JSON.stringify(presentationReceipt(url.searchParams.get('request_id'))));return;}
   if(req.method!=='POST'||!['/api/action','/api/present','/api/probe'].includes(url.pathname))fail('Not found',404);if(req.headers.origin!==origin||!req.headers['content-type']?.startsWith('application/json'))fail('Same-origin JSON required',403);
   let raw='',size=0;for await(const chunk of req){size+=chunk.length;if(size>64*1024)fail('Request exceeds 64 KiB',413);raw+=chunk;}let body;try{body=JSON.parse(raw);}catch{fail('Invalid JSON');}
   if(url.pathname==='/api/probe'){
    fields(body,['expected_object_id','source_object_id','coordinate_space','coordinates','component']);
    if(body.expected_object_id!==current.object_id)fail('Probe belongs to a changed current image',409);
    if((current.panels??[]).length!==1)fail('Inspect a single scientific array, not a comparison PNG');
    const selected=checkSelection({kind:'point',source_object_id:body.source_object_id,coordinate_space:body.coordinate_space,coordinates:body.coordinates,panel:current.panels[0]}),id=current.object_id,revision=stateRevision;
    const result=await client.tool('image_probe',{object_id:id,points:[selected.coordinates],coordinate_space:selected.coordinate_space,component:body.component??'raw'});
    if(current.object_id!==id||stateRevision!==revision)fail('Probe completed for an older image revision',409);
    if(result.data.object_id!==id)fail('Probe returned a foreign scientific object',409);
    res.end(JSON.stringify({...result.data,state_revision:revision}));return;
   }
   if(url.pathname==='/api/action'&&body.action==='draft'){res.end(JSON.stringify(await act(body)));return;}
   const run=busy.then(()=>url.pathname==='/api/present'?present(body):act(body));busy=run.catch(()=>{});res.end(JSON.stringify(await run));
  }catch(error){res.statusCode=error.status??400;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({error:error.message}));}
 });
 try{await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});saveSelection();}catch(error){await client.close();throw error;}
 return {server,client,url:`http://127.0.0.1:${server.address().port}/#${token}`,token,journal,state,async close(){try{await new Promise(resolve=>server.close(resolve));saveSelection();}finally{if(selectionTimer!==null){clearTimeout(selectionTimer);selectionTimer=null;}await client.close();}}};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const options={};for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i],value=process.argv[i+1];if(!['--workspace','--python','--object','--port','--selection','--connection-file','--panel-id'].includes(key)||!value)throw new Error('Usage: node tools/image_panel.mjs --workspace ABS --python ABS --object ID [--port 0]; --selection ABS_CURRENT_SELECTION_JSON');options[key.slice(2)]=value;}
 if(options.selection){if(!path.isAbsolute(options.selection)||!existsSync(options.selection))throw new Error('Existing absolute selection record required');process.stdout.write(readFileSync(options.selection));}
 else {if(options['connection-file']&&(!path.isAbsolute(options['connection-file'])||!objectId.test(options['panel-id']??'')||existsSync(options['connection-file'])))throw new Error('Absolute new connection file and random panel ID required');const panel=await createImagePanel({workspace:options.workspace,python:options.python,object_id:options.object,port:Number(options.port??0),panel_id:options['panel-id']??null});if(options['connection-file']){if(!path.isAbsolute(options['connection-file'])||!objectId.test(options['panel-id']??''))throw new Error('Absolute new connection file and random panel ID required');const temporary=options['connection-file']+'.'+randomBytes(8).toString('hex')+'.tmp';try{writeJournal(temporary,{schema_version:1,panel_id:options['panel-id'],port:panel.server.address().port,token:panel.token,pid:process.pid});linkSync(temporary,options['connection-file']);}finally{if(existsSync(temporary))unlinkSync(temporary);}}process.stdout.write(JSON.stringify({url:panel.url,selection_path:path.join(panel.journal,'current-selection.json')})+'\n');let closing=false;const close=async()=>{if(!closing){closing=true;await panel.close();}};process.on('SIGINT',close);process.on('SIGTERM',close);}
}
