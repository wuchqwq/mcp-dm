// Direct researcher entry: the same local MCP/scientific backend, no model.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomBytes} from 'node:crypto';
import {mkdirSync,existsSync,realpathSync,statSync,openSync,writeFileSync,fsyncSync,closeSync,readFileSync,renameSync,unlinkSync} from 'node:fs';
import {StdioImageClient,createImagePanel} from './image_panel.mjs';

const objectId=/^[a-f0-9]{32}$/;
const HELP='node tools/researcher_inspector.mjs --source ABS_TIFF --workspace ABS_DIRECTORY --python ABS_PYTHON [--frame 1]. Reopen with the same workspace/python; source and initial frame may be omitted.';
function durableNew(file,value){const fd=openSync(file,'wx');try{writeFileSync(fd,JSON.stringify(value,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}}
function boundedJSON(file){if(statSync(file).size>1024*1024)throw new Error('Inspector record exceeds 1 MiB');return JSON.parse(readFileSync(file,'utf8'));}
function replaceJSON(file,value){const temporary=file+'.'+randomBytes(6).toString('hex')+'.tmp';durableNew(temporary,value);try{renameSync(temporary,file);}finally{if(existsSync(temporary))unlinkSync(temporary);}}
function inside(root,file){const resolved=realpathSync(file),relative=path.relative(realpathSync(root),resolved);if(relative.startsWith('..')||path.isAbsolute(relative))throw new Error('Inspector reference escapes its workspace');return resolved;}

export function parseResearcherArgs(argv){
 const options={};
 for(let i=0;i<argv.length;i+=2){const key=argv[i],value=argv[i+1];if(!['--source','--workspace','--python','--frame'].includes(key)||!value||options[key.slice(2)]!==undefined)throw new Error(HELP);options[key.slice(2)]=value;}
 for(const key of ['workspace','python'])if(!path.isAbsolute(options[key]??''))throw new Error('Explicit absolute '+key+' required. '+HELP);
 if(options.source!==undefined&&!path.isAbsolute(options.source))throw new Error('Source must be an absolute local TIFF path');
 if(options.frame!==undefined&&(!/^[1-9][0-9]*$/.test(options.frame)||!Number.isSafeInteger(Number(options.frame))))throw new Error('Frame is a human-facing integer starting at 1');
 if(options.frame!==undefined)options.frame=Number(options.frame);
 return options;
}

export async function startResearcherInspector(options,{createClient=args=>new StdioImageClient(args),openPanel=createImagePanel}={}){
 // The only file entry is the explicitly named TIFF. All later references are
 // provider objects or this launcher's own bounded journal within the workspace.
 const workspace=path.resolve(options.workspace),python=options.python;
 if(!path.isAbsolute(options.workspace??'')||!path.isAbsolute(python??''))throw new Error('Absolute workspace and external Python paths required');
 if(!existsSync(python)||!statSync(python).isFile())throw new Error('External Python executable does not exist');
 mkdirSync(workspace,{recursive:true});
 const directory=path.join(workspace,'researcher-inspector');mkdirSync(directory,{recursive:true});
 const sessionPath=path.join(directory,'session.json');let session;
 if(existsSync(sessionPath)){
  session=boundedJSON(inside(workspace,sessionPath));
  if(session.schema_version!==1||session.workspace!==realpathSync(workspace)||!objectId.test(session.session_id??''))throw new Error('Inspector session binding is invalid');
  if(options.source!==undefined&&realpathSync(options.source)!==session.source_path)throw new Error('Workspace is bound to a different TIFF; use a new workspace');
  if(options.frame!==undefined&&options.frame!==session.initial_frame)throw new Error('Initial frame differs; resume the saved view and use its frame navigation');
 }else{
  if(!path.isAbsolute(options.source??'')||!existsSync(options.source)||!statSync(options.source).isFile())throw new Error('First launch requires an explicit existing local TIFF source');
  const initialFrame=options.frame??1;if(!Number.isSafeInteger(initialFrame)||initialFrame<1)throw new Error('Frame starts at 1');
  session={schema_version:1,session_id:randomBytes(16).toString('hex'),workspace:realpathSync(workspace),source_path:realpathSync(options.source),initial_frame:initialFrame,created_utc:new Date().toISOString()};
  durableNew(sessionPath,session);
 }
 const startup=path.join(directory,'startup');mkdirSync(startup,{recursive:true});
 const call=async(client,label,name,args)=>{
  const request={name,arguments:{...args,request_id:`inspector-${session.session_id.slice(0,12)}-${label}`}},requestFile=path.join(startup,label+'.request.json'),responseFile=path.join(startup,label+'.response.json');
  if(existsSync(requestFile)){
   const saved=boundedJSON(requestFile);if(JSON.stringify(saved)!==JSON.stringify(request))throw new Error('Original inspector request conflicts with saved parameters');
   // An accepted operation is queried by its original ID, never resubmitted.
   const result=await client.tool('image_result',{request_id:saved.arguments.request_id});
   if(!objectId.test(result.data?.object_id??''))throw new Error('Original request remains unresolved: '+saved.arguments.request_id);
   if(existsSync(responseFile)){const receipt=boundedJSON(responseFile);if(receipt.object_id!==result.data.object_id)throw new Error('Recovered request returned a different object');}
   else durableNew(responseFile,{object_id:result.data.object_id,request_id:saved.arguments.request_id});
   return result.data;
  }
  durableNew(requestFile,request);
  let result;try{result=await client.tool(name,request.arguments);}catch(error){error.message+=` Original inspector request_id=${request.arguments.request_id}; reopen this workspace to query it. Do not submit another write to recover it.`;throw error;}
  if(!objectId.test(result.data?.object_id??''))throw new Error('Operation has not returned a saved object. Recover original request '+request.arguments.request_id);
  durableNew(responseFile,{object_id:result.data.object_id,request_id:request.arguments.request_id});return result.data;
 };
 let bootstrap=createClient({workspace,python}),selected,previousDraft=false,resumed=false;
 try{
  const initialized=await bootstrap.rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'mcp-dm-researcher-inspector',version:'1'}});if(initialized.error)throw new Error(initialized.error.message);
  const pointer=path.join(directory,'latest-panel.json');
  if(existsSync(pointer)){
   resumed=true;
   const saved=boundedJSON(inside(workspace,pointer));
   if(saved.schema_version!==1||saved.session_id!==session.session_id||!objectId.test(saved.run_id??''))throw new Error('Saved panel binding is invalid');
   const selectionPath=inside(workspace,path.join(directory,'panels',saved.run_id,'journal','current-selection.json'));
   const selection=boundedJSON(selectionPath);if(!objectId.test(selection.object_id??''))throw new Error('Saved panel object identity is invalid');
   selected=(await bootstrap.tool('image_info',{object_id:selection.object_id})).data;
   previousDraft=Boolean(selection.edit_state?.dirty||selection.edit_state?.gesture_active);
  }else{
   const source=await call(bootstrap,'open','image_open',{source_path:session.source_path});
   const frame=await call(bootstrap,'frame','image_frame',{object_id:source.object_id,frame_index:session.initial_frame-1});
   selected=await call(bootstrap,'preview','image_preview',{object_id:frame.object_id});
  }
 }finally{await bootstrap.close();}
 const runId=randomBytes(16).toString('hex'),runDirectory=path.join(directory,'panels',runId),journalDirectory=path.join(runDirectory,'journal');mkdirSync(runDirectory,{recursive:true});
 durableNew(path.join(runDirectory,'run.json'),{schema_version:1,session_id:session.session_id,object_id:selected.object_id,created_utc:new Date().toISOString()});
 let panel;
 try{panel=await openPanel({workspace,python,object_id:selected.object_id,journalDirectory});replaceJSON(path.join(directory,'latest-panel.json'),{schema_version:1,session_id:session.session_id,run_id:runId});}
 catch(error){if(panel)await panel.close();throw error;}
 return {panel,workspace,source_path:session.source_path,resumed,previous_unsaved_draft:previousDraft,
  async close(){await panel.close();}};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 let instance;
 try{
  instance=await startResearcherInspector(parseResearcherArgs(process.argv.slice(2)));
  process.stdout.write('Researcher Image Inspector — scientific backend active; no model session.\n'+instance.panel.url+'\n');
  process.stdout.write('Keep this process running. Ctrl+C closes the local panel normally. Reuse the same workspace to reopen saved results.\n');
  if(instance.previous_unsaved_draft)process.stderr.write('The previous session had an unsaved draft. Its original journal is retained; this window resumes only the last saved scientific object.\n');
  let closing=false;const close=async()=>{if(!closing){closing=true;await instance.close();}};process.on('SIGINT',close);process.on('SIGTERM',close);
 }catch(error){process.stderr.write(error.message+'\n');process.exitCode=1;}
}
