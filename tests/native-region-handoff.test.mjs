// Synthetic receipts/pipe only. The independent NumPy reader is an oracle,
// not a processing fallback or a real-DM acceptance claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {execFileSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {handoffRegion,planRegion,hashFile} from '../tools/native_region_handoff.mjs';
import {canonical} from '../tools/native_snapshot_handoff.mjs';
import {createHash} from 'node:crypto';
import {readFixture,imageMetadata,fourierFixture} from './fixtures/native-operations.mjs';
import {frameHandoffFixture} from './fixtures/native-frame-handoff.mjs';

const session='b'.repeat(32),pid=123;
const opts=workspace=>({workspace,output:'capture',requestId:'region-test',imageId:77,rect:[1,1,8,6],session,hostPid:pid,blockSamples:8});
function temp(t){const p=fs.mkdtempSync(path.join(os.tmpdir(),'native-region-'));t.after(()=>fs.rmSync(p,{recursive:true}));return p;}
const readJson=p=>JSON.parse(fs.readFileSync(p,'utf8'));
function fixture({unsigned=false,mutate=()=>{},source=imageMetadata(77,{unsigned,shape:[7,9]})}={}) {
  const calls=[],saved=new Map();
  function response(op,args,id){
    let result;
    if(op==='STATUS')result={backend:'digitalmicrograph-native',host_pid:pid,ready:true,binary_gate:true,compatibility:{state:'SUPPORTED'}};
    else {
      result=readFixture(args,{source});const [x0,y0,x1,y1]=args.slice(1),bytes=Buffer.alloc((x1-x0)*(y1-y0)*4);let at=0;
      for(let y=y0;y<y1;++y)for(let x=x0;x<x1;++x){const value=unsigned?[0,16777217,2147483648,4294967295][(x+y*9)%4]:((x+y*9)%4===0?-0:(y*9+x-21)/8);
        if(unsigned)bytes.writeUInt32LE(value,at);else bytes.writeFloatLE(value,at);at+=4;}
      result.values_base64=bytes.toString('base64');
    }
    const reply={protocol:'NB2',session,id,state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},
      original_operation:op,normalized_args:args,result_type:op==='STATUS'?'status':'native_data_snapshot',result_version:1,result};
    mutate(reply,calls);return reply;
  }
  const bridge={async execute(op,args,{requestId}) {calls.push([op,requestId,args]);const r=response(op,args,requestId);saved.set(requestId,r);return r;},
    async query(id){calls.push(['QUERY',id,[]]);assert.ok(saved.has(id));return saved.get(id);},close(){}};
  return {bridge,calls,saved,response};
}
test('deterministic coverage includes right/bottom remainder and rejects budgets before calls',()=>{
  const planning={...opts('unused'),captureId:'a'.repeat(32)};
  const plan=planRegion(planning),covered=new Set();
  assert.equal(plan.blocks.length,5);
  for(const block of plan.blocks){const [id,x0,y0,x1,y1]=block.request.args;assert.equal(id,77);assert.ok((x1-x0)*(y1-y0)<=8);
    for(let y=y0;y<y1;++y)for(let x=x0;x<x1;++x){assert.ok(!covered.has(`${x},${y}`));covered.add(`${x},${y}`);}}
  assert.equal(covered.size,35);
  const split=planRegion({...planning,rect:[2,3,21,8],blockSamples:12});assert.equal(split.blocks.length,10);assert.deepEqual(split.blocks.at(-1).request.args,[77,14,7,21,8]);
  for(const bad of [{rect:[0,0,2049,2048]},{blockSamples:0},{blockSamples:16385},{rect:[0,0,1000,1000],blockSamples:1},{requestId:'bad id'},{hostPid:0},{session:'bad'}])
    assert.throws(()=>planRegion({...planning,...bad}));
});
for(const unsigned of [false,true])test(`streamed ${unsigned?'uint32':'float32'} capture independently reopens with exact positions and bits; reuse makes no calls`,async t=>{
  const dir=temp(t),f=fixture({unsigned}),options=opts(dir);
  const result=await handoffRegion(options,()=>f.bridge);assert.equal(result.state,'captured');assert.equal(f.calls.filter(c=>c[0]==='READ').length,5);
  const info=readJson(path.join(dir,'capture','input.json')),manifest=readJson(path.join(dir,'capture','capture.json'));
  assert.equal(info.native_receipt,null);assert.equal(info.native_receipt_scope,'per_block');assert.equal(info.native_receipts.length,5);
  assert.equal(info.working_calibration_xy[0].origin,1);assert.equal(info.working_calibration_xy[1].origin,-2);
  assert.equal(manifest.complete_coverage,true);assert.equal(manifest.budgets.session_record_reservation,false);
  const verified=execFileSync('python',['tools/verify_native_region.py','--capture',path.join(dir,'capture'),'--host-pid','123','--session',session],{encoding:'utf8'});assert.equal(JSON.parse(verified).status,'PASS_INDEPENDENT_CHUNKED_FILES');
  const script=String.raw`import sys,numpy as np
p=sys.argv[1];u=sys.argv[2]=='true';a=np.load(p,allow_pickle=False)
v=[]
for y in range(1,6):
 row=[]
 for x in range(1,8):
  n=x+y*9
  row.append([0,16777217,2147483648,4294967295][n%4] if u else (-0. if n%4==0 else (n-21)/8.))
 v.append(row)
b=np.array(v,dtype='<u4' if u else '<f4')
assert a.shape==(5,7) and a.dtype==b.dtype and a.tobytes()==b.tobytes()
print('bitwise independent PASS')`;
  assert.match(execFileSync('python',['-c',script,path.join(dir,'capture','input.npy'),String(unsigned)],{encoding:'utf8'}),/independent PASS/);
  const before=f.calls.length;assert.deepEqual(await handoffRegion(options,()=>{throw Error('no bridge on reuse');}),result);assert.equal(f.calls.length,before);
  await assert.rejects(()=>handoffRegion({...options,rect:[1,1,7,6]},()=>f.bridge),/conflict/);assert.equal(f.calls.length,before);
  fs.appendFileSync(path.join(dir,'capture','input.npy'),'x');await assert.rejects(()=>handoffRegion(options,()=>f.bridge),/changed/);
});
test('journal exists with every original wire ID before first connection; unknown READ uses only same-ID QUERY on explicit recovery',async t=>{
  const dir=temp(t),f=fixture(),options=opts(dir);let once=true;
  const original=f.bridge.execute;
  f.bridge.execute=async(...args)=>{const r=await original(...args);if(args[0]==='READ'&&once){once=false;throw Error('accepted then disconnected');}return r;};
  await assert.rejects(()=>handoffRegion(options,()=>{
    const name=fs.readdirSync(dir).find(n=>n.endsWith('.json')),journal=readJson(path.join(dir,name));
    assert.equal(journal.blocks.length,5);assert.ok(journal.blocks.every(b=>b.request.wire.endsWith('\n')&&b.state==='PLANNED'));return f.bridge;
  }),/disconnected/);
  const sent=f.calls.find(c=>c[0]==='READ'),count=f.calls.length;
  assert.equal((await handoffRegion(options,()=>{throw Error('no reconnect without recover');})).state,'UNKNOWN_INCOMPLETE');assert.equal(f.calls.length,count);
  const result=await handoffRegion({...options,recover:true},()=>f.bridge);assert.equal(result.state,'captured');
  assert.equal(f.calls.filter(c=>c[0]==='READ'&&c[1]===sent[1]).length,1);assert.ok(f.calls.some(c=>c[0]==='QUERY'&&c[1]===sent[1]));
  await assert.rejects(()=>handoffRegion({...options,recover:true,session:'c'.repeat(32)},()=>f.bridge),/conflict/);
});
test('unknown original receipt cannot become a successful capture or cause a second READ',async t=>{
  const dir=temp(t),f=fixture(),options=opts(dir);f.bridge.execute=async(op,args,{requestId})=>{
    f.calls.push([op,requestId,args]);if(op==='READ')throw Error('uncertain send');return f.response(op,args,requestId);
  };f.bridge.query=async id=>{f.calls.push(['QUERY',id,[]]);return {state:'unknown'};};
  await assert.rejects(()=>handoffRegion(options,()=>f.bridge),/uncertain/);
  await assert.rejects(()=>handoffRegion({...options,recover:true},()=>f.bridge),/Original completed/);
  assert.equal(f.calls.filter(c=>c[0]==='READ').length,1);assert.equal(readJson(path.join(dir,'capture','capture.json')).state,'partial');
  assert.ok(!fs.existsSync(path.join(dir,'capture','input.npy')));
});
for(const bad of ['host','session','args','dtype','base64','calibration','science','source','not-ready','write-failure'])test('negative '+bad+' never produces a complete capture',async t=>{
  const dir=temp(t);let reads=0;
  const f=fixture({mutate:r=>{
    if(bad==='not-ready'&&r.original_operation==='STATUS')r.result.ready=false;
    if(r.original_operation!=='READ')return;++reads;
    if(bad==='host')r.host_pid=999;
    if(bad==='session')r.session='c'.repeat(32);
    if(bad==='args')r.normalized_args=[77,0,0,7,1];
    if(bad==='dtype')r.result.dtype='float64';
    if(bad==='base64')r.result.values_base64='bad';
    if(bad==='calibration'&&reads===2)r.result.source.calibration[0].unit='pm';
    if(bad==='science'&&reads===2)r.result.scientific_context={schema_version:1,status:'unresolved_lineage'};
    if(bad==='source'&&reads===2)r.result.source.name='changed';
    if(bad==='write-failure')fs.mkdirSync(path.join(dir,'capture','input.partial.npy'));
  }});
  await assert.rejects(()=>handoffRegion(opts(dir),()=>f.bridge));
  assert.equal(readJson(path.join(dir,'capture','capture.json')).state,'partial');assert.ok(!fs.existsSync(path.join(dir,'capture','input.npy')));
});
test('existing target, unsafe path and corrupted coverage journal are refused without native calls',async t=>{
  const dir=temp(t),f=fixture();fs.mkdirSync(path.join(dir,'capture'));
  await assert.rejects(()=>handoffRegion(opts(dir),()=>f.bridge),/Existing output/);assert.equal(f.calls.length,0);
  for(const output of ['../escape','CON','bad:stream','capture/../other'])await assert.rejects(()=>handoffRegion({...opts(dir),output},()=>f.bridge));
  assert.equal(f.calls.length,0);
});
test('independent verifier rejects self-consistent negative receipts, placements, calibration and file bytes',async t=>{
  const dir=temp(t),f=fixture();await handoffRegion(opts(dir),()=>f.bridge);
  const sha=value=>createHash('sha256').update(value).digest('hex');
  const save=(p,v)=>fs.writeFileSync(p,JSON.stringify(v));
  for(const kind of ['pixel','shape','dtype','overlap','missing','host','session','calibration','offset','base64','partial','invented-science']) {
    const target=path.join(dir,'bad-'+kind);fs.cpSync(path.join(dir,'capture'),target,{recursive:true});
    const info=readJson(path.join(target,'input.json')),manifest=readJson(path.join(target,'capture.json'));
    if(kind==='pixel'){const p=path.join(target,'input.npy'),bytes=fs.readFileSync(p);bytes[bytes.length-1]^=1;fs.writeFileSync(p,bytes);info.input_sha256=manifest.input_sha256=hashFile(p);info.pixel_sha256=manifest.pixel_sha256=hashFile(p,128);}
    if(kind==='shape')info.shape_yx=[7,5];
    if(kind==='dtype')info.dtype='uint32';
    if(kind==='overlap')manifest.blocks[1].request.args[2]=1;
    if(kind==='missing'){manifest.blocks.pop();info.native_receipts.pop();}
    if(kind==='host')manifest.host_pid=999;
    if(kind==='session')manifest.native_session='c'.repeat(32);
    if(kind==='calibration')info.working_calibration_xy[0].scale=0.25;
    if(kind==='offset')info.working_calibration_xy[1].source_offset=2;
    if(kind==='base64'){
      const name=path.join(target,'read-0.json'),r=readJson(name);r.values_base64='!!!!';save(name,r);
      manifest.blocks[0].snapshot_sha256=hashFile(name);info.native_receipts[0].snapshot_sha256=hashFile(name);
    }
    if(kind==='partial')manifest.state='partial';
    if(kind==='invented-science')info.scientific_semantics.domain='frequency';
    save(path.join(target,'input.json'),info);manifest.input_metadata_sha256=sha(canonical(info));save(path.join(target,'capture.json'),manifest);
    assert.throws(()=>execFileSync('python',['tools/verify_native_region.py','--capture',target,'--host-pid','123','--session',session],{encoding:'utf8',stdio:'pipe'}),kind);
  }
});
test('chunk metadata composes Fourier ROI/DC and processed phase without a forged whole-ROI READ',async t=>{
  const dir=temp(t),producer=fourierFixture('VENDOR_ARG'),source=producer.image;
  const f=fixture({source,mutate:r=>{if(r.original_operation==='READ'){
    r.result.source_provenance={operation:'VENDOR_ARG',request_id:'phase',source_image_ids:[77],semantics:'synthetic'};
    r.result.scientific_context={schema_version:1,status:'tracked_fourier',original_operation:'VENDOR_ARG',request_id:'phase',normalized_args:[77],result_version:2,result:producer,source_offset_xy:[0,0],postprocessing:[]};
  }}});
  f.saved.set('phase',{protocol:'NB2',session,id:'phase',state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},
    original_operation:'VENDOR_ARG',normalized_args:[77],result_type:'native_fourier_operation',result_version:2,result:producer});
  await handoffRegion({...opts(dir),imageId:source.id,rect:[5,1,8,4],blockSamples:2},()=>f.bridge);
  const info=readJson(path.join(dir,'capture','input.json')),axes=info.scientific_semantics.coordinate_axes;
  assert.equal(info.scientific_semantics.phase_units,'radians');assert.deepEqual(axes.map(a=>a.source_index_offset),[5,1]);
  assert.deepEqual(axes.map(a=>a.dc_index_in_roi),[-1,1]);assert.deepEqual(axes.map(a=>a.size),[3,3]);
  assert.equal(info.native_receipt,null);assert.equal(info.native_receipts.length,6);
  assert.deepEqual(info.native_source_creation_record.normalized_args,[77]);assert.equal(f.calls.filter(c=>c[0]==='QUERY'&&c[1]==='phase').length,1);
  assert.equal(JSON.parse(execFileSync('python',['tools/verify_native_region.py','--capture',path.join(dir,'capture')],{encoding:'utf8'})).status,'PASS_INDEPENDENT_CHUNKED_FILES');
  info.scientific_semantics.coordinate_axes[0].dc_index_in_roi=0;fs.writeFileSync(path.join(dir,'capture','input.json'),JSON.stringify(info));const manifest=readJson(path.join(dir,'capture','capture.json'));manifest.input_metadata_sha256=createHash('sha256').update(canonical(info)).digest('hex');fs.writeFileSync(path.join(dir,'capture','capture.json'),JSON.stringify(manifest));assert.throws(()=>execFileSync('python',['tools/verify_native_region.py','--capture',path.join(dir,'capture')],{encoding:'utf8',stdio:'pipe'}));
});
test('immediate processing parameters are saved only from original QUERY, never inferred from a name; unavailable producer is partial',async t=>{
  for(const bad of [false,true]) {
    const dir=temp(t),source=imageMetadata(88,{shape:[7,9]}),f=fixture({source,mutate:r=>{if(r.original_operation==='READ')r.result.source_provenance={operation:'CROP',request_id:'original-crop',source_image_ids:[77],semantics:'DM native independent copy'};}});
    const producer={protocol:'NB2',session,id:'original-crop',state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},
      original_operation:'CROP',normalized_args:[77,1,2,10,9],result_type:'image_crop',result_version:1,result:{backend:'digitalmicrograph-native',image_id:88,image:source}};
    f.saved.set('original-crop',bad?{...producer,id:'different-id'}:producer);
    const options={...opts(dir),imageId:88};
    if(bad){await assert.rejects(()=>handoffRegion(options,()=>f.bridge),/source creation record mismatch/);assert.ok(!fs.existsSync(path.join(dir,'capture','input.npy')));}
    else {
      const result=await handoffRegion(options,()=>f.bridge),info=readJson(path.join(dir,'capture','input.json'));
      assert.deepEqual(info.native_source_creation_record.normalized_args,[77,1,2,10,9]);assert.equal(info.source_creation_parameters_status,'ORIGINAL_QUERY_SAVED');
      assert.equal(hashFile(path.join(dir,'capture','source-creation.json')),result.files_sha256['source-creation.json']);
      assert.equal(f.calls.filter(c=>c[0]==='CROP').length,0);
      assert.deepEqual(await handoffRegion(options,()=>{throw Error('offline verified reuse');}),result);
      for(const fault of ['args','host','type','threads','backend']) {
        const target=path.join(dir,'bad-creator-'+fault);fs.cpSync(path.join(dir,'capture'),target,{recursive:true});
        const record=readJson(path.join(target,'source-creation.json')),metadata=readJson(path.join(target,'input.json'));
        if(fault==='args')record.normalized_args=[77];
        if(fault==='host')record.host_pid=999;
        if(fault==='type')record.result_type='status';
        if(fault==='threads')record.exec_tid=record.worker_tid;
        if(fault==='backend')record.result.backend='python';
        fs.writeFileSync(path.join(target,'source-creation.json'),JSON.stringify(record));
        metadata.native_source_creation_record.sha256=hashFile(path.join(target,'source-creation.json'));
        metadata.native_source_creation_record.normalized_args=record.normalized_args;
        fs.writeFileSync(path.join(target,'input.json'),JSON.stringify(metadata));
        const manifest=readJson(path.join(target,'capture.json'));manifest.input_metadata_sha256=createHash('sha256').update(canonical(metadata)).digest('hex');
        fs.writeFileSync(path.join(target,'capture.json'),JSON.stringify(manifest));
        assert.throws(()=>execFileSync('python',['tools/verify_native_region.py','--capture',target],{encoding:'utf8',stdio:'pipe'}),fault);
      }
    }
  }
});

