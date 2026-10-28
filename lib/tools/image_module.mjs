// Explicit registration adapter. Contracts describe existing delegated guards;
// this module does not replace the worker's scientific checks or journal.
import {ImageWorkspace, imageTools, IMAGE_INSTRUCTIONS} from '../image_workspace.mjs';

const workerBudgets = [
  'ImageWorkspace: request <=256 KiB; worker response <=4 MiB; inline PNG <=2 MiB',
  'tools/image_workspace.py: scalar plane <=4194304 pixels and <=64 MiB; source hash budget <=4 GiB; object JSON <=2 MiB',
];
const immutable = 'tools/image_workspace.py validates immutable object/journal/file hashes; no live DM access or native fallback';
const recipes = {
  image_probe: {
    inputs:['ScientificArrayRef:exact immutable saved plane','PointBatch:1..64 source or original FFT frequency coordinates','Component:raw scalar or explicit real/imag/amplitude/power'],
    outputs:['ReadOnlySampleBatch:original-array nearest samples and exact source identity; not PNG brightness'],
    kind:'inspect',requestId:'none',gates:['Persistent read-only NumPy worker validates immutable provider journals/manifest/payload hashes on every request; no result creation or pointer journals'],
    budgets:['One persistent probe worker per ImageWorkspace; <=8 queued batches; <=64 points/batch; cache <=2 arrays /128 MiB; request <=32 KiB; source bounds and explicit nearest tie rule'],
  },
  image_statistics: {
    inputs:['ScientificArrayRef:exact immutable plane','ROI:half-open source edges or original FFT-bin edges','Component:explicit raw/complex component'],
    outputs:['StatisticsRef:saved population mean/stddev/minimum/maximum with source, dtype, ROI and calibration'],
    kind:'measurement-record-write',gates:['NumPy float64 finite reductions; ddof0; original scientific samples, never display values; complex component explicit'],
    budgets:['One admitted bounded plane/ROI; original request ID recovery and no source mutation'],
  },
  image_profile: {
    inputs:['ScientificArrayRef:exact immutable plane','PointPair:domain-bound endpoints and explicit sampling'],
    outputs:['ProfileRef:saved NPY/CSV plus coordinates, original-array samples, calibration and component provenance'],
    kind:'measurement-record-write',gates:['Width1 nearest-neighbor only; floor(index+0.5), no clipping; signed anisotropic physical path distances only with active sourced calibration; reciprocal path distance is not d-spacing'],
    budgets:['2..4096 evenly spaced samples; exact immutable scientific input and original request ID recovery'],
  },
  image_open: {
    inputs: ['ExplicitSourcePath:read-only uint16 TIFF or validated schema-1 numerical capture'],
    outputs: ['ScientificArrayRef:tiff_source or fixed capture frame', 'CalibrationRevisionRef:admitted native axes only; otherwise pixel-domain input'],
    kind: 'fixed-source-snapshot-write',
    gates: ['TIFF admission/page metadata or existing native-capture validator; domain and native calibration admission remain delegated'],
    budgets: ['TIFF metadata <=4096 pages; selected pages are decoded only by image_frame'],
  },
  image_info: {
    inputs: ['ScientificObjectRef:exact saved image/view/calibration/measurement'],
    outputs: ['SavedObjectMetadata:historical immutable metadata, not a fresh observation'],
    kind: 'inspect', requestId: 'none',
    gates: [immutable], budgets: [],
  },
  image_frame: {
    inputs: ['ScientificArrayRef:exact opened TIFF source', 'FrameIndex:explicit zero-based storage index'],
    outputs: ['ScientificArrayRef:independent uint16 XY frame with source/frame identity', 'CalibrationRevisionRef:applicable selected sequence record'],
    kind: 'scientific-array-write',
    gates: ['Exact uint16 TIFF frame/axis and source-stability checks; frame index is not physical depth'],
    budgets: ['One admitted scalar XY plane; no full-stack decode'],
  },
  image_preview: {
    inputs: ['ScientificArrayRef or ImageViewRef:explicit frame/ROI/comparison/saved complex FFT', 'DisplayParameters:source pixel ROI or original fftshift-bin frequency_rect'],
    outputs: ['ImageViewRef:immutable display recipe and scientific coordinate mappings', 'DisplayPNG:nonquantitative, original scientific arrays unchanged'],
    kind: 'display-view-write',
    gates: ['Display-domain/ROI/annotation and calibration-version checks; spatial pixel edges and original FFT-bin edges are distinct', 'Optional SciPy display filtering is explicit; physical axes/bar require active sourced calibration; no FFT recomputation'],
    budgets: ['Preview max_size <=1024; inline PNG bound still enforced; zoom adds no sampled resolution'],
  },
  image_compare: {
    inputs: ['ScientificArrayRef[]:explicit frames over one source-pixel ROI', 'DisplayParameters:one shared range'],
    outputs: ['ImageViewRef:multi-frame comparison with exact per-panel source mapping', 'DisplayPNG and raw statistics:not evidence of structural change'],
    kind: 'comparison-view-write',
    gates: ['Exact supported frame identities and half-open ROI; no comparison frequency_rect or implicit registration'],
    budgets: ['2..4 frames; one admitted ROI per source; max_size <=1024'],
  },
  image_fft: {
    inputs: ['ScientificArrayRef:explicit spatial frame and source-pixel ROI', 'FFTParameters:explicit none/Hann window and mean subtraction'],
    outputs: ['ScientificArrayRef:external complex128 fft2/fftshift with fixed mathematical DC and cycles/pixel axes', 'ImageViewRef and DisplayPNG:log-amplitude presentation'],
    kind: 'scientific-derived-array-write',
    gates: ['Spatial-domain/scalar finite array and ROI checks; no conversion of real-space scale into diffraction-image calibration', 'Computation is explicitly external NumPy, never a replacement for a failed dm_native_fft'],
    budgets: ['Admitted scalar ROI; scientific complex array <=64 MiB'],
  },
  image_measure: {
    inputs: ['ScientificArrayRef or ImageViewRef:exact selected scientific grid', 'PointPair:source_pixels, source_array_indices, or original frequency_cycles_per_pixel according to actual domain'],
    outputs: ['MeasurementRef:point geometry and calibration dependency', 'PixelGeometry or PhysicalGeometry:physical quantities only with active sourced calibration; no phase/HKL inference'],
    kind: 'measurement-record-write',
    gates: ['Domain/point-bound and signed anisotropic calibration checks; reciprocal d-spacing requires an explicit DC endpoint', 'Unknown/withdrawn scale permits pixel geometry only; no physical confidence inferred from missing uncertainties'],
    budgets: ['Exactly two finite point coordinates; admitted scientific grid'],
  },
  image_center: {
    inputs: ['ScientificArrayRef:established reciprocal scalar with image-scoped calibration', 'CenterRevisionRef:explicit sourced correction in original source_array_indices'],
    outputs: ['CalibrationRevisionRef:new centre wrapper retaining scale and raw source evidence'],
    kind: 'centre-revision-write',
    gates: ['Existing reciprocal scalar/image scope; finite in-bounds sourced centre; no external complex FFT or tracked native Fourier DC movement', 'Original scientific pixels, old centre and prior measurement records remain immutable'],
    budgets: ['One two-coordinate centre; source_text <=4000 characters'],
  },
  image_remeasure: {
    inputs: ['ScientificArrayRef or CalibrationRevisionRef:explicit selected current wrapper', 'MeasurementRef:committed previous measurement', 'PointPair:optional explicit sourced correction'],
    outputs: ['MeasurementRef:new geometry with previous manifest hash, effective points and centre/scale dependency'],
    kind: 'measurement-revision-write',
    gates: ['Original request/journal and recursive remeasurement validation; exact source/frame/ROI/array hash/FFT-producer grid agreement', 'Only an originally explicit DC endpoint follows a corrected scalar centre; explicit replacement points require source_text; no FFT recomputation'],
    budgets: ['Previous-measurement revision recursion <=16; scientific-parent traversal <=32; exactly two points'],
  },
  image_calibrate: {
    inputs: ['ScientificArrayRef or ImageViewRef:exact image/sequence scope', 'CalibrationRevisionRef or UserStatement:signed XY scale/domain/source, explicit withdrawal, or exact-scope attachment'],
    outputs: ['CalibrationRevisionRef:immutable active/withdrawn wrapper; original source metadata unchanged'],
    kind: 'calibration-revision-write',
    gates: ['Exact image/sequence/domain scope and length versus inverse-length unit checks; original native provenance remains historical', 'Unknown reciprocal declaration needs explicit declare_reciprocal and sourced image-scoped inverse scale; cannot override known real-space/reconstruction/Fourier lineage', 'Withdrawn calibration removes physical claims; subsequent view/measurement must select the new wrapper'],
    budgets: ['One scope and XY record; source_text <=4000 characters; source scientific array is reused'],
  },
  image_annotate: {
    inputs: ['ImageViewRef:exact displayed object with source/frequency mappings', 'AnnotationRevisionRef:full replacement or sparse updates of stable annotation_id anchors'],
    outputs: ['ImageViewRef:immutable overlay and DisplayPNG', 'AnnotationRevisionRef:source_pixels/source_array_indices/frequency anchors and explicit hypothesis/confirmation/retraction status'],
    kind: 'annotation-view-write',
    gates: ['Exactly one of annotations/updates; stable ID, anchor domain, source identity and coordinate checks remain delegated', 'Display-only marks never alter scientific values; user_confirmed is caller-supplied status, not authenticated phase confirmation'],
    budgets: ['<=100 marks/updates; bounded text, geometry and preview dimensions in existing schema/worker'],
  },
  image_context: {
    inputs: ['ScientificObjectRef:exact source/image/view', 'UserStatement:reconstruction, value/frame meaning and revisable descriptive context'],
    outputs: ['ContextRevisionRef:source-bound narrative metadata wrapper; not operational XY calibration', 'Optional scoped research observation:presence-only confirmation with explicit researcher versus synthetic authority'],
    kind: 'context-revision-write',
    gates: ['Existing typed contextual fields and immutable ancestry checks; legacy context.xy_scale is descriptive only', 'Twinning observation binds the provider scientific grid; confirms only twinning_present, never a twin law, orientation or HKL; caller-reported authority is not independent authentication', 'No inference of uint16 phase radians, physical depth, phase identity or a changed scientific array domain'],
    budgets: ['Existing bounded metadata field lengths and object JSON budget'],
  },
  image_export: {
    inputs: ['ScientificArrayRef or ImageViewRef:exact selected/rendered revision', 'ExplicitOutputDirectory:new user-selected path'],
    outputs: ['ScientificExportRef:NPY plus available PNG, calibration, annotations, parameters and provenance'],
    kind: 'no-overwrite-file-export',
    gates: ['Exclusive new output directory; exact object/files and calibration/render dependency checked; no source overwrite', 'Bridge data handoff only; not DM-native SaveAs and not a display PNG substituted for scientific values'],
    budgets: ['Existing admitted science/display array and manifest budgets'],
  },
  image_result: {
    inputs: ['OperationReceipt:original pre-saved image request_id'],
    outputs: ['OriginalOperationResult:hash-checked committed result or explicit missing/pending/failed error'],
    kind: 'query', requestId: 'query',
    gates: ['Original durable request identity; no re-execution, live DM observation, global-latest lookup or automatic retry'],
    budgets: ['Existing journal/object/PNG budgets'],
  },
};

