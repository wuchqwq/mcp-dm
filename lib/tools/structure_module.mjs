// Registration-only adapter for existing independent ASE/diffsims operations.
// It preserves scientific validation/errors and the separate viewer namespace.
import {StructureWorkspace, structureTools, STRUCTURE_INSTRUCTIONS} from '../structure_workspace.mjs';
import {attachStructureViewer, closeStructureViewer, structureViewerTools} from '../structure_viewer_client.mjs';

const workerBudgets = [
  'StructureWorkspace: request <=256 KiB; worker response <=4 MiB; inline PNG <=2 MiB; configured worker deadline',
  'crystallography/structure_tools.py: <=4096 atoms; bounded source/object files and scientific manifests',
];
const recipes = {
  structure_open: {
    inputs: ['ExplicitSourcePath:bounded read-only CIF1 or XYZ/extXYZ'],
    outputs: ['StructureRef:fixed hashed cell/atomic-coordinate snapshot; ASE Angstrom coordinates, not an experimentally confirmed phase'],
    kind: 'fixed-structure-snapshot-write',
    gates: ['ASE source format, finite species/coordinates and original-source stability checks; no calculator, network or DM', 'Generic/nonorthogonal/partial cell and cell-free XYZ may be observed; no inferred periodic cell'],
    budgets: ['Source structure file <=2 MiB; admitted atomic budget'],
  },
  structure_info: {
    inputs: ['StructureRef or ScientificObjectRef:exact saved structure/view/simulation/measurement'],
    outputs: ['SavedObjectMetadata:optional finite Angstrom atoms, exact cell and PBC; historical, not live experimental state'],
    kind: 'inspect', requestId: 'none',
    gates: ['Committed manifest/original journal/scientific file hashes and exact requested object identity'],
    budgets: ['include_atoms remains bounded by the exact saved <=4096-atom snapshot'],
  },
  structure_view: {
    inputs: ['StructureRef:exact immutable atomic snapshot', 'OrientationRef or legacy Cartesian display rotation:choose only one', 'DisplayParameters:optional interactive local 3Dmol attachment'],
    outputs: ['ImageViewRef and DisplayPNG:ASE projection, not scientific image intensity', 'Optional ViewerRef:reported applied orientation/configuration/verification status; camera movement is not a model transformation'],
    kind: 'structure-view-write-and-optional-owned-viewer',
    gates: ['Source/orientation and exact cell/partial-periodicity validation; optional viewer snapshot and pinned local asset/license validation', 'Missing/failed viewer reports NOT_CONFIGURED/UNVERIFIED without relabelling the completed ASE projection as 3D; scientific source unchanged'],
    budgets: ['Projection max_size 128..1024; optional viewer snapshot <=4096 atoms; local 3Dmol asset <=8 MiB; owned reuse generations <=256', 'Optional renderer geometric contacts <=512 atoms and <=8192 undirected contacts; not a chemical bond-order calculation'],
  },
  structure_measure: {
    inputs: ['StructureRef:exact atoms/cell', 'GeometryQuery:atom indices, three-index HKL and/or direct UVW in the supplied cell basis'],
    outputs: ['MeasurementRef:atomic/cell geometry in Angstrom or angles; no experimental indexing or phase proof'],
    kind: 'structure-measurement-write',
    gates: ['Kind-specific atom count/index and nonzero/full-rank metric checks; MIC requires declared periodicity', 'Nonorthogonal metric and direct versus reciprocal indices stay distinct; no implicit four-index conversion'],
    budgets: ['2..4 atom indices or <=2 supplied HKL/UVW tuples, each bounded by the existing schema'],
  },
  structure_derive: {
    inputs: ['StructureRef:original immutable scientific model', 'OrientationRef or active Cartesian rotation, plus explicit repeat'],
    outputs: ['StructureRef:new independent repeated/rotated positions and cell with transform provenance'],
    kind: 'scientific-derived-structure-write',
    gates: ['Explicit orientation versus legacy rotation exclusivity; finite exact model/cell transform; no source overwrite or silent double orientation'],
    budgets: ['Each repeat axis 1..32 and resulting atoms <=4096'],
  },
  structure_orient: {
    inputs: ['StructureRef:exact supplied row-vector cell', 'Direction:nonzero three-index UVW; optional transverse direct direction and roll'],
    outputs: ['OrientationRef:source-bound proper matrix mapping positive beam to lab +Z, conventions and simulator angles'],
    kind: 'orientation-record-write',
    gates: ['Actual direct-lattice metric and nonzero supplied cell vectors; right-handed rotation and nonparallel in-plane direction checks', 'Partial cell only where that direct direction is defined; no guessed Euler angles or camera-to-model promotion'],
    budgets: ['Existing index components -32..32; one direction/reference pair and bounded rotation'],
  },
  structure_simulate: {
    inputs: ['StructureRef:exact full periodic model with occupancy evidence', 'OrientationRef or explicit RZXZ Euler angles:exactly one', 'SimulationParameters:voltage, reciprocal radius, excitation error and sampling'],
    outputs: ['SimulationRef:unrastered reciprocal coordinates/HKL/kinematic intensities and parameters', 'ScientificArrayRef:external scientific raster/schema-1 capture, plus optional explicit float32 conversion', 'DisplayPNG:qualitative raster, not experimental counts, SAED/HRTEM equivalence or dynamical scattering'],
    kind: 'kinematic-simulation-write',
    gates: ['Pinned diffsims 0.7.0 and exact orientation matrix; full periodic occupancy and analytic reciprocal-enumeration certificate', 'Uncertified skew/cutoff enumeration is refused, not silently rebased or moved to another simulator', 'native_float32 is a separate explicit conversion/handoff, not native dtype/import qualification'],
    budgets: ['Candidate reciprocal vectors <=100000; atom-reflection pairs <=5000000; retained reflections <=4096', 'Raster size 64..512; native_float32 requires size <=128; configured explicit voltage/cutoff/excitation/sigma bounds'],
  },
  structure_register: {
    inputs: ['SimulationRef:saved pinned-engine unrastered reflections', 'MeasurementRef[]:committed DC-to-peak image_measure/image_remeasure manifests', 'ScientificArrayRef:explicit current_image_object_id wrapper', 'ConfirmedCorrespondences:fit and separate held-out HKL; fixed screen parity and caller-declared authority'],
    outputs: ['RegistrationRef:one proper in-plane rotation with scale=1, translation=0 and fixed flip_y', 'ComparisonRef:fit/held-out/unassigned geometric evidence and immutable current grid/calibration binding'],
    kind: 'registration-proposal-write',
    gates: ['Current image grid, source/frame/ROI/FFT producer, exact centre/active scale and original measurement request/hash checks', 'At least two non-collinear fit pairs; held-out peaks/HKL/projections/Friedel/conjugate equivalents cannot reuse fit evidence', 'confirmation is a recorded caller assertion; real unconfirmed hypotheses cannot be declared user_confirmed or synthetic_fixture', 'No guessed mirror, experimental-scale fit, arbitrary translation, intensity matching or unique phase claim'],
    budgets: ['1..32 saved measurements; combined fixed manifest/journal bytes <=2 MiB; comparison evidence <=1 MiB; fixed predeclared residual tolerance'],
  },
  structure_compare: {
    inputs: ['SimulationRef:committed unrastered reflections', 'MeasurementRef[]:committed sourced reciprocal/DC geometry', 'RegistrationRef or explicit transform:exactly one', 'Optional CurrentGeometryRef/PreviousComparisonRef:explicit continue_current versus historical_review'],
    outputs: ['ComparisonRef:residuals, matched/unmatched/ambiguous candidates, registration source and analysis revision links'],
    kind: 'reflection-comparison-write',
    gates: ['Committed original measurement journals, signed/domain units, DC endpoint and physical-vector consistency checks', 'continue_current checks selected wrapper grid and centre/scale; saved registration must bind its exact simulation/points/current geometry', 'Historical/standalone snapshots are not live/current observations; changed capture/frame/ROI continuation requires source_change_basis with previous comparison', 'Explicit transform never changes independent calibration; no FFT/SAED intensity equivalence or unique phase assertion'],
    budgets: ['1..32 measurements; fixed evidence bytes <=2 MiB; result evidence <=1 MiB; matching resources refused rather than truncated'],
  },
  structure_result: {
    inputs: ['OperationReceipt:original saved scientific structure request_id'],
    outputs: ['OriginalOperationResult:hash-checked completed scientific record or explicit missing/pending/failed error'],
    kind: 'query', requestId: 'query',
    gates: ['Original durable scientific request identity; not viewer-close namespace, new computation, current-wrapper lookup or fresh DM capture'],
    budgets: ['Existing original journal/object/scientific files and inline PNG budgets'],
  },
};