test('copied completed journal cannot claim a capture from another directory',async t=>{
  const dir=temp(t),f=fixture(),options=opts(dir);await handoffRegion(options,()=>f.bridge);
  const copied=temp(t);fs.cpSync(dir,copied,{recursive:true});
  await assert.rejects(()=>handoffRegion({...options,workspace:copied},()=>{throw Error('no native calls');}),/another output directory/);
});

function frameRegionFixture({index=1,mutate=()=>{}}={}) {
  const frame=frameHandoffFixture({index}),f=fixture({source:frame.result.image,mutate:r=>{
    if(r.original_operation==='READ'){
      r.result.source_provenance=structuredClone(frame.provenance);r.result.frame_ancestry=structuredClone(frame.ancestry);
      const bytes=Buffer.alloc(r.result.raw_bytes);for(let n=0;n<r.result.sample_count;n++)bytes.writeFloatLE([0,32767,32768,65535][n%4],n*4);
      r.result.values_base64=bytes.toString('base64');
    }
    mutate(r);
  }});
  f.saved.set('original-frame',{protocol:'NB2',session,id:'original-frame',state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,
    timings_us:{queue:0,execute:1},original_operation:'FRAME',normalized_args:[31,index],result_type:'native_frame_copy',result_version:1,
    result:{...structuredClone(frame.result),retention:{token:1,creation_request_id:'original-frame',state_at_creation:'plugin_retained',
      identity_scope:'bridge token in this native session, not a host image ID'}}});
  return {...f,frame};
}