function contract(name, workspace) {
  const recipe = recipes[name];
  if (!recipe) throw new Error(`Missing image module contract for ${name}`);
  const query = recipe.requestId === 'none' || recipe.requestId === 'query';
  return {
    backend: 'external-image-workspace', inputs: [...recipe.inputs], outputs: [...recipe.outputs],
    effects: {kind: recipe.kind, sourceMutation: false, requestId: recipe.requestId ?? 'required'},
    gates: ['Delegated per-call guards in ImageWorkspace/tools/image_workspace.py; contract metadata is not qualification proof', immutable, ...recipe.gates],
    execution: {
      resourceKeys: query ? [] : [`image-workspace:${workspace}`],
      serialization: query ? 'ImageWorkspace info/result reads bypass coordinated writes; image_result uses the explicit recovery query port' : 'ExecutionCoordinator serializes the adapter-supplied image workspace resource until actual worker close, including after cancellation/deadline; single-process scope',
      budgets: [...workerBudgets, ...recipe.budgets],
      cancellation: query ? 'Abort stops waiting; recovery only queries the existing durable journal, never resubmits scientific work' : 'Queued cancellation prevents submission; after start abort stops waiting only. Coordinator deadline requests worker termination, response guard may also terminate it; actual close releases the resource. Incomplete/unknown state is not retried',
    },
    recovery: query
      ? {method: name === 'image_result' ? 'Query the original durable request without re-execution' : 'Inspect the same immutable object; this is not a fresh capture', tool: name, idField: name === 'image_result' ? 'request_id' : 'object_id', scope: 'Configured image workspace and original immutable evidence'}
      : {method: 'Query original pre-saved request; changed arguments need a new request ID and unknown operations are not replayed', tool: 'image_result', idField: 'request_id', scope: 'Configured image workspace durable journal; no live/cross-session DM recovery claim'},
  };
}

export function createImageModule({imageWorkspace, workspaceOptions} = {}) {
  const runtime = imageWorkspace ?? new ImageWorkspace(workspaceOptions);
  if (!runtime || typeof runtime.call !== 'function') throw new TypeError('Image module requires an ImageWorkspace-compatible call method');
  return {
    id: 'images', enabled: true, workspace: runtime,
    close:()=>runtime.close?.(),
    instructions: IMAGE_INSTRUCTIONS,
    tools: imageTools.map(definition => ({definition, contract: contract(definition.name, runtime.workspace), execute: (args, {signal} = {}) => runtime.call(definition.name, args, signal)})),
  };
}
