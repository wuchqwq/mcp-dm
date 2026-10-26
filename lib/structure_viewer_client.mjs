// A small optional presentation attachment. Scientific work is already complete;
// missing viewer dependencies never relabel its ASE projection as interactive3D.
import {spawn} from 'node:child_process';
import {randomBytes,createHash} from 'node:crypto';
import {existsSync,mkdirSync,lstatSync,realpathSync,readFileSync,openSync,writeFileSync,fsyncSync,closeSync,linkSync,unlinkSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateStructureSnapshot,read3DmolAsset} from '../tools/structure_viewer.mjs';
const id=/^[a-f0-9]{32}$/,sha=bytes=>createHash('sha256').update(bytes).digest('hex'),active=new Map();
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function require(value,message){if(!value)throw new Error(message);}
function readJson(file,directory,maxBytes=2*1024*1024){const stat=lstatSync(file),real=realpathSync.native(file),relative=path.relative(directory,real);require(stat.isFile()&&!stat.isSymbolicLink()&&stat.size>0&&stat.size<=maxBytes&&relative!=='..'&&!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative),'Invalid private viewer record');return JSON.parse(readFileSync(real,'utf8'));}
function newFile(file,bytes){const temp=file+'.'+randomBytes(8).toString('hex')+'.tmp',fd=openSync(temp,'wx');try{writeFileSync(fd,bytes);fsyncSync(fd);}finally{closeSync(fd);}try{linkSync(temp,file);}finally{unlinkSync(temp);}}
function privateDirectory(workspace){require(typeof workspace==='string'&&path.isAbsolute(workspace),'Configured absolute structure workspace required');const root=realpathSync.native(workspace),directory=path.join(root,'viewer-connections');mkdirSync(directory,{recursive:true});const stat=lstatSync(directory);require(stat.isDirectory()&&!stat.isSymbolicLink(),'Viewer registry must be an ordinary owned directory');return realpathSync.native(directory);}
function parseResult(result){require(result&&!result.isError&&Array.isArray(result.content),'A completed structure_view MCP result is required');const index=result.content.findIndex(c=>c.type==='text');require(index>=0,'Missing structure view metadata');const data=JSON.parse(result.content[index].text);require(data.backend==='external-structure-workspace'&&data.state==='completed'&&data.kind==='view'&&id.test(data.object_id??'')&&id.test(data.structure_object_id??''),'Interactive viewer requires an exact completed structure view');return {data,index};}
function attach(result,index,data,viewer){const content=[...result.content];content[index]={...content[index],text:JSON.stringify({...data,...viewer,automatic_model_wake:false},null,2)};return {...result,content};}
async function connectionState(file,directory,viewId,snapshotHash,assetHash,signal){
 const started=Date.now();while(!existsSync(file)){if(signal?.aborted)throw new Error('Stopped waiting; the original owned viewer may still start. It will not be relaunched.');if(Date.now()-started>10000)throw new Error('Original viewer launch remains unverified; it will not be relaunched.');await wait(40);}
 const conn=readJson(file,directory,8192);require(conn.schema_version===1&&conn.object_id===viewId&&conn.snapshot_sha256===snapshotHash&&conn.renderer?.name==='3Dmol.js'&&conn.renderer?.asset_sha256===assetHash&&Number.isInteger(conn.port)&&conn.port>=1&&conn.port<=65535&&typeof conn.token==='string'&&/^[a-f0-9]{48}$/.test(conn.token)&&Number.isSafeInteger(conn.pid)&&conn.pid>0,'Owned viewer connection identity mismatch');
 const origin='http://127.0.0.1:'+conn.port,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000),abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
 try{
  if(signal?.aborted)abort();const response=await fetch(origin+'/api/structure',{headers:{'X-Viewer-Token':conn.token,Origin:origin},signal:controller.signal});require(response.ok,'Owned viewer is no longer available; it will not be relaunched');
  const reader=response.body.getReader(),chunks=[];let count=0;for(;;){const {done,value}=await reader.read();if(done)break;count+=value.byteLength;if(count>2*1024*1024){await reader.cancel();throw new Error('Viewer reply exceeds bounded snapshot budget');}chunks.push(Buffer.from(value));}
  const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));require(body.structure?.object_id===viewId&&body.snapshot_sha256===snapshotHash&&sha(Buffer.from(JSON.stringify(body.structure)))===snapshotHash&&body.renderer?.name==='3Dmol.js'&&body.renderer?.asset_sha256===assetHash&&body.read_only===true,'Live viewer snapshot does not match its original structure view');
  return {interactive_3d:'AVAILABLE_NOT_OBSERVED',viewer_state:'ready',viewer_url:origin+'/#'+conn.token,viewer_renderer:body.renderer,viewer_snapshot_sha256:snapshotHash,viewer_process_id:conn.pid,viewer_semantics:'Owned local 3Dmol view of fixed ASE atoms; URL readiness is not browser/WebGL acceptance. Camera changes do not alter scientific coordinates.'};
 }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