test('FRAME region preserves frozen stack/frame identity and independently validates the original creation QUERY',async t=>{
  const dir=temp(t),f=frameRegionFixture(),options=opts(dir),receipt=await handoffRegion(options,()=>f.bridge);
  const target=path.join(dir,'capture'),info=readJson(path.join(target,'input.json'));
  assert.deepEqual(info.frame_ancestry,f.frame.ancestry);assert.equal(info.dtype,'float32');
  assert.deepEqual(info.native_source_creation_record.normalized_args,[31,1]);
  assert.equal(f.calls.filter(([op])=>op==='FRAME').length,0,'handoff queries the original frame; never extracts again');
  const verified=JSON.parse(execFileSync(process.env.DM_TEST_PYTHON||'python',['tools/verify_native_region.py','--capture',target,'--host-pid','123','--session',session],{encoding:'utf8'}));
  assert.deepEqual(verified.frame_ancestry,f.frame.ancestry);
  assert.deepEqual(await handoffRegion(options,()=>{throw Error('offline reuse only');}),receipt);
  for(const fault of ['source-code','conversion','selected-coordinate','creator-index','frame-identity']) {
    const bad=path.join(dir,'bad-frame-'+fault);fs.cpSync(target,bad,{recursive:true});
    const metadata=readJson(path.join(bad,'input.json')),manifest=readJson(path.join(bad,'capture.json'));
    if(fault==='source-code')metadata.frame_ancestry.result.source.data_type_code=11;
    if(fault==='conversion')metadata.frame_ancestry.result.dtype_conversion.lossless_values=false;
    if(fault==='selected-coordinate')metadata.frame_ancestry.result.frame_axis.calibrated_value=0;
    if(fault==='frame-identity')metadata.frame_ancestry.result.frame_axis.role='time';
    if(fault==='creator-index'){
      const creation=readJson(path.join(bad,'source-creation.json'));creation.result.frame_index=2;
      fs.writeFileSync(path.join(bad,'source-creation.json'),JSON.stringify(creation));
      metadata.native_source_creation_record.sha256=hashFile(path.join(bad,'source-creation.json'));
    }
    manifest.frame_ancestry=structuredClone(metadata.frame_ancestry);
    fs.writeFileSync(path.join(bad,'input.json'),JSON.stringify(metadata));
    manifest.input_metadata_sha256=createHash('sha256').update(canonical(metadata)).digest('hex');
    fs.writeFileSync(path.join(bad,'capture.json'),JSON.stringify(manifest));
    assert.throws(()=>execFileSync(process.env.DM_TEST_PYTHON||'python',['tools/verify_native_region.py','--capture',bad],{encoding:'utf8',stdio:'pipe'}),fault);
  }
  // Deliberately rewrite all local hashes for a valid but different second
  // frame. Equal pixel bytes and XY metadata must not hide a frame boundary.
  const mixed=path.join(dir,'mixed-frame-block');fs.cpSync(target,mixed,{recursive:true});
  const metadata=readJson(path.join(mixed,'input.json')),manifest=readJson(path.join(mixed,'capture.json'));
  const block=readJson(path.join(mixed,'read-1.json')),other=frameHandoffFixture({index:2});
  block.frame_ancestry=other.ancestry;block.frame_ancestry.request_id='second-frame';block.source_provenance.request_id='second-frame';
  fs.writeFileSync(path.join(mixed,'read-1.json'),JSON.stringify(block));
  const snapshotHash=hashFile(path.join(mixed,'read-1.json'));
  manifest.blocks[1].snapshot_sha256=snapshotHash;metadata.native_receipts[1].snapshot_sha256=snapshotHash;
  fs.writeFileSync(path.join(mixed,'input.json'),JSON.stringify(metadata));
  manifest.input_metadata_sha256=createHash('sha256').update(canonical(metadata)).digest('hex');
  fs.writeFileSync(path.join(mixed,'capture.json'),JSON.stringify(manifest));
  assert.throws(()=>execFileSync(process.env.DM_TEST_PYTHON||'python',['tools/verify_native_region.py','--capture',mixed],{encoding:'utf8',stdio:'pipe'}),
    'independent verifier must reject a different valid original frame even after hashes are recomputed');
});

