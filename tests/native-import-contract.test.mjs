// Hand-built protocol fixtures only. No vendor API, physical experiment or
// actual imported image is established by these tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {NativeBridge,validateNativeImport,validateNativeDataSnapshot} from '../lib/native_bridge.mjs';
import {imageMetadata,readFixture} from './fixtures/native-operations.mjs';
function bits(value){const b=Buffer.alloc(4);b.writeFloatLE(value);return b.readUInt32LE();}
function fixture(){
 const image=imageMetadata(91),manifest_json='{"source":"independent numerical contract fixture","computation":"external"}';
 const context={schema_version:1,ticket:'1'.repeat(32),npy_sha256:'a'.repeat(64),manifest_sha256:createHash('sha256').update(manifest_json).digest('hex'),coordinate_domain:'real_space',manifest_json,scope:'external immutable input at import; current DM values remain mutable; no embedded DM tags'};
 const words=hex=>hex.match(/.{8}/g).map(v=>Number.parseInt(v,16));
 const args=[...words(context.ticket),...words(context.npy_sha256),...words(context.manifest_sha256),8,4,bits(2),bits(-.25),bits(-1),bits(.5),17];
 const result={backend:'digitalmicrograph-native',operation:'IMPORT',image_id:91,image,shape:[4,8],dtype:'float32',axes:['y','x'],external_import:context,pixel_readback_exact:true,calibration_readback_exact:true,operator:'GMS::Image::CreateImage + GMS::Image::SetRealValue',computation:'data handoff only; scientific values computed externally',intensity_calibration_applied:false,intensity_semantics:'raw external numeric values',visible_dm_document:false,source_write_requested:false,snapshot_atomic:false,qualification:'CANDIDATE_BUILD_NOT_RELEASE_QUALIFIED',retention:{token:17,creation_request_id:'saved-import',state_at_creation:'plugin_retained',identity_scope:'bridge token in this native session, not a host image ID'}};
 return {args,result};
}
test('IMPORT keeps independent float32 shape, signed raw origin, unapplied intensity and exact external manifest hash',()=>{
 const {args,result}=fixture();validateNativeImport(result,args,'saved-import');
 assert.equal(result.image.calibration[0].scale,-.25);assert.equal(result.qualification,'CANDIDATE_BUILD_NOT_RELEASE_QUALIFIED');
 const unknown=structuredClone(result),pixel=[...args];pixel[26]=0;unknown.external_import.coordinate_domain='image_coordinates';unknown.image.calibration_complete=false;for(const axis of unknown.image.calibration){axis.unit=null;axis.usable=false;axis.issue='unknown_units';}validateNativeImport(unknown,pixel,'saved-import');
});
test('IMPORT refuses wrong producer, array identity, conversion, hash, calibration, ownership and numerical claims',()=>{
 const mutations=[r=>r.operation='READ',r=>r.image_id=0,r=>r.shape.reverse(),r=>r.dtype='float64',r=>r.axes.reverse(),r=>r.pixel_readback_exact=false,r=>r.calibration_readback_exact=false,r=>r.operator='NumPy',r=>r.computation='DM native diffraction simulation',r=>r.intensity_calibration_applied=true,r=>r.visible_dm_document=true,r=>r.source_write_requested=true,r=>r.qualification='NOT_QUALIFIED',r=>r.retention.creation_request_id='another',r=>delete r.retention,r=>r.image.packing_style=2,r=>r.image.calibration[0].scale=.25,r=>r.image.calibration[1].origin++,r=>r.image.calibration[0].calibrated_value_at_pixel_zero=1,r=>r.image.calibration[0].unit='counts',r=>r.external_import.ticket='2'.repeat(32),r=>r.external_import.npy_sha256='b'.repeat(64),r=>r.external_import.manifest_json='{}',r=>r.external_import.coordinate_domain='reciprocal_space',r=>r.external_import.scope='embedded DM tags'];
 for(const [i,mutate]of mutations.entries()){const f=fixture();mutate(f.result);assert.throws(()=>validateNativeImport(f.result,f.args,'saved-import'),Error,'mutation '+i);}
 for(const [index,value]of [[20,0],[20,16385],[23,bits(Infinity)],[23,bits(0)],[26,18+16],[26,4]]){const f=fixture();f.args[index]=value;assert.throws(()=>validateNativeImport(f.result,f.args,'saved-import'));}
});
test('saved IMPORT READ has zero DM source IDs and retains the exact external input rather than pretending a DM computation',()=>{
 const {result}=fixture(),args=[91,0,0,8,4],provenance={operation:'IMPORT',request_id:'saved-import',source_image_ids:[],semantics:'external fixed input copied without processing'};
 const read=readFixture(args,{source:result.image,provenance});read.external_import=result.external_import;read.external_import_scope='creation identity only; current values/calibration are fresh and may differ';validateNativeDataSnapshot(read,args);
 for(const mutate of [r=>delete r.external_import,r=>delete r.external_import_scope,r=>r.external_import_scope='current pixels unchanged',r=>r.external_import.manifest_json='{}',r=>r.source_provenance.source_image_ids=[77],r=>r.source_provenance.operation='arbitrary-import']){const bad=structuredClone(read);mutate(bad);assert.throws(()=>validateNativeDataSnapshot(bad,args));}
});
test('importSnapshot requires a saved caller ID and uses the single-submit transport entry',async()=>{
 const bridge=new NativeBridge({session:'a'.repeat(32)}),{args}=fixture(),calls=[];
 bridge.execute=async(...values)=>{calls.push(values);return {state:'queued'};};
 await assert.rejects(()=>bridge.importSnapshot(args),/caller-saved/);
 assert.deepEqual(await bridge.importSnapshot(args,{requestId:'before-submit'}),{state:'queued'});assert.equal(calls.length,1);assert.equal(calls[0][0],'IMPORT');assert.deepEqual(calls[0][1],args);assert.equal(calls[0][2].requestId,'before-submit');
});
test('IMPORT refuses an otherwise hash-consistent sidecar that would overflow the bounded encoded receipt',()=>{
 const {args,result}=fixture();result.external_import.manifest_json=JSON.stringify({source:'\\'.repeat(9000)});
 const hash=createHash('sha256').update(result.external_import.manifest_json).digest('hex');result.external_import.manifest_sha256=hash;
 args.splice(12,8,...hash.match(/.{8}/g).map(v=>Number.parseInt(v,16)));
 assert.ok(Buffer.byteLength(result.external_import.manifest_json)<32768);assert.ok(Buffer.byteLength(JSON.stringify(result.external_import.manifest_json))>16384);
 assert.throws(()=>validateNativeImport(result,args,'saved-import'),/frozen external input\/hash\/context mismatch/);
});
