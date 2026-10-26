// Real external worker and Node stdio MCP, using public synthetic structures.
// Neither this protocol test nor an inline PNG establishes actual3D/DM viewing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {existsSync,mkdtempSync,readFileSync,readdirSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {StructureWorkspace,structureTools} from '../lib/structure_workspace.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_STRUCTURE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const optionalEnvironment={skip:!process.env.DM_STRUCTURE_PYTHON&&'Set DM_STRUCTURE_PYTHON to the optional independent ASE/diffsims environment'};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const unpack=reply=>JSON.parse(reply.content.find(block=>block.type==='text').text);
function client(workspace){
  const child=spawn(process.execPath,[path.join(root,'server.mjs')],{windowsHide:true,env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:path.join(workspace,'images'),DM_STRUCTURE_WORKSPACE:path.join(workspace,'structures'),DM_STRUCTURE_PYTHON:python,DM_IMAGE_PYTHON:python},stdio:['pipe','pipe','pipe']});
  let buffer='',next=0,stderr='';const pending=new Map();child.stderr.on('data',part=>stderr+=part);child.stdin.on('error',()=>{});
  child.stdout.on('data',part=>{buffer+=part;let n;while((n=buffer.indexOf('\n'))>=0){const msg=JSON.parse(buffer.slice(0,n));buffer=buffer.slice(n+1);const item=pending.get(msg.id);if(item){pending.delete(msg.id);clearTimeout(item.timer);item.resolve(msg);}}});
  const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++next,timer=setTimeout(()=>{pending.delete(id);reject(new Error('MCP timeout '+stderr));},180000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
  return {rpc,raw:(name,args={})=>rpc('tools/call',{name,arguments:args}),async tool(name,args={}){const msg=await rpc('tools/call',{name,arguments:args});assert.equal(msg.error,undefined,JSON.stringify(msg.error));assert.notEqual(msg.result.isError,true,JSON.stringify(msg.result));return msg.result;},async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
function fixture(){
  const directory=mkdtempSync(path.join(tmpdir(),'dm-structure-mcp-')),source=path.join(directory,'copper.cif'),xyz=path.join(directory,'molecule.xyz');
  const made=spawnSync(python,['-c',"from ase.build import bulk; from ase.io import write; import sys; write(sys.argv[1],bulk('Cu','fcc',a=3.6,cubic=True),format='cif')",source],{encoding:'utf8'});assert.equal(made.status,0,made.stderr);
  writeFileSync(xyz,'3\nSynthetic XYZ, no declared cell\nC 0 0 0\nC 1 0 0\nO 1 1 0\n');
  return {directory,source,xyz,workspace:path.join(directory,'workspace')};
}
function picture(reply){const image=reply.content.find(block=>block.type==='image');assert.ok(image,'actual MCP image content must exist');assert.equal(image.mimeType,'image/png');assert.equal(Buffer.from(image.data,'base64').subarray(0,8).toString('hex'),'89504e470d0a1a0a');}

test('worker-boundary counterexamples cannot mix original request or requested object identities',async()=>{
  const spawnReply=result=>()=>{
    const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin=new PassThrough();
    child.stdin.once('finish',()=>queueMicrotask(()=>{child.stdout.write(JSON.stringify({ok:true,result}));child.emit('close',0);}));
    return child;
  };
  const object_id='a'.repeat(32),base={backend:'external-structure-workspace',state:'completed',object_id,request_id:'WRONG_REQUEST'};
  for(const name of ['structure_open','structure_result']){
    const manager=new StructureWorkspace({workspace:path.join(tmpdir(),'unused-identity-guard'),spawnProcess:spawnReply(base)});
    await assert.rejects(manager.call(name,{request_id:'ORIGINAL_REQUEST',...(name==='structure_open'?{source_path:'irrelevant.xyz'}:{})}),/different original request identity/);
    await manager.queue;
  }
  const manager=new StructureWorkspace({workspace:path.join(tmpdir(),'unused-object-guard'),spawnProcess:spawnReply({...base,object_id:'b'.repeat(32)})});
  await assert.rejects(manager.call('structure_info',{object_id}),/different requested object identity/);
});

test('structure catalog is typed, opt-in, refuses missing IDs/scripts before worker and accepts cell-freeXYZ observation',optionalEnvironment,async()=>{
  const f=fixture(),c=client(f.workspace);try{
    const tools=(await c.rpc('tools/list')).result.tools;for(const tool of structureTools){const entry=tools.find(t=>t.name===tool.name);assert.ok(entry,tool.name);assert.equal(entry.inputSchema.additionalProperties,false);}
    assert.equal((await c.raw('structure_open',{source_path:f.xyz})).error.code,-32602);
    assert.equal(existsSync(path.join(f.workspace,'structures')),false);
    assert.ok((await c.raw('structure_run_script',{script:'unsafe'})).error);
    assert.equal((await c.raw('structure_open',{source_path:f.xyz,request_id:'bad',script:'unsafe'})).error.code,-32602);
    const opened=unpack(await c.tool('structure_open',{source_path:f.xyz,request_id:'xyz'}));assert.equal(opened.cell_rank,0);assert.equal(opened.backend,'external-structure-workspace');assert.equal(opened.dm_called,false);
    const info=unpack(await c.tool('structure_info',{object_id:opened.object_id,include_atoms:true}));assert.deepEqual(info.atoms.positions_angstrom,[[0,0,0],[1,0,0],[1,1,0]]);
    const shown=await c.tool('structure_view',{object_id:opened.object_id,max_size:256,request_id:'xyz-view'});picture(shown);assert.equal(unpack(shown).projection_only,true);
    const measurement=unpack(await c.tool('structure_measure',{object_id:opened.object_id,kind:'angle',atom_indices:[0,1,2],request_id:'angle'}));assert.equal(measurement.measurement.value,90);
    const failure=await c.raw('structure_simulate',{object_id:opened.object_id,voltage_kv:200,euler_rzxz_deg:[0,0,0],reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,request_id:'missing-cell'});assert.equal(failure.result.isError,true);assert.match(failure.result.content[0].text,/periodic/);
  }finally{await c.close();rmSync(f.directory,{recursive:true,force:true});}
});

test('actual MCP ASE→diffsims→scientific capture→image PNG→fresh-client original result preserves source/science',optionalEnvironment,async()=>{
  const f=fixture();let c=client(f.workspace);try{
    const sourceBytes=readFileSync(f.source),opened=unpack(await c.tool('structure_open',{source_path:f.source,request_id:'cif'}));
    assert.equal(opened.cell_rank,3);assert.equal(opened.atom_count,4);
    const view=await c.tool('structure_view',{object_id:opened.object_id,rotation_deg_xyz:[15,25,0],max_size:256,request_id:'view'});picture(view);
    const derived=unpack(await c.tool('structure_derive',{object_id:opened.object_id,repeat:[2,1,1],request_id:'repeat'}));assert.equal(derived.atom_count,8);
    const spacing=unpack(await c.tool('structure_measure',{object_id:opened.object_id,kind:'d_spacing',hkls:[[2,0,0]],request_id:'d200'}));assert.ok(Math.abs(spacing.measurement.value-1.8)<1e-13);
    const direct=unpack(await c.tool('structure_measure',{object_id:opened.object_id,kind:'direction_angle',directions:[[1,0,0],[0,1,0]],request_id:'directions'}));assert.equal(direct.measurement.value,90);
    const zone=unpack(await c.tool('structure_measure',{object_id:opened.object_id,kind:'zone_relation',hkls:[[1,1,0]],directions:[[1,-1,0]],request_id:'zone'}));assert.equal(zone.measurement.zone_law_hu_kv_lw,0);assert.equal(zone.measurement.plane_contains_direction,true);
    const simulationMessage=await c.tool('structure_simulate',{object_id:opened.object_id,voltage_kv:200,euler_rzxz_deg:[0,0,0],reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,size:128,native_float32:true,request_id:'simulation'}),simulation=unpack(simulationMessage);picture(simulationMessage);
    assert.equal(simulation.phase_identified,false);assert.ok(simulation.reflection_count>0);assert.equal(simulation.dtype,'float64');assert.equal(simulation.native_float32_conversion.dtype,'float32');
    assert.match(simulation.rasterization.authority,/qualitative only/);assert.equal(simulation.native_float32_conversion.external_provenance.rasterization.sigma_pixels,1);
    const originalScience=readFileSync(simulation.array_path),converted=readFileSync(simulation.native_float32_path);
    const imported=unpack(await c.tool('image_open',{source_path:simulation.capture_path,source_kind:'capture',request_id:'import-simulation'}));assert.equal(imported.array_domain,'frequency');
    assert.deepEqual(readFileSync(imported.array_path),originalScience);
    const visible=await c.tool('image_preview',{object_id:imported.object_id,max_size:256,upscale:true,request_id:'simulation-view'});picture(visible);
    await c.close();c=client(f.workspace);const recovered=unpack(await c.tool('structure_result',{request_id:'simulation'}));assert.equal(recovered.object_id,simulation.object_id);assert.deepEqual(readFileSync(recovered.array_path),originalScience);
    const again=unpack(await c.tool('structure_open',{source_path:f.source,request_id:'cif'}));assert.equal(again.object_id,opened.object_id);
    assert.equal((await c.raw('structure_open',{source_path:f.xyz,request_id:'cif'})).result.isError,true);
    assert.deepEqual(readFileSync(f.source),sourceBytes);assert.deepEqual(readFileSync(simulation.native_float32_path),converted);
    assert.equal(simulation.software_provenance.diffsims,'0.7.0');assert.equal(simulation.parameters.native_float32,true);
  }finally{await c.close();rmSync(f.directory,{recursive:true,force:true});}
});

test('zone-axis MCP record drives the same view and actual diffsims laboratory coordinates',optionalEnvironment,async()=>{
  const f=fixture();let c=client(f.workspace);try{
    const bytes=readFileSync(f.source),opened=unpack(await c.tool('structure_open',{source_path:f.source,request_id:'zone-cif'}));
    const orientation=unpack(await c.tool('structure_orient',{object_id:opened.object_id,zone_axis_uvw:[1,1,0],in_plane_direction_uvw:[0,0,1],request_id:'zone-110'}));
    assert.equal(orientation.kind,'orient');assert.equal(orientation.orientation.structure_object_id,opened.object_id);
    const a=1/Math.sqrt(2),expected=[[0,0,1],[a,-a,0],[a,a,0]];
    orientation.orientation.rotation_matrix_cartesian.forEach((row,i)=>row.forEach((v,j)=>assert.ok(Math.abs(v-expected[i][j])<1e-14)));
    const initial=unpack(await c.tool('structure_info',{object_id:opened.object_id,include_atoms:true}));
    const message=await c.tool('structure_view',{object_id:opened.object_id,orientation_id:orientation.object_id,max_size:256,request_id:'zone-view'});picture(message);
    const view=unpack(message);assert.deepEqual(view.orientation,orientation.orientation);assert.equal(view.display_recipe.scientific_coordinates_modified,false);
    assert.deepEqual(unpack(await c.tool('structure_info',{object_id:view.object_id,include_atoms:true})).atoms,initial.atoms);
    const simulation=unpack(await c.tool('structure_simulate',{object_id:opened.object_id,orientation_id:orientation.object_id,voltage_kv:200,reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,size:64,request_id:'zone-simulation'}));
    assert.deepEqual(simulation.orientation,orientation.orientation);assert.ok(simulation.reflection_count>2);
    simulation.reflections.hkl.forEach(([h,k,l],i)=>{
      const expectedVector=[l/3.6,(h-k)*a/3.6,(h+k)*a/3.6];assert.equal(h+k,0);
      simulation.reflections.coordinates_inv_angstrom[i].forEach((v,j)=>assert.ok(Math.abs(v-expectedVector[j])<2e-14));
    });
    const double=await c.raw('structure_simulate',{object_id:opened.object_id,orientation_id:orientation.object_id,euler_rzxz_deg:[0,0,0],voltage_kv:200,reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,request_id:'double-rotation'});
    assert.equal(double.result.isError,true);assert.match(double.result.content[0].text,/exactly one/);
    assert.equal(existsSync(path.join(f.workspace,'structures','requests','double-rotation.json')),false);
    await c.close();c=client(f.workspace);const recovered=unpack(await c.tool('structure_result',{request_id:'zone-110'}));assert.equal(recovered.object_id,orientation.object_id);assert.deepEqual(recovered.orientation,orientation.orientation);
    assert.deepEqual(readFileSync(f.source),bytes);
  }finally{await c.close();rmSync(f.directory,{recursive:true,force:true});}
});

test('actual MCP compares sourced FFT peak measurements with unrastered simulated reflections without changing calibration',optionalEnvironment,async()=>{
  const f=fixture(),c=client(f.workspace),tiff=path.join(f.directory,'known-periods.tiff');try{
    const code="import numpy as np,tifffile,sys; y,x=np.indices((16,16)); a=np.rint(1000+100*np.cos(2*np.pi*x/4)+100*np.cos(2*np.pi*y/4)).astype(np.uint16); tifffile.imwrite(sys.argv[1],a,photometric='minisblack')";
    const made=spawnSync(python,['-c',code,tiff],{encoding:'utf8'});assert.equal(made.status,0,made.stderr);
    const source=readFileSync(tiff),opened=unpack(await c.tool('structure_open',{source_path:f.source,request_id:'comparison-cif'}));
    const oriented=unpack(await c.tool('structure_orient',{object_id:opened.object_id,zone_axis_uvw:[0,0,1],in_plane_direction_uvw:[1,0,0],request_id:'comparison-001'}));
    const sim=unpack(await c.tool('structure_simulate',{object_id:opened.object_id,orientation_id:oriented.object_id,voltage_kv:200,reciprocal_radius_inv_angstrom:1.3,max_excitation_error_inv_angstrom:.02,size:64,request_id:'comparison-simulation'}));
    const sequence=unpack(await c.tool('image_open',{source_path:tiff,source_kind:'tiff',request_id:'comparison-open-image'}));
    const frame=unpack(await c.tool('image_frame',{object_id:sequence.object_id,frame_index:0,request_id:'comparison-frame'}));
    const cal=unpack(await c.tool('image_calibrate',{object_id:frame.object_id,scope:'image',xy_scale:{x:.045,y:.045,unit:'nm'},source_text:'Synthetic independent scale: a four-pixel period equals1.8Angstrom, no experimental calibration inferred',request_id:'comparison-calibration'}));
    const fft=unpack(await c.tool('image_fft',{object_id:cal.object_id,rect:[0,0,16,16],window:'none',subtract_mean:true,request_id:'comparison-fft'}));
    const m1=unpack(await c.tool('image_measure',{object_id:fft.object_id,coordinate_space:'frequency_cycles_per_pixel',points:[[0,0],[.25,0]],request_id:'comparison-peak-x'}));
    const m2=unpack(await c.tool('image_measure',{object_id:fft.object_id,coordinate_space:'frequency_cycles_per_pixel',points:[[0,0],[0,.25]],request_id:'comparison-peak-y'}));
    const old=[readFileSync(m1.manifest_path),readFileSync(m2.manifest_path)],science=readFileSync(fft.array_path);
    const result=unpack(await c.tool('structure_compare',{object_id:sim.object_id,measurement_paths:[m1.manifest_path,m2.manifest_path],experimental_kind:'real_space_fft',registration:{rotation_deg:0,scale:1,translation_inv_angstrom:[0,0],flip_y:false,basis:'Synthetic common XY convention; identity is supplied, not automatically fitted'},max_residual_inv_angstrom:1e-12,correspondences:[{measurement_index:0,hkl:[2,0,0]},{measurement_index:1,hkl:[0,2,0]}],request_id:'comparison-geometric'}));
    assert.equal(result.all_experimental_reflections_matched_within_tolerance,true);assert.equal(result.matched.length,2);assert.equal(result.phase_identified,false);assert.equal(result.intensity_comparison_performed,false);
    assert.equal(result.registration.experimental_calibration_modified,false);assert.equal(result.registration.registration_verified,false);
    assert.equal(result.observations[0].calibration_dependency.calibration_id,cal.object_id);
    for(const match of result.matched){assert.ok(match.position_residual_inv_angstrom<1e-14);assert.ok(Math.abs(match.experiment_original_projected_period_angstrom-1.8)<1e-14);}
    assert.equal(result.pairwise_angles[0].experimental_registered_signed_angle_deg,90);
    assert.deepEqual([readFileSync(m1.manifest_path),readFileSync(m2.manifest_path)],old);assert.deepEqual(readFileSync(fft.array_path),science);assert.deepEqual(readFileSync(tiff),source);
    const recovered=unpack(await c.tool('structure_result',{request_id:'comparison-geometric'}));assert.equal(recovered.object_id,result.object_id);assert.deepEqual(recovered.matched,result.matched);
  }finally{await c.close();rmSync(f.directory,{recursive:true,force:true});}
});

test('accepted external structure wait cancellation recovers the same object without a second write',optionalEnvironment,async()=>{
  const f=fixture(),workspace=path.join(f.directory,'cancel-workspace'),marker=path.join(f.directory,'accepted'),worker=path.join(f.directory,'slow-worker.py');
  const code=`import sys,time\nfrom pathlib import Path\nsys.path.insert(0,${JSON.stringify(root)})\nfrom crystallography import structure_tools as st\nfrom tools import structure_worker\noriginal=st.StructureWorkspace.action\ndef delayed(self,request):\n    Path(${JSON.stringify(marker)}).write_text('accepted')\n    time.sleep(0.4)\n    return original(self,request)\nst.StructureWorkspace.action=delayed\nraise SystemExit(structure_worker.main())\n`;
  writeFileSync(worker,code);const manager=new StructureWorkspace({workspace,python,workerPath:worker});const controller=new AbortController();
  try{
    const waiting=manager.call('structure_open',{source_path:f.xyz,request_id:'cancelled-open'},controller.signal),outcome=waiting.then(value=>({value}),error=>({error}));
    const deadline=Date.now()+30000;while(!existsSync(marker)){assert.ok(Date.now()<deadline,'worker must durably accept original request');await sleep(20);}
    const journal=JSON.parse(readFileSync(path.join(workspace,'requests','cancelled-open.json')));assert.equal(journal.state,'prepared');controller.abort();assert.match((await outcome).error.message,/Stopped waiting/);
    await manager.queue;
    const recovered=unpack(await new StructureWorkspace({workspace,python}).call('structure_result',{request_id:'cancelled-open'}));assert.equal(recovered.kind,'structure');assert.equal(readdirSync(path.join(workspace,'objects')).length,1);
    const original=unpack(await manager.call('structure_open',{source_path:f.xyz,request_id:'cancelled-open'}));assert.equal(original.object_id,recovered.object_id);assert.equal(readdirSync(path.join(workspace,'objects')).length,1);
  }finally{await manager.queue;rmSync(f.directory,{recursive:true,force:true});}
});
