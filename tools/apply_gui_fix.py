from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
expected={'ui/image-panel/app.mjs':'70efd3502e079f5f89013582ca09448587bf7ebb','tools/image_panel.mjs':'885d4e400adb0e221f9bc4bdbf964299f9a3e1d6'}
for name,sha in expected.items():
    actual=subprocess.check_output(['git','hash-object',str(ROOT/name)],text=True).strip()
    if actual!=sha: raise RuntimeError('Source changed; refusing to overwrite '+name)
def edit(name, fn):
    p=ROOT/name
    old=p.read_text(encoding='utf-8')
    new=fn(old)
    if old==new: raise RuntimeError('No change: '+name)
    p.write_text(new,encoding='utf-8')
    print(name, len(old), '->', len(new))
def replace(s, old, new, n=1):
    if s.count(old)!=n: raise RuntimeError('Expected %s occurrences, found %s: %s'%(n,s.count(old),old[:160]))
    return s.replace(old,new)
def app(s):
    s=replace(s,"import {DataProbes} from './data-probes.mjs';", "import {DataProbes} from './data-probes.mjs';\nimport {UserActionHistory,SavedViewHistory,workflowScope,selectionActionReason,measurementLabel} from './user-workflow.mjs';")
    s=replace(s,'const queuedEdits=new Map(),editUndo=[],editRedo=[];', 'const queuedEdits=new Map(),userHistory=new UserActionHistory(),savedViews=new SavedViewHistory();\nlet lastUserDisplay=null;')
    start=s.index('function diagnostics()');end=s.index('async function api(',start)
    s=s[:start]+r'''function diagnostics(){
 const status=autoFailed?'保存失败 · 草稿保留':busy?'正在保存':queuedEdits.size?'等待保存':dirty()?'本地草稿':draft?'选择已就绪':'已保存 · 原图只读';
 $('performance-data').textContent=JSON.stringify({...perf,dirty:dirty(),gesture_active:Boolean(drag),draft_revision:historyDraft.revision,object_id:state?.object.object_id,scale:view.scale,busy,queued_edits:queuedEdits.size});$('draft-status').textContent=status;$('autosave-status').textContent=status;
 const undo=userHistory.peek('undo'),redo=userHistory.peek('redo');
 $('undo').disabled=!undo&&!labelDraft&&!fieldDirty;$('redo').disabled=!redo;
 $('undo').title=undo?'撤销：'+undo.label:'没有可撤销操作';$('redo').title=redo?'恢复：'+redo.label:'没有可恢复操作';
 for(const [id,action]of [['apply-roi','roi'],['fft','fft'],['measure','measure'],['share','select'],['full','full'],['roi-statistics','statistics'],['line-profile','profile']]){
  const button=$(id);if(!button)continue;if(id==='roi-statistics')button.hidden=draft?.kind!=='rectangle';if(id==='line-profile')button.hidden=!['line','arrow'].includes(draft?.kind);const reason=selectionActionReason(action,draft,state?.object??{});button.disabled=Boolean(reason)||busy||Boolean(drag);button.title=reason||({roi:'查看选定区域',fft:'计算当前实空间 ROI 的 FFT',measure:'保存测量结果',select:'可选：把当前选择交给 Agent',full:'仅恢复完整频谱，不返回原图',statistics:'读取保存科学数组的 ROI 统计',profile:'读取当前线的原数组剖面'})[action];
 }
 for(const [id,target]of [['view-back',savedViews.target(-1)],['view-forward',savedViews.target(1)],['view-original',savedViews.original(state)]])if($(id))$(id).disabled=!target||busy||Boolean(drag)||target.id===state?.object?.object_id;
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
 await act('show',{object_id:target.id});
}
''' + s[end:]
    s=replace(s,"...(includeSelection&&draft?{selection:selection()}:{})", "...(includeSelection?{selection:draft?selection():null}:{})")
    old="if(undo&&JSON.stringify(prior)!==JSON.stringify(after)){editUndo.push({before:prior,after});if(editUndo.length>40)editUndo.shift();editRedo.length=0;}"
    new="if(undo){const keys=Object.keys(update).filter(k=>!['annotation_id','presentation_replace','note'].includes(k)&&!equalRecords(prior[k],update[k]));if(keys.length){const project=value=>({annotation_id:update.annotation_id,...Object.fromEntries(keys.map(k=>[k,value[k]]))});userHistory.push({kind:'annotation',label:changedGeometry?'移动科学标记':'调整标注',scope:workflowScope(state),before:project(prior),after:project(after)});}}"
    s=replace(s,old,new)
    s=replace(s,"state=r;for(const [key]of batch)","state=r;savedViews.remember(state,{replace:true});for(const [key]of batch)")
    s=replace(s,"measurement_kind:period?'period':'distance'}}});}","measurement_kind:period?'period':'distance'}}},null,{undo:false});}")
    s=replace(s,"if(dirty()&&['frame','roi','fft','calibrate','accept-result'].includes(action))", "if(dirty()&&['frame','roi','fft','calibrate','accept-result','show','measurement-jump'].includes(action))")
    s=replace(s,"else await load(r,{keepDisplay:keepDisplay?local.display:null,keepMark:keepMark?local:null});", "else await load(r,{keepDisplay:keepDisplay?local.display:null,keepMark:keepMark?local:null,role:action==='roi'?'ROI':action==='fft'?'FFT':action==='frame'?'原图':null});")
    s=replace(s,"message(({select:'选择已交接；可继续使用当前选区。',measure:'测量完成；当前选区已保留。',export:'已导出；当前选区已保留。'})[action]??'已保存新版本；原像素与旧版本保留。');return r;", "if(['measure','statistics','profile'].includes(action))setResultsTab(action==='measure'?'measurements':action);\n  message(action==='export'?`科学数据已保存到 ${r.last_operation?.output_dir??'工作区 exports 目录'}（不是浏览器图片下载）`:({select:'选择已交接；可继续使用当前选区。',measure:'测量完成；当前选区已保留。',show:'已打开保存视图；未重算 FFT。'})[action]??'已保存新版本；原像素与旧版本保留。');return r;")
    s=replace(s,"async function load(next,{keepDisplay=null,keepMark=null}={}){", "async function load(next,{keepDisplay=null,keepMark=null,role=null}={}){\n const priorScope=state?workflowScope(state):null;")
    s=replace(s,"historyDraft.reset(snapshot());showDraft();paint();showPending();", "historyDraft.reset(snapshot());lastUserDisplay=displayDraft();if(priorScope!==workflowScope(state))userHistory.reset();savedViews.remember(state,{replace:Boolean(continued),role});showDraft();paint();showPending();")
    s=replace(s,"if(changeMode)$('mode').value='edit';", "if(changeMode)setMode('select');")
    s=replace(s,"if(changeMode)$('mode').value='arrow';", "if(changeMode)setMode('select');")
    s=replace(s,"let kind=$('mode').value;try{", "let kind=$('mode').value==='edit'?'select':$('mode').value;const selectionBefore={draft:draft?JSON.parse(JSON.stringify(draft)):null,selectedId};let blankSelect=false;try{")
    s=replace(s,"if(kind==='select'){if(hit){if(!chooseMark(hit.mark.annotation_id))return;kind='edit';}else kind='rectangle';}else if(kind==='edit'&&hit&&!chooseMark(hit.mark.annotation_id))return;", "if(kind==='select'){if(hit){if(!chooseMark(hit.mark.annotation_id))return;kind='edit';}else{chooseMark('');draft=null;blankSelect=true;kind='rectangle';}}")
    s=replace(s,"else drag={kind,start,end:start,originalStart:start,p:drawingPanel};drag.pointerId=event.pointerId;", "else drag={kind,start,end:start,originalStart:start,p:drawingPanel,selectionBefore,blankSelect};drag.pointerId=event.pointerId;")
    s=replace(s,"if(kind==='pan')return;if(kind==='label')", "if(kind==='pan')return;if(drag.blankSelect&&Math.hypot(drag.end[0]-drag.start[0],drag.end[1]-drag.start[1])*view.scale<3){draft=null;rememberSelection(drag.selectionBefore,{draft:null,selectedId:''});showDraft();return;}if(kind==='label')")
    s=replace(s,"draft={...selected,rendered:transformCoordinates(selected.coordinates,selected.panel,{edges:kind==='rectangle',inverse:true})};showDraft();", "draft={...selected,rendered:transformCoordinates(selected.coordinates,selected.panel,{edges:kind==='rectangle',inverse:true})};rememberSelection(drag.selectionBefore??{draft:null,selectedId:''},{draft:JSON.parse(JSON.stringify(draft)),selectedId});showDraft();")
    s=replace(s,"const picked=selection();let mark=", "const picked=selection(),reason=selectionActionReason('measure',picked,state.object);if(reason)throw new Error(reason);let mark=")
    s=replace(s,"text:`g${(state.object.annotations?.length??0)+1}`", "text:measurementLabel(picked,(state.object.annotations?.length??0)+1)")
    old="for(const id of ['gamma','low','high','axes','scale'])$(id).oninput=()=>{$('gamma-label').textContent=$('gamma').value;record();schedulePaint();publishDraft();message('显示草稿即时反馈；保存后从原科学数组重绘，不重算 FFT。');};"
    new="for(const id of ['gamma','low','high','axes','scale']){$(id).oninput=()=>{recordDisplayInput(id);$('gamma-label').textContent=$('gamma').value;record();schedulePaint();publishDraft();message('显示草稿即时反馈；保存后从原科学数组重绘，不重算 FFT。');};$(id).onchange=()=>userHistory.endGroup();}"
    s=replace(s,old,new)
    a=s.index("$('undo').onclick=");b=s.index("$('discard-local').onclick=",a)
    s=s[:a]+"$('undo').onclick=()=>applyUserHistory('undo');$('redo').onclick=()=>applyUserHistory('redo');\n"+s[b:]
    s=replace(s,"function setMode(mode){$('mode').value=mode;", "function setMode(mode){mode=mode==='edit'?'select':mode;$('mode').value=mode;canvas.style.cursor=mode==='pan'?'grab':mode==='select'?'default':'crosshair';")
    needle="$('frame').onkeydown=event=>{if(event.key==='Enter')$('set-frame').onclick();};"
    s=replace(s,needle,needle+r'''
$('view-back').onclick=guarded(()=>navigateSavedView(savedViews.target(-1)));
$('view-forward').onclick=guarded(()=>navigateSavedView(savedViews.target(1)));
$('view-original').onclick=guarded(()=>navigateSavedView(savedViews.original(state)));
for(const tab of ['measurements','statistics','profile']){
 const button=$('results-tab-'+tab);if(button){button.onclick=()=>setResultsTab(tab);button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const names=['measurements','statistics','profile'],i=names.indexOf(tab),next=event.key==='Home'?0:event.key==='End'?2:(i+(event.key==='ArrowRight'?1:2))%3;setResultsTab(names[next]);$('results-tab-'+names[next])?.focus?.();};}
}
setResultsTab('measurements',{expand:false});
''')
    s=replace(s,"for(const [id,action]of [['apply-roi','roi'],['share','select']])$(id).onclick=guarded(()=>act(action,{selection:selection()}));", "for(const [id,action]of [['apply-roi','roi'],['share','select']])$(id).onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason(action,picked,state.object);if(reason)throw new Error(reason);return act(action,{selection:picked});});")
    s=replace(s,"$('fft').onclick=guarded(()=>act('fft',{selection:selection(),window:$('fft-window').value,subtract_mean:$('fft-mean').checked}));", "$('fft').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('fft',picked,state.object);if(reason)throw new Error(reason);return act('fft',{selection:picked,window:$('fft-window').value,subtract_mean:$('fft-mean').checked});});")
    s=replace(s,"$('roi-statistics').onclick=guarded(()=>act('statistics',{selection:selection(),component:$('probe-component').value}));", "$('roi-statistics').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('statistics',picked,state.object);if(reason)throw new Error(reason);return act('statistics',{selection:picked,component:$('probe-component').value});});")
    s=replace(s,"$('line-profile').onclick=guarded(()=>act('profile',{selection:selection(),component:$('probe-component').value,sample_count:Number($('profile-count').value)}));", "$('line-profile').onclick=guarded(()=>{const picked=selection(),reason=selectionActionReason('profile',picked,state.object);if(reason)throw new Error(reason);return act('profile',{selection:picked,component:$('probe-component').value,sample_count:Number($('profile-count').value)});});")
    s=replace(s,"if(['statistics','profile'].includes(state.last_operation?.kind))dataProbes.renderResult(state.last_operation);", "dataProbes.restoreSavedResults(state.numeric_results??{});if(['statistics','profile'].includes(state.last_operation?.kind))dataProbes.renderResult(state.last_operation);")
    return s
