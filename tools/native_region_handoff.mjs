#!/usr/bin/env node
// Explicit numerical handoff, not a DM operator or SaveAs. The only host work
// here is existing STATUS/READ/QUERY; bytes are copied without pixel arithmetic.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {NativeBridge, validRequestId, validateNativeFrame} from '../lib/native_bridge.mjs';
import {canonical, strictJson, newTarget, validateSavedSnapshot, encodeNpyHeader, packageInfo, captureFrameAncestry} from './native_snapshot_handoff.mjs';

const check=(yes,message)=>{if(!yes)throw new Error(message);};
const hash=b=>createHash('sha256').update(b).digest('hex');
const equal=(a,b)=>canonical(a)===canonical(b);
const uint=n=>Number.isInteger(n)&&n>=0&&n<=0xffffffff;
const LIMIT=Object.freeze({samplesPerBlock:16384,sourcePixels:4194304,blocks:512,savedResponseBytes:128*1024,
  diskBytes:96*1024*1024,ioBufferBytes:65536});
export const REGION_LIMITS=LIMIT;
const jsonBytes=v=>Buffer.from(JSON.stringify(v,null,2)+'\n');
function ordinary(filename,max) {const s=fs.lstatSync(filename);check(s.isFile()&&!s.isSymbolicLink()&&s.size<=max,'Bounded ordinary evidence file required');return s;}
function json(filename,max=1024*1024) {ordinary(filename,max);return strictJson(new TextDecoder('utf-8',{fatal:true}).decode(fs.readFileSync(filename)));}
function write(fd,bytes,position=0) {let n=0;while(n<bytes.length){const k=fs.writeSync(fd,bytes,n,bytes.length-n,position+n);check(k>0,'File write made no progress');n+=k;}}
function saveNew(filename,bytes) {const fd=fs.openSync(filename,'wx');try{write(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
function update(fd,value) {const bytes=jsonBytes(value);check(bytes.length<=1024*1024,'Journal budget exceeded');fs.ftruncateSync(fd,0);write(fd,bytes);fs.fsyncSync(fd);}
export function hashFile(filename,skip=0) {
  const s=ordinary(filename,LIMIT.diskBytes),fd=fs.openSync(filename,'r'),digest=createHash('sha256'),buf=Buffer.alloc(LIMIT.ioBufferBytes);
  try {for(let pos=skip;pos<s.size;){const n=fs.readSync(fd,buf,0,Math.min(buf.length,s.size-pos),pos);check(n>0,'File read made no progress');digest.update(buf.subarray(0,n));pos+=n;}}
  finally{fs.closeSync(fd);}return digest.digest('hex');
}

function regionLayout({imageId,rect,blockSamples=LIMIT.samplesPerBlock,session,hostPid,requestId}) {
  check(uint(imageId)&&imageId>0&&uint(hostPid)&&hostPid>0&&/^[a-f0-9]{32}$/.test(session)&&validRequestId(requestId),'Explicit image/session/PID/export ID required');
  check(Array.isArray(rect)&&rect.length===4&&rect.every(uint)&&rect[2]>rect[0]&&rect[3]>rect[1],'Positive half-open integer rectangle required');
  const width=rect[2]-rect[0],height=rect[3]-rect[1];
  check(width*height<=LIMIT.sourcePixels&&Number.isInteger(blockSamples)&&blockSamples>0&&blockSamples<=LIMIT.samplesPerBlock,'Pixel/block budget exceeded before reads');
  const tileWidth=Math.min(width,blockSamples),tileHeight=Math.max(1,Math.floor(blockSamples/tileWidth));
  check(Math.ceil(width/tileWidth)*Math.ceil(height/tileHeight)<=LIMIT.blocks,'Block/session request budget exceeded before reads');
  return {width,height,tileWidth,tileHeight};
}

// A null namespace exists only to validate completed historical journals.
// It must never be used for a new capture or a live recovery.
function regionPlan({imageId,rect,blockSamples=LIMIT.samplesPerBlock,session,hostPid,requestId},captureId) {
  const options={imageId,rect,blockSamples,session,hostPid,requestId};
  const {width,height,tileWidth,tileHeight}=regionLayout(options);
  const identity=captureId===null?options:{...options,captureId};
  const prefix='region-'+hash(canonical(identity)).slice(0,32);
  const make=(op,args,suffix)=>{const id=prefix+'-'+suffix;return {protocol:'NB2',session,host_pid:hostPid,id,op,args,
    wire:`NB2 ${session} ${id} ${op}${args.length?' '+args.join(' '):''}\n`};};
  const blocks=[];
  for(let y=rect[1];y<rect[3];y+=tileHeight)for(let x=rect[0];x<rect[2];x+=tileWidth){
    const r=[x,y,Math.min(rect[2],x+tileWidth),Math.min(rect[3],y+tileHeight)];
    blocks.push({index:blocks.length,request:make('READ',[imageId,...r],String(blocks.length)),state:'PLANNED'});
  }
  const estimate=blocks.length*LIMIT.savedResponseBytes+width*height*4+2*1024*1024;
  check(estimate<=LIMIT.diskBytes,'Disk budget exceeded before reads');
  return {shape:[height,width],blocks,status:{request:make('STATUS',[],'status'),state:'PLANNED'},
    new_request_records:blocks.length+1,max_new_request_records:LIMIT.blocks+1,session_record_reservation:false,
    disk_budget_bytes:LIMIT.diskBytes,disk_estimate_bytes:estimate,io_buffer_bytes:LIMIT.ioBufferBytes};
}

export function planRegion(options) {
  check(typeof options.captureId==='string'&&options.captureId.length===32&&/^[a-f0-9]{32}$/.test(options.captureId),
    'Explicit persisted capture ID required for request isolation');
  return regionPlan(options,options.captureId);
}

function checkReply(reply,request) {
  check(reply?.protocol==='NB2'&&reply.session===request.session&&reply.id===request.id&&reply.host_pid===request.host_pid&&
    reply.state==='completed'&&reply.original_operation===request.op&&equal(reply.normalized_args,request.args)&&
    reply.result_version===1&&uint(reply.exec_tid)&&reply.exec_tid>0&&uint(reply.worker_tid)&&reply.worker_tid>0&&reply.exec_tid!==reply.worker_tid,
  'Original completed host/session/operation receipt required; query this saved ID, never resubmit');
  return reply;
}
function readSnapshot(reply,request) {
  checkReply(reply,request);
  const {result,...receipt}=reply;const payload={...result,native_receipt:{...receipt,request_id:receipt.id}};
  const bytes=jsonBytes(payload);check(bytes.length<=LIMIT.savedResponseBytes,'Saved response budget exceeded');
  return {snapshot:validateSavedSnapshot(bytes),bytes};
}
function descriptor(snapshot) {
  const r=snapshot.result;
  return {source:r.source,scientific_context:r.scientific_context??null,source_provenance:r.source_provenance,
    source_provenance_scope:r.source_provenance_scope,coordinate_mapping_policy:r.coordinate_mapping_policy,dtype:r.dtype,
    frame_ancestry:captureFrameAncestry(r)};
}
function creationRecord(reply,snapshot,parameters) {
  const provenance=snapshot.result.source_provenance;
  const schemas={FRAME:[2,'native_frame_copy'],CROP:[5,'image_crop'],UNARY:[2,'native_image_operation'],BINARY:[3,'native_image_operation'],FILTER:[2,'native_image_operation'],
    FFT:[1,'native_fourier_operation'],IFFT:[1,'native_fourier_operation'],REAL:[1,'native_fourier_operation'],IMAG:[1,'native_fourier_operation'],VENDOR_ARG:[1,'native_fourier_operation'],VENDOR_NORM:[1,'native_fourier_operation']};
  const contract=schemas[provenance?.operation];
  check(contract&&reply?.protocol==='NB2'&&reply.session===parameters.session&&reply.host_pid===parameters.hostPid&&reply.id===provenance.request_id&&
    reply.state==='completed'&&reply.original_operation===provenance.operation&&reply.result_type===contract[1]&&
    reply.result_version===(contract[1]==='native_fourier_operation'?2:1)&&Array.isArray(reply.normalized_args)&&reply.normalized_args.length===contract[0]&&reply.normalized_args.every(uint)&&
    uint(reply.exec_tid)&&reply.exec_tid>0&&uint(reply.worker_tid)&&reply.worker_tid>0&&reply.exec_tid!==reply.worker_tid&&
    reply.result?.backend==='digitalmicrograph-native'&&reply.result.image_id===snapshot.result.source_image_id&&equal(reply.result.image,snapshot.result.source)&&
    equal(provenance.source_image_ids,reply.normalized_args.slice(0,reply.original_operation==='BINARY'?2:1)),
  'Original source creation record mismatch; no reconstructed processing parameters');
  if(provenance.operation==='FRAME') {
    validateNativeFrame(reply.result,reply.normalized_args);
    const ancestry=captureFrameAncestry(snapshot.result),{retention,native_receipt,...payload}=reply.result;void retention;void native_receipt;
    check(ancestry?.request_id===reply.id&&equal(ancestry.normalized_args,reply.normalized_args)&&equal(ancestry.result,payload),
      'Original FRAME creation record differs from frozen frame ancestry');
  }
  return {file:'source-creation.json',sha256:hash(jsonBytes(reply)),request_id:reply.id,original_operation:reply.original_operation,
    normalized_args:reply.normalized_args,scope:'original immediate source creation only; earlier ancestry is not traversed'};
}
function checkedSnapshot(target,block,parameters) {
  check(block.state==='COMPLETED'&&typeof block.snapshot_sha256==='string','Incomplete block');
  const filename=path.join(target,`read-${block.index}.json`);ordinary(filename,LIMIT.savedResponseBytes);
  const bytes=fs.readFileSync(filename);check(hash(bytes)===block.snapshot_sha256,'Saved block hash changed');
  const snapshot=validateSavedSnapshot(bytes),receipt=snapshot.receipt;
  checkReply({...receipt,result:snapshot.result},block.request);
  check(receipt.session===parameters.session&&receipt.host_pid===parameters.hostPid,'Saved block host changed');
  return snapshot;
}
function verifiedCapture(target,journal,plan) {
  const receipt=journal.capture_receipt;check(journal.state==='CAPTURED'&&receipt?.state==='captured','Incomplete capture');
  check(receipt.capture_dir===target&&receipt.request_id===journal.parameters.requestId,
    'Capture receipt belongs to another output directory or export ID');
  const info=json(path.join(target,'input.json')),manifest=json(path.join(target,'capture.json'));
  check(info.capture_mode==='native_chunked_read'&&manifest.state==='captured'&&info.capture_id===journal.capture_id&&manifest.capture_id===journal.capture_id&&
    equal(manifest.blocks,journal.blocks)&&manifest.complete_coverage===true&&equal(info.shape_yx,plan.shape)&&
    equal(info.source_rect_xyxy,journal.parameters.rect)&&info.source_image_id===journal.parameters.imageId&&info.pixel_capture_atomic===false&&
    info.native_receipt===null&&info.native_receipt_scope==='per_block','Capture metadata/coverage mismatch');
  for(const name of ['input.npy','input.json','capture.json',...(info.native_source_creation_record?['source-creation.json']:[])])check(hashFile(path.join(target,name))===receipt.files_sha256[name],'Captured file changed: '+name);
  check(info.input_sha256===receipt.files_sha256['input.npy']&&hash(canonical(info))===manifest.input_metadata_sha256,'Capture input/metadata hash mismatch');
  for(const block of journal.blocks){const snapshot=checkedSnapshot(target,block,journal.parameters);
    if(info.native_source_creation_record)check(equal(creationRecord(json(path.join(target,'source-creation.json'),LIMIT.savedResponseBytes),snapshot,journal.parameters),info.native_source_creation_record),'Captured source creation changed');}
  return receipt;
}

// Bridge injection is only for offline tests. The CLI always constructs the
// real native transport after the original full plan has been durably saved.
export async function handoffRegion({workspace:workspaceArg,output,requestId,imageId,rect,session,hostPid,blockSamples=16384,recover=false},
  makeBridge=options=>new NativeBridge(options)) {
  const planning={imageId,rect,session,hostPid,blockSamples,requestId};
  regionLayout(planning); // Validate bounds before filesystem changes; no wire IDs yet.
  let plan;
  const workspace=fs.realpathSync(workspaceArg);check(fs.statSync(workspace).isDirectory(),'Existing independent workspace required');
  const {target,relative}=newTarget(workspace,output);
  const parameters={imageId,rect,session,hostPid,blockSamples,requestId,output:relative};
  const filename=path.join(workspace,'.native-region-'+hash(requestId)+'.json'),lock=filename+'.lock';
  const lockFd=fs.openSync(lock,'wx');let fd,bridge,npyFd,journal;
  try {
    write(lockFd,jsonBytes({pid:process.pid,request_id:requestId}));fs.fsyncSync(lockFd);
    if(fs.existsSync(filename)) {
      journal=json(filename);check(equal(journal.parameters,parameters)&&journal.parameters_sha256===hash(canonical(parameters)),'Export ID parameters conflict; no calls or output overwrite');
      check(typeof journal.capture_id==='string'&&journal.capture_id.length===32&&/^[a-f0-9]{32}$/.test(journal.capture_id),'Invalid saved capture identity');
      const legacy=!Object.hasOwn(journal,'request_namespace_version');
      if(legacy) {
        // Completed files are historical evidence only. Incomplete legacy IDs
        // may already collide with another export; never query/replay them here.
        check(journal.state==='CAPTURED','LEGACY_REGION_RECOVERY_UNSAFE: preserve old files; start a new export ID in a new output directory');
        plan=regionPlan(planning,null);
      } else {
        check(journal.request_namespace_version===2,'Unsupported region request namespace version');
        check(journal.workspace_realpath===workspace,'Journal belongs to another output directory/workspace; copied recovery is not supported');
        plan=planRegion({...planning,captureId:journal.capture_id});
      }
      check(equal(journal.plan,plan)&&Array.isArray(journal.blocks)&&journal.blocks.every((b,i)=>equal(b.request,plan.blocks[i]?.request))&&
        journal.blocks.length===plan.blocks.length&&equal(journal.status?.request,plan.status.request),'Original saved plan changed');
      const stat=fs.lstatSync(target);check(stat.isDirectory()&&!stat.isSymbolicLink()&&fs.realpathSync(target)===target,'Capture directory changed');
      if(journal.state==='CAPTURED') {
        const receipt=verifiedCapture(target,journal,plan);
        return legacy?{...receipt,request_namespace_status:'legacy_unscoped_saved_evidence_only'}:receipt;
      }
      if(!recover)return {state:'UNKNOWN_INCOMPLETE',request_id:requestId,capture_dir:target,automatic_retry:false,query_original_ids:journal.blocks.filter(b=>b.state==='SENT').map(b=>b.request.id)};
      check(['CAPTURING','PARTIAL'].includes(journal.state),'Failed capture requires inspection; not automatically repaired');
      fd=fs.openSync(filename,'r+');
    } else {
      check(!fs.existsSync(target),'Existing output is never overwritten');
      const captureId=randomUUID().replaceAll('-','');
      plan=planRegion({...planning,captureId});
      journal={schema_version:1,request_namespace_version:2,workspace_realpath:workspace,
        state:'CAPTURING',capture_mode:'native_chunked_read',capture_id:captureId,parameters,
        parameters_sha256:hash(canonical(parameters)),plan,blocks:structuredClone(plan.blocks),status:structuredClone(plan.status),
        created_utc:new Date().toISOString(),pixel_capture_atomic:false};
      fd=fs.openSync(filename,'wx+');update(fd,journal); // before output creation or first connection
      fs.mkdirSync(target);saveNew(path.join(target,'capture.json'),jsonBytes({schema_version:1,capture_id:journal.capture_id,state:'capturing',complete_coverage:false}));
    }
    bridge=makeBridge({session});
    const submit=async record=>{
      if(record.state==='COMPLETED')return record.reply;
      if(record.state==='SENT')return checkReply(await bridge.query(record.request.id),record.request);
      check(record.state==='PLANNED','Invalid request state');record.state='SENT';update(fd,journal);
      return checkReply(await bridge.execute(record.request.op,record.request.args,{requestId:record.request.id}),record.request);
    };
    const status=checkReply(await submit(journal.status),journal.status.request);
    check(status.result_type==='status'&&status.result.backend==='digitalmicrograph-native'&&status.result.ready===true&&status.result.binary_gate===true&&
      status.result.compatibility?.state==='SUPPORTED'&&status.result.host_pid===hostPid,'Native supported ready host required');
    journal.status={...journal.status,state:'COMPLETED',reply:status};update(fd,journal);
    let first,header,anchor,sourceCreation=null,total=0;
    for(const block of journal.blocks) {
      let snapshot;
      if(block.state==='COMPLETED')snapshot=checkedSnapshot(target,block,parameters);
      else {
        const value=readSnapshot(await submit(block),block.request);snapshot=value.snapshot;
        const blockFile=path.join(target,`read-${block.index}.json`);
        // A crash may have saved the immutable response but not journaled its
        // hash. Resolve SENT only with QUERY, then require exactly these bytes.
        if(fs.existsSync(blockFile)) {ordinary(blockFile,LIMIT.savedResponseBytes);check(fs.readFileSync(blockFile).equals(value.bytes),'Existing block differs from original QUERY');}
        else saveNew(blockFile,value.bytes);
        block.state='COMPLETED';block.snapshot_sha256=hash(value.bytes);block.pixel_sha256=snapshot.pixelHash;update(fd,journal);
      }
      if(!first) {
        first=snapshot;anchor=descriptor(snapshot);
        if(first.result.source_provenance!==null) {
          const id=first.result.source_provenance.request_id;
          const request={protocol:'NB2',session,host_pid:hostPid,id,op:'QUERY',args:[],wire:`NB2 ${session} ${id} QUERY\n`};
          const creationPath=path.join(target,'source-creation.json');
          let reply;
          if(journal.source_creation?.state==='COMPLETED'){
            check(equal(journal.source_creation.request,request),'Original source query identity changed');
            reply=json(creationPath,LIMIT.savedResponseBytes);check(hashFile(creationPath)===journal.source_creation.sha256,'Original source creation file changed');
          }else{
            if(journal.source_creation)check(equal(journal.source_creation.request,request),'Original source query identity changed');
            journal.source_creation={state:'SENT',request};update(fd,journal); // QUERY only; never re-create a source
            reply=await bridge.query(id);sourceCreation=creationRecord(reply,first,parameters);
            const bytes=jsonBytes(reply);check(bytes.length<=LIMIT.savedResponseBytes,'Source creation response budget exceeded');
            if(fs.existsSync(creationPath)){ordinary(creationPath,LIMIT.savedResponseBytes);check(fs.readFileSync(creationPath).equals(bytes),'Saved source creation differs from original QUERY');}
            else saveNew(creationPath,bytes);
            journal.source_creation={state:'COMPLETED',request,sha256:hash(bytes)};update(fd,journal);
          }
          sourceCreation=creationRecord(reply,first,parameters);
        }
        const source=first.result.source;
        check(source.shape[0]*source.shape[1]<=LIMIT.sourcePixels&&rect[2]<=source.shape[1]&&rect[3]<=source.shape[0],'Requested region outside bounded source');
        header=encodeNpyHeader(plan.shape,first.result.dtype);const partial=path.join(target,'input.partial.npy'),size=header.length+plan.shape[0]*plan.shape[1]*4;
        if(fs.existsSync(partial)) {check(recover,'Partial output requires explicit recovery');const stat=ordinary(partial,LIMIT.diskBytes);check(stat.size===size&&stat.nlink===1,'Partial NPY size/link ownership changed; inspect without writing');
          npyFd=fs.openSync(partial,'r+');const old=Buffer.alloc(header.length);check(fs.readSync(npyFd,old,0,old.length,0)===old.length&&old.equals(header),'Partial NPY header changed');
        } else {npyFd=fs.openSync(partial,'wx+');write(npyFd,header);fs.ftruncateSync(npyFd,size);fs.fsyncSync(npyFd);}
      }
      check(equal(descriptor(snapshot),anchor),'Source/calibration/lineage changed between blocks; no atomic snapshot claim');
      const r=block.request.args.slice(1),w=r[2]-r[0],h=r[3]-r[1],bytes=snapshot.values,checkBytes=Buffer.alloc(w*4);
      for(let row=0;row<h;++row) {
        const offset=header.length+((r[1]-rect[1]+row)*plan.shape[1]+r[0]-rect[0])*4,part=bytes.subarray(row*w*4,(row+1)*w*4);
        write(npyFd,part,offset);check(fs.readSync(npyFd,checkBytes,0,checkBytes.length,offset)===checkBytes.length&&checkBytes.equals(part),'NPY row readback differs from native bytes');
      }
      total+=w*h;
    }
    check(total===plan.shape[0]*plan.shape[1]&&journal.blocks.every(b=>b.state==='COMPLETED'),'Incomplete region coverage');
    fs.fsyncSync(npyFd);fs.closeSync(npyFd);npyFd=undefined;
    const partial=path.join(target,'input.partial.npy'),input=path.join(target,'input.npy');
    const fileHash=hashFile(partial),pixelHash=hashFile(partial,header.length);
    // Reuse schema-1 and its scientific coordinate machinery, without forging
    // a whole-ROI READ. The following is metadata composition only.
    const result={...first.result,shape:plan.shape,requested_rect:rect,effective_rect:rect,sample_count:total,raw_bytes:total*4,
      roi_calibration:first.result.roi_calibration.map((axis,i)=>({...axis,size:plan.shape[1-i]}))};
    const info={...packageInfo({result,receipt:null,receiptHash:null,snapshotHash:null,pixelHash},journal.capture_id,
      {sha256:fileHash,byteLength:header.length+total*4}),capture_mode:'native_chunked_read',native_receipt_scope:'per_block',
      native_receipts:journal.blocks.map(b=>({request:b.request,snapshot_file:`read-${b.index}.json`,snapshot_sha256:b.snapshot_sha256})),
      native_source_creation_record:sourceCreation,source_creation_parameters_status:sourceCreation?'ORIGINAL_QUERY_SAVED':'NOT_PLUGIN_CREATED',
      capture_consistency:'serial bounded READs; equal descriptors are not proof of unchanged pixels; source must remain idle and unedited'};
    const infoPath=path.join(target,'input.json'),infoBytes=jsonBytes(info);
    if(fs.existsSync(infoPath)) {check(recover,'Existing metadata cannot be overwritten');ordinary(infoPath,1024*1024);check(fs.readFileSync(infoPath).equals(infoBytes),'Existing metadata differs from completed original blocks');}
    else saveNew(infoPath,infoBytes);
    if(fs.existsSync(input)) {check(recover,'Existing published NPY cannot be overwritten');check(hashFile(input)===fileHash,'Existing published NPY differs from original blocks');}
    else fs.linkSync(partial,input); // exclusive publication; never replace a target
    check(hashFile(input)===fileHash,'Published NPY differs');fs.unlinkSync(partial);
    const manifest={schema_version:1,capture_id:journal.capture_id,state:'captured',capture_mode:'native_chunked_read',complete_coverage:true,
      shape_yx:plan.shape,dtype:info.dtype,source_image_id:imageId,source_rect_xyxy:rect,native_session:session,host_pid:hostPid,
      blocks:journal.blocks,input_sha256:fileHash,pixel_sha256:pixelHash,input_metadata_sha256:hash(canonical(info)),
      pixel_capture_atomic:false,dm_file_save:false,source_write_requested:false,budgets:plan,
      ...(Object.hasOwn(info,'frame_ancestry')?{frame_ancestry:info.frame_ancestry}:{}),
      capture_consistency:info.capture_consistency,completed_utc:new Date().toISOString()};
    const manifestPath=path.join(target,'capture.json');check(json(manifestPath).capture_id===journal.capture_id,'Mutable manifest ownership changed');
    const manifestFd=fs.openSync(manifestPath,'r+');try{update(manifestFd,manifest);}finally{fs.closeSync(manifestFd);}
    const receipt={state:'captured',capture_id:journal.capture_id,capture_dir:target,request_id:requestId,
      native_session:session,host_pid:hostPid,shape_yx:plan.shape,dtype:info.dtype,complete_coverage:true,pixel_capture_atomic:false,dm_file_save:false,
      files_sha256:Object.fromEntries(['input.npy','input.json','capture.json',...(sourceCreation?['source-creation.json']:[])].map(name=>[name,hashFile(path.join(target,name))]))};
    journal.capture_receipt=receipt;journal.state='CAPTURED';update(fd,journal);
    return verifiedCapture(target,journal,plan);
  } catch(error) {
    if(fd!==undefined&&journal&&journal.state!=='CAPTURED') {journal.state='PARTIAL';journal.error=String(error);try{update(fd,journal);}catch{}
      try{const name=path.join(target,'capture.json');check(json(name).capture_id===journal.capture_id,'Mutable manifest ownership changed');const mfd=fs.openSync(name,'r+');try{update(mfd,{schema_version:1,capture_id:journal.capture_id,state:'partial',complete_coverage:false,error:String(error)});}finally{fs.closeSync(mfd);}}catch{}}
    throw error;
  } finally {bridge?.close();if(npyFd!==undefined)fs.closeSync(npyFd);if(fd!==undefined)fs.closeSync(fd);fs.closeSync(lockFd);fs.unlinkSync(lock);}
}

export async function main(argv=process.argv.slice(2)) {
  const opts={};for(let i=0;i<argv.length;++i){const key=argv[i];check(/^--(workspace|output|request-id|image-id|rect|session|host-pid|block-samples|recover)$/.test(key)&&!Object.hasOwn(opts,key),'Unknown or repeated argument');
    opts[key]=key==='--recover'?true:argv[++i];check(opts[key]!==undefined,'Argument value required');}
  const integer=s=>{check(typeof s==='string'&&/^(0|[1-9][0-9]*)$/.test(s),'Decimal integer required');return Number(s);};
  check(typeof opts['--rect']==='string','Explicit --rect required');
  const result=await handoffRegion({workspace:opts['--workspace'],output:opts['--output'],requestId:opts['--request-id'],imageId:integer(opts['--image-id']),
    rect:opts['--rect'].split(',').map(integer),session:opts['--session'],hostPid:integer(opts['--host-pid']),
    blockSamples:opts['--block-samples']===undefined?16384:integer(opts['--block-samples']),recover:opts['--recover']===true});
  process.stdout.write(JSON.stringify(result)+'\n');return result.state==='captured'?0:1;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().then(code=>{process.exitCode=code;}).catch(error=>{process.stderr.write(String(error)+'\n');process.exitCode=1;});
