// Optional external ASE/diffsims tools. Never a DM/native fallback.
import {spawn} from 'node:child_process';
import {readFileSync,realpathSync,statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ExecutionCoordinator} from './runtime/execution_coordinator.mjs';

const id={type:'string',pattern:'^[a-f0-9]{32}$',minLength:32,maxLength:32};
const request={type:'string',pattern:'^[A-Za-z0-9_-]+$',minLength:1,maxLength:64,description:'Save before submission. After timeout/cancellation query structure_result using this original ID; never automatically repeat an unknown operation.'};
const degrees={type:'array',minItems:3,maxItems:3,items:{type:'number',minimum:-360,maximum:360}};
const direction={type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:-32,maximum:32}};
const measurementPaths={type:'array',minItems:1,maxItems:32,items:{type:'string',minLength:1}};
const correspondence={type:'object',additionalProperties:false,required:['measurement_index','hkl'],properties:{measurement_index:{type:'integer',minimum:0,maximum:31},hkl:direction}};
const correspondences={type:'array',minItems:0,maxItems:32,items:correspondence};
const residualTolerance={type:'number',minimum:1e-12,maximum:1};
const experimentalKind={type:'string',enum:['real_space_fft','saed','other_diffraction']};
const make=(name,description,properties,required)=>({name,description,inputSchema:{type:'object',additionalProperties:false,properties,required}});
const write=(name,description,properties,required)=>make(name,description,{...properties,request_id:request},[...required,'request_id']);
export const structureTools=[
  write('structure_open','Read one bounded user-selected CIF1 or XYZ/extXYZ using ASE into a fixed hashed copy, preserving generic/nonorthogonal cells and atomic positions. No FCC/BCC/HCP or phase inference, no calculator/network/DM. Cell-free XYZ can be viewed/measured but not simulated.',{source_path:{type:'string',minLength:1}},['source_path']),
  make('structure_info','Inspect a saved immutable structure/view/measurement/simulation. include_atoms returns finite Cartesian Angstrom positions, exact cell and PBC for a mature viewer; it does not classify a phase.',{object_id:id,include_atoms:{type:'boolean'}},['object_id']),
  write('structure_view','Return an ASE plot_atoms projection PNG from the exact structure snapshot. Choose shared orientation_id or legacy display rotation_deg_xyz, never both. The orientation rotates a display copy into the same laboratory frame as diffsims; source coordinates stay immutable. interactive=true also requests the configured mature3D browser viewer; inspect its applied-orientation status, never relabel the PNG as3D.',{object_id:id,orientation_id:id,rotation_deg_xyz:degrees,max_size:{type:'integer',minimum:128,maximum:1024},interactive:{type:'boolean'}},['object_id']),
  write('structure_measure','Use ASE atomic/cell geometry for atomic distance/angle/dihedral, plane d-spacing, reciprocal HKL angle, direct UVW direction_angle or plane/direction zone_relation. Atom indices are zero-based; MIC requires a declared periodic cell. Crystal metrics require full-rank cell. directions are three-index UVW in the exact cell basis, never four-index Miller-Bravais. zone_relation takes one HKL and one UVW, reports exact hu+kv+lw and angles; no experiment orientation/phase proof.',{object_id:id,kind:{type:'string',enum:['distance','angle','dihedral','d_spacing','reciprocal_angle','direction_angle','zone_relation']},atom_indices:{type:'array',minItems:2,maxItems:4,items:{type:'integer',minimum:0,maximum:4095}},hkls:{type:'array',minItems:1,maxItems:2,items:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:-32,maximum:32}}},directions:{type:'array',minItems:1,maxItems:2,items:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:-32,maximum:32}}},mic:{type:'boolean'}},['object_id','kind']),
  write('structure_derive','Create an independent bounded ASE repeat/active rotation of positions and cell. Choose orientation_id for the shared source-to-laboratory matrix, or legacy rotation_deg_xyz (x then y then z). Never both; no source overwrite. Applying an orientation produces a new scientific structure; later simulation of that derived structure must not silently reapply the old orientation.',{object_id:id,repeat:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:1,maximum:32}},orientation_id:id,rotation_deg_xyz:degrees},['object_id']),
  write('structure_simulate','Run actual diffsims kinematic electron diffraction on the exact periodic structure: explicit voltage, reciprocal cutoff and excitation-error cutoff, plus exactly one of shared orientation_id or legacy euler_rzxz_deg. A shared orientation is verified against the exact structure and the pinned engine matrix; no language-guessed Euler angles. Return authoritative unrastered reflections/HKL/intensities, qualitative raster, PNG and schema1 NPY. Optional native_float32=true adds a SECOND explicit conversion with error/hash sidecar (size<=128). No dynamical/multislice/image-contrast simulation or unique phase assertion. Full occupancy and the existing reciprocal-enumeration certificate are required; uncertified skew cases return UNQUALIFIED_ENUMERATION without substituting a basis or simulator.',{object_id:id,voltage_kv:{type:'number',minimum:20,maximum:400},orientation_id:id,euler_rzxz_deg:degrees,reciprocal_radius_inv_angstrom:{type:'number',minimum:.05,maximum:5},max_excitation_error_inv_angstrom:{type:'number',minimum:.00001,maximum:.2},size:{type:'integer',minimum:64,maximum:512},sigma_pixels:{type:'number',minimum:.2,maximum:8},with_direct_beam:{type:'boolean'},native_float32:{type:'boolean',description:'Explicit additional boundedfloat32 handoff for a separately qualified native import. Requires size<=128. Original scientificfloat64 NPY remains unchanged; conversion error and both hashes are recorded.'}},['object_id','voltage_kv','reciprocal_radius_inv_angstrom','max_excitation_error_inv_angstrom']),
  make('structure_result','Query an original pre-saved structure request without recomputation. Incomplete/unreadable is unknown, never automatic retry. Completed objects and scientific files are hash-checked.',{request_id:request},['request_id']),
  write('structure_orient','Create an immutable reusable orientation from a three-index direct-lattice zone_axis_uvw in the exact supplied cell. Optionally choose in_plane_direction_uvw (projected onto the beam-normal plane) and in_plane_rotation_deg. Maps the positive zone direction to laboratory +Z with a proper right-handed matrix; default roll uses the Cartesian axis least parallel to the beam and is recorded. Reuse returned orientation_id in structure_view/structure_simulate; camera dragging never changes this scientific record.',{object_id:id,zone_axis_uvw:direction,in_plane_direction_uvw:direction,in_plane_rotation_deg:{type:'number',minimum:-360,maximum:360}},['object_id','zone_axis_uvw']),
  write('structure_register','Propose a deterministic proper in-plane rotation from explicitly confirmed experiment/HKL correspondences. Independent experimental scale stays 1, translation 0 and declared screen flip fixed. Requires a selected current image revision. Separate fitting and held-out reflections; no held-out observations means NOT_VALIDATED. This is an external geometric proposal, not a centre correction, intensity comparison or phase proof. Save the returned registration object for structure_compare.',{object_id:id,measurement_paths:measurementPaths,current_image_object_id:id,fit_correspondences:{...correspondences,minItems:2},validation_correspondences:correspondences,screen_axes:{type:'object',additionalProperties:false,required:['flip_y','basis'],properties:{flip_y:{type:'boolean'},basis:{type:'string',minLength:1,maxLength:500}}},confirmation:{type:'object',additionalProperties:false,required:['source','source_text'],properties:{source:{type:'string',enum:['user_confirmed','synthetic_fixture']},source_text:{type:'string',minLength:1,maxLength:1000}}},experimental_kind:experimentalKind,max_residual_inv_angstrom:residualTolerance},['object_id','measurement_paths','current_image_object_id','fit_correspondences','screen_axes','confirmation','experimental_kind','max_residual_inv_angstrom']),
  write('structure_compare','Compare committed reciprocal image_measure/image_remeasure records to saved unrastered simulated reflections. Choose explicit registration or a saved registration_object_id; never both. continue_current requires current_image_object_id and rejects old centre/scale/grid evidence. Historical review is explicit and is not a fresh DM observation. previous_comparison_id links immutable revisions; a changed capture/frame/ROI additionally requires source_change_basis. Preserve unmatched candidates and fit-versus-validation evidence; do not identify a unique phase or compare FFT/SAED intensities.',{object_id:id,measurement_paths:measurementPaths,experimental_kind:experimentalKind,registration:{type:'object',additionalProperties:false,required:['rotation_deg','scale','translation_inv_angstrom','flip_y','basis'],properties:{rotation_deg:{type:'number',minimum:-360,maximum:360},scale:{type:'number',minimum:1e-6,maximum:1e6},translation_inv_angstrom:{type:'array',minItems:2,maxItems:2,items:{type:'number',minimum:-1e6,maximum:1e6}},flip_y:{type:'boolean'},basis:{type:'string',minLength:1,maxLength:2000}}},registration_object_id:id,current_image_object_id:id,analysis_mode:{type:'string',enum:['continue_current','historical_review']},previous_comparison_id:id,source_change_basis:{type:'string',minLength:1,maxLength:2000},max_residual_inv_angstrom:residualTolerance,correspondences},['object_id','measurement_paths','experimental_kind','max_residual_inv_angstrom']),
];
structureTools.find(tool=>tool.name==='structure_simulate').inputSchema.oneOf=[
  {required:['orientation_id'],not:{required:['euler_rzxz_deg']}},
  {required:['euler_rzxz_deg'],not:{required:['orientation_id']}},
];
structureTools.find(tool=>tool.name==='structure_compare').inputSchema.oneOf=[
  {required:['registration'],not:{required:['registration_object_id']}},
  {required:['registration_object_id'],not:{required:['registration']}},
];
export const STRUCTURE_INSTRUCTIONS='structure_* is an optional external ASE/diffsims companion in an independent Python environment, never inside GMS or a fallback for dm_* failures. Open explicit CIF/XYZ once and retain its fixed snapshot ID. Generic cells and cell-free XYZ are valid for observation; crystal metrics need a full-rank cell and electron diffraction requires declared periodicity. XYZ positions use ASE Angstrom convention, not independent physical-unit verification. Use actual atom indices, supplied HKLs or three-index UVW in the exact cell basis, never inferred image indices or four-index Miller-Bravais. Use structure_orient with the exact three-index zone direction to create an immutable shared matrix; reuse orientation_id for structure_view and structure_simulate. Do not guess Euler angles or confuse a camera drag with scientific orientation. Simulations use explicit voltage, shared orientation_id or legacy RZXZ angles, excitation/radius and the kinematic approximation. The pinned library reciprocal enumeration must pass an analytic completeness certificate in the exact supplied basis; uncertified skew-cell/cutoff cases are explicitly refused, not silently reduced or incompletely simulated. Use unrastered reflection coordinates/intensities for numeric comparison: the library qualitative raster quantizes centers, overwrites coincident integer centers rather than summing, applies Gaussian sigma and normalizes its maximum. It is not experimental counts, phase fractions, HRTEM contrast or dynamical scattering. Scientific simulation capture_path can be explicitly imported by image_open(source_kind=capture) for shared observation; that import is external data handoff, not DM computation. structure_compare accepts committed image_measure manifest paths with active sourced reciprocal/DC geometry plus explicit caller registration; it fixes evidence bytes/hashes, never fits or changes experimental calibration, retains unmatched and ambiguous reflection candidates, and does not compare FFT/SAED intensities or identify a phase. Remeasure after calibration correction or withdrawal; old measurements remain historical. Use image_center and image_remeasure before continuing after centre/scale/point corrections; never recompute unchanged complex FFT arrays or silently reuse old measurements. structure_register estimates only proper in-plane rotation from confirmed correspondences with fixed experimental scale, zero translation and explicitly fixed screen-axis parity. Fit points are not held-out validation; absent independent reflections means NOT_VALIDATED. Use structure_compare with current_image_object_id to bind current geometry, or analysis_mode=historical_review for saved evidence. previous_comparison_id links versions without a global current-state database; DM editing requires a new capture. Save every scientific-worker request_id before dispatch and recover it via structure_result. Viewer closure has a separate request namespace: recover structure_viewer_close with that same tool and its original request_id and view object_id. Preserve original files and immutable arrays.';
const actions={structure_open:'open',structure_info:'get',structure_view:'view',structure_measure:'measure',structure_derive:'derive',structure_simulate:'simulate',structure_result:'result',structure_orient:'orient',structure_compare:'compare',structure_register:'register'};