function contract(name, workspace) {
  const recipe = recipes[name];
  if (!recipe) throw new Error(`Missing structure module contract for ${name}`);
  const query = recipe.requestId === 'none' || recipe.requestId === 'query';
  return {
    backend: 'external-structure-workspace', inputs: [...recipe.inputs], outputs: [...recipe.outputs],
    effects: {kind: recipe.kind, sourceMutation: false, requestId: recipe.requestId ?? 'required'},
    gates: ['Delegated per-call StructureWorkspace/crystallography checks; catalog metadata does not admit missing dependencies or unqualified scientific ranges', ...recipe.gates],
    execution: {
      resourceKeys: query ? [] : [`structure-workspace:${workspace}`],
      serialization: query ? 'StructureWorkspace info/result reads bypass coordinated writes and use query capacity; structure_result invokes only the original-record query port' : 'ExecutionCoordinator serializes the structure-workspace resource and holds worker capacity until actual close; optional viewer attachment keeps its existing independent deduplication',
      budgets: [...workerBudgets, ...recipe.budgets],
      cancellation: query ? 'Stop waiting for a read; no scientific operation is resubmitted or worker terminated' : 'Queued abort prevents submission. Started abort/deadline/response overflow stops waiting only and NEVER terminates the structure worker; resource/capacity releases on actual close. Optional viewer launch remains separately governed, never automatically relaunched',
    },
    recovery: query
      ? {method: name === 'structure_result' ? 'Query original durable scientific result without recomputation' : 'Inspect the same immutable object, not live experiment state', tool: name, idField: name === 'structure_result' ? 'request_id' : 'object_id', scope: 'Configured independent scientific structure workspace; viewer-close requests are separate'}
      : {method: name === 'structure_view' ? 'Query structure_result for scientific view; optional helper attachment recovers through the exact original structure_view arguments without an automatic new launch' : 'Query original pre-saved request; never automatically repeat unknown science work', tool: 'structure_result', idField: 'request_id', scope: 'Configured structure workspace durable scientific journal; not cross-session DM or helper-close recovery'},
  };
}

