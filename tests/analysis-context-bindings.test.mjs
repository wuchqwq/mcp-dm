// Provider-port counterexamples only. Fixtures stand for already-verified
// immutable metadata; these tests do not qualify scientific workers or DM.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createScientificContextBindings} from '../lib/analysis_context_bindings.mjs';
import {createAnalysisContextModule} from '../lib/tools/analysis_context_module.mjs';
import {ToolRegistry} from '../lib/runtime/tool_registry.mjs';

function fixture(t) {
  const directory=mkdtempSync(path.join(tmpdir(),'context-bindings-')),workspace=path.join(directory,'image');mkdirSync(workspace);
  const requestScope={provider:'external-image-workspace',workspace,session:'workspace-journal-v1'},objects=new Map();let calls=0;
  const provider={workspace,requestScope,call:async(name,args)=>{calls++;assert.equal(name,'image_info');const value=objects.get(args.object_id);if(!value)throw new Error('OBJECT_NOT_FOUND');return {content:[{type:'text',text:JSON.stringify({...value,state:'completed'})}]};}};
  const save=(number,value)=>{const object_id=number.toString(16).padStart(32,'0'),folder=path.join(workspace,'objects',object_id);mkdirSync(folder,{recursive:true});const manifest_path=path.join(folder,'object.json');
    const metadata={object_id,backend:requestScope.provider,manifest_path,...value};objects.set(object_id,metadata);writeFileSync(manifest_path,JSON.stringify(metadata));return {...requestScope,objectId:object_id};};
  const record=id=>({calibration_id:id,revision:1,status:'active',source:'user_statement_not_independently_verified',coordinate_domain:'real_space',xy_scale:{x:.05,y:-.05,unit:'nm'}});
  const frame=save(1,{kind:'frame',shape_yx:[4,4],dtype:'uint16',files_sha256:{'data.npy':'1'.repeat(64)}});
  const other=save(2,{kind:'frame',shape_yx:[4,4],dtype:'uint16',files_sha256:{'data.npy':'2'.repeat(64)}});
  const calibration=save(3,{kind:'calibration',base_object_id:frame.objectId,xy_calibration:record('scale-original')});
  const fft=save(4,{kind:'fft',parent_object_id:calibration.objectId,shape_yx:[4,4],dtype:'complex128',files_sha256:{'data.npy':'3'.repeat(64)},xy_calibration:record('scale-original')});
  const revised=save(5,{kind:'calibration',base_object_id:fft.objectId,xy_calibration:{...record('scale-revised'),revision:2}});
  const providers={image:provider},bindings=createScientificContextBindings({providers});
  t.after(()=>rmSync(directory,{recursive:true,force:true}));
  return {directory,bindings,save,frame,other,calibration,fft,revised,providers,calls:()=>calls,objects};
}
const active=(ref,proof,dependsOn={})=>({ref,proof,dependsOn,status:'active',staleBecause:[]});

test('provider proof resolves wrapper to the original fixed grid while keeping its corrected calibration',async t=>{
  const f=fixture(t),old=await f.bindings.resolveReference(f.fft),revised=await f.bindings.resolveReference(f.revised);
  assert.deepEqual(revised.scientific.grid,old.scientific.grid);
  assert.notEqual(revised.scientific.calibration.calibration_id,old.scientific.calibration.calibration_id);
  assert.equal(revised.roles.includes('fft'),true);assert.equal(revised.roles.includes('calibration'),true);
});

test('another provider/workspace/session cannot resolve the same local object ID',async t=>{
  const f=fixture(t);
  for(const bad of [{provider:'external-structure-workspace'},{workspace:f.directory},{session:'another-session'}])await assert.rejects(f.bindings.resolveReference({...f.frame,...bad}),/configured provider\/workspace\/session/);
  assert.equal(f.calls(),0);
});

test('new dependency fingerprints cannot relabel an old FFT as produced by a different experiment',async t=>{
  const f=fixture(t),fft=active(f.fft,await f.bindings.resolveReference(f.fft),{experiment:'new-fingerprint'});
  await assert.rejects(f.bindings.validateBindings({slot:'fft',entry:fft,slots:{experiment:active(f.other,await f.bindings.resolveReference(f.other))}}),/not produced from/);
  await f.bindings.validateBindings({slot:'fft',entry:fft,slots:{experiment:active(f.frame,await f.bindings.resolveReference(f.frame))}});
});

test('saved measurements cannot be rebound to a newer scale without actual remeasurement',async t=>{
  const f=fixture(t),fft=await f.bindings.resolveReference(f.fft),measure=f.save(6,{kind:'measure',parent_object_id:f.fft.objectId,
    points:[[0,0],[.25,0]],coordinate_space:'frequency_cycles_per_pixel',scientific_grid_identity:fft.scientific.grid,calibration_dependency:fft.scientific.calibration});
  const entry=active(measure,await f.bindings.resolveReference(measure),{fft:'saved',calibration:'new'}),slots={fft:active(f.fft,fft),calibration:active(f.revised,await f.bindings.resolveReference(f.revised))};
  await assert.rejects(f.bindings.validateBindings({slot:'measurements',entry,slots}),/different calibration/);
});

test('context MCP auto-binds current proof fingerprints, keeps FFT and stales dependent measurements on scale correction',async t=>{
  const f=fixture(t),registry=new ToolRegistry().register(createAnalysisContextModule({directory:path.join(f.directory,'contexts'),providers:f.providers})).seal();
  const call=async(name,args)=>JSON.parse((await registry.call(name,args)).content[0].text);
  await call('analysis_create',{analysis_id:'task',request_id:'create',reason:'Synthetic port fixture'});
  let update=await call('analysis_update',{analysis_id:'task',expected_revision:1,request_id:'frame',reason:'Select fixed frame',selections:{experiment:{provider:'image',object_id:f.frame.objectId}}});
  update=await call('analysis_update',{analysis_id:'task',expected_revision:update.context.revision,request_id:'fft',reason:'Select existing FFT',selections:{fft:{provider:'image',object_id:f.fft.objectId}}});
  assert.equal(update.context.slots.fft.status,'active');
  update=await call('analysis_update',{analysis_id:'task',expected_revision:update.context.revision,request_id:'scale',reason:'Correct signed scale',selections:{calibration:{provider:'image',object_id:f.revised.objectId}}});
  assert.equal(update.context.slots.fft.status,'active');assert.equal(update.context.slots.calibration.status,'active');
  const before=f.calls(),restored=await call('analysis_read',{analysis_id:'task',request_id:'scale'});
  assert.equal(restored.context.revision,update.context.revision);assert.equal(f.calls(),before,'original context mutation query does not run a scientific provider');
});
