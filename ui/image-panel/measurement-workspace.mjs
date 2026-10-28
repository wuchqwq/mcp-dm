// Read-only table projection of the provider's saved measurements. Scientific
// values are never reconstructed from annotation text or preview pixels.
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const asRecord=entry=>entry.measurement??entry;
const statusNames={current:'当前',active:'当前',historical:'历史',history:'历史',stale:'待重测',needs_remeasure:'待重测',needs_remeasurement:'待重测',unknown:'未知'};
export function requiresMeasurementJump(entry){return Boolean(entry&&(!entry.same_grid||!entry.visible_in_current_view||!entry.annotation_matches_current));}
const unitText=value=>typeof value==='string'&&value.trim()?value:'未知';
export const measurementNumber=value=>finite(value)?Number(value.toPrecision(7)).toString():'未知';
export function measurementValues(entry){
 const m=asRecord(entry),result=[];
 if(finite(m.physical_distance))result.push({kind:'distance',label:'距离',value:m.physical_distance,unit:unitText(m.physical_unit)});
 else if(finite(m.distance_physical))result.push({kind:'distance',label:'距离',value:m.distance_physical,unit:unitText(m.physical_unit)});
 if(finite(m.physical_frequency_magnitude))result.push({kind:'frequency',label:'|g|',value:m.physical_frequency_magnitude,unit:unitText(m.physical_frequency_unit)});
 // Only an explicit DC-to-peak result may be called d. A two-peak difference
 // can have a reciprocal period, but that is not an identified plane spacing.
 if(finite(m.d_spacing))result.push({kind:'d_spacing',label:'DC→峰周期',value:m.d_spacing,unit:unitText(m.d_spacing_unit)});
 else if(finite(m.period))result.push({kind:'period',label:'差矢量周期',value:m.period,unit:unitText(m.period_unit)});
 if(!result.length&&finite(m.distance_pixels))result.push({kind:'pixel_distance',label:'图像坐标距离',value:m.distance_pixels,unit:'px'});
 if(!result.length&&finite(m.frequency_distance_cycles_per_pixel))result.push({kind:'pixel_frequency',label:'频率差',value:m.frequency_distance_cycles_per_pixel,unit:'cycles/pixel'});
 return result;
}
export function measurementType(entry){const m=asRecord(entry);if(m.coordinate_space==='frequency_cycles_per_pixel'||m.measurement_domain==='reciprocal_space')return m.dc_reference_point_index===0||m.dc_reference_point_index===1?'DC→峰':'两点差矢量';return '两点距离';}
export function measurementName(entry){return entry.name??entry.annotation_name??entry.annotation_id??`测量 ${asRecord(entry).object_id?.slice(0,8)??'未知'}`;}
export function measurementStatus(entry){return statusNames[entry.status]??'未知';}
export function measurementDetails(entry){
 const m=asRecord(entry),scope=entry.source??entry.scope??{},cal=m.xy_calibration??m.calibration_record,grid=m.scientific_grid_identity??scope.scientific_grid_identity??{};
 return [
  ['类型',measurementType(entry)],['状态',measurementStatus(entry)+(entry.status_reason?' · '+entry.status_reason:'')],
  ['科学端点',Array.isArray(m.points)?JSON.stringify(m.points):'未知'],['坐标域',m.coordinate_space??'未知'],
  ['源帧',Number.isInteger(scope.frame_index)?String(scope.frame_index+1):Number.isInteger(m.frame_index)?String(m.frame_index+1):'未知'],
  ['源 ROI',Array.isArray(scope.source_rect_xyxy??grid.source_rect_xyxy??m.source_rect_xyxy)?JSON.stringify(scope.source_rect_xyxy??grid.source_rect_xyxy??m.source_rect_xyxy):'未知'],
  ['标定版本',cal?.calibration_id?`${cal.calibration_id} · v${cal.revision??'未知'}`:'无有效物理标定'],
  ['标定来源',cal?.source_text??cal?.source??'未知'],['不确定性',m.uncertainty_status??'未知'],
  ['原始结果',m.object_id??'未知'],['原始请求',m.request_id??'未知'],['输入对象',m.parent_object_id??'未知'],
  ['结果校验',entry.measurement_manifest_sha256??entry.manifest_sha256??'未知']
 ];
}
export function inspectorDetails(current={}){
 const cal=current.xy_calibration,scale=cal?.xy_scale,source=current.source_identity;
 const sourcePath=typeof source==='string'?source:source?.path??current.source_path;
 const dimensions=Array.isArray(current.shape_yx)?current.shape_yx.join(' × ')+' (Y × X)':'未知';
 const meaning=current.provenance?.data_meaning??current.user_context?.data_meaning??current.data_meaning;
 const sourceKind=['synthetic','synthetic_demo','合成演示'].includes(meaning)?'合成数据（显式声明）':({tiff:'独立 TIFF 固定来源',native_capture:'DM 原生数值捕获',imported_capture:'导入的受控数值捕获',unknown:'未知'})[current.source_kind]??current.source_kind??current.provenance_type??source?.kind??(sourcePath?'TIFF 固定来源；实验/模拟含义未声明':'未知');
 const domain=current.domain??current.array_domain;
 const domainText=({source_pixels:'实空间 / 原图像素坐标',spatial_pixels:'实空间 / 原图像素坐标',frequency_cycles_per_pixel:'倒空间 / cycles/pixel',frequency:'倒空间 / 原 FFT 频率',reciprocal:'倒空间',source_array_indices:'数值数组索引；物理域见标定',real_space:'实空间',reciprocal_space:'倒空间'})[domain]??domain??'未知';
 return [
  ['源文件',sourcePath??'未知'],['来源',sourceKind],['数据含义',meaning??'未知'],
  ['帧',Number.isInteger(current.frame_index)?String(current.frame_index+1):'未知'],
  ['科学数组',`${dimensions} · ${current.dtype??'未知 dtype'}`],['坐标域',domainText],
  ['源 ROI',Array.isArray(current.source_rect_xyxy)?JSON.stringify(current.source_rect_xyxy):'未知'],
  ['XY 标定',cal?.status==='active'&&scale?`X ${scale.x} / Y ${scale.y} ${scale.unit} / px`:'未知 / 已撤回；保留像素域'],
  ['标定来源',cal?.source_text??cal?.source??'未知'],['标定版本',cal?.calibration_id?`${cal.calibration_id} · v${cal.revision??'未知'}`:'未知'],
  ['标定不确定性',cal?.uncertainty??cal?.xy_scale?.uncertainty??'未知']
 ];
}
// Spreadsheet text is escaped separately from finite numeric fields: -0.12
// remains a useful number, while =CMD(), @..., and leading whitespace formulas
// from labels/source statements cannot execute when opened in a spreadsheet.
export function tabularCell(value,delimiter=','){
 let text;if(typeof value==='number')text=finite(value)?String(value):'';else if(value===null||value===undefined)text='';else {text=String(value);if(/^[\s\uFEFF]*[=+\-@]/u.test(text))text="'"+text;}
 return text.includes(delimiter)||/["\r\n]/u.test(text)?'"'+text.replaceAll('"','""')+'"':text;
}
export function exportMeasurementTable(entries,{delimiter=','}={}){
 if(![',','\t'].includes(delimiter))throw new Error('Only CSV and TSV are supported');
 const columns=['name','type','status','distance','distance_unit','frequency','frequency_unit','period','period_unit','d_spacing','d_spacing_unit','pixel_distance','frequency_cycles_per_pixel','point_0_x','point_0_y','point_1_x','point_1_y','coordinate_space','source_frame','source_roi','calibration_id','calibration_revision','calibration_source','result_object_id','input_object_id','request_id','manifest_sha256'];
 const rows=entries.map(entry=>{const m=asRecord(entry),scope=entry.source??entry.scope??{},cal=m.xy_calibration??m.calibration_record,points=m.points??[];return [measurementName(entry),measurementType(entry),measurementStatus(entry),m.physical_distance??m.distance_physical,m.physical_unit,m.physical_frequency_magnitude,m.physical_frequency_unit,m.period,m.period_unit,m.d_spacing,m.d_spacing_unit,m.distance_pixels,m.frequency_distance_cycles_per_pixel,points[0]?.[0],points[0]?.[1],points[1]?.[0],points[1]?.[1],m.coordinate_space,Number.isInteger(scope.frame_index)?scope.frame_index+1:null,(Array.isArray(scope.source_rect_xyxy??m.scientific_grid_identity?.source_rect_xyxy??m.source_rect_xyxy)?JSON.stringify(scope.source_rect_xyxy??m.scientific_grid_identity?.source_rect_xyxy??m.source_rect_xyxy):null),cal?.calibration_id,cal?.revision,cal?.source_text??cal?.source,m.object_id,m.parent_object_id,m.request_id,entry.measurement_manifest_sha256??entry.manifest_sha256];});
 return [columns,...rows].map(row=>row.map(cell=>tabularCell(cell,delimiter)).join(delimiter)).join('\r\n')+'\r\n';
}
export class MeasurementWorkspace {
 constructor({getState,api,onSelect=()=>{},onJump=()=>{},onUpdate=()=>{},onError=()=>{},document:doc=globalThis.document}={}){
  Object.assign(this,{getState,api,onSelect,onJump,onUpdate,onError,document:doc});this.entries=[];this.selectedId=null;this.checked=new Set();this.ticket=0;this.current=null;
  const el=id=>doc?.getElementById(id);this.el=el;
  if(el('measurement-sort'))el('measurement-sort').onchange=()=>this.render();
  if(el('measurement-history'))el('measurement-history').onchange=()=>this.render();
  if(el('measurement-jump'))el('measurement-jump').onclick=()=>this.run(()=>this.onJump(this.selected()));
  if(el('measurement-update'))el('measurement-update').onclick=()=>this.run(()=>this.onUpdate(this.selected()));
  if(el('measurement-copy'))el('measurement-copy').onclick=()=>this.run(async()=>{if(!globalThis.navigator?.clipboard?.writeText)throw new Error('当前浏览器不能复制，请下载 TSV');await globalThis.navigator.clipboard.writeText(exportMeasurementTable(this.exportSelection({selectedOnly:true}),{delimiter:'\t'}));});
  for(const [id,delimiter,extension]of [['measurement-csv',',','csv'],['measurement-tsv','\t','tsv']])if(el(id))el(id).onclick=()=>this.download(delimiter,extension);
 }
 async run(callback){try{return await callback();}catch(error){this.onError(error);}}
 selected(){return this.entries.find(entry=>asRecord(entry).object_id===this.selectedId)??null;}
 displayEntry(entry){
  const state=this.getState();if(this.current?.object_id!==state?.object?.object_id||!['current','active'].includes(entry.status)||entry.same_grid!==true||entry.annotation_matches_current!==true)return entry;
  const mark=state.object.annotations?.find(value=>value.annotation_id===entry.annotation_id);
  // A current automatic label can be saved after the immutable measurement.
  // Project its exact bound mark name only; numerical columns stay in the
  // original result and historical names are never rewritten.
  return typeof mark?.text==='string'&&mark.text.trim()?{...entry,name:mark.text}:entry;
 }
 exportSelection({selectedOnly=false}={}){const checked=this.entries.filter(entry=>this.checked.has(asRecord(entry).object_id));return (checked.length?checked:selectedOnly&&this.selected()?[this.selected()]:this.visible()).map(entry=>this.displayEntry(entry));}
 visible(){const history=this.el('measurement-history')?.checked??false;let rows=this.entries.filter(e=>history||!['historical','history'].includes(e.status)).map(entry=>this.displayEntry(entry));const sort=this.el('measurement-sort')?.value??'record';if(sort==='name')rows=rows.toSorted?rows.toSorted((a,b)=>measurementName(a).localeCompare(measurementName(b))):[...rows].sort((a,b)=>measurementName(a).localeCompare(measurementName(b)));if(sort==='value')rows=[...rows].sort((a,b)=>(measurementValues(a)[0]?.value??Infinity)-(measurementValues(b)[0]?.value??Infinity));return rows;}
 hasAnnotation(id){return Boolean(this.latestForAnnotation(id));}
 latestForAnnotation(id){const entries=this.entries.filter(e=>e.annotation_id===id);return entries.find(e=>['current','active','stale','needs_remeasure','needs_remeasurement'].includes(e.status))??entries.at(-1)??null;}
 selectAnnotation(id){const entry=this.latestForAnnotation(id);if(!entry)return false;this.select(asRecord(entry).object_id,{notify:false});this.el('measurement-rows')?.querySelector(`[data-measurement-id="${asRecord(entry).object_id}"]`)?.scrollIntoView?.({block:'nearest'});return true;}
 select(id,{notify=true}={}){const entry=this.entries.find(e=>asRecord(e).object_id===id);if(!entry)return false;this.selectedId=id;if(['historical','history'].includes(entry.status)&&this.el('measurement-history'))this.el('measurement-history').checked=true;this.render();if(notify)this.run(()=>this.onSelect(entry));return true;}
 async refresh(){
  const state=this.getState(),objectId=state?.object?.object_id,revision=state?.state_revision;if(!objectId)return false;const ticket=++this.ticket;
  try{const next=await this.api('/api/measurements?object_id='+encodeURIComponent(objectId));const latest=this.getState();if(ticket!==this.ticket||latest?.object?.object_id!==objectId||latest?.state_revision!==revision||next.current?.object_id!==objectId)return false;
   this.current=next.current;this.entries=next.entries??next.measurements??[];this.truncated=Boolean(next.truncated);if(this.selectedId&&!this.entries.some(e=>asRecord(e).object_id===this.selectedId))this.selectedId=null;this.checked=new Set([...this.checked].filter(id=>this.entries.some(e=>asRecord(e).object_id===id)));this.render();return true;
  }catch(error){if(ticket===this.ticket&&this.getState()?.object?.object_id===objectId)this.onError(error);return false;}
 }
 renderDetails(target,details){if(!target||!this.document)return;target.replaceChildren();const dl=this.document.createElement('dl');for(const [name,value]of details){const dt=this.document.createElement('dt'),dd=this.document.createElement('dd');dt.textContent=name;dd.textContent=typeof value==='object'?JSON.stringify(value):String(value);dl.append(dt,dd);}target.append(dl);}
 render(){
  this.el('measurement-workspace')?.classList?.toggle('empty-results',this.entries.length===0);
  this.renderDetails(this.el('data-inspector'),inspectorDetails(this.current??{}));const body=this.el('measurement-rows');if(!body||!this.document)return;body.replaceChildren();const visible=this.visible();
  if(this.el('measurement-count'))this.el('measurement-count').textContent=`${visible.length} / ${this.entries.length} 条${this.truncated?' · 达到读取上限':''}`;
  for(const entry of visible){const m=asRecord(entry),row=this.document.createElement('tr');row.dataset.measurementId=m.object_id;row.setAttribute('aria-selected',String(this.selectedId===m.object_id));row.classList.toggle('selected',this.selectedId===m.object_id);row.classList.toggle('stale',['stale','needs_remeasure','needs_remeasurement'].includes(entry.status));row.tabIndex=0;
   const checkbox=this.document.createElement('input');checkbox.type='checkbox';checkbox.checked=this.checked.has(m.object_id);checkbox.setAttribute('aria-label','选择导出 '+measurementName(entry));checkbox.onchange=()=>{if(checkbox.checked)this.checked.add(m.object_id);else this.checked.delete(m.object_id);};checkbox.onclick=event=>event.stopPropagation();const checkCell=this.document.createElement('td');checkCell.append(checkbox);row.append(checkCell);
   const values=measurementValues(entry);for(const text of [measurementName(entry)+' · '+measurementType(entry),values.map(v=>`${v.label} ${measurementNumber(v.value)}`).join(' / ')||'未知',values.map(v=>v.unit).join(' / ')||'未知',measurementStatus(entry)]){const cell=this.document.createElement('td');cell.textContent=text;row.append(cell);}
   row.onclick=()=>this.select(m.object_id);row.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();this.select(m.object_id);}};body.append(row);
  }
  const selected=this.selected();this.renderDetails(this.el('measurement-detail'),selected?measurementDetails(selected):[['结果','选择一行查看科学坐标、来源与版本；查看不会重算']]);
  if(this.el('measurement-jump')){this.el('measurement-jump').hidden=!requiresMeasurementJump(selected);this.el('measurement-jump').disabled=!selected;}
  if(this.el('measurement-update'))this.el('measurement-update').disabled=!selected||selected.can_remeasure===false||['historical','history'].includes(selected.status);
 }
 download(delimiter,extension){try{const entries=this.exportSelection();if(!entries.length)throw new Error('当前没有可导出的保存测量');const blob=new Blob(['\uFEFF',exportMeasurementTable(entries,{delimiter})],{type:extension==='csv'?'text/csv;charset=utf-8':'text/tab-separated-values;charset=utf-8'}),url=URL.createObjectURL(blob),a=this.document.createElement('a');a.href=url;a.download=`mcp-dm-measurements.${extension}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){this.onError(error);}}
}
