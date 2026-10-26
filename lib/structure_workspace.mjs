// Optional external ASE/diffsims tools. Never a DM/native fallback.
import {spawn} from 'node:child_process';
import {readFileSync,realpathSync,statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const id={type:'string',pattern:'^[a-f0-9]{32}$',minLength:32,maxLength:32};
const request={type:'string',pattern:'^[A-Za-z0-9_-]+$',minLength:1,maxLength:64,description:'Save before submission. After timeout/cancellation query structure_result using this original ID; never automatically repeat an unknown operation.'};
const degrees={type:'array',minItems:3,maxItems:3,items:{type:'number',minimum:-360,maximum:360}};
const make=(name,description,properties,required)=>({name,description,inputSchema:{type:'object',additionalProperties:false,properties,required}});
const write=(name,description,properties,required)=>make(name,description,{...properties,request_id:request},[...required,'request_id']);
export const structureTools=[
  write('structure_open','Read one bounded user-selected CIF1 or XYZ/extXYZ using ASE into a fixed hashed copy, preserving generic/nonorthogonal cells and atomic positions. No FCC/BCC/HCP or phase inference, no calculator/network/DM. Cell-free XYZ can be viewed/measured but not simulated.',{source_path:{type:'string',minLength:1}},['source_path']),
  make('structure_info','Inspect a saved immutable structure/view/measurement/simulation. include_atoms returns finite Cartesian Angstrom positions, exact cell and PBC for a mature viewer; it does not classify a phase.',{object_id:id,include_atoms:{type:'boolean'}},['object_id']),
  write('structure_view','Return an ASE plot_atoms projection PNG from the exact structure snapshot, retaining atom/cell identity. Camera rotation changes display only; this PNG is a 2D projection. interactive=true also requests the separately configured mature3D browser viewer; unavailable must be reported explicitly, never relabel the PNG as3D.',{object_id:id,rotation_deg_xyz:degrees,max_size:{type:'integer',minimum:128,maximum:1024},interactive:{type:'boolean'}},['object_id']),
  write('structure_measure','Use ASE atomic/cell geometry for atomic distance/angle/dihedral, plane d-spacing, reciprocal HKL angle, direct UVW direction_angle or plane/direction zone_relation. Atom indices are zero-based; MIC requires a declared periodic cell. Crystal metrics require full-rank cell. directions are three-index UVW in the exact cell basis, never four-index Miller-Bravais. zone_relation takes one HKL and one UVW, reports exact hu+kv+lw and angles; no experiment orientation/phase proof.',{object_id:id,kind:{type:'string',enum:['distance','angle','dihedral','d_spacing','reciprocal_angle','direction_angle','zone_relation']},atom_indices:{type:'array',minItems:2,maxItems:4,items:{type:'integer',minimum:0,maximum:4095}},hkls:{type:'array',minItems:1,maxItems:2,items:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:-32,maximum:32}}},directions:{type:'array',minItems:1,maxItems:2,items:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:-32,maximum:32}}},mic:{type:'boolean'}},['object_id','kind']),
  write('structure_derive','Create an independent bounded ASE repeat/active Cartesian rotation of positions and cell. Repeat and rotation never modify the source snapshot or input file. Rotation is x then y then z about the Cartesian origin; distinct from simulation RZXZ orientation.',{object_id:id,repeat:{type:'array',minItems:3,maxItems:3,items:{type:'integer',minimum:1,maximum:32}},rotation_deg_xyz:degrees},['object_id']),
  write('structure_simulate','Run actual diffsims kinematic electron diffraction on the exact periodic structure: explicit voltage, RZXZ Euler orientation, reciprocal cutoff and excitation-error cutoff. Return reflections/intensities and a library-rasterized qualitative relative-intensity image, PNG and existing schema1 scientific NPY capture. Optional native_float32=true adds a SECOND explicit conversion with error/hash sidecar (size<=128), retaining original float64. No dynamical/multislice/image-contrast simulation or unique phase assertion. Full occupancy is required; the pinned library index box must pass an analytic completeness certificate or UNQUALIFIED_ENUMERATION is returned (some skew cells/cutoffs are refused). Missing-cell XYZ remains viewable but is refused here.',{object_id:id,voltage_kv:{type:'number',minimum:20,maximum:400},euler_rzxz_deg:degrees,reciprocal_radius_inv_angstrom:{type:'number',minimum:.05,maximum:5},max_excitation_error_inv_angstrom:{type:'number',minimum:.00001,maximum:.2},size:{type:'integer',minimum:64,maximum:512},sigma_pixels:{type:'number',minimum:.2,maximum:8},with_direct_beam:{type:'boolean'},native_float32:{type:'boolean',description:'Explicit additional boundedfloat32 handoff for a separately qualified native import. Requires size<=128. Original scientificfloat64 NPY remains unchanged; conversion error and both hashes are recorded.'}},['object_id','voltage_kv','euler_rzxz_deg','reciprocal_radius_inv_angstrom','max_excitation_error_inv_angstrom']),
  make('structure_result','Query an original pre-saved structure request without recomputation. Incomplete/unreadable is unknown, never automatic retry. Completed objects and scientific files are hash-checked.',{request_id:request},['request_id']),
];
export const STRUCTURE_INSTRUCTIONS='structure_* is an optional external ASE/diffsims companion in an independent Python environment, never inside GMS or a fallback for dm_* failures. Open explicit CIF/XYZ once and retain its fixed snapshot ID. Generic cells and cell-free XYZ are valid for observation; crystal metrics need a full-rank cell and electron diffraction requires declared periodicity. XYZ positions use ASE Angstrom convention, not independent physical-unit verification. Use actual atom indices, supplied HKLs or three-index UVW in the exact cell basis, never inferred image indices or four-index Miller-Bravais. Simulations use explicit voltage/RZXZ orientation/excitation/radius and the kinematic approximation. The pinned library reciprocal enumeration must pass an analytic completeness certificate in the exact supplied basis; uncertified skew-cell/cutoff cases are explicitly refused, not silently reduced or incompletely simulated. Use unrastered reflection coordinates/intensities for numeric comparison: the library qualitative raster quantizes centers, overwrites coincident integer centers rather than summing, applies Gaussian sigma and normalizes its maximum. It is not experimental counts, phase fractions, HRTEM contrast or dynamical scattering. Scientific simulation capture_path can be explicitly imported by image_open(source_kind=capture) for shared observation; that import is external data handoff, not DM computation. Save every mutating request_id before dispatch, recover via structure_result, preserve original files and immutable arrays.';
const actions={structure_open:'open',structure_info:'get',structure_view:'view',structure_measure:'measure',structure_derive:'derive',structure_simulate:'simulate',structure_result:'result'};