edit('ui/image-panel/app.mjs',app)
def backend(s):
    s=replace(s,"import {readImageMeasurements,writeMeasurementLink} from '../lib/image_measurement_records.mjs';", "import {readImageMeasurements,writeMeasurementLink} from '../lib/image_measurement_records.mjs';\nimport {framePreviewRecipe} from '../ui/image-panel/user-workflow.mjs';")
    s=replace(s,'const sources=new Map(),figureBars=new Map();','const sources=new Map(),figureBars=new Map();\n const numericResults={statistics:null,profile:null};')
    s=replace(s,'schema_version:1,panel_id,backend:', 'schema_version:1,panel_id,numeric_results:numericResults,backend:')
    s=replace(s,"const picked=p.selection===undefined?null:checkSelection(p.selection);", "const picked=p.selection==null?null:checkSelection(p.selection);")
    s=replace(s,"selection:picked??editState.selection", "selection:p.selection===undefined?editState.selection:picked")
    s=replace(s,"if(picked)selection=picked;saveSelection", "if(p.selection!==undefined)selection=picked;saveSelection")
    s=replace(s,"...(effectiveDisplay?{gamma:effectiveDisplay.gamma,display_range:effectiveDisplay.display_range,max_size:effectiveDisplay.max_size}:{})", "...framePreviewRecipe(current,effectiveDisplay)")
    s=replace(s,"lastOperation={...r.data};selection=selected;saveSelection();return state();", "numericResults[body.action]=r.data;lastOperation={...r.data};selection=selected;saveSelection();return state();")
    s=replace(s,"if(['statistics','profile'].includes(r.data.kind)){lastOperation=r.data;saveSelection();return state();}", "if(['statistics','profile'].includes(r.data.kind)){numericResults[r.data.kind]=r.data;lastOperation=r.data;saveSelection();return state();}")
    s=replace(s,"['/data-probes.mjs',['data-probes.mjs','text/javascript; charset=utf-8']]", "['/data-probes.mjs',['data-probes.mjs','text/javascript; charset=utf-8']],['/user-workflow.mjs',['user-workflow.mjs','text/javascript; charset=utf-8']]")
    return s
