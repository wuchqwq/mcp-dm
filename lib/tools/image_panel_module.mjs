// Panel presentation is an explicit optional module, not a science fallback or
// another image state database. Existing manager/HTTP guards remain in place.
import {ImagePanelManager, imagePanelTools, IMAGE_PANEL_INSTRUCTIONS} from '../image_panel_mcp.mjs';

const recipes = {
  image_panel_open: {
    inputs: ['ImageViewRef or ScientificObjectRef:existing exact image object', 'OperationReceipt:pre-saved panel request_id'],
    outputs: ['PanelRef:owned token-protected loopback URL and panel_id', 'DisplayPNG:saved immutable view; not unsaved gesture/tone drafts'],
    kind: 'owned-panel-launch', requestId: 'required',
    gates: ['Existing image_info inspection before durable launch intent; no arbitrary path/script/URL parameter', 'Absolute independent Python required for actual panel launch; same request/arguments recovers rather than relaunches'],
    serialization: 'ImagePanelManager deduplicates each original request ID and durable panel intent; no new global queue',
    recovery: {method: 'Repeat image_panel_open with the exact original request_id and object_id; inspect its original live panel without launching another', tool: 'image_panel_open', idField: 'request_id', scope: 'Configured image workspace panel registry; an absent/stopped helper is not automatically restarted'},
  },
  image_panel_current: {
    inputs: ['PanelRef:explicit panel_id, or exactly one live registered panel'],
    outputs: ['PanelSelectionRef:exact current object, source/frequency coordinates, draft revision and dirty status', 'DisplayPNG:saved view only; not a fresh screenshot or unsaved local display'],
    kind: 'inspect-panel-state', requestId: 'none',
    gates: ['Owned connection token and returned panel/object identity; no recency-based selection if zero/multiple live panels', 'No automatic model wake; image selection remains independent from scientific interpretation'],
    serialization: 'Live state GETs use existing manager; no scientific write queue. Manager may initialize its auxiliary registry directories',
    recovery: {method: 'Read current state again using the retained panel_id; this is not recovery of a scientific operation', tool: 'image_panel_current', idField: 'panel_id', scope: 'Currently live registered owned panel; exact one-panel omission rule'},
  },
  image_panel_show: {
    inputs: ['PanelRef:explicit retained panel_id', 'ImageViewRef:existing result object', 'PanelSelectionRef:expected_object_id and draft_revision', 'OperationReceipt:pre-saved presentation request_id'],
    outputs: ['PresentationReceipt:shown or queued, with original immutable presentation snapshot', 'DisplayPNG:saved immutable view, not scientific array'],
    kind: 'panel-presentation', requestId: 'required',
    gates: ['Existing image_info inspection, owned panel identity and exact presentation request arguments', 'Existing HTTP compare/draft checks queue dirty or newer drafts instead of overwriting them; queued is not shown'],
    serialization: 'Existing request-ID deduplication plus panel compare/draft guard; unrelated observation is not locked by this adapter',
    recovery: {method: 'Repeat image_panel_show with exactly the original arguments; query its original receipt, then image_panel_current for latest state', tool: 'image_panel_show', idField: 'request_id', scope: 'Configured image workspace panel request registry and owned helper; no automatic resubmission'},
  },
};

function contract(name, manager) {
  const recipe = recipes[name];
  if (!recipe) throw new Error(`Missing image panel module contract for ${name}`);
  return {
    backend: 'external-image-tools', inputs: [...recipe.inputs], outputs: [...recipe.outputs],
    effects: {kind: recipe.kind, sourceMutation: false, requestId: recipe.requestId},
    gates: ['Delegated per-call ImagePanelManager and owned helper guards; metadata does not certify a running viewer or model vision', ...recipe.gates],
    execution: {
      resourceKeys: [`image-panel-registry:${manager.workspace}`], serialization: recipe.serialization,
      budgets: ['Existing manager: response/private record <=20 MiB; saved PNG base64 <=6 MiB; connection record <=4096 bytes', 'Panel omission inspects <=100 registry entries; GET deadline <=3s; launch/presentation waits use configured manager deadlines'],
      cancellation: 'Abort before submission refuses. After start only stop waiting; durable open/show may finish. Recover with the same tool and original arguments, never a new-ID retry',
    },
    recovery: {...recipe.recovery},
  };
}

export function createImagePanelModule({imageWorkspace, manager, managerOptions} = {}) {
  let runtime = manager;
  if (!runtime) {
    if (!imageWorkspace || typeof imageWorkspace.call !== 'function') throw new TypeError('Image panel module requires its existing image workspace');
    runtime = new ImagePanelManager({
      ...managerOptions, workspace: imageWorkspace.workspace, python: imageWorkspace.python,
      inspect: async object_id => {
        const result = await imageWorkspace.call('image_info', {object_id});
        if (result.isError) throw new Error('Image object inspection failed');
      },
    });
  }
  if (typeof runtime.call !== 'function') throw new TypeError('Image panel module requires an ImagePanelManager-compatible call method');
  return {
    id: 'image-panel', enabled: true, manager: runtime,
    instructions: IMAGE_PANEL_INSTRUCTIONS,
    tools: imagePanelTools.map(definition => ({definition, contract: contract(definition.name, runtime), execute: (args, {signal} = {}) => runtime.call(definition.name, args, signal)})),
  };
}