test('equal pixels, shape and calibration cannot join different original frames into one region',async t=>{
  let seen=0;
  const dir=temp(t),f=frameRegionFixture({mutate:r=>{
    if(r.original_operation==='READ'&&++seen===2) {
      const other=frameHandoffFixture({index:2});r.result.frame_ancestry=other.ancestry;
      // Same creation ID would be an argument conflict; use a different valid original creation.
      r.result.frame_ancestry.request_id='second-frame';r.result.source_provenance.request_id='second-frame';
    }
  }});
  await assert.rejects(()=>handoffRegion(opts(dir),()=>f.bridge),/Source\/calibration\/lineage changed/);
  assert.equal(fs.existsSync(path.join(dir,'capture','input.npy')),false);
  assert.equal(readJson(path.join(dir,'capture','capture.json')).state,'partial');
});
test('real NativeBridge Windows pipe transports each planned READ once; output remains schema-1',async t=>{
  const dir=temp(t),s=randomUUID().replaceAll('-',''),f=fixture(),sockets=new Set();
  const server=net.createServer(socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));let input='';socket.on('data',c=>{
    input+=c.toString('ascii');if(!input.includes('\n'))return;const [protocol,actual,id,op,...args]=input.trim().split(' ');assert.equal(protocol,'NB2');assert.equal(actual,s);
    const reply=f.response(op,args.map(Number),id);reply.session=s;f.calls.push([op,id,args]);socket.end(JSON.stringify(reply)+'\n');
  });});
  const pipe=`\\\\.\\pipe\\dm_mcp_native_${s}`;await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(pipe,resolve);});
  try{const result=await handoffRegion({...opts(dir),session:s});assert.equal(result.state,'captured');assert.equal(f.calls.length,6);assert.equal(hashFile(path.join(dir,'capture','input.npy')),result.files_sha256['input.npy']);}
  finally{for(const socket of sockets)socket.destroy();await new Promise(resolve=>server.close(resolve));}
});

