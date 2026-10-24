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
  const plan=planRegion(opts('unused')),covered=new Set();
  assert.equal(plan.blocks.length,5);
  for(const block of plan.blocks){const [id,x0,y0,x1,y1]=block.request.args;assert.equal(id,77);assert.ok((x1-x0)*(y1-y0)<=8);
    for(let y=y0;y<y1;++y)for(let x=x0;x<x1;++x){assert.ok(!covered.has(`${x},${y}`));covered.add(`${x},${y}`);}}
  assert.equal(covered.size,35);
  const split=planRegion({...opts('unused'),rect:[2,3,21,8],blockSamples:12});assert.equal(split.blocks.length,10);assert.deepEqual(split.blocks.at(-1).request.args,[77,14,7,21,8]);
  for(const bad of [{rect:[0,0,2049,2048]},{blockSamples:0},{blockSamples:16385},{rect:[0,0,1000,1000],blockSamples:1},{requestId:'bad id'},{hostPid:0},{session:'bad'}])
    assert.throws(()=>planRegion({...opts('unused'),...bad}));
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
