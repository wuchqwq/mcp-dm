// Actual stdio MCP + independent image/ASE workers, not DM/browser acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_STRUCTURE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const optional={skip:!process.env.DM_STRUCTURE_PYTHON&&'Set DM_STRUCTURE_PYTHON to the independent image/ASE environment'};
const hash=p=>createHash('sha256').update(readFileSync(p)).digest('hex');
function client(workspace){
 const child=spawn(process.execPath,[path.join(root,'server.mjs')],{windowsHide:true,env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:path.join(workspace,'images'),DM_STRUCTURE_WORKSPACE:path.join(workspace,'structures'),DM_IMAGE_PYTHON:python,DM_STRUCTURE_PYTHON:python},stdio:['pipe','pipe','pipe']});
 let next=1,buffer='',stderr='';const pending=new Map();child.stderr.on('data',x=>stderr+=x);child.stdin.on('error',()=>{});
 child.stdout.on('data',x=>{buffer+=x;let end;while((end=buffer.indexOf('\n'))>=0){const row=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);const wait=pending.get(row.id);if(wait){pending.delete(row.id);clearTimeout(wait.timer);wait.resolve(row);}}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=next++,timer=setTimeout(()=>{pending.delete(id);reject(Error('MCP deadline '+stderr));},180000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 return {rpc,raw:(name,args)=>rpc('tools/call',{name,arguments:args}),async tool(name,args){const row=await rpc('tools/call',{name,arguments:args});assert.equal(row.error,undefined,JSON.stringify(row));assert.notEqual(row.result.isError,true,JSON.stringify(row));return {data:JSON.parse(row.result.content.find(b=>b.type==='text').text),content:row.result.content};},async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
test('current diffraction revisions preserve source numbers, separate fit/heldout and recover in a new MCP client',optional,async()=>{
 const folder=mkdtempSync(path.join(tmpdir(),'revisable-diffraction-')),workspace=path.join(folder,'workspace'),tiff=path.join(folder,'synthetic.tiff'),cif=path.join(folder,'copper.cif');
 const script="from ase.build import bulk; from ase.io import write; import numpy as np,tifffile,sys; write(sys.argv[2],bulk('Cu','fcc',a=4,cubic=True),format='cif'); y,x=np.indices((32,32)); a=(1000+100*np.cos(2*np.pi*x/4)+80*np.cos(2*np.pi*y/4)).round().astype(np.uint16); tifffile.imwrite(sys.argv[1],a,photometric='minisblack')";
 const made=spawnSync(python,['-c',script,tiff,cif],{encoding:'utf8'});assert.equal(made.status,0,made.stderr);
 const sourceHash=hash(tiff);let c=client(workspace);try{
  await c.rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'revision-contract',version:'1'}});
  const catalog=(await c.rpc('tools/list')).result.tools;
  for(const name of ['image_center','image_remeasure','structure_register'])assert.ok(catalog.find(t=>t.name===name));
  const bad=await c.raw('structure_register',{object_id:'a'.repeat(32),request_id:'missing-current'});assert.equal(bad.error.code,-32602);assert.equal(existsSync(path.join(workspace,'structures')),false);
  const source=(await c.tool('image_open',{source_path:tiff,source_kind:'tiff',request_id:'source'})).data;
  const frame=(await c.tool('image_frame',{object_id:source.object_id,frame_index:0,request_id:'frame'})).data;
  const described=(await c.tool('image_context',{object_id:frame.object_id,metadata:{data_meaning:'SAED diffraction intensity supplied by the researcher'},request_id:'describe-before-scale'})).data;
  const declared=(await c.tool('image_calibrate',{object_id:described.object_id,scope:'image',coordinate_domain:'reciprocal_space',declare_reciprocal:true,xy_scale:{x:1.25,y:-2.5,unit:'1/nm'},source_text:'Independent synthetic diffraction-coordinate fixture',request_id:'scale'})).data;
  const centre=(await c.tool('image_center',{object_id:declared.object_id,center_xy:[16,16],coordinate_space:'source_array_indices',source_text:'Literal synthetic DC',request_id:'centre'})).data;
  const peaks=[[20,16],[16,14],[20,14],[20,18]],measures=[];
  const displayA=(await c.tool('image_preview',{object_id:centre.object_id,gamma:.8,request_id:'display-a'})).data;
  const displayB=(await c.tool('image_preview',{object_id:displayA.object_id,gamma:1.1,request_id:'display-b'})).data;
  const measurementViews=[centre,displayA,displayB,displayA];
  for(let i=0;i<peaks.length;i++)measures.push((await c.tool('image_measure',{object_id:measurementViews[i].object_id,points:[[16,16],peaks[i]],coordinate_space:'source_array_indices',request_id:'peak-'+i})).data);
  assert.equal(new Set(measures.map(m=>m.source_object_id)).size,3);
  assert.equal(displayB.user_context.data_meaning,'SAED diffraction intensity supplied by the researcher');
  const structure=(await c.tool('structure_open',{source_path:cif,request_id:'cif'})).data;
  const oriented=(await c.tool('structure_orient',{object_id:structure.object_id,zone_axis_uvw:[0,0,1],in_plane_direction_uvw:[1,0,0],request_id:'orientation'})).data;
  const sim=(await c.tool('structure_simulate',{object_id:structure.object_id,orientation_id:oriented.object_id,voltage_kv:200,reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,size:64,request_id:'simulate'})).data;
  const proposalArgs={object_id:sim.object_id,current_image_object_id:centre.object_id,measurement_paths:measures.map(m=>m.manifest_path),fit_correspondences:[{measurement_index:0,hkl:[2,0,0]},{measurement_index:1,hkl:[0,2,0]}],validation_correspondences:[{measurement_index:2,hkl:[2,2,0]},{measurement_index:3,hkl:[2,-2,0]}],screen_axes:{flip_y:false,basis:'Explicit common synthetic axes; signed calibration already applied'},confirmation:{source:'synthetic_fixture',source_text:'Predeclared literal synthetic correspondences, not human experiment confirmation'},experimental_kind:'saed',max_residual_inv_angstrom:1e-12,request_id:'registration'};
  const proposal=(await c.tool('structure_register',proposalArgs)).data;
  assert.equal(proposal.registration.scale,1);assert.deepEqual(proposal.registration.translation_inv_angstrom,[0,0]);assert.equal(proposal.fit_evidence.length,2);assert.equal(proposal.validation_evidence.length,2);assert.equal(proposal.held_out_validation_passed,true);
  for(const row of proposal.validation_evidence)assert.ok(row.position_residual_inv_angstrom<1e-14);
  const first=(await c.tool('structure_compare',{object_id:sim.object_id,current_image_object_id:centre.object_id,measurement_paths:measures.map(m=>m.manifest_path),registration_object_id:proposal.object_id,experimental_kind:'saed',max_residual_inv_angstrom:1e-12,request_id:'compare-before'})).data;
  assert.match(first.registration.parameter_source,/saved constrained/);
  const revised=(await c.tool('image_center',{object_id:centre.object_id,center_xy:[16.5,15.5],coordinate_space:'source_array_indices',source_text:'Explicit synthetic half-pixel correction',request_id:'centre-revision'})).data;
  const stale=await c.raw('structure_compare',{object_id:sim.object_id,current_image_object_id:revised.object_id,measurement_paths:measures.map(m=>m.manifest_path),registration_object_id:proposal.object_id,experimental_kind:'saed',max_residual_inv_angstrom:1e-12,request_id:'reject-stale'});assert.equal(stale.result.isError,true);assert.match(stale.result.content[0].text,/remeasure/);
  const updated=[];for(let i=0;i<measures.length;i++)updated.push((await c.tool('image_remeasure',{object_id:revised.object_id,measurement_object_id:measures[i].object_id,request_id:'remeasure-'+i})).data);
  assert.deepEqual(updated[0].points,[[16.5,15.5],[20,16]]);assert.deepEqual(updated[0].physical_vector_xy,[4.375,-1.25]);
  const secondProposal=(await c.tool('structure_register',{...proposalArgs,current_image_object_id:revised.object_id,measurement_paths:updated.map(m=>m.manifest_path),request_id:'registration-revised'})).data;
  assert.equal(secondProposal.held_out_validation_passed,false);
  const second=(await c.tool('structure_compare',{object_id:sim.object_id,current_image_object_id:revised.object_id,measurement_paths:updated.map(m=>m.manifest_path),registration_object_id:secondProposal.object_id,previous_comparison_id:first.object_id,experimental_kind:'saed',max_residual_inv_angstrom:1e-12,request_id:'compare-after'})).data;
  assert.equal(second.analysis_revision,2);assert.equal(second.analysis_root_id,first.object_id);assert.equal(second.unchanged_scientific_array_reused,true);assert.equal(second.phase_identified,false);
  const view=await c.tool('image_preview',{object_id:revised.object_id,max_size:128,upscale:true,request_id:'visible'});assert.ok(view.content.find(b=>b.type==='image'&&b.mimeType==='image/png'));
  const exported=(await c.tool('image_export',{object_id:view.data.object_id,output_dir:path.join(folder,'new-export'),request_id:'export'})).data;assert.ok(exported);
  assert.equal(hash(frame.array_path),frame.files_sha256['data.npy']);assert.equal(hash(tiff),sourceHash);
  await c.close();c=client(workspace);
  const historical=(await c.tool('structure_result',{request_id:'registration'})).data;assert.equal(historical.object_id,proposal.object_id);assert.equal(historical.held_out_validation_passed,true);
  const same=(await c.tool('structure_register',proposalArgs)).data;assert.equal(same.object_id,proposal.object_id);
  const changed=await c.raw('structure_register',{...proposalArgs,current_image_object_id:revised.object_id});assert.equal(changed.result.isError,true);
 }finally{await c.close();rmSync(folder,{recursive:true,force:true});}
});