for (const unsigned of [false, true]) test(`independent directories with the same export name read fresh ${unsigned ? 'uint32' : 'float32'} pixels`, async t => {
  const firstDir = temp(t), secondDir = temp(t);
  let epoch = 1, executions = 0;
  const f = fixture({unsigned, mutate: reply => {
    if (reply.original_operation !== 'READ') return;
    const bytes = Buffer.from(reply.result.values_base64, 'base64');
    for (let i = 0; i < bytes.length; i += 4) {
      if (unsigned) bytes.writeUInt32LE(16777216 + epoch, i);
      else bytes.writeFloatLE(epoch + 0.25, i);
    }
    reply.result.values_base64 = bytes.toString('base64');
  }});
  // Emulate the production core's immutable same-session deduplication, not
  // an echo peer which incorrectly executes every repeated READ afresh.
  f.bridge.execute = async (op, args, {requestId}) => {
    f.calls.push([op, requestId, args]);
    if (!f.saved.has(requestId)) {
      const reply = f.response(op, args, requestId);
      f.saved.set(requestId, reply);
      if (op === 'READ') ++executions;
    }
    return f.saved.get(requestId);
  };
  const first = await handoffRegion(opts(firstDir), () => f.bridge);
  const firstFile = path.join(firstDir, 'capture', 'input.npy');
  const firstBytes = fs.readFileSync(firstFile);
  epoch = 2; // Editing BETWEEN completed exports, never during a capture.
  const second = await handoffRegion(opts(secondDir), () => f.bridge);
  const secondBytes = fs.readFileSync(path.join(secondDir, 'capture', 'input.npy'));
  assert.equal(first.state, 'captured'); assert.equal(second.state, 'captured');
  assert.equal(executions, 10, 'both independent exports must execute all five READs');
  assert.notDeepEqual(firstBytes, secondBytes, 'the new directory must not receive a cached old capture');
  assert.deepEqual(fs.readFileSync(firstFile), firstBytes, 'the old capture remains immutable');
  const value = bytes => unsigned ? bytes.readUInt32LE(bytes.length - 4) : bytes.readFloatLE(bytes.length - 4);
  assert.equal(value(firstBytes), unsigned ? 16777217 : 1.25);
  assert.equal(value(secondBytes), unsigned ? 16777218 : 2.25);
  const calls = f.calls.length;
  assert.deepEqual(await handoffRegion(opts(firstDir), () => { throw Error('reuse must be offline'); }), first);
  assert.deepEqual(await handoffRegion(opts(secondDir), () => { throw Error('reuse must be offline'); }), second);
  assert.equal(f.calls.length, calls);
});