async function inspectData(inspect,viewId,sourceId){
 const response=await inspect(viewId),raw=response?.content?.find(c=>c.type==='text')?.text,data=raw===undefined?response:JSON.parse(raw);require(!response?.isError&&data?.object_id===viewId&&data.structure_object_id===sourceId&&data.atoms,'Exact structure_info view/atom ancestry is required');
 const atoms=data.atoms,snapshot={object_id:viewId,symbols:atoms.symbols,positions_angstrom:atoms.positions_angstrom,cell_angstrom:atoms.cell_angstrom,pbc:atoms.pbc};const normalized=validateStructureSnapshot(snapshot);return {snapshot,normalized};
}
async function obtainViewer(data,{workspace,assetPath,inspect,signal}){
 const directory=privateDirectory(workspace),viewId=data.object_id,sourceId=data.structure_object_id,intentFile=path.join(directory,viewId+'.intent.json'),snapshotFile=path.join(directory,viewId+'.snapshot.json'),connectionFile=path.join(directory,viewId+'.connection.json');
 if(existsSync(intentFile)){const prior=readJson(intentFile,directory,16384);require(prior.schema_version===1&&prior.view_object_id===viewId&&prior.structure_object_id===sourceId&&/^[a-f0-9]{64}$/.test(prior.snapshot_sha256??'')&&/^[a-f0-9]{64}$/.test(prior.asset_sha256??''),'Original viewer intent identity mismatch');return connectionState(connectionFile,directory,viewId,prior.snapshot_sha256,prior.asset_sha256,signal);}
 const asset=read3DmolAsset(assetPath);require(typeof inspect==='function','Existing structure_info inspector required');const {snapshot,normalized}=await inspectData(inspect,viewId,sourceId),snapshotBytes=Buffer.from(JSON.stringify(snapshot)),snapshotHash=sha(Buffer.from(JSON.stringify(normalized)));
 if(signal?.aborted)return {interactive_3d:'NOT_STARTED',viewer_state:'cancelled_before_launch',viewer_url:null};
 try{newFile(snapshotFile,snapshotBytes);}catch(error){if(error.code!=='EEXIST')throw error;const prior=readJson(snapshotFile,directory);require(sha(Buffer.from(JSON.stringify(prior)))===sha(snapshotBytes),'Viewer fixed-snapshot identity conflict');}
 const intent={schema_version:1,view_object_id:viewId,structure_object_id:sourceId,snapshot_sha256:snapshotHash,snapshot_file_sha256:sha(snapshotBytes),asset_sha256:asset.sha256,original_request_id:data.request_id??null,state:'launch_requested',created_utc:new Date().toISOString()};let ownsLaunch=true;
 try{newFile(intentFile,Buffer.from(JSON.stringify(intent)));}catch(error){if(error.code!=='EEXIST')throw error;ownsLaunch=false;const prior=readJson(intentFile,directory,16384);require(prior.view_object_id===viewId&&prior.structure_object_id===sourceId&&prior.snapshot_sha256===snapshotHash,'Viewer launch identity conflict');}
 if(ownsLaunch){const child=spawn(process.execPath,[fileURLToPath(new URL('../tools/structure_viewer.mjs',import.meta.url)),'--snapshot',snapshotFile,'--asset',assetPath,'--connection-file',connectionFile],{detached:true,windowsHide:true,stdio:'ignore'});await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});child.unref();}
 return connectionState(connectionFile,directory,viewId,snapshotHash,asset.sha256,signal);
}
export async function attachStructureViewer(result,{workspace,assetPath,inspect,signal}={}){
 const {data,index}=parseResult(result);
 if(!assetPath)return attach(result,index,data,{interactive_3d:'NOT_CONFIGURED',viewer_state:'not_configured',viewer_url:null,viewer_limitation:'The returned image remains the ASE2D projection. Configure the independent local3dmol asset to request interactive3D.'});
 if(signal?.aborted)return attach(result,index,data,{interactive_3d:'NOT_STARTED',viewer_state:'cancelled_before_launch',viewer_url:null});
 const key=String(workspace)+'|'+data.object_id;
 try{let pending=active.get(key);if(!pending){pending=obtainViewer(data,{workspace,assetPath,inspect,signal});active.set(key,pending);pending.finally(()=>{if(active.get(key)===pending)active.delete(key);}).catch(()=>{});}const viewer=await pending;return attach(result,index,data,{...viewer,viewer_source:{view_object_id:data.object_id,structure_object_id:data.structure_object_id}});}
 catch(error){return attach(result,index,data,{interactive_3d:'UNVERIFIED',viewer_state:'unavailable_or_unknown',viewer_url:null,viewer_limitation:error.message});}
}