edit('tools/image_panel.mjs',backend)
def markup(s):
    s=replace(s,'<span>导出</span></button>','<span>科学数据</span></button>')
    s=replace(s,'>论文出图 ↗</button>','>论文图片 ↗</button>')
    s=replace(s,'<div id="viewport">','<nav class="view-navigation" aria-label="保存视图导航"><button id="view-back" title="返回上一个保存视图">← 返回</button><button id="view-forward" title="前进到保存视图">前进 →</button><button id="view-original" title="打开本帧已保存的原图视图">原图</button><span id="view-current" aria-live="polite">当前视图</span><small>打开已有结果，不重算 FFT</small></nav>\n    <div id="viewport">')
    s=replace(s,'class="accent-button" title="把当前科学坐标交给 Agent">交给 Agent', 'class="quiet-button" title="可选：把当前科学坐标交给 Agent">AI 交接')
    s=replace(s,'<summary>测量结果 <span id="measurement-count">0</span>', '<summary>数据结果 <span id="measurement-count">0</span>')
    before='<div class="results-toolbar">'
    tabs='<div class="results-tabs" role="tablist" aria-label="数据结果类型">'+''.join(f'<button id="results-tab-{key}" role="tab" aria-controls="results-{key}" aria-selected="{str(key=="measurements").lower()}">{name}</button>' for key,name in [('measurements','测量'),('statistics','ROI 统计'),('profile','强度剖面')])+'</div>\n        <section id="results-measurements" role="tabpanel" aria-labelledby="results-tab-measurements">'+before
    s=replace(s,before,tabs)
    s=replace(s,'<details id="numeric-data"><summary>原始数值、ROI 统计与强度剖面</summary>', '</section><details id="numeric-data" class="numeric-tab-container"><summary hidden>原数组数值</summary>')
    stats='<button id="roi-statistics">统计当前 ROI</button>'
    profile='<label>剖面采样点数<input id="profile-count" type="number" min="2" max="4096" value="128"></label><button id="line-profile">读取当前线剖面</button><button id="profile-csv">剖面 CSV</button>'
    s=replace(s,stats,'')
    s=replace(s,profile,'')
    s=replace(s,'<button id="share"',stats+'<button id="line-profile">强度剖面</button><button id="share"')
    s=replace(s,'<p id="statistics-summary"></p><p id="profile-summary"></p>', '<section id="results-statistics" role="tabpanel" aria-labelledby="results-tab-statistics" hidden><p id="statistics-summary">框选一个矩形 ROI 后读取统计</p></section><section id="results-profile" role="tabpanel" aria-labelledby="results-tab-profile" hidden>'+profile.replace('<button id="line-profile">读取当前线剖面</button>','')+'<p id="profile-summary">画线后读取已保存数组的剖面</p><output id="profile-readout" aria-live="polite"></output>')
    s=replace(s,'<p class="help-text">首版仅 1 像素宽、最近邻取样；复数分量明确选择。无强度标定时单位未知，不代表电子计数。</p></details>', '<p class="help-text">首版仅 1 像素宽、最近邻取样；曲线/表格点击或方向键读取采样点，不插值新数值。无强度标定时单位未知。</p></section></details>')
    return s