const journalPath = dir => path.join(dir, fs.readdirSync(dir).find(name => name.startsWith('.native-region-') && name.endsWith('.json')));
const saveJson = (filename, value) => fs.writeFileSync(filename, JSON.stringify(value, null, 2) + '\n');
const shaBytes = value => createHash('sha256').update(value).digest('hex');

test('wire plans are deterministic only within one persisted capture identity', () => {
  const args = {...opts('unused'), captureId: 'a'.repeat(32)};
  const first = planRegion(args), same = planRegion(args), next = planRegion({...args, captureId: 'c'.repeat(32)});
  assert.deepEqual(first, same);
  const ids = p => [p.status.request.id, ...p.blocks.map(block => block.request.id)];
  assert.ok(ids(first).every(id => !ids(next).includes(id) && /^[A-Za-z0-9_-]{1,64}$/.test(id)));
  for (const captureId of [undefined, null, '', true, 'A'.repeat(32), 'a'.repeat(32) + '\n'])
    assert.throws(() => planRegion({...args, captureId}), /capture ID/);
});

test('capture namespace is durable before dispatch and is reused on explicit recovery', async t => {
  const dir = temp(t), f = fixture(); let interrupt = true, original;
  const execute = f.bridge.execute;
  f.bridge.execute = async (...args) => {
    const reply = await execute(...args);
    if (args[0] === 'READ' && interrupt) { interrupt = false; throw Error('accepted then disconnected'); }
    return reply;
  };
  await assert.rejects(() => handoffRegion(opts(dir), () => {
    original = readJson(journalPath(dir));
    assert.equal(original.request_namespace_version, 2);
    assert.equal(original.workspace_realpath, fs.realpathSync(dir));
    assert.deepEqual(original.plan, planRegion({...opts(dir), captureId: original.capture_id}));
    assert.equal(f.calls.length, 0);
    return f.bridge;
  }), /disconnected/);
  await handoffRegion({...opts(dir), recover: true}, () => f.bridge);
  const restored = readJson(journalPath(dir));
  assert.equal(restored.capture_id, original.capture_id);
  assert.deepEqual(restored.plan, original.plan);
  assert.equal(f.calls.filter(([op]) => op === 'READ').length, 5, 'no accepted READ resubmitted');
});

