// Explicit external image tools. No DM connection or native fallback lives here.
import {spawn} from 'node:child_process';
import {readFileSync, realpathSync, statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const id = {type:'string', minLength:1, maxLength:80, pattern:'^[A-Za-z0-9_-]+$'};
const requestId = {...id, maxLength:64, description:'Save this ID before submission; query image_result after timeout/cancellation. Reusing it with different parameters is rejected.'};
const annotationId = {...id, maxLength:64, description:'Stable label identity reused across overlay revisions; distinct from operation request_id and not an image_result query ID.'};
const rect = {type:'array',items:{type:'integer',minimum:0},minItems:4,maxItems:4,description:'Half-open source pixel edges [x0,y0,x1,y1], no clipping.'};
const display = {display_range:{type:['array','null'],items:{type:'number'},minItems:2,maxItems:2,description:'Explicit display limits; image_preview inherits an existing view when omitted. New frames/comparisons or null use auto-range.'},gamma:{type:'number',minimum:0.05,maximum:20},max_size:{type:'integer',minimum:32,maximum:1024}};
const metadata = {type:'object',additionalProperties:false,properties:{
  reconstruction_type:{type:['string','null'],maxLength:500},data_meaning:{type:['string','null'],maxLength:500},frame_meaning:{type:['string','null'],maxLength:500},
  xy_scale:{type:['object','null'],additionalProperties:false,properties:{x:{type:'number'},y:{type:'number'},unit:{type:'string',maxLength:40},source:{type:'string',maxLength:1000}},required:['x','y','unit','source']},
  value_unit:{type:['string','null'],maxLength:100},
  frame_scale:{type:['object','null'],additionalProperties:false,properties:{origin:{type:'number'},step:{type:'number'},unit:{type:'string',maxLength:40},source:{type:'string',maxLength:1000}},required:['origin','step','unit','source']},
  source_text:{type:['string','null'],maxLength:2000}}};
const make=(name,description,properties,required)=>({name,description,inputSchema:{type:'object',properties,required,additionalProperties:false}});
const write=(name,description,properties,required)=>make(name,description,{...properties,request_id:requestId},[...required,'request_id']);
export const imageTools=[
  write('image_open','Open an explicit TIFF read-only outside DM; inspect pages without decoding the whole stack. Or import an existing verified DM numerical capture. No scale, phase unit or depth is inferred.',{source_path:{type:'string',minLength:1},source_kind:{type:'string',enum:['tiff','capture']}},['source_path']),
  make('image_info','Inspect a saved image/view/context object without running analysis.',{object_id:id},['object_id']),
  write('image_frame','Select an explicit zero-based TIFF frame, preserving raw dtype and source identity in an independent NPY. This is external TIFF I/O, not a DM native operation.',{object_id:id,frame_index:{type:'integer',minimum:0}},['object_id','frame_index']),
  write('image_preview','Render an image/ROI, annotated view or saved comparison; re-render a saved external FFT without recomputing it. Anchored annotations follow size/display changes. Omitted display limits/gamma/size inherit; null range recalculates. FFT representation changes reset only range; FFT/comparison rect is unsupported. PNG is display-only.',{object_id:id,rect,...display,spectrum_axes:{type:'boolean',description:'Label signed fx/fy axes in cycles/pixel on the FFT display; max_size>=256. No physical scale inferred.'},upscale:{type:'boolean',description:'Enlarge the display PNG to max_size; adds no measured detail; numeric data unchanged.'},spectrum_filter:{type:['object','null'],additionalProperties:false,properties:{smooth_sigma_bins:{type:'number',minimum:0,maximum:4},background_sigma_bins:{type:'number',minimum:1,maximum:64}},required:['smooth_sigma_bins','background_sigma_bins'],description:'Explicit SciPy Gaussian smoothing then background subtraction/clamp on FFT display representation only; sigma in original FFT bins; background must exceed smooth. null disables; omission inherits.'},representation:{type:'string',enum:['log_amplitude','amplitude','power'],description:'Saved complex FFT display only, not a scientific transform; omit to keep its current representation.'}},['object_id']),
  write('image_compare','Compare 2..4 explicit frames over the same pixel ROI with one fixed shared display range. Return PNG plus raw statistics. Differences do not by themselves establish structural change.',{object_ids:{type:'array',items:id,minItems:2,maxItems:4},rect,...display},['object_ids']),
  write('image_fft','Explicit external NumPy fft2 of a pixel ROI; returns complex data and a viewable log-amplitude spectrum, cycles/pixel axes. Independent of native FFT, no automatic backend switch, no phase identification.',{object_id:id,rect,window:{type:'string',enum:['none','hann']},subtract_mean:{type:'boolean'},max_size:display.max_size},['object_id']),
  write('image_measure','Measure two source pixel centres. Reports image-coordinate displacement, pixel distance and image-coordinate angle; physical values require separately sourced calibration.',{object_id:id,points:{type:'array',minItems:2,maxItems:2,items:{type:'array',minItems:2,maxItems:2,items:{type:'number'}}}},['object_id','points']),
  write('image_annotate','Replace an overlay revision; [] removes all marks. Line/arrow endpoints are pixel/bin centres; rectangle/polygon vertices are pixel edges. Default coordinates are rendered PNG pixels; prefer source_pixels or frequency_cycles_per_pixel with the exact panels source_object_id. Stable anchors survive preview changes. Hypothesized/confirmed/retracted are explicit, never automatic scientific classification.',{object_id:id,annotations:{type:'array',maxItems:100,items:{type:'object',additionalProperties:false,properties:{annotation_id:annotationId,line_width:{type:'integer',minimum:1,maximum:4},arrowhead_size:{type:'integer',minimum:1,maximum:12},kind:{type:'string',enum:['point','rectangle','text','line','arrow','polygon']},coordinate_space:{type:'string',enum:['rendered_image_pixels','source_pixels','source_array_indices','frequency_cycles_per_pixel']},source_object_id:id,coordinates:{type:'array',minItems:2,maxItems:64,items:{type:'number'}},text:{type:'string',maxLength:256},status:{type:'string',enum:['hypothesized','user_confirmed','retracted']},note:{type:'string',maxLength:1000}},required:['kind','coordinates','status']}}},['object_id','annotations']),
  write('image_context','Record a revisable user-provided interpretation/calibration separately from storage units. Creates a new revision; never rewrites source metadata or relabels uint16 values as radians.',{object_id:id,metadata},['object_id','metadata']),
  write('image_export','Write scientific NPY, available display PNG and provenance to an explicitly new output directory. Refuse overwrite; this is data handoff, not DM native SaveAs.',{object_id:id,output_dir:{type:'string',minLength:1}},['object_id','output_dir']),
  make('image_result','Query the pre-saved request ID without re-executing an operation. A missing/pending/failed record is not success.',{request_id:requestId},['request_id']),
];
export const IMAGE_INSTRUCTIONS='Explicit multi-source image tools use an independent Python environment and never connect to DM or replace a failed native operation. Choose source and frame IDs, use pixel ROI and fixed cross-frame display ranges. PNG is display only. Save request_id before every write; after cancellation query image_result. Unknown scale permits pixel exploration, but not nm/Angstrom spacings or physical depth. User context is revisable evidence, not measured calibration. Optional crystallography is never required.';
const actions={image_open:'open',image_info:'get',image_frame:'frame',image_preview:'view',image_compare:'compare',image_fft:'fft',image_measure:'measure',image_annotate:'annotate',image_context:'context',image_export:'export',image_result:'result'};

export class ImageWorkspace {
  constructor({workspace,python=process.env.DM_IMAGE_PYTHON||process.env.DM_ANALYSIS_PYTHON||'python',timeoutMs=120000,workerPath=fileURLToPath(new URL('../tools/image_workspace.py',import.meta.url)),spawnProcess=spawn}={}) {
    if(!workspace||!path.isAbsolute(workspace)) throw new Error('DM_IMAGE_WORKSPACE must be an explicit absolute output directory');
    this.workspace=path.resolve(workspace);this.python=python;this.timeoutMs=timeoutMs;this.workerPath=workerPath;this.spawnProcess=spawnProcess;this.queue=Promise.resolve();
  }
  call(name,args,signal) {
    const action=actions[name];if(!action)throw new Error('Unknown external image tool');
    const payload={...args,action,workspace:this.workspace};
    if(action==='result'){payload.query_request_id=payload.request_id;delete payload.request_id;}
    if(action==='open'&&payload.source_kind==='capture')payload.action='import_capture';
    delete payload.source_kind;
    // Query may inspect the durable record while another worker is running.
    if(action==='result'||action==='get')return this.run(payload,signal);
    let resolveWait,rejectWait,started=false;
    const waiting=new Promise((resolve,reject)=>{resolveWait=resolve;rejectWait=reject;});
    const abortQueued=()=>{if(!started)rejectWait(new Error('Cancelled while queued; external operation was not started'));};
    signal?.addEventListener('abort',abortQueued,{once:true});
    if(signal?.aborted)abortQueued();
    const start=()=>{
      started=true;signal?.removeEventListener('abort',abortQueued);
      const operation=this.run(payload,signal);operation.then(resolveWait,rejectWait);
      // Client cancellation settles only the wait. Writes remain serialized
      // until the actual process closes, including after timeout/kill request.
      return operation.workerDone ?? operation.catch(()=>{});
    };
    this.queue=this.queue.then(start,start).catch(rejectWait);return waiting;
  }
  run(payload,signal) {
    if(signal?.aborted)return Promise.reject(new Error('Cancelled before starting external image operation'));
    const raw=JSON.stringify(payload);if(Buffer.byteLength(raw)>256*1024)throw new Error('Image request exceeds 256 KiB');
    let finishWorker;
    const workerDone=new Promise(resolve=>{finishWorker=resolve;});
    const waiting=new Promise((resolve,reject)=>{
      let child;
      try {child=this.spawnProcess(this.python,['-B',this.workerPath],{stdio:['pipe','pipe','pipe'],windowsHide:true});}
      catch(error){finishWorker();reject(error);return;}
      let chunks=[],bytes=0,stderr='',settled=false;
      const hint='Query image_result with the original request_id; do not automatically resubmit.';
      const finish=(fn,value)=>{if(!settled){settled=true;signal?.removeEventListener('abort',abort);fn(value);}};
      const abort=()=>finish(reject,new Error('Stopped waiting; external operation may still finish. '+hint));
      signal?.addEventListener('abort',abort,{once:true});
      // A live worker can finish its durable record after client cancellation.
      const timer=setTimeout(()=>{try{child.kill();}catch{}finish(reject,new Error('External image time limit; state may be incomplete. '+hint));},this.timeoutMs);
      child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes>4*1024*1024){try{child.kill();}catch{}finish(reject,new Error('Image worker response exceeds 4 MiB. '+hint));}else chunks.push(chunk);});
      child.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-4096);});
      child.once('error',err=>{
        // An error can also mean kill failed while the child is still alive.
        // Only close releases the write queue, including after spawn failure.
        if(!child.pid)clearTimeout(timer);
        finish(reject,new Error(child.pid ? 'External image process error: '+err.message+'. '+hint : 'Cannot start independent image Python (DM_IMAGE_PYTHON): '+err.message));
      });
      child.stdin.on('error',err=>finish(reject,new Error('Image worker input failed: '+err.message+' '+hint)));
      child.once('close',code=>{clearTimeout(timer);finishWorker();if(settled)return;try{
        const reply=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(code!==0||reply.ok!==true)throw new Error((typeof reply.error==='object' ? `${reply.error.code}: ${reply.error.message}` : reply.error)||stderr||'Image operation failed');
        const result=reply.result;if(!result||typeof result!=='object'||Array.isArray(result))throw new Error('Invalid image result');
        if(result.backend!=='external-image-workspace'||result.state!=='completed')throw new Error('External image operation did not return a completed external result');
        const content=[{type:'text',text:JSON.stringify(result,null,2)}];
        if(result.image_path){
          // Python resolves Windows 8.3 aliases to long paths. Canonicalize
          // both sides through the native filesystem before containment checks.
          const root=realpathSync.native(this.workspace),file=realpathSync.native(result.image_path),relative=path.relative(root,file);
          if(relative.startsWith('..')||path.isAbsolute(relative))throw new Error('Image result escapes workspace');
          if(statSync(file).size>2*1024*1024)throw new Error('PNG exceeds 2 MiB inline budget');
          const png=readFileSync(file);
          if(!png.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))throw new Error('Image result is not PNG');
          content.push({type:'image',data:png.toString('base64'),mimeType:'image/png'});
        }
        finish(resolve,{content});
      }catch(err){finish(reject,err);}});
      child.stdin.end(raw);if(signal?.aborted)abort();
    });
    waiting.workerDone=workerDone;return waiting;
  }
}
