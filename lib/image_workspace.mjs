// Explicit external image tools. No DM connection or native fallback lives here.
import {spawn} from 'node:child_process';
import {readFileSync, realpathSync, statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ExecutionCoordinator} from './runtime/execution_coordinator.mjs';
import {readImageMeasurements} from './image_measurement_records.mjs';
import {ImageProbeClient} from './image_probe_client.mjs';

const id = {type:'string', minLength:1, maxLength:80, pattern:'^[A-Za-z0-9_-]+$'};
const requestId = {...id, maxLength:64, description:'Save this ID before submission; query image_result after timeout/cancellation. Reusing it with different parameters is rejected.'};
const annotationId = {...id, maxLength:64, description:'Stable label identity reused across overlay revisions; distinct from operation request_id and not an image_result query ID.'};
export const annotationPresentation = {type:'object',additionalProperties:false,description:'Optional display-only style. Label offsets use base-render pixels and never change the scientific anchor, mark text or confirmation status. Sparse presentation and nested label patches retain omitted fields.',properties:{
  marker_shape:{type:'string',enum:['circle','square','double_circle','diamond','cross']},
  marker_radius:{type:'number',minimum:4,maximum:12},line_width:{type:'number',minimum:.5,maximum:3},
  category:{type:'string',enum:['A','B','shared','unexplained','none']},layer:{type:'string',enum:['experimental','simulation_A','simulation_B']},
  geometry_visible:{type:'boolean'},label:{type:'object',additionalProperties:false,properties:{
    text:{type:'string',maxLength:256},offset:{type:'array',minItems:2,maxItems:2,items:{type:'number',minimum:-4096,maximum:4096}},
    font_size:{type:'number',minimum:8,maximum:32},leader:{type:'boolean'},pinned:{type:'boolean'},visible:{type:'boolean'},figure_visible:{type:'boolean'},important:{type:'boolean'},
    measurement_object_id:{type:'string',pattern:'^[a-f0-9]{32}$',description:'Saved image_measure reference for a displayed numeric label; format validation does not authenticate its relation to this anchor.'},
    measurement_kind:{type:'string',enum:['distance','period']}
  }}
}};
const annotationUpdates = {
  type:'array',minItems:1,maxItems:100,
  description:'Sparse edits to existing annotation_id values on this exact view. Omitted marks/fields persist. Coordinates use the saved anchor source/frequency space, never the PNG or shortened arrow tail. Use status=retracted to hide a mark; no implicit additions.',
  items:{type:'object',additionalProperties:false,required:['annotation_id'],properties:{
    annotation_id:annotationId,
    presentation:annotationPresentation,
    presentation_replace:{type:'boolean',description:'Update-only control; requires presentation. True replaces the whole display metadata for exact recipe replay; false/omission merges sparse presentation and label fields. Never stored on an annotation.'},
    coordinates:{type:'array',minItems:2,maxItems:64,items:{type:'number'},description:"Coordinates in this mark's saved anchor coordinate_space; kind and source cannot change."},
    text:{type:'string',maxLength:256},note:{type:'string',maxLength:1000},
    status:{type:'string',enum:['hypothesized','user_confirmed','retracted']},
    color:{type:'string',enum:['white','cyan','orange','amber','green']},
    line_width:{type:'integer',minimum:1,maximum:4},
    arrowhead_size:{type:'integer',minimum:1,maximum:12},
    arrow_length:{type:['integer','null'],minimum:4,maximum:128}
  }}
};
const rect = {type:'array',items:{type:'integer',minimum:0},minItems:4,maxItems:4,description:'Half-open source pixel edges [x0,y0,x1,y1], no clipping.'};
const display = {display_range:{type:['array','null'],items:{type:'number'},minItems:2,maxItems:2,description:'Explicit display limits; image_preview inherits an existing view when omitted. New frames/comparisons or null use auto-range.'},gamma:{type:'number',minimum:0.05,maximum:20},max_size:{type:'integer',minimum:32,maximum:1024}};
const metadata = {type:'object',additionalProperties:false,properties:{
  research_observation:{type:'object',additionalProperties:false,required:['kind','source_text','authority'],properties:{kind:{type:'string',enum:['twinning_present']},source_text:{type:'string',minLength:1,maxLength:1000},authority:{type:'string',enum:['user_confirmed','synthetic_fixture']}}},
  reconstruction_type:{type:['string','null'],maxLength:500},data_meaning:{type:['string','null'],maxLength:500},frame_meaning:{type:['string','null'],maxLength:500},
  xy_scale:{type:['object','null'],additionalProperties:false,properties:{x:{type:'number'},y:{type:'number'},unit:{type:'string',maxLength:40},source:{type:'string',maxLength:1000}},required:['x','y','unit','source']},
  value_unit:{type:['string','null'],maxLength:100},
  frame_scale:{type:['object','null'],additionalProperties:false,properties:{origin:{type:'number'},step:{type:'number'},unit:{type:'string',maxLength:40},source:{type:'string',maxLength:1000}},required:['origin','step','unit','source']},
  source_text:{type:['string','null'],maxLength:2000}}};