test('copied partial journals fail before connecting or changing existing evidence', async t => {
  const dir = temp(t), f = fixture();
  const execute = f.bridge.execute;
  f.bridge.execute = async (...args) => { const r = await execute(...args); if (args[0] === 'READ') throw Error('disconnect'); return r; };
  await assert.rejects(() => handoffRegion(opts(dir), () => f.bridge), /disconnect/);
  const copy = temp(t); fs.cpSync(dir, copy, {recursive: true});
  const filename = journalPath(copy), before = fs.readFileSync(filename);
  await assert.rejects(() => handoffRegion({...opts(copy), recover: true}, () => { throw Error('must not connect'); }), /another output directory/);
  assert.deepEqual(fs.readFileSync(filename), before);
  assert.equal(fs.readdirSync(copy).some(name => name.endsWith('.lock')), false);
});

test('changed capture namespace and STATUS request fail before native calls', async t => {
  const dir = temp(t), f = fixture(); await handoffRegion(opts(dir), () => f.bridge);
  const filename = journalPath(dir), original = readJson(filename);
  for (const mutate of [
    j => { j.capture_id = 'c'.repeat(32); },
    j => { j.capture_id += '\n'; },
    j => { j.request_namespace_version = 99; },
    j => { j.status.request.id = 'another-status'; },
  ]) {
    const changed = structuredClone(original); mutate(changed); saveJson(filename, changed);
    const before = fs.readFileSync(filename);
    await assert.rejects(() => handoffRegion({...opts(dir), recover: true}, () => { throw Error('must not connect'); }), /identity|namespace|plan/);
    assert.deepEqual(fs.readFileSync(filename), before);
  }
  saveJson(filename, original);
});