edit('ui/image-panel/index.html',markup)
def styles(s):
    s=s.replace('.results-scroll tr[data-id]', '.results-scroll tr[data-measurement-id]')
    return s+r'''
/* Result modes share one height budget rather than stacking every data widget. */
.view-navigation{display:flex;align-items:center;gap:7px;padding:5px 12px;background:#141e29;border-bottom:1px solid var(--border);flex-shrink:0;font-size:12px}
.view-navigation button{font-size:11px;min-height:28px;padding:4px 8px}.view-navigation small{margin-left:auto;color:var(--muted)}#view-current{color:var(--muted)}
.results-tabs{display:flex;gap:5px;position:sticky;top:0;z-index:2;background:#17222e;padding:5px 0}.results-tabs [aria-selected=true]{background:#284b57;border-color:#6db5be;color:#e1f4f5}
.measurement-content{display:block;height:280px;max-height:min(55vh,calc(100vh - 390px));padding-bottom:12px}.results-scroll{max-height:180px;min-height:50px;margin-top:7px}.measurement-detail{margin-top:7px}
.numeric-tab-container{margin-top:6px}#numeric-data>summary[hidden]{display:none}.numeric-controls{margin:7px 0}.results-tabs~section[hidden]{display:none}
#results-profile>label{font-size:12px;display:inline-flex;align-items:center;gap:6px;margin-right:10px}#profile-count{width:66px}#profile-readout{display:block;min-height:22px;font-size:12px;color:#bbd9df;margin:6px 0}
#profile-plot{height:auto;min-height:190px;max-height:250px;touch-action:none}.profile-table{max-height:120px}#profile-plot text{font-size:10px}.profile-table tr[aria-selected=true]{background:#274b56}
.measurement-workspace.empty-results .results-tabs,.measurement-workspace.empty-results #results-measurements{display:block}.measurement-workspace.empty-results .results-tabs{display:flex}
@media(max-width:900px){.view-navigation small{display:none}.results-toolbar button{font-size:11px}.measurement-content{max-height:48vh}}
'''
edit('ui/image-panel/style.css',styles)
def harness(s):
    s=replace(s,"import * as coordinates from '../ui/image-panel/coordinates.mjs';", "import * as coordinates from '../ui/image-panel/coordinates.mjs';\nimport * as userWorkflow from '../ui/image-panel/user-workflow.mjs';")
    s=replace(s,'const sandbox={...coordinates,...viewerState,','const sandbox={...userWorkflow,...coordinates,...viewerState,')
    return s
edit('tests/image-panel-ui.test.mjs',harness)
exec((ROOT/'tools/apply_gui_fix_tail.py').read_text(encoding='utf-8'))
