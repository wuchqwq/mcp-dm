// Restricted bridge to an owned loopback viewer. Scientific objects remain in
// ImageWorkspace; these small records only retain panel/request connections.
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, renameSync, statSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const objectId={type:'string',pattern:'^[a-f0-9]{32}$',minLength:32,maxLength:32};
const requestId={type:'string',pattern:'^[A-Za-z0-9_-]+$',minLength:1,maxLength:64,description:'Save before submission. Reuse this original ID to query the same operation after cancellation; never invent another ID to retry an uncertain operation.'};
const make=(name,description,properties,required)=>({name,description,inputSchema:{type:'object',additionalProperties:false,properties,required}});
export const imagePanelTools=[
  make('image_panel_open','Open an existing image object in an owned local browser panel and return its URL and saved PNG. No user path, script or arbitrary URL is accepted. The panel survives MCP client disconnect; same request ID recovers its original panel, never launches another.',{object_id:objectId,request_id:requestId},['object_id','request_id']),
  make('image_panel_current','Read exact current panel/object, source-coordinate selection, saved scoped research_observation reference and unsaved-draft status, plus the saved PNG. A twinning observation confirms only its explicitly recorded scope, not a twin law, orientation or HKL; synthetic_fixture is not human confirmation. With one live registered panel, panel_id may be omitted. This reads after the user says continue; it does not automatically wake the model. Unsaved browser tone/gesture drafts are described separately from the saved image.',{panel_id:objectId},[]),
  make('image_panel_show','Offer an existing result to an explicit panel. Save request_id first. expected_object_id and draft_revision bind the inspected view. Dirty/newer drafts queue the result for explicit user acceptance instead of overwriting them. Same ID returns the original presentation receipt, never repeats it; call image_panel_current for the latest view.',{panel_id:objectId,object_id:objectId,expected_object_id:objectId,draft_revision:{type:'integer',minimum:0},request_id:requestId},['panel_id','object_id','expected_object_id','draft_revision','request_id']),
];
export const IMAGE_PANEL_INSTRUCTIONS='Use image_panel_open to give the researcher a local shared view of an existing image object. Retain the returned panel_id internally. After the user circles a region and says continue, image_panel_current returns its exact source/frequency coordinates and unsaved draft state; use ordinary image_* tools for the chosen operation, then image_panel_show with the inspected object/draft revision. Do not claim automatic model wake. A queued result has not replaced the current view; the researcher explicitly accepts it without losing an unseen draft. Returned PNG is the saved immutable view, not a screenshot of unsaved local tone/gesture drafts. Panel connection records persist across MCP clients but are not a scientific state database; stopped panels are not automatically restarted.';

const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const canonical=value=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):Array.isArray(value)?value.map(canonical):value;
const identical=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const ownKeys=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(key=>keys.includes(key));
function validateId(value,label,request=false){if(typeof value!=='string'||!(request?/^[A-Za-z0-9_-]{1,64}$/:/^[a-f0-9]{32}$/).test(value))throw new Error(`Invalid ${label}`);}
function validateArguments(name,args){
  const entry=imagePanelTools.find(tool=>tool.name===name);if(!entry)throw new Error('Unknown panel tool');
  if(!ownKeys(args,Object.keys(entry.inputSchema.properties)))throw new Error('Panel arguments contain unknown fields');
  for(const required of entry.inputSchema.required)if(!Object.hasOwn(args,required))throw new Error(`Missing ${required}`);
  for(const [key,value] of Object.entries(args)){
    if(key==='draft_revision'){if(!Number.isSafeInteger(value)||value<0)throw new Error('Invalid draft_revision');}
    else validateId(value,key,key==='request_id');
  }
}
function durableWrite(file,value,{exclusive=false}={}){
  const target=exclusive?file:`${file}.${randomBytes(8).toString('hex')}.tmp`,fd=openSync(target,'wx');
  try{writeFileSync(fd,JSON.stringify(value));fsyncSync(fd);}finally{closeSync(fd);}
  if(!exclusive)renameSync(target,file);
}
function readJson(file,root,maxBytes=20*1024*1024){
  const real=realpathSync.native(file),relative=path.relative(root,real);
  if(relative.startsWith('..'+path.sep)||relative==='..'||path.isAbsolute(relative)||!statSync(real).isFile()||statSync(real).size>maxBytes)throw new Error('Invalid private panel record');
  return JSON.parse(readFileSync(real,'utf8'));
}
function connection(value,panelId){
  if(!ownKeys(value,['schema_version','panel_id','port','token','pid'])||value.schema_version!==1||value.panel_id!==panelId||!Number.isInteger(value.port)||value.port<1||value.port>65535||typeof value.token!=='string'||!/^[a-f0-9]{48,64}$/.test(value.token)||!Number.isSafeInteger(value.pid)||value.pid<1)throw new Error('Invalid owned panel connection');
  return value;
}
function waitWithoutCancelling(operation,signal){
  if(!signal)return operation;
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(new Error('Stopped waiting for the panel operation; query its original request_id. It was not cancelled or automatically repeated.'));
    if(signal.aborted){abort();return;}
    signal.addEventListener('abort',abort,{once:true});
    operation.then(resolve,reject).finally(()=>signal.removeEventListener('abort',abort));
  });
}

