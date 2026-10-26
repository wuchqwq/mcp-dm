import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {callNativeImport,parseImportNpy,nativeImportTool} from '../lib/native_import.mjs';
function npy(values=[-3.25,0,1.5,2,4,123.125],descr='<f4',shape='2, 3'){
 const text=`{'descr': '${descr}', 'fortran_order': False, 'shape': (${shape}), }`,header=Buffer.from(text+' '.repeat((64-(10+text.length+1)%64)%64)+'\n'),prefix=Buffer.alloc(10),raw=Buffer.alloc(values.length*4);prefix.write('\x93NUMPY',0,'binary');prefix[6]=1;prefix.writeUInt16LE(header.length,8);values.forEach((v,i)=>raw.writeFloatLE(v,i*4));return Buffer.concat([prefix,header,raw]);
}
function receipt(session,id,wire,image_id=42){return {protocol:'NB2',session,id,state:'completed',host_pid:101,worker_tid:102,exec_tid:102,timings_us:{queue:0,execute:0},original_operation:'IMPORT',normalized_args:[...wire],result_type:'native_numeric_import',result_version:1,result:{image_id}};}
async function fixture(fn){const dir=mkdtempSync(path.join(tmpdir(),'dm-native-import-')),source=path.join(dir,'source.npy'),manifest=path.join(dir,'source.json');writeFileSync(source,npy());writeFileSync(manifest,JSON.stringify({schema_version:1,computation:'independent synthetic fixture',axis_order:['y','x'],dtype:'float32',shape:[2,3]}));const args={source_path:source,source_manifest_path:manifest,coordinate_domain:'real_space',calibration:{x:{origin:1.25,scale:.02},y:{origin:-2,scale:-.04},unit:'nm'},request_id:'known-before-import'},calls=[];const bridge={session:'1'.repeat(32),async importSnapshot(wire,options){calls.push({wire,options});return receipt(this.session,options.requestId,wire);},async query(id){calls.push({query:id});return receipt(this.session,id,calls.find(c=>c.wire).wire);}};try{await fn({dir,source,manifest,args,calls,bridge});}finally{rmSync(dir,{recursive:true,force:true});}}
test('bounded float32 NPY admission preserves signed fractional samples and refuses invalid format/data',()=>{
 assert.deepEqual(parseImportNpy(npy()).shape_yx,[2,3]);
 for(const bytes of [npy([0,0,0,0,0,Infinity]),npy(undefined,'<u4'),npy(undefined,'<f4','1, 2, 3'),Buffer.concat([npy(),Buffer.from([1])]),npy().subarray(0,20)])assert.throws(()=>parseImportNpy(bytes));
 assert.deepEqual(nativeImportTool.inputSchema.required,['source_path','source_manifest_path','coordinate_domain','calibration','request_id']);
});
test('import snapshots and fsyncs original intent before dispatch, preserving bytes and reporting ABI scale rounding',async()=>fixture(async({dir,source,manifest,args,calls,bridge})=>{
 const original=readFileSync(source),sidecarOriginal=readFileSync(manifest),invoke=bridge.importSnapshot.bind(bridge);
 bridge.importSnapshot=async(wire,options)=>{const root=path.join(dir,'mcp-dm','native-import',bridge.session),record=JSON.parse(readFileSync(path.join(root,args.request_id+'.request.json'),'utf8'));assert.deepEqual(record.args,wire);assert.equal(wire.length,27);assert.deepEqual(readFileSync(path.join(root,record.ticket+'.npy')),original);assert.equal(wire.slice(4,12).map(v=>v.toString(16).padStart(8,'0')).join(''),createHash('sha256').update(original).digest('hex'));assert.equal(record.handoff.calibration.native_binary32.y.scale,Math.fround(-.04));assert.equal(record.handoff.calibration.requested.y.scale,-.04);return invoke(wire,options);};
 const reply=await callNativeImport(bridge,args,{localAppData:dir});assert.equal(reply.result.image_id,42);assert.equal(reply.import_handoff.scientific_data_changed,false);assert.deepEqual(readFileSync(source),original);assert.deepEqual(readFileSync(manifest),sidecarOriginal);assert.equal(calls.length,1);
 const second=await callNativeImport(bridge,args,{localAppData:dir});assert.equal(second.result.image_id,42);assert.equal(second.recovered_by_query,true);assert.equal(calls.filter(c=>c.wire).length,1);assert.equal(calls[1].query,args.request_id);
}));
test('missing ID, wrong domain, nonfinite data and invalid UTF-8 reject before any native submission',async()=>fixture(async({dir,source,manifest,args,calls,bridge})=>{
 for(const override of [{request_id:undefined},{coordinate_domain:'reciprocal_space'},{calibration:{...args.calibration,x:{origin:0,scale:0}}}])await assert.rejects(callNativeImport(bridge,{...args,...override},{localAppData:dir}));
 writeFileSync(source,npy([0,0,0,0,0,NaN]));await assert.rejects(callNativeImport(bridge,args,{localAppData:dir}),/finite/);
 writeFileSync(source,npy());writeFileSync(manifest,Buffer.from([0x7b,0x22,0xff,0x22,0x3a,0x31,0x7d]));await assert.rejects(callNativeImport(bridge,args,{localAppData:dir}),/UTF-8/);assert.equal(calls.length,0);
}));
test('changed parameters refuse; changed live files recover historical input and only a new ID captures again',async()=>fixture(async({dir,source,args,calls,bridge})=>{
 bridge.importSnapshot=async(wire,options)=>{calls.push({wire,options});throw new Error('Stopped waiting after host accepted');};
 await assert.rejects(callNativeImport(bridge,args,{localAppData:dir}),/Stopped waiting/);
 await assert.rejects(callNativeImport(bridge,{...args,calibration:{...args.calibration,y:{origin:0,scale:1}}},{localAppData:dir}),/conflict/);
 const newClient={...bridge,importSnapshot(){throw new Error('Must not resubmit');}};
 const recovered=await callNativeImport(newClient,args,{localAppData:dir});assert.equal(recovered.result.image_id,42);
 writeFileSync(source,npy([1,2,3,4,5,6]));const historical=await callNativeImport(newClient,args,{localAppData:dir});assert.equal(historical.import_handoff.source.sha256,recovered.import_handoff.source.sha256);assert.equal(historical.recovered_by_query,true);assert.equal(calls.filter(c=>c.wire).length,1);
 const fresh={...bridge,async importSnapshot(wire,options){calls.push({wire,options});return receipt(this.session,options.requestId,wire,43);}};
 const newlyCaptured=await callNativeImport(fresh,{...args,request_id:'explicit-new-capture'},{localAppData:dir});assert.equal(newlyCaptured.result.image_id,43);assert.notEqual(newlyCaptured.import_handoff.source.sha256,recovered.import_handoff.source.sha256);assert.equal(calls.filter(c=>c.wire).length,2);
}));
