// Explicit bounded numerical handoff into the pinned native adapter. This is
// data encoding/staging, not a processing fallback or arbitrary file execution.
import {createHash,randomBytes} from 'node:crypto';
import {openSync,closeSync,readSync,writeFileSync,fsyncSync,fstatSync,lstatSync,mkdirSync,realpathSync,existsSync,constants,linkSync,unlinkSync} from 'node:fs';
import path from 'node:path';
import {TextDecoder} from 'node:util';

const requestPattern=/^[A-Za-z0-9_-]{1,64}$/;
const axis={type:'object',additionalProperties:false,required:['origin','scale'],properties:{origin:{type:'number',description:'Raw DM index origin; physical coordinate = (index-origin)*scale.'},scale:{type:'number',description:'Signed nonzero axis scale; native binary32 rounding is recorded explicitly.'}}};
export const nativeImportTool={name:'dm_native_import',description:'Import one explicit immutable float32 NPY + provenance sidecar into a NEW bounded 2D DM working image. Normal-build qualification is only real_space nm or reciprocal_space 1/nm; other schema units require an explicit diagnostic build and remain unqualified. No source overwrite, hidden conversion, PNG import or automatic SHOW. Requires separately qualified native_numeric_import capability. Save request_id before calling; uncertain requests are queried, never automatically recreated.',inputSchema:{type:'object',additionalProperties:false,required:['source_path','source_manifest_path','coordinate_domain','calibration','request_id'],properties:{source_path:{type:'string',minLength:1,description:'Existing absolute scientific NPY, little-endian float32, C-order 2D, at most 16384 finite samples.'},source_manifest_path:{type:'string',minLength:1,description:'Existing absolute UTF-8 JSON source/provenance record; never executed.'},coordinate_domain:{type:'string',enum:['image_coordinates','real_space','reciprocal_space']},calibration:{type:'object',additionalProperties:false,required:['x','y','unit'],properties:{x:axis,y:axis,unit:{type:'string',enum:['','nm','angstrom','um','1/nm','1/angstrom','1/um']}}},request_id:{type:'string',pattern:'^[A-Za-z0-9_-]+$',minLength:1,maxLength:64}}}};
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const keys=(value,allowed)=>{if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!allowed.includes(k)))throw new Error('Unexpected native import fields');};
function flushNew(file,value){const temp=file+'.'+randomBytes(8).toString('hex')+'.tmp',fd=openSync(temp,'wx');try{writeFileSync(fd,typeof value==='string'||Buffer.isBuffer(value)?value:JSON.stringify(value));fsyncSync(fd);}finally{closeSync(fd);}try{linkSync(temp,file);}finally{unlinkSync(temp);}}
function absolutePath(file){if(typeof file!=='string'||!path.isAbsolute(file)||file.includes('\0'))throw new Error('Native import needs explicit absolute source paths');return path.resolve(file);}
function plainPath(file){
 absolutePath(file);
 let value=path.resolve(file);while(true){if(existsSync(value)&&lstatSync(value).isSymbolicLink())throw new Error('Native import refuses symlink/reparse paths');const parent=path.dirname(value);if(parent===value)break;value=parent;}
 return path.resolve(file);
}
function snapshot(file,maxBytes){
 const requested=plainPath(file),fd=openSync(requested,constants.O_RDONLY|(constants.O_NOFOLLOW??0));try{
  const before=fstatSync(fd,{bigint:true});if(!before.isFile()||before.size<=0n||before.size>BigInt(maxBytes))throw new Error('Native import source exceeds byte budget or is not a regular file');
  // A pre-read stat alone does not bound readFileSync on a growing file. Read
  // at most the observed size plus one byte, with a fixed bounded allocation.
  const buffer=Buffer.alloc(Number(before.size)+1);let total=0;
  while(total<buffer.length){const count=readSync(fd,buffer,total,buffer.length-total,null);if(!count)break;total+=count;}
  const after=fstatSync(fd,{bigint:true});plainPath(requested);const current=lstatSync(requested,{bigint:true});
  if(before.size!==after.size||before.mtimeNs!==after.mtimeNs||before.ctimeNs!==after.ctimeNs||before.dev!==current.dev||before.ino!==current.ino||before.size!==current.size||before.mtimeNs!==current.mtimeNs||before.ctimeNs!==current.ctimeNs||total!==Number(before.size))throw new Error('Source changed during bounded capture');
  const bytes=buffer.subarray(0,total);return {path:realpathSync.native(requested),bytes,sha256:hash(bytes)};
 }finally{closeSync(fd);}
}
export function parseImportNpy(bytes){
 if(!Buffer.isBuffer(bytes)||bytes.length<16||bytes.subarray(0,6).toString('hex')!=='934e554d5059'||![1,2].includes(bytes[6])||bytes[7]!==0)throw new Error('Only bounded NPY v1/v2 is supported');
 const start=bytes[6]===1?10:12,length=bytes[6]===1?bytes.readUInt16LE(8):bytes.readUInt32LE(8);
 if(length>4096||start+length>bytes.length)throw new Error('Invalid bounded NPY header');
 const headerBytes=bytes.subarray(start,start+length);
 if(!length||headerBytes.at(-1)!==10||headerBytes.some(value=>value>126||value<32&&![9,10,13].includes(value)))throw new Error('NPY header must be strict ASCII and end with a newline');
 const header=headerBytes.toString('ascii');
 const match=header.match(/^\{\s*(['"])descr\1\s*:\s*(['"])<f4\2\s*,\s*(['"])fortran_order\3\s*:\s*False\s*,\s*(['"])shape\4\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,?\s*\)\s*,?\s*\}\s*$/);
 if(!match)throw new Error('Import requires canonical little-endian float32, C-order, rank-two NPY; no pickle or silent dtype conversion');
 const height=Number(match[5]),width=Number(match[6]),count=width*height;
 if(!Number.isSafeInteger(count)||width<1||height<1||count>16384||bytes.length!==start+length+count*4)throw new Error('Import shape/byte length exceeds its exact 16384-sample budget');
 for(let i=start+length;i<bytes.length;i+=4)if(!Number.isFinite(bytes.readFloatLE(i)))throw new Error('Non-finite scientific input is unsupported');
 return {width,height,data_offset:start+length,dtype:'float32',shape_yx:[height,width]};
}
const words=hex=>hex.match(/.{8}/g).map(v=>Number.parseInt(v,16));
const bits=value=>{const b=Buffer.alloc(4);b.writeFloatLE(value);return b.readUInt32LE();};
function calibration(args){
 keys(args.calibration,['x','y','unit']);const original=args.calibration,result={};
 for(const key of ['x','y']){keys(original[key],['origin','scale']);result[key]={};for(const prop of ['origin','scale']){const value=original[key][prop],rounded=Math.fround(value);if(typeof value!=='number'||!Number.isFinite(value)||!Number.isFinite(rounded)||prop==='scale'&&rounded===0)throw new Error('Finite native calibration with nonzero signed scales required');result[key][prop]=rounded;}}
 for(const key of ['x','y'])if(!Number.isFinite(Math.fround(-result[key].origin*result[key].scale)))throw new Error('Native binary32 calibration physical-zero overflow');
 const domains=['image_coordinates','real_space','reciprocal_space'],units=['','nm','angstrom','um','1/nm','1/angstrom','1/um'],domain=domains.indexOf(args.coordinate_domain),unit=units.indexOf(original.unit);
 if(domain<0||unit<0||domain===0&&unit!==0||domain===1&&unit>3||domain===2&&unit!==0&&unit<4)throw new Error('Coordinate domain and spatial/reciprocal unit disagree');
 return {requested:structuredClone(original),native_binary32:{...result,unit:original.unit},packed:(domain<<4)|unit};
}
function validateEndpoints(cal,width,height){for(const [key,size]of [['x',width],['y',height]]){const axis=cal.native_binary32[key];if(!Number.isFinite(Math.fround(Math.fround(size-1-axis.origin)*axis.scale)))throw new Error('Native binary32 calibration endpoint overflow');}}
function parameterIdentity(args,cal){const source=absolutePath(args.source_path),manifest=absolutePath(args.source_manifest_path);if(path.extname(source).toLowerCase()!=='.npy'||path.extname(manifest).toLowerCase()!=='.json')throw new Error('Explicit .npy and .json source files required');const numericBits={};for(const key of ['x','y'])for(const prop of ['origin','scale']){const bytes=Buffer.alloc(8);bytes.writeDoubleLE(cal.requested[key][prop]);numericBits[key+'_'+prop]=bytes.toString('hex');}return {source_path:source,source_manifest_path:manifest,coordinate_domain:args.coordinate_domain,calibration:cal.requested,calibration_binary64_bits:numericBits};}
function originalRecord(file,parameters,cal,bridge,requestId){
 const prior=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(snapshot(file,64*1024).bytes));
 if(prior.schema_version!==2||!equal(prior.identity?.parameters,parameters)||prior.handoff?.session!==bridge.session||prior.handoff?.request_id!==requestId||prior.identity?.request_id!==requestId||!Array.isArray(prior.args)||prior.args.length!==27||!prior.args.every(v=>Number.isInteger(v)&&v>=0&&v<=0xffffffff))throw new Error('Native import original request ID parameter conflict or incomplete journal');
 const handoff=prior.handoff,shape=handoff.shape_yx,sourceHash=prior.identity.source_sha256,manifestHash=prior.identity.source_manifest_sha256;
 if(!/^[a-f0-9]{32}$/.test(prior.ticket??'')||!/^[a-f0-9]{64}$/.test(sourceHash??'')||!/^[a-f0-9]{64}$/.test(manifestHash??'')||handoff.source?.sha256!==sourceHash||handoff.source?.manifest_sha256!==manifestHash||handoff.source?.path!==prior.identity.source_path||handoff.source?.manifest_path!==prior.identity.source_manifest_path||!Array.isArray(shape)||shape.length!==2||!shape.every(v=>Number.isInteger(v)&&v>=1)||shape[0]*shape[1]>16384||handoff.dtype!=='float32'||!equal(handoff.axis_order,['y','x'])||handoff.coordinate_domain!==parameters.coordinate_domain||!equal(handoff.calibration,cal)||typeof handoff.source_provenance_raw_json!=='string'||hash(Buffer.from(handoff.source_provenance_raw_json,'utf8'))!==manifestHash)throw new Error('Native import journal scientific identity mismatch');
 validateEndpoints(cal,shape[1],shape[0]);
 const expected=[...words(prior.ticket),...words(sourceHash),...words(hash(Buffer.from(JSON.stringify(handoff)))),shape[1],shape[0],bits(cal.native_binary32.x.origin),bits(cal.native_binary32.x.scale),bits(cal.native_binary32.y.origin),bits(cal.native_binary32.y.scale),cal.packed];
 if(!equal(expected,prior.args))throw new Error('Native import journal wire/hash/calibration mismatch');return prior;
}
function validateImportReceipt(reply,bridge,requestId,wire){
 if(!reply||reply.protocol!=='NB2'||reply.session!==bridge.session||reply.id!==requestId)throw new Error('Native import receipt protocol/session/request mismatch');
 if(reply.original_operation===null){if(!['unknown','failed'].includes(reply.state)||reply.normalized_args!==null||reply.result_type!==null||reply.result_version!==null||Object.hasOwn(reply,'result'))throw new Error('Native import missing-record receipt cannot claim completion');}
 else if(reply.original_operation!=='IMPORT'||!equal(reply.normalized_args,wire)||reply.result_type!=='native_numeric_import'||reply.result_version!==1||!['queued','running','completed','failed'].includes(reply.state))throw new Error('Native import receipt original operation/wire identity mismatch');
 return reply;
}
async function queryOriginal(bridge,requestId,prior,signal){const reply=validateImportReceipt(await bridge.query(requestId,{signal}),bridge,requestId,prior.args);return {...reply,import_handoff:prior.handoff,recovered_by_query:true};}
function parsedProvenanceSafe(value){const pending=[value];while(pending.length){const current=pending.pop();if(typeof current==='number'&&(!Number.isFinite(current)||Number.isInteger(current)&&!Number.isSafeInteger(current)))return false;if(current&&typeof current==='object')pending.push(...Object.values(current));}return true;}
export async function callNativeImport(bridge,args,{signal,localAppData=process.env.LOCALAPPDATA}={}){
 keys(args,['source_path','source_manifest_path','coordinate_domain','calibration','request_id']);
 if(typeof args.request_id!=='string'||!requestPattern.test(args.request_id))throw new Error('Pre-saved request_id required before native import');
 if(!/^[a-f0-9]{32}$/.test(bridge?.session??'')||typeof bridge.importSnapshot!=='function'||typeof bridge.query!=='function')throw new Error('Explicit native session/import adapter required');
 if(signal?.aborted)throw new Error('Cancelled before native import capture');
 const cal=calibration(args),parameters=parameterIdentity(args,cal);
 if(!localAppData||!path.isAbsolute(localAppData))throw new Error('Native import requires configured absolute LOCALAPPDATA');
 const directory=plainPath(path.join(localAppData,'mcp-dm','native-import',bridge.session));mkdirSync(directory,{recursive:true});plainPath(directory);
 const recordPath=path.join(directory,args.request_id+'.request.json');
 // An original ID always refers to the originally captured bytes. Recovery
 // must not depend on the current existence/content of those source paths.
 if(existsSync(recordPath))return queryOriginal(bridge,args.request_id,originalRecord(recordPath,parameters,cal,bridge,args.request_id),signal);
 const source=snapshot(args.source_path,64*1024+4108),npy=parseImportNpy(source.bytes),manifest=snapshot(args.source_manifest_path,24*1024);let provenance,manifestText;
 try{manifestText=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(manifest.bytes);provenance=JSON.parse(manifestText.replace(/^\uFEFF/,''));}catch{throw new Error('Source provenance must be valid UTF-8 JSON; no encoding guessing');}
 if(!provenance||typeof provenance!=='object'||Array.isArray(provenance))throw new Error('Source provenance must be a JSON object');
 validateEndpoints(cal,npy.width,npy.height);
 const identity={request_id:args.request_id,parameters,source_path:source.path,source_sha256:source.sha256,source_manifest_path:manifest.path,source_manifest_sha256:manifest.sha256,coordinate_domain:args.coordinate_domain,calibration:cal.requested};
 const ticket=randomBytes(16).toString('hex'),safeProvenance=parsedProvenanceSafe(provenance),handoff={schema_version:1,session:bridge.session,request_id:args.request_id,source:{path:source.path,sha256:source.sha256,manifest_path:manifest.path,manifest_sha256:manifest.sha256},dtype:npy.dtype,shape_yx:npy.shape_yx,axis_order:['y','x'],coordinate_domain:args.coordinate_domain,calibration:cal,source_provenance:safeProvenance?provenance:null,source_provenance_raw_json:manifestText,source_provenance_authority:'Exact hash-bound original UTF-8 JSON text; parsed object is convenience only',source_provenance_parsed_numbers_safe:safeProvenance,scientific_data_changed:false,original_files_modified:false,source_history:'Preserved supplied provenance; no unobserved DM processing history is inferred.'};
 const sidecar=Buffer.from(JSON.stringify(handoff));if(sidecar.length>32768)throw new Error('Import handoff provenance exceeds 32 KiB budget');
 if(Buffer.byteLength(JSON.stringify(sidecar.toString('utf8')),'utf8')>16*1024)throw new Error('Import quoted provenance exceeds the 16 KiB native response budget');
 const wire=[...words(ticket),...words(source.sha256),...words(hash(sidecar)),npy.width,npy.height,bits(cal.native_binary32.x.origin),bits(cal.native_binary32.x.scale),bits(cal.native_binary32.y.origin),bits(cal.native_binary32.y.scale),cal.packed];
 flushNew(path.join(directory,ticket+'.npy'),source.bytes);flushNew(path.join(directory,ticket+'.json'),sidecar);
 try{flushNew(recordPath,{schema_version:2,identity,ticket,args:wire,handoff});}catch(error){if(!existsSync(recordPath))throw error;return queryOriginal(bridge,args.request_id,originalRecord(recordPath,parameters,cal,bridge,args.request_id),signal);}
 // No second submission on cancellation, timeout or a new client. A retained
 // original intent is queried even if a process stopped before sending it.
 const reply=validateImportReceipt(await bridge.importSnapshot(wire,{requestId:args.request_id,signal}),bridge,args.request_id,wire);
 return {...reply,import_handoff:handoff};
}