// Construct a saved legacy fixture by rewriting only wire identities and all
// dependent hashes. No legacy producer/recovery path is enabled in production.
function convertCompletedToLegacy(dir) {
  const file = journalPath(dir); let journal = readJson(file);
  const p = journal.parameters;
  const oldPrefix = 'region-' + shaBytes(canonical({imageId:p.imageId, rect:p.rect, blockSamples:p.blockSamples,
    session:p.session, hostPid:p.hostPid, requestId:p.requestId})).slice(0,32);
  const prefix = journal.plan.status.request.id.slice(0, -7);
  const remap = value => JSON.parse(JSON.stringify(value).replaceAll(prefix, oldPrefix));
  journal = remap(journal);
  delete journal.request_namespace_version; delete journal.workspace_realpath;
  const target = path.join(dir, p.output);
  let info = remap(readJson(path.join(target,'input.json'))), manifest = remap(readJson(path.join(target,'capture.json')));
  for (let i=0;i<journal.blocks.length;++i) {
    const name = path.join(target, `read-${i}.json`);
    saveJson(name, remap(readJson(name)));
    const digest = hashFile(name);
    journal.blocks[i].snapshot_sha256 = digest; info.native_receipts[i].snapshot_sha256 = digest;
  }
  manifest.blocks = structuredClone(journal.blocks);
  saveJson(path.join(target,'input.json'), info);
  manifest.input_metadata_sha256 = shaBytes(canonical(info));
  saveJson(path.join(target,'capture.json'), manifest);
  for(const name of ['input.npy','input.json','capture.json']) journal.capture_receipt.files_sha256[name]=hashFile(path.join(target,name));
  saveJson(file, journal);
  return {file, journal};
}

test('completed legacy journals remain verifiable offline, without claiming new isolated reads', async t => {
  const dir=temp(t),f=fixture(); await handoffRegion(opts(dir),()=>f.bridge);
  const {file}=convertCompletedToLegacy(dir),before=fs.readFileSync(file);
  const result=await handoffRegion({...opts(dir),recover:true},()=>{throw Error('legacy never connects');});
  assert.equal(result.state,'captured');
  assert.equal(result.request_namespace_status,'legacy_unscoped_saved_evidence_only');
  assert.deepEqual(fs.readFileSync(file),before);
  assert.equal(JSON.parse(execFileSync('python',['tools/verify_native_region.py','--capture',path.join(dir,'capture')],{encoding:'utf8'})).status,'PASS_INDEPENDENT_CHUNKED_FILES');
});

test('incomplete legacy journals are not silently migrated or recovered with colliding IDs', async t => {
  const dir=temp(t),f=fixture(); await handoffRegion(opts(dir),()=>f.bridge);
  const {file,journal}=convertCompletedToLegacy(dir);journal.state='PARTIAL';saveJson(file,journal);
  const before=fs.readFileSync(file);
  for(const recover of [false,true]) await assert.rejects(()=>handoffRegion({...opts(dir),recover},()=>{throw Error('legacy never connects');}),/LEGACY_REGION_RECOVERY_UNSAFE/);
  assert.deepEqual(fs.readFileSync(file),before);
});