const make=(name,description,properties,required)=>({name,description,inputSchema:{type:'object',properties,required,additionalProperties:false}});
const write=(name,description,properties,required)=>make(name,description,{...properties,request_id:requestId},[...required,'request_id']);
const numericComponent={type:'string',enum:['raw','real','imag','amplitude','power'],description:'Scalar scientific arrays use raw; complex FFT requires explicit real/imag/amplitude/power. Never PNG brightness or electron counts.'};
const numericSpace={type:'string',enum:['source_pixels','source_array_indices','frequency_cycles_per_pixel']};
const numericPoints={type:'array',minItems:2,maxItems:2,items:{type:'array',minItems:2,maxItems:2,items:{type:'number'}}};
export const imageTools=[
  make('image_probe','Read up to64 original-array samples with a persistent read-only worker; no result object or request journal per probe. Nearest sample uses floor(index+0.5), with no clipping. Bind response to exact immutable object; physical/intensity units are not inferred.',{object_id:id,points:{...numericPoints,minItems:1,maxItems:64},coordinate_space:numericSpace,component:numericComponent},['object_id','points']),
  write('image_statistics','Save original-array ROI statistics: mean, population stddev(ddof0), minimum and maximum with binary64 reductions. Source rect and original FFT frequency_rect are distinct; complex component must be explicit. No display gamma/filter is applied.',{object_id:id,rect,frequency_rect:rect,component:numericComponent},['object_id']),
  write('image_profile','Save an evenly sampled straight width-one nearest-neighbor scientific profile, including original coordinates, sampled indices/values, calibrated path distance when sourced, NPY and CSV. No clipping, no inferred intensity unit; reciprocal path distance is not d-spacing.',{object_id:id,points:numericPoints,coordinate_space:numericSpace,component:numericComponent,sample_count:{type:'integer',minimum:2,maximum:4096},line_width:{type:'integer',enum:[1]},interpolation:{type:'string',enum:['nearest']}},['object_id','points']),
  write('image_open','Open an explicit TIFF read-only outside DM; inspect pages without decoding the whole stack. Or import an existing verified DM numerical capture. Validated native READ axis calibration activates a versioned sourced geometry record when domain and units agree; generic metadata or missing/ambiguous native scales remain pixel-only. No phase unit or depth is inferred.',{source_path:{type:'string',minLength:1},source_kind:{type:'string',enum:['tiff','capture']}},['source_path']),
  make('image_info','Inspect a saved image/view/context object without running analysis.',{object_id:id},['object_id']),
  write('image_center','Create a sourced centre revision of an established reciprocal scalar image, preserving signed XY scale and immutable pixels. center_xy uses original source_array_indices. Tracked native Fourier scalars and external complex FFTs have fixed mathematical DC and cannot be recentered here. Remeasure saved points using the returned wrapper; previous measurements remain historical.',{object_id:id,center_xy:{type:'array',minItems:2,maxItems:2,items:{type:'number'}},coordinate_space:{type:'string',enum:['source_array_indices']},source_text:{type:'string',minLength:1,maxLength:4000}},['object_id','center_xy','coordinate_space','source_text']),
  write('image_remeasure','Reuse a committed measurement on the selected current calibration/centre wrapper. Requires the exact same scientific source/frame/ROI/FFT grid. Omit points to reuse anchors and move only an originally explicit DC endpoint to the corrected centre. Explicit points require source_text and are used as supplied. Returns a new measure object; no FFT recomputation or latest-object guessing.',{object_id:id,measurement_object_id:id,points:{type:'array',minItems:2,maxItems:2,items:{type:'array',minItems:2,maxItems:2,items:{type:'number'}}},source_text:{type:'string',minLength:1,maxLength:4000}},['object_id','measurement_object_id']),
  write('image_frame','Select an explicit zero-based TIFF frame, preserving raw dtype and source identity in an independent NPY. This is external TIFF I/O, not a DM native operation.',{object_id:id,frame_index:{type:'integer',minimum:0}},['object_id','frame_index']),
  write('image_preview','Render an image/ROI, annotated view or saved comparison; re-render a saved external FFT without recomputing it. Anchored annotations follow size/display changes. Omitted display limits/gamma/size inherit; null range recalculates. FFT representation changes reset only range; FFT uses frequency_rect for display-only zoom; comparison rect is unsupported. PNG is display-only.',{object_id:id,rect,frequency_rect:{type:['array','null'],items:{type:'integer',minimum:0},minItems:4,maxItems:4,description:'FFT display-only zoom: absolute half-open [x0,y0,x1,y1] edges in the original fftshift bin grid, never PNG or previous zoom coordinates. Omit to inherit; null restores full spectrum. Original complex NPY and frequency resolution unchanged.'},...display,interpolation:{type:'string',enum:['lanczos','nearest'],description:'Display resizing only: nearest exposes the original sampled bins without interpolation blur; lanczos is the existing smooth display. Neither adds measured resolution or changes NPY. Omission inherits.'},display_preset:{type:'string',enum:['fft_detail'],description:'General detail-first FFT figure: log amplitude, no smoothing/background subtraction, no large axes, gamma0.8 (slightly darker midtones), enlarged512px and display percentiles5/99.8. Explicit parameters override; scientific data unchanged. Prefer before adding optional filters.'},spectrum_axes:{type:'boolean',description:'Label signed fx/fy axes on saved FFT; active image_calibrate record uses cycles/length-unit, otherwise cycles/pixel; max_size>=256. Original cycles/pixel anchors and complex data never change.'},scale_bar:{type:'boolean',description:'Spatial/comparison display only. Show a sourced horizontal physical bar when operational XY calibration is active (default true); absent/withdrawn calibration never invents a bar. FFT uses spectrum_axes instead.'},upscale:{type:'boolean',description:'Enlarge the display PNG to max_size; adds no measured detail; numeric data unchanged.'},spectrum_filter:{type:['object','null'],additionalProperties:false,properties:{smooth_sigma_bins:{type:'number',minimum:0,maximum:4},background_sigma_bins:{type:'number',minimum:1,maximum:64}},required:['smooth_sigma_bins','background_sigma_bins'],description:'Explicit SciPy Gaussian smoothing then background subtraction/clamp on FFT display representation only; sigma in original FFT bins; background must exceed smooth. null disables; omission inherits.'},representation:{type:'string',enum:['log_amplitude','amplitude','power'],description:'Saved complex FFT display only, not a scientific transform; omit to keep its current representation.'}},['object_id']),
  write('image_compare','Compare 2..4 explicit frames over the same pixel ROI with one fixed shared display range. Return PNG plus raw statistics. Differences do not by themselves establish structural change.',{object_ids:{type:'array',items:id,minItems:2,maxItems:4},rect,...display},['object_ids']),
  write('image_fft','Explicit external NumPy fft2 of a pixel ROI; returns complex data and a viewable log-amplitude spectrum, cycles/pixel axes. Independent of native FFT, no automatic backend switch, no phase identification.',{object_id:id,rect,window:{type:'string',enum:['none','hann']},subtract_mean:{type:'boolean'},max_size:display.max_size},['object_id']),
  write('image_measure','Measure two source pixel centres, reciprocal scalar-array indices or original saved FFT frequencies. Uses an active sourced native/user calibration; otherwise returns pixel geometry only. Domains remain distinct: reciprocal-array measurement returns frequency/period, not real-space distance. No FFT recomputation or unique phase assertion.',{object_id:id,coordinate_space:{type:'string',enum:['source_pixels','source_array_indices','frequency_cycles_per_pixel'],description:'Must match actual object domain. Spatial coordinates are source pixel centres inside this view ROI; reciprocal scalar captures use source_array_indices; saved complex FFT uses original signed cycles/pixel, never PNG pixels or physical frequency input. Omission follows the actual domain.'},points:{type:'array',minItems:2,maxItems:2,items:{type:'array',minItems:2,maxItems:2,items:{type:'number'}}}},['object_id','points']),
  write('image_calibrate','Create a versioned user-stated XY calibration, revise/withdraw it, or attach an existing exact-scope native/user record to a saved frame/FFT. Never changes pixels/file metadata/intensity/frame depth. New statement requires scope, xy_scale (null withdraws) and actual source_text; alternatively provide only calibration_object_id. After changes preview this new wrapper to redraw physical scales/axes before annotation/export. Old objects/exports remain immutable; saved complex FFT is reused.',{object_id:id,declare_reciprocal:{type:'boolean',description:'Explicit user declaration for a previously unknown scalar image only, together with reciprocal_space, image scope, inverse-length xy_scale and source_text. Cannot override known spatial/native/FFT lineage or an existing reconstruction interpretation.'},coordinate_domain:{type:'string',enum:['real_space','reciprocal_space'],description:'Defaults to real_space for new statements. Reciprocal scalar inputs require reciprocal_space and inverse-length units; withdrawal preserves its prior domain.'},scope:{type:'string',enum:['image','sequence'],description:'image binds one immutable frame; sequence binds one exact opened TIFF source, not every matching filename.'},xy_scale:{type:['object','null'],additionalProperties:false,required:['x','y','unit'],properties:{x:{type:'number',description:'Signed nonzero length or inverse-length per source X index, according to the declared domain; never inferred from Y.'},y:{type:'number',description:'Signed nonzero length or inverse-length per source Y index, according to the declared domain; never inferred from X.'},unit:{type:'string',enum:['m','mm','um','nm','angstrom','Å','Å','Angstrom','µm','μm','1/m','1/mm','1/um','1/nm','1/angstrom','1/Å','1/µm','1/μm']},uncertainty_x:{type:'number',minimum:0,description:'Optional absolute standard uncertainty in stated length/pixel; omission means unknown, not zero.'},uncertainty_y:{type:'number',minimum:0}}},source_text:{type:'string',minLength:1,maxLength:4000,description:'Actual user statement, including scope/XY assumptions; never substitute the example calibration for experimental data.'},calibration_object_id:{...id,description:'Existing image_calibrate wrapper or automatically calibrated native-capture frame; its record must match this exact source/image. Cannot be combined with scope, xy_scale, coordinate_domain or source_text.'}},['object_id']),
  write('image_annotate','Supply exactly one: annotations replaces the entire overlay ([] clears all); updates edits existing stable IDs while preserving omitted marks and fields. Line/arrow endpoints are pixel/bin centres; rectangle/polygon vertices are pixel edges. Default coordinates are rendered PNG pixels; prefer source_pixels or frequency_cycles_per_pixel with the exact panels source_object_id. Stable anchors survive preview changes. Hypothesized/confirmed/retracted are explicit, never automatic scientific classification.',{object_id:id,updates:annotationUpdates,annotations:{type:'array',maxItems:100,items:{type:'object',additionalProperties:false,properties:{annotation_id:annotationId,presentation:annotationPresentation,color:{type:'string',enum:['white','cyan','orange','amber','green'],description:'Display color only; independent of scientific status. Arrows default to cyan. Use orange for a second-phase candidate when explicitly proposed, never as automatic phase confirmation.'},line_width:{type:'integer',minimum:1,maximum:4,description:'Display pixels; arrows default3, other marks1.'},arrowhead_size:{type:'integer',minimum:1,maximum:12,description:'Display pixels; arrows default6.'},arrow_length:{type:['integer','null'],minimum:4,maximum:128,description:'Arrows only: maximum displayed shaft length in PNG pixels, default24; null draws the full anchored segment. Keeps direction/tip/anchors, shortens only the displayed tail, never extends short arrows. Labels follow the displayed tail.'},kind:{type:'string',enum:['point','rectangle','text','line','arrow','polygon']},coordinate_space:{type:'string',enum:['rendered_image_pixels','source_pixels','source_array_indices','frequency_cycles_per_pixel']},source_object_id:id,coordinates:{type:'array',minItems:2,maxItems:64,items:{type:'number'}},text:{type:'string',maxLength:256},status:{type:'string',enum:['hypothesized','user_confirmed','retracted']},note:{type:'string',maxLength:1000}},required:['kind','coordinates','status']}}},['object_id']),
  write('image_context','Record revisable user interpretation separately from storage units. Legacy metadata.xy_scale remains descriptive and is not applied to geometry; use image_calibrate for operational real-space XY. Never rewrites source metadata or relabels uint16 values as radians.',{object_id:id,metadata},['object_id','metadata']),
  write('image_export','Write scientific NPY, available display PNG and provenance to an explicitly new output directory. Refuse overwrite; this is data handoff, not DM native SaveAs.',{object_id:id,output_dir:{type:'string',minLength:1}},['object_id','output_dir']),
  make('image_result','Query the pre-saved request ID without re-executing an operation. A missing/pending/failed record is not success.',{request_id:requestId},['request_id']),
];
export const IMAGE_INSTRUCTIONS='Explicit multi-source image tools use an independent Python environment and never connect to DM or replace a failed native operation. Choose source and frame IDs, use pixel ROI and fixed cross-frame display ranges. PNG is display only. Save request_id before every write; after cancellation query image_result. Unknown scale permits pixel exploration, but not nm/Angstrom spacings or physical depth. User context is revisable evidence. Validated native READ captures automatically activate sourced XY records when current axis units/domain agree; inspect calibration_admission and source. Use image_calibrate for user revisions with explicit scope/source_text and reciprocal_space for inverse-length calibration; never relabel real-space scale as diffraction calibration; legacy image_context.xy_scale is descriptive only. Sequence calibration follows selected frames; explicitly attach the record to an older saved FFT if needed. After calibration changes preview the new wrapper to redraw bars/physical frequency axes, then remeasure; old physical measurements/interpretations require review and old exports remain immutable. Physical FFT conversion divides cycles/pixel by signed axis scales, with no2pi; intensity units and physical depth remain separate. Optional crystallography is never required. For frequency zoom use image_preview frequency_rect in the original FFT bin grid; keep the full-spectrum reference and shared display range. Zoom never recomputes FFT, increases resolution, or re-centres DC. For an FFT figure, first try image_preview display_preset=fft_detail and inspect the returned image. Preserve the unfiltered texture/streaks; smoothing and background subtraction are optional explicit display treatments, never a default recipe. Use sparse short cyan arrows by default (3px wide, 6px head, maximum24px shaft); stop outside features. Use color=orange for an explicitly proposed second-phase candidate, keeping its hypothesized/user_confirmed/retracted status separate. Color never establishes a phase. Explicit styling overrides defaults; existing revisions keep their styles. Do not copy literature indices or physical scale onto uncalibrated data. Use image_center only to correct an established reciprocal scalar centre, never the mathematical DC of a saved external complex FFT. Use image_remeasure with the current wrapper and old measurement to reuse valid point anchors; only an originally explicit DC endpoint follows a centre correction. Source/frame/ROI/FFT grid must agree. A previously unknown scalar image can be explicitly declared reciprocal via image_calibrate declare_reciprocal=true with inverse scale and user source; known real-space or reconstruction meaning cannot be silently replaced.';
const actions={image_probe:'probe',image_statistics:'statistics',image_profile:'profile',image_open:'open',image_info:'get',image_frame:'frame',image_preview:'view',image_compare:'compare',image_fft:'fft',image_measure:'measure',image_center:'centre',image_remeasure:'remeasure',image_calibrate:'calibrate',image_annotate:'annotate',image_context:'context',image_export:'export',image_result:'result'};

