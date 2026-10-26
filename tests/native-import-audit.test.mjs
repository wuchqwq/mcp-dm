// Independent hand-enumerable counterexamples to the preflight/recovery layer.
// No native transport, vendor call or real DM is used in this file.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {callNativeImport,parseImportNpy} from '../lib/native_import.mjs';
function smallNpy(){const text="{'descr': '<f4', 'fortran_order': False, 'shape': (1, 3), }",header=Buffer.from(text+' '.repeat((64-(10+text.length+1)%64)%64)+'\n'),prefix=Buffer.alloc(10),pixels=Buffer.alloc(12);prefix.write('\x93NUMPY',0,'binary');prefix[6]=1;prefix.writeUInt16LE(header.length,8);[-2.5,0,3.125].forEach((v,i)=>pixels.writeFloatLE(v,4*i));return Buffer.concat([prefix,header,pixels]);}
function receipt(session,id,wire){return {protocol:'NB2',session,id,state:'completed',host_pid:101,worker_tid:102,exec_tid:102,timings_us:{queue:0,execute:0},original_operation:'IMPORT',normalized_args:[...wire],result_type:'native_numeric_import',result_version:1,result:{image_id:42}};}
async function fixture(fn){const directory=fs.mkdtempSync(path.join(tmpdir(),'dm-import-audit-')),source=path.join(directory,'input.npy'),manifest=path.join(directory,'manifest.json'),calls=[];fs.writeFileSync(source,smallNpy());fs.writeFileSync(manifest,'{"origin":"independent fixture"}');const args={source_path:source,source_manifest_path:manifest,coordinate_domain:'real_space',calibration:{x:{origin:0,scale:1},y:{origin:0,scale:-1},unit:'nm'},request_id:'saved-before-dispatch'},bridge={session:'2'.repeat(32),async importSnapshot(wire,options){calls.push({wire});return receipt(this.session,options.requestId,wire);},async query(id){calls.push({query:id});return receipt(this.session,id,calls.find(c=>c.wire).wire);}};try{await fn({directory,source,manifest,args,bridge,calls});}finally{fs.rmSync(directory,{recursive:true,force:true});}}
test('same saved request recovers its original input even after current source files change or disappear',async()=>fixture(async({directory,source,manifest,args,bridge,calls})=>{
 bridge.importSnapshot=async wire=>{calls.push({wire});throw new Error('Accepted, client stopped waiting');};await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/Accepted/);
 fs.writeFileSync(source,'now invalid live input');fs.unlinkSync(manifest);const recovered=await callNativeImport(bridge,args,{localAppData:directory});assert.equal(recovered.result.image_id,42);assert.equal(recovered.recovered_by_query,true);assert.equal(calls.filter(c=>c.wire).length,1);assert.deepEqual(calls.at(-1),{query:args.request_id});
}));
test('binary32 physical-zero overflow rejects before any plugin dispatch',async()=>fixture(async({directory,args,bridge,calls})=>{
 args.calibration.x={origin:1e30,scale:1e30};await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/calibration|finite|overflow/i);assert.equal(calls.length,0);
}));
test('finite binary32 endpoints are required for the complete imported axis',async()=>fixture(async({directory,args,bridge,calls})=>{
 args.calibration.x={origin:0,scale:3e38};await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/calibration|finite|overflow/i);assert.equal(calls.length,0);
}));
test('high-bit header bytes and missing NPY newline cannot be laundered through ASCII decoding',()=>{
 const high=smallNpy();high[10]|=0x80;assert.throws(()=>parseImportNpy(high),/header|ASCII|ascii|NPY/i);const missing=smallNpy(),end=10+missing.readUInt16LE(8)-1;missing[end]=0x20;assert.throws(()=>parseImportNpy(missing),/header|newline|NPY/i);
});
test('a growing source is read with a max-plus-one bound and rejected before staging',async()=>fixture(async({directory,source,args,bridge,calls})=>{
 const originalFstat=fs.fstatSync,originalRead=fs.readFileSync,originalReadSync=fs.readSync;let grew=false,observed=0;
 fs.fstatSync=function(fd,options){const value=originalFstat(fd,options);if(!grew&&options?.bigint&&value.size===BigInt(smallNpy().length)){grew=true;fs.appendFileSync(source,Buffer.alloc(1024*1024));}return value;};
 fs.readFileSync=function(fd,...options){const bytes=originalRead(fd,...options);if(typeof fd==='number')observed=Math.max(observed,bytes.length);return bytes;};
 fs.readSync=function(fd,buffer,offset,length,...rest){observed=Math.max(observed,Number(length)||0);return originalReadSync(fd,buffer,offset,length,...rest);};syncBuiltinESMExports();
 try{await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/changed|budget|capture/i);}finally{fs.fstatSync=originalFstat;fs.readFileSync=originalRead;fs.readSync=originalReadSync;syncBuiltinESMExports();}
 assert.equal(grew,true);assert.ok(observed<=64*1024+4108+1,'Captured '+observed+' bytes despite the bound');assert.equal(calls.length,0);
}));
test('original UTF-8 provenance survives JSON numbers, duplicate keys and a BOM without silent rewriting',async()=>fixture(async({directory,manifest,args,bridge})=>{
 const text='\uFEFF{\r\n "unsafe":9007199254740993, "huge":1e400, "same":1, "same":2\r\n}\n';fs.writeFileSync(manifest,text,'utf8');
 const reply=await callNativeImport(bridge,args,{localAppData:directory});assert.equal(reply.import_handoff.source_provenance_raw_json,text);assert.deepEqual(Buffer.from(reply.import_handoff.source_provenance_raw_json,'utf8'),fs.readFileSync(manifest));assert.equal(reply.import_handoff.source_provenance,null);assert.equal(reply.import_handoff.source_provenance_parsed_numbers_safe,false);
}));
test('quoted provenance response budget rejects oversized evidence before any staged files or plugin call',async()=>fixture(async({directory,manifest,args,bridge,calls})=>{
 fs.writeFileSync(manifest,JSON.stringify({note:'a'.repeat(9000)}));await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/quoted provenance.*16 KiB/i);assert.equal(calls.length,0);assert.deepEqual(fs.readdirSync(path.join(directory,'mcp-dm','native-import',bridge.session)),[]);
}));
test('changed explicit source paths still conflict even when they happen to hold identical values',async()=>fixture(async({directory,source,args,bridge,calls})=>{
 await callNativeImport(bridge,args,{localAppData:directory});const other=path.join(directory,'different-input.npy');fs.writeFileSync(other,fs.readFileSync(source));await assert.rejects(callNativeImport(bridge,{...args,source_path:other},{localAppData:directory}),/conflict/);assert.equal(calls.filter(c=>c.wire).length,1);assert.equal(calls.filter(c=>c.query).length,0);
}));
test('reparse directory input is rejected without entering the plugin',async()=>fixture(async({directory,args,bridge,calls})=>{
 const real=path.join(directory,'real-input'),link=path.join(directory,'linked-input');fs.mkdirSync(real);fs.writeFileSync(path.join(real,'input.npy'),smallNpy());fs.symlinkSync(real,link,process.platform==='win32'?'junction':'dir');await assert.rejects(callNativeImport(bridge,{...args,source_path:path.join(link,'input.npy')},{localAppData:directory}),/symlink|reparse/i);assert.equal(calls.length,0);
}));
test('a mixed journal cannot attach another source or calibration to a correctly queried image',async()=>fixture(async({directory,args,bridge,calls})=>{
 await callNativeImport(bridge,args,{localAppData:directory});const file=path.join(directory,'mcp-dm','native-import',bridge.session,args.request_id+'.request.json'),original=fs.readFileSync(file,'utf8');
 for(const mutate of [r=>{r.handoff.source.sha256='f'.repeat(64);},r=>{r.args[4]=(r.args[4]^1)>>>0;},r=>{r.ticket='e'.repeat(32);},r=>{r.handoff.shape_yx=[3,1];},r=>{r.handoff.calibration.native_binary32.x.scale=2;}]){const record=JSON.parse(original);mutate(record);fs.writeFileSync(file,JSON.stringify(record));await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/journal.*(identity|wire|hash|calibration)/i);}
 assert.equal(calls.filter(c=>c.query).length,0);assert.equal(calls.filter(c=>c.wire).length,1);fs.writeFileSync(file,original);assert.equal((await callNativeImport(bridge,args,{localAppData:directory})).result.image_id,42);
}));
test('typed QUERY receipts must match the exact saved session, request, IMPORT operation and wire',async()=>fixture(async({directory,args,bridge,calls})=>{
 await callNativeImport(bridge,args,{localAppData:directory});const wire=calls.find(c=>c.wire).wire;
 for(const override of [{protocol:'NB1'},{session:'f'.repeat(32)},{id:'other-request'},{original_operation:'MEAN'},{normalized_args:wire.map((v,i)=>i===0?(v^1)>>>0:v)},{result_type:'image_crop'},{result_version:2}]){bridge.query=async()=>({...receipt(bridge.session,args.request_id,wire),...override});await assert.rejects(callNativeImport(bridge,args,{localAppData:directory}),/receipt.*mismatch/i);}
 assert.equal(calls.filter(c=>c.wire).length,1);
}));
test('an unobserved host request stays unknown and is never promoted to a completed import',async()=>fixture(async({directory,args,bridge,calls})=>{
 await callNativeImport(bridge,args,{localAppData:directory});const wire=calls.find(c=>c.wire).wire;bridge.query=async()=>{const output={...receipt(bridge.session,args.request_id,wire),state:'unknown',exec_tid:0,original_operation:null,normalized_args:null,result_type:null,result_version:null};delete output.result;return output;};const unknown=await callNativeImport(bridge,args,{localAppData:directory});assert.equal(unknown.state,'unknown');assert.equal(unknown.result,undefined);assert.equal(unknown.recovered_by_query,true);assert.equal(calls.filter(c=>c.wire).length,1);
}));