export class ImagePanelManager {
  constructor({workspace,python,inspect,launch,fetchImpl=fetch,readyTimeoutMs=120000,requestTimeoutMs=120000}={}){
    if(!workspace||!path.isAbsolute(workspace))throw new Error('Panel workspace must be an absolute configured directory');
    if(typeof python!=='string'||!python)throw new Error('Panel requires a configured DM_IMAGE_PYTHON executable');
    if(typeof inspect!=='function')throw new Error('Panel requires the existing image inspector');
    this.workspace=path.resolve(workspace);this.python=python;this.inspect=inspect;this.fetch=fetchImpl;this.readyTimeoutMs=readyTimeoutMs;this.requestTimeoutMs=requestTimeoutMs;
    this.directory=path.join(this.workspace,'panel-registry');this.requests=path.join(this.directory,'requests');this.panels=path.join(this.directory,'panels');this.active=new Map();
    this.launch=launch??(async({panel_id,connection_file,object_id})=>{
      if(!path.isAbsolute(this.python))throw new Error('Panel launch requires an absolute DM_IMAGE_PYTHON executable; configure the independent image environment');
      const child=spawn(process.execPath,[fileURLToPath(new URL('../tools/image_panel.mjs',import.meta.url)),'--workspace',this.workspace,'--python',this.python,'--object',object_id,'--connection-file',connection_file,'--panel-id',panel_id],{detached:true,windowsHide:true,stdio:'ignore'});
      await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});child.unref();
    });
  }
  initialize(){mkdirSync(this.requests,{recursive:true});mkdirSync(this.panels,{recursive:true});this.canonicalDirectory=realpathSync.native(this.directory);}
  requestFile(id){return path.join(this.requests,id+'.json');}
  connectionFile(id){return path.join(this.panels,id+'.json');}
  getConnection(id){validateId(id,'panel_id');return connection(readJson(this.connectionFile(id),this.canonicalDirectory,4096),id);}
  async request(conn,method,route,body){
    const origin=`http://127.0.0.1:${conn.port}`,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),method==='GET'?Math.min(this.requestTimeoutMs,3000):this.requestTimeoutMs);
    try{
      const response=await this.fetch(origin+route,{method,headers:{'X-Panel-Token':conn.token,Origin:origin,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:controller.signal});
      const text=await response.text();if(Buffer.byteLength(text)>20*1024*1024)throw new Error('Panel response exceeds bound');
      let value;try{value=JSON.parse(text);}catch{throw new Error('Invalid owned panel response');}
      if(!response.ok){const error=new Error(value.error??`Panel HTTP ${response.status}`);error.httpStatus=response.status;throw error;}
      return value;
    }finally{clearTimeout(timer);}
  }
  response(panelId,state,extra={}){
    if(!state||typeof state!=='object'||!state.object||typeof state.object.object_id!=='string')throw new Error('Panel did not return an explicit current object');
    if(state.panel_id!==panelId)throw new Error('Panel response identity does not match the owned connection');
    validateId(state.object.object_id,'current object_id');
    // MCP already exposes tools/list; avoid returning the entire catalog with
    // every selection, and never duplicate the base64 image inside text.
    const {png_base64,clean_png_base64,tools,...view}=state,conn=this.getConnection(panelId);
    const data={schema_version:1,backend:'external-image-tools',panel_id:panelId,panel_url:`http://127.0.0.1:${conn.port}/#${conn.token}`,...extra,view,image_semantics:'Saved immutable PNG. Unsaved local display/gesture drafts are described by edit_state and are not baked into this image.',automatic_model_wake:false};
    const content=[{type:'text',text:JSON.stringify(data,null,2)}];
    if(png_base64!==null&&png_base64!==undefined){
      if(typeof png_base64!=='string'||png_base64.length>6*1024*1024)throw new Error('Invalid bounded saved panel PNG');
      const png=Buffer.from(png_base64,'base64');if(png.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')throw new Error('Panel saved image is not PNG');
      content.push({type:'image',mimeType:'image/png',data:png_base64});
    }
    return {content};
  }
  async current(args){
    let panelId=args.panel_id;
    if(!panelId){
      const entries=readdirSync(this.panels);if(entries.length>100)throw new Error('Panel registry exceeds inspection bound; specify panel_id');
      const live=[];
      await Promise.all(entries.filter(name=>/^[a-f0-9]{32}\.json$/.test(name)).map(async name=>{
        const id=name.slice(0,-5);try{const conn=this.getConnection(id),state=await this.request(conn,'GET','/api/state');if(state.panel_id!==id)throw new Error('Wrong panel identity');live.push({id,state});}catch{/* A stopped or malformed panel is not selected by recency. */}
      }));
      if(live.length!==1)throw new Error(`Expected exactly one live registered panel; found ${live.length}. Specify the retained panel_id.`);
      return this.response(live[0].id,live[0].state);
    }
    return this.response(panelId,await this.request(this.getConnection(panelId),'GET','/api/state'));
  }
  async waitForConnection(panelId){
    const started=Date.now();
    while(!existsSync(this.connectionFile(panelId))){if(Date.now()-started>this.readyTimeoutMs)throw new Error('Panel launch is unverified; query the original request_id. It will not be automatically relaunched.');await delay(40);}
    return this.getConnection(panelId);
  }
  async recover(record){
    if(record.status==='failed')throw new Error(record.error);
    if(record.name==='image_panel_open'){
      if(!existsSync(this.connectionFile(record.panel_id)))throw new Error('Original panel launch is still unverified. It will not be automatically relaunched.');
      const state=await this.request(this.getConnection(record.panel_id),'GET','/api/state');
      return this.response(record.panel_id,state,{request_id:record.request_id,recovered:true});
    }
    if(record.status==='completed')return this.response(record.panel_id,record.response,{request_id:record.request_id,recovered:true,snapshot_semantics:'Original immutable presentation receipt; use image_panel_current for the latest view.'});
    const state=await this.request(this.getConnection(record.panel_id),'GET','/api/present?request_id='+encodeURIComponent(record.request_id));
    if(!state.presentation||state.presentation.request_id!==record.request_id||!['shown','queued'].includes(state.presentation.status))throw new Error('Original panel presentation is not verified; no operation was repeated.');
    record.status='completed';record.response=state;durableWrite(this.requestFile(record.request_id),record);
    return this.response(record.panel_id,state,{request_id:record.request_id,recovered:true,snapshot_semantics:'Original immutable presentation receipt; use image_panel_current for the latest view.'});
  }
  async mutate(name,args){
    const file=this.requestFile(args.request_id);
    if(existsSync(file)){
      const prior=readJson(file,this.canonicalDirectory);
      if(prior.schema_version!==1||prior.name!==name||!identical(prior.arguments,args))throw new Error('Panel request_id conflicts with its original operation/parameters');
      return this.recover(prior);
    }
    await this.inspect(args.object_id);
    const panelId=name==='image_panel_open'?randomBytes(16).toString('hex'):args.panel_id;
    const record={schema_version:1,request_id:args.request_id,name,arguments:args,panel_id:panelId,status:'submitted'};
    // Exclusive/fsynced intent is saved before a child or HTTP mutation exists.
    try{durableWrite(file,record,{exclusive:true});}catch(error){if(error.code==='EEXIST')return this.mutate(name,args);throw error;}
    try{
      let state;
      if(name==='image_panel_open'){
        await this.launch({panel_id:panelId,object_id:args.object_id,connection_file:this.connectionFile(panelId)});
        state=await this.request(await this.waitForConnection(panelId),'GET','/api/state');
      }else{
        const {panel_id,request_id,object_id,expected_object_id,draft_revision}=args;
        state=await this.request(this.getConnection(panel_id),'POST','/api/present',{request_id,object_id,expected_object_id,draft_revision});
        if(!state.presentation||state.presentation.request_id!==request_id||!['shown','queued'].includes(state.presentation.status))throw new Error('Presentation response is unverified; query the original request_id.');
      }
      record.status='completed';if(name==='image_panel_show')record.response=state;
      durableWrite(file,record);
      return this.response(panelId,state,{request_id:args.request_id,recovered:false,...(name==='image_panel_show'?{snapshot_semantics:'Original immutable presentation receipt; use image_panel_current for the latest view.'}:{})});
    }catch(error){
      if(error.httpStatus&&error.httpStatus<500){record.status='failed';record.error=error.message;durableWrite(file,record);}
      throw new Error(`${error.message} Original panel request_id: ${args.request_id}; query the same tool with the same arguments, never submit a new ID to retry.`);
    }
  }
  call(name,args={},signal){
    validateArguments(name,args);this.initialize();
    if(signal?.aborted)throw new Error('Cancelled before panel operation submission');
    if(name==='image_panel_current')return waitWithoutCancelling(this.current(args),signal);
    const identity=args.request_id;
    let operation=this.active.get(identity);
    if(operation){
      if(!identical(operation.args,args)||operation.name!==name)throw new Error('Panel request_id conflicts with the in-flight operation');
    }else{
      const promise=this.mutate(name,args);operation={name,args,promise};this.active.set(identity,operation);
      promise.then(()=>this.active.delete(identity),()=>this.active.delete(identity));
    }
    return waitWithoutCancelling(operation.promise,signal);
  }
}
