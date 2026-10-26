// Synthetic saved native READ only; no host or experimental data is accessed.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {handoff} from '../tools/native_snapshot_handoff.mjs';
import {readFixture,imageMetadata} from './fixtures/native-operations.mjs';
test('scientific NPY handoff preserves imported external source, exact sidecar hash and reciprocal domain',t=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'native-import-handoff-'));
 t.after(()=>{const actual=fs.realpathSync(directory);assert.equal(path.dirname(actual),fs.realpathSync(os.tmpdir()));assert.ok(path.basename(actual).startsWith('native-import-handoff-'));fs.rmSync(actual,{recursive:true});});
 const manifest_json='{"source":"external synthetic diffraction fixture","calibration_source":"synthetic reciprocal grid"}',args=[91,0,0,8,4],source=imageMetadata(91);
 source.calibration.forEach(a=>{a.unit='1/Å';});
 const value=readFixture(args,{source,provenance:{operation:'IMPORT',request_id:'original-import',source_image_ids:[],semantics:'external numerical snapshot handed into a new DM image'}});
 value.external_import={schema_version:1,ticket:'1'.repeat(32),npy_sha256:'a'.repeat(64),manifest_sha256:createHash('sha256').update(manifest_json).digest('hex'),coordinate_domain:'reciprocal_space',manifest_json,scope:'external immutable input at import; current DM values remain mutable; no embedded DM tags'};
 value.external_import_scope='creation identity only; current values/calibration are fresh and may differ';
 value.native_receipt={protocol:'NB2',session:'a'.repeat(32),id:'synthetic-import-read',request_id:'synthetic-import-read',original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1,state:'completed',host_pid:1234,exec_tid:10,worker_tid:20,timings_us:{queue:3,execute:4}};
 const snapshot=path.join(directory,'saved.json');fs.writeFileSync(snapshot,JSON.stringify(value));
 const receipt=handoff({workspace:directory,output:'capture',requestId:'handoff-import',snapshot});assert.equal(receipt.state,'captured');
 const input=JSON.parse(fs.readFileSync(path.join(directory,'capture','input.json'),'utf8')),capture=JSON.parse(fs.readFileSync(path.join(directory,'capture','capture.json'),'utf8'));
 assert.deepEqual(input.native_external_import,value.external_import);assert.deepEqual(capture.native_external_import,value.external_import);
 assert.equal(input.native_source_provenance.operation,'IMPORT');assert.equal(input.native_external_import.coordinate_domain,'reciprocal_space');
 assert.equal(input.native_external_import_scope,value.external_import_scope);assert.equal(capture.native_external_import_scope,value.external_import_scope);assert.equal(input.scientific_semantics.domain,'unknown');
 assert.equal(createHash('sha256').update(input.native_external_import.manifest_json).digest('hex'),input.native_external_import.manifest_sha256);
 assert.deepEqual(handoff({workspace:directory,output:'capture',requestId:'handoff-import',snapshot}),receipt);
 // A later numeric capture can legitimately differ from the imported source.
 // It retains the old creation hash without reusing that old array/calibration.
 const currentSource=structuredClone(source);currentSource.calibration[0].origin=3;currentSource.calibration[0].calibrated_value_at_pixel_zero=.75;
 const current=readFixture(args,{source:currentSource,provenance:value.source_provenance});Object.assign(current,{external_import:value.external_import,external_import_scope:value.external_import_scope,native_receipt:{...value.native_receipt,id:'fresh-current-read',request_id:'fresh-current-read'}});
 const freshBytes=Buffer.from(current.values_base64,'base64');freshBytes.writeFloatLE(999.25,0);current.values_base64=freshBytes.toString('base64');
 const currentPath=path.join(directory,'current-read.json');fs.writeFileSync(currentPath,JSON.stringify(current));handoff({workspace:directory,output:'after-user-edit',requestId:'capture-current',snapshot:currentPath});
 const currentInfo=JSON.parse(fs.readFileSync(path.join(directory,'after-user-edit','input.json'),'utf8')),currentNpy=fs.readFileSync(path.join(directory,'after-user-edit','input.npy'));
 assert.equal(currentNpy.readFloatLE(10+currentNpy.readUInt16LE(8)),999.25);assert.equal(currentInfo.source_calibration_dm[0].origin,3);assert.deepEqual(currentInfo.native_external_import,value.external_import);assert.equal(currentInfo.scientific_semantics.domain,'unknown');
 const forged=structuredClone(value);forged.external_import.manifest_json='{}';const other=path.join(directory,'forged.json');fs.writeFileSync(other,JSON.stringify(forged));
 assert.throws(()=>handoff({workspace:directory,output:'rejected',requestId:'handoff-forged',snapshot:other}),/import|context|hash/i);assert.equal(fs.existsSync(path.join(directory,'rejected')),false);
});