export class StructureWorkspace {
  constructor({workspace,python=process.env.DM_STRUCTURE_PYTHON||'python',timeoutMs=180000,workerPath=fileURLToPath(new URL('../tools/structure_worker.py',import.meta.url)),spawnProcess=spawn}={}){
    if(!workspace||!path.isAbsolute(workspace))throw new Error('DM_STRUCTURE_WORKSPACE must be an absolute configured independent output directory');
    this.workspace=path.resolve(workspace);this.python=python;this.timeoutMs=timeoutMs;this.workerPath=workerPath;this.spawn=spawnProcess;this.queue=Promise.resolve();
  }
  call(name,args={},signal){
    const action=actions[name];if(!action)throw new Error('Unknown external structure tool');
    const payload={...args,workspace:this.workspace,action};
    if(action==='result'){payload.query_request_id=payload.request_id;delete payload.request_id;}
    if(action==='get'||action==='result')return this.run(payload,signal);
    let resolve,reject,started=false;const waiting=new Promise((a,b)=>{resolve=a;reject=b;});
    const abort=()=>{if(!started)reject(new Error('Cancelled while queued; structure operation was not started'));};
    signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
    const begin=()=>{started=true;signal?.removeEventListener('abort',abort);const work=this.run(payload,signal);work.then(resolve,reject);return work.workerDone??work.catch(()=>{});};
    this.queue=this.queue.then(begin,begin).catch(reject);return waiting;
  }
  run(payload,signal){
    if(signal?.aborted)return Promise.reject(new Error('Cancelled before structure operation submission'));
    const raw=JSON.stringify(payload);if(Buffer.byteLength(raw)>256*1024)throw new Error('Structure request exceeds256KiB');
    let finishWorker;const workerDone=new Promise(resolve=>finishWorker=resolve);
    const waiting=new Promise((resolve,reject)=>{
      let child;try{child=this.spawn(this.python,['-B',this.workerPath],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,MPLBACKEND:'Agg',NUMBA_NUM_THREADS:'1',OPENBLAS_NUM_THREADS:'1'}});}catch(error){finishWorker();reject(error);return;}
      let settled=false,bytes=0,stderr='';const chunks=[],hint='Query structure_result with the original request_id; do not automatically resubmit.';
      const finish=(fn,value)=>{if(!settled){settled=true;signal?.removeEventListener('abort',abort);fn(value);}};
      const abort=()=>finish(reject,new Error('Stopped waiting; external structure operation may still finish. '+hint));
      signal?.addEventListener('abort',abort,{once:true});
      const timer=setTimeout(()=>finish(reject,new Error('Structure worker deadline; it may still finish. '+hint)),this.timeoutMs);
      child.stdout.on('data',part=>{bytes+=part.length;if(bytes>4*1024*1024)finish(reject,new Error('Structure response exceeds4MiB; '+hint));else chunks.push(part);});
      child.stderr.on('data',part=>{if(stderr.length<8192)stderr+=part;});
      child.once('error',error=>{clearTimeout(timer);finishWorker();finish(reject,new Error('Independent structure Python could not start: '+error.message));});
      child.stdin.on('error',error=>finish(reject,new Error('Structure worker input failed: '+error.message+'. '+hint)));
      child.once('close',code=>{clearTimeout(timer);finishWorker();if(settled)return;try{
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
      child.stdin.end(raw);if(signal?.aborted)abort();
    });
    waiting.workerDone=workerDone;return waiting;
  }
}