function viewerCloseContract(workspace) {
  return {
    backend: 'external-structure-workspace',
    inputs: ['ImageViewRef:exact saved structure_view alias', 'OperationReceipt:pre-saved independent viewer-close request_id'],
    outputs: ['ViewerClosureReceipt:exact shared owner/affected aliases; completed only with acknowledged closure and stopped process/port, otherwise unknown'],
    effects: {kind: 'owned-viewer-close', sourceMutation: false, requestId: 'required'},
    gates: ['Existing owned-viewer token, snapshot/asset/view identity and original close argument guards', 'Only this owned helper closes; aliases may share it; no DM/scientific data closure or force kill'],
    execution: {
      resourceKeys: [`structure-viewer-registry:${workspace}`],
      serialization: 'Existing exclusive durable close intent owns at most one HTTP dispatch; repeated original ID only queries; this module adds no queue',
      budgets: ['Existing close request/receipt records <=16 KiB; owned connection/closure records <=8192 bytes; HTTP close <=3s, process/port observation wait <=5s'],
      cancellation: 'Abort before durable submission refuses; after submission remains queryable/unknown and never automatically resends a close',
    },
    recovery: {method: 'Call structure_viewer_close with the exact original request_id and object_id; never structure_result and never a new-ID retry', tool: 'structure_viewer_close', idField: 'request_id', scope: 'Configured structure workspace owned viewer close-request namespace and original shared helper'},
  };
}

export function createStructureModule({structureWorkspace, workspaceOptions, viewerAssetPath = process.env.DM_STRUCTURE_VIEWER_ASSET, attachViewer = attachStructureViewer, closeViewer = closeStructureViewer} = {}) {
  const runtime = structureWorkspace ?? new StructureWorkspace(workspaceOptions);
  if (!runtime || typeof runtime.call !== 'function') throw new TypeError('Structure module requires a StructureWorkspace-compatible call method');
  if (typeof attachViewer !== 'function' || typeof closeViewer !== 'function') throw new TypeError('Structure module requires its existing viewer attachment/close handlers');
  return {
    id: 'structures', enabled: true, workspace: runtime,
    instructions: STRUCTURE_INSTRUCTIONS,
    tools: [
      ...structureTools.map(definition => ({
        definition, contract: contract(definition.name, runtime.workspace),
        execute: async (args, {signal} = {}) => {
          const result = await runtime.call(definition.name, args, signal);
          if (definition.name === 'structure_view' && args.interactive === true) {
            return attachViewer(result, {workspace: runtime.workspace, assetPath: viewerAssetPath, inspect: object_id => runtime.call('structure_info', {object_id, include_atoms: true}), signal});
          }
          return result;
        },
      })),
      ...structureViewerTools.map(definition => ({definition, contract: viewerCloseContract(runtime.workspace), execute: (args, {signal} = {}) => closeViewer(args, {workspace: runtime.workspace, signal})})),
    ],
  };
}
