// UI-only interaction policy. Scientific records and their recovery stay in the provider.
const copy=value=>JSON.parse(JSON.stringify(value));
const canonical=value=>JSON.stringify(value??null,(_k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
export function workflowScope(state){
 return canonical({frame:state?.frame_identity?.frame_object_id??null,panels:(state?.object?.panels??[]).map(p=>({source:p.source_object_id,domain:p.domain,rect:p.source_rect_xyxy??null,fft:p.fft_shape_yx??null,window:p.fft_rect_xyxy??null}))});
}
// A display slider, selection and saved mark share ONE chronological action list.
// This holds presentation/command references, never a second scientific image.
export class UserActionHistory{
 constructor(limit=80){this.limit=limit;this.undoItems=[];this.redoItems=[];this.group=null;}
 push(entry,{group=null}={}){
  if(canonical(entry.before)===canonical(entry.after))return false;
  const item=copy(entry),last=this.undoItems.at(-1);
  if(group&&this.group===group&&last?.kind===item.kind&&last.scope===item.scope)last.after=item.after;
  else {this.undoItems.push(item);if(this.undoItems.length>this.limit)this.undoItems.shift();}
  this.group=group;this.redoItems.length=0;return true;
 }
 endGroup(){this.group=null;}
 peek(direction='undo'){return (direction==='undo'?this.undoItems:this.redoItems).at(-1)??null;}
 finish(direction,item){const from=direction==='undo'?this.undoItems:this.redoItems,to=direction==='undo'?this.redoItems:this.undoItems;if(from.at(-1)!==item)throw new Error('History changed before the action was accepted');from.pop();to.push(item);this.endGroup();}
 reset(){this.undoItems.length=0;this.redoItems.length=0;this.endGroup();}
}
export function selectionActionReason(action,picked,object={}){
 const domain=picked?.panel?.domain,kind=picked?.kind,coords=picked?.coordinates;
 if(action==='full')return object.panels?.some(p=>p.domain==='frequency')?'':'当前不是可放大的复数 FFT 视图';
 if(!picked||!Array.isArray(coords)||!coords.every(Number.isFinite))return '先在图中选择区域、点或线';
 if(action==='select')return '';
 if(action==='roi')return kind==='rectangle'&&['spatial_pixels','frequency'].includes(domain)?'':'请选择可查看的实空间或 FFT 矩形 ROI';
 if(action==='statistics')return kind==='rectangle'&&['spatial_pixels','source_array_indices','frequency'].includes(domain)?'':'请选择矩形 ROI';
 if(action==='fft')return kind==='rectangle'&&domain==='spatial_pixels'?'':'局部 FFT 需要实空间矩形 ROI';
 if(action==='profile')return ['line','arrow'].includes(kind)&&coords.length===4?'':'请画一条线以读取强度剖面';
 if(action==='measure'){
  if(['line','arrow'].includes(kind)&&coords.length===4)return '';
  if(kind==='point'&&domain==='frequency')return '';
  if(kind==='point'&&domain==='source_array_indices'){
   const c=object.xy_calibration;
   if(c?.status==='active'&&c.coordinate_domain==='reciprocal_space'&&Array.isArray(c.dc_index_xy)&&c.dc_index_xy.length===2&&c.dc_index_xy.every(Number.isFinite))return '';
   return '此倒空间数组尚无有效中心；请画线测两点距离';
  }
  return '测量需要线段或已知中心的倒空间峰；ROI 请用统计';
 }
 return '';
}
export function measurementLabel(picked,count){return picked?.kind==='point'&&['frequency','source_array_indices'].includes(picked.panel?.domain)?`g${count}`:`测距 ${count}`;}
// Frequency display ranges are not real-space intensities. Keep a fixed range
// only for an already spatial view; returning via saved-view navigation uses
// that saved object's own display recipe instead.
export function framePreviewRecipe(object,display){
 const spatial=object?.panels?.length>0&&object.panels.every(p=>p.domain==='spatial_pixels');
 if(!display)return {};
 return Object.fromEntries((spatial?['gamma','display_range','max_size']:['max_size']).filter(k=>display[k]!==undefined).map(k=>[k,copy(display[k])]));
}
export class SavedViewHistory{
 constructor(limit=40){this.limit=limit;this.entries=[];this.index=-1;}
 remember(state,{replace=false,role=null}={}){
  const id=state?.object?.object_id;if(!id)return;
  const found=this.entries.findIndex(e=>e.id===id);
  if(found>=0){this.index=found;return;}
  const prior=this.entries[this.index],frequency=state.object.panels?.some(p=>p.domain==='frequency');
  // A directly reopened spatial object can be a cropped saved view. Its
  // existence does not prove that this browser has the full-source recipe.
  const entry={id,frame:state.frame_identity?.frame_object_id??null,scope:workflowScope(state),role:role??(replace?prior?.role:null)??(frequency?'FFT':'保存视图')};
  if(replace&&prior&&entry.scope===prior.scope)this.entries[this.index]=entry;
  else{this.entries.splice(this.index+1);this.entries.push(entry);if(this.entries.length>this.limit)this.entries.shift();this.index=this.entries.length-1;}
 }
 target(offset){return this.entries[this.index+offset]??null;}
 original(state){const frame=state?.frame_identity?.frame_object_id;return this.entries.find(e=>['原图','全帧（新显示）'].includes(e.role)&&e.frame===frame)??(frame?{id:frame,role:'全帧（新显示）',frame,freshSourceView:true}:null);}
}
