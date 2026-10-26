// Optional loopback gesture surface over the real image_* stdio MCP server.
// It owns no scientific state: every saved revision is an existing tool object.
import http from 'node:http';
import {spawn} from 'node:child_process';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import {mkdirSync,writeFileSync,readFileSync,existsSync,openSync,fsyncSync,closeSync,renameSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {selectionRectangle} from '../ui/image-panel/coordinates.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const objectId=/^[a-f0-9]{32}$/;
const safeId=/^[A-Za-z0-9_-]{1,64}$/;
function fail(message,status=400){const e=new Error(message);e.status=status;throw e;}
function fields(value,allowed){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!allowed.includes(k)))fail('Unexpected action fields');}
function writeJournal(file,value){const fd=openSync(file,'wx');try{writeFileSync(fd,JSON.stringify(value,null,2));fsyncSync(fd);}finally{closeSync(fd);}}
function publicObject(value){
 const keys=['object_id','kind','request_id','parent_object_id','base_object_id','source_object_id','frame_index','page_count','pages','shape_yx','dtype','axes','display','panels','annotations','user_context','calibration','xy_calibration','calibration_record','calibration_status','active_calibration','calibration_dependency','calibration_review','display_calibration_id','frequency_axes','physical_frequency_axes','physical_frequency_magnitude','physical_frequency_unit','scale_bar','measurement','points','dx','dy','coordinate_space','coordinate_system','frequency_distance_cycles_per_pixel','pixel_period','image_coordinate_angle_degrees','physical_angle','physical_angle_degrees','physical_vector_xy','measurement_uncertainty','uncertainty_status','limitation','reciprocal_interpretation','distance_pixels','distance_physical','physical_distance','displacement_pixels','physical_displacement','physical_unit','period','period_unit','d_spacing','d_spacing_unit','fft_recomputed','scientific_data_changed'];
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
function originalMark(mark){if(!mark.anchor)fail('A legacy mark has no unique scientific anchor; replace it through MCP first');return {...Object.fromEntries(['annotation_id','kind','status','text','note','color','line_width','arrowhead_size','arrow_length'].filter(k=>mark[k]!==undefined).map(k=>[k,mark[k]])),...mark.anchor};}
export async function createImagePanel({workspace,python,object_id,port=0,client:givenClient,journalDirectory}={}){
 if(!path.isAbsolute(workspace??'')||!path.isAbsolute(python??'')||!objectId.test(object_id??''))throw new Error('Explicit absolute workspace/python and existing object_id required');
 const token=randomBytes(24).toString('hex'),session=randomBytes(8).toString('hex');
 const journal=journalDirectory??path.join(workspace,'panel-journals',session);mkdirSync(journal,{recursive:true});
 const client=givenClient??new StdioImageClient({workspace,python});let tools,current,png,sequence=0,selection=null,busy=Promise.resolve(),lastOperation=null,frameIdentity=null,effectiveDisplay=null,displaySourceObjectId=null;
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
 const setCurrent=async r=>{
  // Overlay objects own the annotation revision and PNG, while its explicit
  // render base owns the display recipe. Resolve only that recipe; retain the
  // current object's calibration record, identity and scientific anchors.
  let value=r.data;const seen=new Set();effectiveDisplay=null;displaySourceObjectId=null;
  for(let n=0;n<64;n++){
   if(seen.has(value.object_id))fail('Display ancestry contains a cycle');seen.add(value.object_id);
   if(value.display){effectiveDisplay=structuredClone(value.display);displaySourceObjectId=value.object_id;break;}
   if(value.kind==='tiff_source')break;
   const next=value.render_base_object_id??value.base_object_id??value.parent_object_id;
   if(!objectId.test(next??''))break;
   value=(await journalCall('image_info',{object_id:next})).data;
   if(n===63)fail('Display ancestry exceeds 64 records');
  }
  current=r.data;png=r.png??null;selection=null;
 };
 const findFrameIdentity=async value=>{const visited=new Set();for(let n=0;n<64;n++){if(value.kind==='frame'&&Number.isInteger(value.frame_index))return {frame_object_id:value.object_id,frame_index:value.frame_index,source_object_id:value.source_object_id};if(value.kind==='compare'||visited.has(value.object_id))return null;visited.add(value.object_id);const id=value.parent_object_id??value.base_object_id??value.source_object_id;if(!objectId.test(id??''))return null;value=(await journalCall('image_info',{object_id:id})).data;}return null;};
 try{await setCurrent(await displayObject(await journalCall('image_info',{object_id})));frameIdentity=await findFrameIdentity(current);}
 catch(error){await client.close();throw error;}
 const state=()=>({schema_version:1,backend:'external-image-workspace',object:publicObject(current),effective_display:effectiveDisplay,display_source_object_id:displaySourceObjectId,frame_identity:frameIdentity,png_base64:png,tools:tools.map(t=>({name:t.name,inputSchema:t.inputSchema})),selection,last_operation:lastOperation});
 function saveSelection(){if(!current)return;const temp=path.join(journal,`.selection-${randomBytes(6).toString('hex')}.json`);writeJournal(temp,{schema_version:1,object_id:current.object_id,frame_identity:frameIdentity,selection,last_operation:lastOperation,updated_utc:new Date().toISOString()});renameSync(temp,path.join(journal,'current-selection.json'));}
 const sourceForFrame=async()=>{let value=current;const visited=new Set();for(let n=0;n<64;n++){if(value.kind==='tiff_source')return value.object_id;if(visited.has(value.object_id))break;visited.add(value.object_id);const next=value.parent_object_id??value.base_object_id??value.source_object_id;if(!objectId.test(next??''))break;value=(await journalCall('image_info',{object_id:next})).data;}fail('No explicit TIFF source ancestry; choose another object through the Agent');};
 const withCurrentContext=async(sourceId,{newFrame=false}={})=>{
  let target=sourceId;
  const context=Object.fromEntries(Object.entries(current.user_context??{}).filter(([key])=>['reconstruction_type','data_meaning','frame_meaning','xy_scale','value_unit','frame_scale','source_text'].includes(key)));
  if(Object.keys(context).length&&names.has('image_context'))target=(await journalCall('image_context',{object_id:target,metadata:context})).data.object_id;
  const calibration=current.xy_calibration;
  if(calibration?.calibration_id&&(!newFrame||calibration.scope==='sequence'))target=(await journalCall('image_calibrate',{object_id:target,calibration_object_id:calibration.calibration_id})).data.object_id;
  return target;
 };
 const checkSelection=value=>{fields(value,['kind','coordinate_space','source_object_id','coordinates','panel']);const lengths={point:2,line:4,arrow:4,rectangle:4,polygon:null},c=value.coordinates;if(!(value.kind in lengths)||!Array.isArray(c)||!c.every(Number.isFinite)||!objectId.test(value.source_object_id??'')||(value.kind==='polygon'?(c.length<6||c.length>64||c.length%2):c.length!==lengths[value.kind]))fail('Invalid scientific selection');const p=current.panels?.find(p=>p.source_object_id===value.source_object_id&&JSON.stringify(p)===JSON.stringify(value.panel));if(!p)fail('Selection must use an exact current panel');const space={frequency:'frequency_cycles_per_pixel',spatial_pixels:'source_pixels',source_array_indices:'source_array_indices'}[p.domain];if(value.coordinate_space!==space)fail('Selection coordinate domain mismatch');const edges=['rectangle','polygon'].includes(value.kind);let bounds;if(p.domain==='frequency'){const [h,w]=p.fft_shape_yx,[x0,y0,x1,y1]=p.fft_rect_xyxy??[0,0,w,h],margin=edges?.5:0;bounds=[(x0-Math.floor(w/2)-margin)/w,(y0-Math.floor(h/2)-margin)/h,(x1-1-Math.floor(w/2)+margin)/w,(y1-1-Math.floor(h/2)+margin)/h];}else{const [x0,y0,x1,y1]=p.source_rect_xyxy;bounds=[x0,y0,edges?x1:x1-1,edges?y1:y1-1];}for(let i=0;i<c.length;i++)if(c[i]<bounds[i%2]-1e-12||c[i]>bounds[i%2+2]+1e-12)fail('Selection lies outside current source window');if(value.kind==='rectangle'&&(c[0]>=c[2]||c[1]>=c[3]))fail('Rectangle needs increasing nonempty edges');if(['line','arrow'].includes(value.kind)&&c[0]===c[2]&&c[1]===c[3])fail('Line needs distinct endpoints');return structuredClone(value);};
 const act=async body=>{
  fields(body,['expected_object_id','action','params']);if(body.expected_object_id!==current.object_id)fail('Stale object revision; reload before editing',409);const p=body.params??{};let r;
  if(body.action==='select'){fields(p,['selection']);selection=checkSelection(p.selection);saveSelection();return state();}
  if(body.action==='preview'){fields(p,['gamma','display_range','max_size','upscale','interpolation','frequency_rect','spectrum_axes','scale_bar']);r=await journalCall('image_preview',{...p,object_id:current.object_id});}
  else if(body.action==='frame'){fields(p,['frame_index']);r=await journalCall('image_frame',{object_id:await sourceForFrame(),frame_index:p.frame_index});frameIdentity=await findFrameIdentity(r.data);const target=await withCurrentContext(r.data.object_id,{newFrame:true});r=await journalCall('image_preview',{object_id:target,...(effectiveDisplay?{gamma:effectiveDisplay.gamma,display_range:effectiveDisplay.display_range,max_size:effectiveDisplay.max_size}:{})});}
  else if(body.action==='roi'||body.action==='fft'){fields(p,['selection']);const selected=checkSelection(p.selection),rect=selectionRectangle(selected);if(selected.panel.domain==='frequency'){if(body.action==='fft')fail('FFT needs a spatial ROI, not a frequency crop');r=await journalCall('image_preview',{object_id:current.object_id,frequency_rect:rect});}else {if(selected.panel.domain!=='spatial_pixels')fail('Imported frequency arrays have no spatial ROI mapping');const target=await withCurrentContext(selected.source_object_id),recipe=Object.fromEntries(['gamma','display_range','max_size','upscale','interpolation'].filter(key=>effectiveDisplay?.[key]!==undefined).map(key=>[key,effectiveDisplay[key]]));r=await journalCall(body.action==='fft'?'image_fft':'image_preview',{object_id:target,rect,...(body.action==='fft'?{window:'hann',subtract_mean:true}:recipe)});}}
  else if(body.action==='mark'){fields(p,['selection','annotation_id','text','color','status']);const selected=checkSelection(p.selection);if(!safeId.test(p.annotation_id??''))fail('Stable annotation_id required');const old=current.annotations??[];if(old.some(m=>m.annotation_id===p.annotation_id))fail('annotation_id already exists; choose it in the edit list');const {panel,...anchor}=selected;r=await journalCall('image_annotate',{object_id:current.object_id,annotations:[...old.map(originalMark),{...anchor,annotation_id:p.annotation_id,text:p.text??'',color:p.color??'cyan',status:p.status??'hypothesized'}]});}
  else if(body.action==='edit'){fields(p,['updates']);if(!Array.isArray(p.updates)||p.updates.length!==1)fail('Edit exactly one existing annotation per gesture');const u=p.updates[0];fields(u,['annotation_id','coordinates','text','color','status','note']);if(!(current.annotations??[]).some(m=>m.annotation_id===u.annotation_id))fail('Unknown annotation_id');r=await journalCall('image_annotate',{object_id:current.object_id,updates:p.updates});}
  else if(body.action==='measure'){fields(p,['selection']);const selected=checkSelection(p.selection),peak=selected.kind==='point'&&selected.panel.domain==='frequency';if(!peak&&(selected.coordinates.length!==4||!['line','arrow'].includes(selected.kind)))fail('Draw a two-point line, or select an FFT peak relative to mathematical DC');const target=selected.panel.domain==='frequency'?current.object_id:await withCurrentContext(selected.source_object_id);const args={object_id:target,points:peak?[[0,0],selected.coordinates]:[selected.coordinates.slice(0,2),selected.coordinates.slice(2)]};if(selected.panel.domain==='frequency')args.coordinate_space='frequency_cycles_per_pixel';else if(selected.panel.domain!=='spatial_pixels')fail('Array-index physical measurement unavailable');r=await journalCall('image_measure',args);lastOperation={...publicObject(r.data),...(peak?{reference:'mathematical DC [0,0]; geometric period, not phase identification'}:{})};selection=selected;saveSelection();return state();}
  else if(body.action==='calibrate'){fields(p,['scope','xy_scale','source_text']);r=await displayObject(await journalCall('image_calibrate',{object_id:current.object_id,...p}));}
  else if(body.action==='export'){fields(p,[]);mkdirSync(path.join(workspace,'exports'),{recursive:true});const output_dir=path.join(workspace,'exports',`panel-${session}-${sequence+1}`);r=await journalCall('image_export',{object_id:current.object_id,output_dir});lastOperation={...publicObject(r.data),output_dir};saveSelection();return state();}
  else if(body.action==='show'){fields(p,['object_id']);if(!objectId.test(p.object_id??''))fail('Explicit existing object_id required');r=await displayObject(await journalCall('image_info',{object_id:p.object_id}));frameIdentity=await findFrameIdentity(r.data);}
  else if(body.action==='recover'){fields(p,[]);const original=lastOperation?.request_id;if(!safeId.test(original??''))fail('No saved request to query');r=await journalCall('image_result',{request_id:original});if(!r.data.object_id)fail('Original request has not returned an image object');if(['measure','export'].includes(r.data.kind)){lastOperation=publicObject(r.data);saveSelection();return state();}r=await displayObject(r);}
  else fail('Unknown panel action');
  await setCurrent(r);lastOperation={action:body.action,object_id:current.object_id,request_id:current.request_id};saveSelection();return state();
 };
 const staticFiles=new Map([['/',['index.html','text/html; charset=utf-8']],['/app.mjs',['app.mjs','text/javascript; charset=utf-8']],['/coordinates.mjs',['coordinates.mjs','text/javascript; charset=utf-8']],['/style.css',['style.css','text/css; charset=utf-8']]]);
 const server=http.createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
  try{
   const origin=`http://127.0.0.1:${server.address().port}`;if(req.headers.host!==`127.0.0.1:${server.address().port}`)fail('Invalid Host',403);const url=new URL(req.url,origin);
   if(req.method==='GET'&&staticFiles.has(url.pathname)){const [file,type]=staticFiles.get(url.pathname);res.setHeader('Content-Type',type);res.end(readFileSync(path.join(root,'ui','image-panel',file)));return;}
   const supplied=req.headers['x-panel-token'];if(typeof supplied!=='string'||Buffer.byteLength(supplied)!==Buffer.byteLength(token)||!timingSafeEqual(Buffer.from(supplied),Buffer.from(token)))fail('Panel token required',403);
   if(req.headers.origin&&req.headers.origin!==origin)fail('Cross-origin requests refused',403);
   res.setHeader('Content-Type','application/json');
   if(req.method==='GET'&&url.pathname==='/api/state'){res.end(JSON.stringify(state()));return;}
   if(req.method!=='POST'||url.pathname!=='/api/action')fail('Not found',404);if(req.headers.origin!==origin||!req.headers['content-type']?.startsWith('application/json'))fail('Same-origin JSON required',403);
   let raw='',size=0;for await(const chunk of req){size+=chunk.length;if(size>64*1024)fail('Request exceeds 64 KiB',413);raw+=chunk;}let body;try{body=JSON.parse(raw);}catch{fail('Invalid JSON');}
   const run=busy.then(()=>act(body));busy=run.catch(()=>{});res.end(JSON.stringify(await run));
  }catch(error){res.statusCode=error.status??400;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({error:error.message}));}
 });
 try{await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});saveSelection();}catch(error){await client.close();throw error;}
 return {server,client,url:`http://127.0.0.1:${server.address().port}/#${token}`,token,journal,state,async close(){await new Promise(resolve=>server.close(resolve));await client.close();}};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const options={};for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i],value=process.argv[i+1];if(!['--workspace','--python','--object','--port','--selection'].includes(key)||!value)throw new Error('Usage: node tools/image_panel.mjs --workspace ABS --python ABS --object ID [--port 0]; --selection ABS_CURRENT_SELECTION_JSON');options[key.slice(2)]=value;}
 if(options.selection){if(!path.isAbsolute(options.selection)||!existsSync(options.selection))throw new Error('Existing absolute selection record required');process.stdout.write(readFileSync(options.selection));}
 else {const panel=await createImagePanel({workspace:options.workspace,python:options.python,object_id:options.object,port:Number(options.port??0)});process.stdout.write(JSON.stringify({url:panel.url,selection_path:path.join(panel.journal,'current-selection.json')})+'\n');let closing=false;const close=async()=>{if(!closing){closing=true;await panel.close();}};process.on('SIGINT',close);process.on('SIGTERM',close);}
}