export class StructureWorkspace {
  constructor({workspace,python=process.env.DM_STRUCTURE_PYTHON||'python',timeoutMs=180000,workerPath=fileURLToPath(new URL('../tools/structure_worker.py',import.meta.url)),spawnProcess=spawn,coordinator=new ExecutionCoordinator()}={}){
    if(!workspace||!path.isAbsolute(workspace))throw new Error('DM_STRUCTURE_WORKSPACE must be an absolute configured independent output directory');
    this.workspace=path.resolve(workspace);this.python=python;this.timeoutMs=timeoutMs;this.workerPath=workerPath;this.spawn=spawnProcess;this.coordinator=coordinator;
    this.resourceKey='structure-workspace:'+this.workspace;
    this.requestScope=Object.freeze({provider:'external-structure-workspace',workspace:this.workspace,session:'workspace-journal-v1'});
  }
  // Compatibility drain only. The Coordinator owns the one write queue.
  get queue(){return this.coordinator.whenIdle(this.resourceKey);}
  call(name,args={},signal){
    const action=actions[name];if(!action)throw new Error('Unknown external structure tool');
    if(action==='simulate'&&Object.hasOwn(args,'orientation_id')===Object.hasOwn(args,'euler_rzxz_deg'))throw new Error('Choose exactly one of orientation_id or euler_rzxz_deg before starting the structure worker');
    const payload={...args,workspace:this.workspace,action};
    if(action==='result'){payload.query_request_id=payload.request_id;delete payload.request_id;}
    const readonly=action==='get'||action==='result';
    const spec={operation:name,requestId:readonly?(action==='result'?args.request_id:null):args.request_id,
      requestScope:this.requestScope,parameters:payload,resourceKeys:readonly?[]:[this.resourceKey],lane:readonly?'query':'work',timeoutMs:this.timeoutMs};
    const start=accepted=>{const work=this.run(accepted);return {result:work,closed:work.workerDone};};
    const messages={queued:'Cancelled while queued; structure operation was not started',
      cancelled:'Stopped waiting; external structure operation may still finish. Query structure_result with the original request_id; do not automatically resubmit.',
      timeout:'Structure worker deadline; it may still finish. Query structure_result with the original request_id; do not automatically resubmit.'};
    return action==='result'
      ? this.coordinator.recover(spec,{query:start,messages},{signal})
      : this.coordinator.invoke(spec,{start,messages},{signal});
  }
  run(payload){
    const raw=JSON.stringify(payload);if(Buffer.byteLength(raw)>256*1024)throw new Error('Structure request exceeds256KiB');
    let finishWorker;const workerDone=new Promise(resolve=>finishWorker=resolve);
    const waiting=new Promise((resolve,reject)=>{
      let child;try{child=this.spawn(this.python,['-B',this.workerPath],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,MPLBACKEND:'Agg',NUMBA_NUM_THREADS:'1',OPENBLAS_NUM_THREADS:'1'}});}catch(error){finishWorker();reject(error);return;}
      let settled=false,bytes=0,stderr='';const chunks=[],hint='Query structure_result with the original request_id; do not automatically resubmit.';
      const finish=(fn,value)=>{if(!settled){settled=true;fn(value);}};
      child.stdout.on('data',part=>{bytes+=part.length;if(bytes>4*1024*1024)finish(reject,new Error('Structure response exceeds4MiB; '+hint));else chunks.push(part);});
      child.stderr.on('data',part=>{if(stderr.length<8192)stderr+=part;});
      // A process/pipe error is not proof that a spawned worker is gone.
      // Only actual close releases the Coordinator resource/capacity slot.
      child.once('error',error=>finish(reject,new Error('Independent structure Python could not start: '+error.message)));
      child.stdin.on('error',error=>finish(reject,new Error('Structure worker input failed: '+error.message+'. '+hint)));
      child.once('close',code=>{finishWorker();if(settled)return;try{
        const reply=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(code!==0||reply.ok!==true)throw new Error((typeof reply.error==='object'?`${reply.error.code}: ${reply.error.message}`:reply.error)||stderr||'Structure worker failed');
        const result=reply.result;if(!result||result.backend!=='external-structure-workspace'||result.state!=='completed')throw new Error('Structure worker did not return completed external provenance');
        if(payload.action==='get'){
          if(result.object_id!==payload.object_id)throw new Error('Structure worker returned a different requested object identity');
        }else if(result.request_id!==(payload.action==='result'?payload.query_request_id:payload.request_id)){
          throw new Error('Structure worker returned a different original request identity; '+hint);
        }
        const content=[{type:'text',text:JSON.stringify(result,null,2)}];
        if(result.image_path){const root=realpathSync.native(this.workspace),file=realpathSync.native(result.image_path),relative=path.relative(root,file);if(relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative)||statSync(file).size>2*1024*1024)throw new Error('Structure PNG escapes workspace or inline budget');const png=readFileSync(file);if(png.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')throw new Error('Structure image is not PNG');content.push({type:'image',mimeType:'image/png',data:png.toString('base64')});}
        finish(resolve,{content});
      }catch(error){finish(reject,error);}});
      child.stdin.end(raw);
    });
    waiting.workerDone=workerDone;return waiting;
  }
}