export class ImageWorkspace {
  constructor({workspace,python=process.env.DM_IMAGE_PYTHON||process.env.DM_ANALYSIS_PYTHON||'python',timeoutMs=120000,workerPath=fileURLToPath(new URL('../tools/image_workspace.py',import.meta.url)),spawnProcess=spawn,coordinator=new ExecutionCoordinator()}={}) {
    if(!workspace||!path.isAbsolute(workspace)) throw new Error('DM_IMAGE_WORKSPACE must be an explicit absolute output directory');
    this.workspace=path.resolve(workspace);this.python=python;this.timeoutMs=timeoutMs;this.workerPath=workerPath;this.spawnProcess=spawnProcess;this.coordinator=coordinator;
    this.resourceKey='image-workspace:'+this.workspace;
    this.requestScope={provider:'external-image-workspace',workspace:this.workspace,session:'workspace-journal-v1'};
    this.probeClient=new ImageProbeClient({workspace:this.workspace,python:this.python,spawnProcess:this.spawnProcess});
  }
  // Compatibility drain for callers/tests; there is no second image queue.
  get queue(){return this.coordinator.whenIdle(this.resourceKey);}
  inspectMeasurements({objectId,limit}={}) {return readImageMeasurements({workspace:this.workspace,objectId,limit});}
  call(name,args,signal) {
    const action=actions[name];if(!action)throw new Error('Unknown external image tool');
    if(action==='probe')return this.coordinator.invoke({operation:name,requestId:null,parameters:args,resourceKeys:[],timeoutMs:Math.min(this.timeoutMs,10000),requestScope:this.requestScope,lane:'query'},
      {start:parameters=>{const result=this.probeClient.call(parameters);return {result,closed:result.then(()=>{},()=>{}),requestStop:()=>{}};},messages:{queued:'Probe cancelled before submission',cancelled:'Stopped waiting for read-only probe',timeout:'Read-only probe timed out; no scientific write was submitted'}},{signal});
    const payload={...args,action,workspace:this.workspace};
    if(action==='result'){payload.query_request_id=payload.request_id;delete payload.request_id;}
    if(action==='open'&&payload.source_kind==='capture')payload.action='import_capture';
    delete payload.source_kind;
    // The portable coordinator owns queue/wait/deadline mechanics only.
    // The existing worker remains authoritative for hashes, original IDs,
    // scientific admission and durable completion, including after restart.
    const readonly=action==='result'||action==='get';
    const spec={operation:name,requestId:readonly?(action==='result'?args.request_id:null):args.request_id,
      parameters:payload,resourceKeys:readonly?[]:[this.resourceKey],timeoutMs:this.timeoutMs,
      requestScope:this.requestScope,lane:readonly?'query':'work'};
    const start=accepted=>{const work=this.run(accepted);return {result:work,closed:work.workerDone,requestStop:work.requestStop};};
    const messages={queued:'Cancelled while queued; external operation was not started',
      cancelled:'Stopped waiting; external operation may still finish. Query image_result with the original request_id; do not automatically resubmit.',
      timeout:'External image time limit; state may be incomplete. Query image_result with the original request_id; do not automatically resubmit.'};
    return action==='result'
      ? this.coordinator.recover(spec,{query:start,messages},{signal})
      : this.coordinator.invoke(spec,{start,messages},{signal});
  }
  close(){this.probeClient.close();}
  run(payload) {
    const raw=JSON.stringify(payload);if(Buffer.byteLength(raw)>256*1024)throw new Error('Image request exceeds 256 KiB');
    let finishWorker,child;
    const workerDone=new Promise(resolve=>{finishWorker=resolve;});
    const waiting=new Promise((resolve,reject)=>{
      try {child=this.spawnProcess(this.python,['-B',this.workerPath],{stdio:['pipe','pipe','pipe'],windowsHide:true});}
      catch(error){finishWorker();reject(error);return;}
      let chunks=[],bytes=0,stderr='',settled=false;
      const hint='Query image_result with the original request_id; do not automatically resubmit.';
      const finish=(fn,value)=>{if(!settled){settled=true;fn(value);}};
      child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes>4*1024*1024){try{child.kill();}catch{}finish(reject,new Error('Image worker response exceeds 4 MiB. '+hint));}else chunks.push(chunk);});
      child.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-4096);});
      child.once('error',err=>{
        // An error can also mean kill failed while the child is still alive.
        // Only close releases the write queue, including after spawn failure.
        finish(reject,new Error(child.pid ? 'External image process error: '+err.message+'. '+hint : 'Cannot start independent image Python (DM_IMAGE_PYTHON): '+err.message));
      });
      child.stdin.on('error',err=>finish(reject,new Error('Image worker input failed: '+err.message+' '+hint)));
      child.once('close',code=>{finishWorker();if(settled)return;try{
        const reply=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(code!==0||reply.ok!==true)throw new Error((typeof reply.error==='object' ? `${reply.error.code}: ${reply.error.message}` : reply.error)||stderr||'Image operation failed');
        const result=reply.result;if(!result||typeof result!=='object'||Array.isArray(result))throw new Error('Invalid image result');
        if(result.backend!=='external-image-workspace'||result.state!=='completed')throw new Error('External image operation did not return a completed external result');
        if(payload.action==='get'){
          if(result.object_id!==payload.object_id)throw new Error('Image worker returned a different requested object identity');
        }else if(result.request_id!==(payload.action==='result'?payload.query_request_id:payload.request_id)){
          throw new Error('Image worker returned a different original request identity; '+hint);
        }
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
      child.stdin.end(raw);
    });
    waiting.workerDone=workerDone;waiting.requestStop=()=>child?.kill();return waiting;
  }
}
