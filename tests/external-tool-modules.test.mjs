// Registration adapters only: fakes exercise wiring without scientific workers,
// browser helpers, DM, input arrays or creation of workspace directories.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImageModule} from '../lib/tools/image_module.mjs';
import {createImagePanelModule} from '../lib/tools/image_panel_module.mjs';
import {createStructureModule} from '../lib/tools/structure_module.mjs';
import {imageTools, IMAGE_INSTRUCTIONS} from '../lib/image_workspace.mjs';
import {imagePanelTools, IMAGE_PANEL_INSTRUCTIONS} from '../lib/image_panel_mcp.mjs';
import {structureTools, STRUCTURE_INSTRUCTIONS} from '../lib/structure_workspace.mjs';
import {structureViewerTools} from '../lib/structure_viewer_client.mjs';

const freshPath = () => path.join(tmpdir(), 'mcp-dm-module-not-created-' + randomUUID());
const fake = () => ({workspace: freshPath(), python: process.execPath, call() { throw Error('unexpected call'); }});
const entry = (module, name) => module.tools.find(tool => tool.definition.name === name);

test('external module factories preserve catalog objects and have no constructor I/O', () => {
  const imagePath = freshPath(), structurePath = freshPath();
  const images = createImageModule({workspaceOptions: {workspace: imagePath}});
  const panels = createImagePanelModule({imageWorkspace: images.workspace});
  const structures = createStructureModule({workspaceOptions: {workspace: structurePath}});
  for (const [module, id, definitions, instructions] of [
    [images, 'images', imageTools, IMAGE_INSTRUCTIONS],
    [panels, 'image-panel', imagePanelTools, IMAGE_PANEL_INSTRUCTIONS],
    [structures, 'structures', [...structureTools, ...structureViewerTools], STRUCTURE_INSTRUCTIONS],
  ]) {
    assert.equal(module.id, id);
    assert.equal(module.enabled, true);
    assert.equal(module.instructions, instructions);
    assert.equal(module.close, undefined, 'disconnect must not close surviving owned helpers');
    assert.equal(module.tools.length, definitions.length);
    module.tools.forEach((tool, index) => {
      assert.equal(tool.definition, definitions[index], 'original MCP definition must not be copied or changed');
      assert.equal(typeof tool.execute, 'function');
      const c = tool.contract;
      assert.deepEqual(Object.keys(c).sort(), ['backend', 'effects', 'execution', 'gates', 'inputs', 'outputs', 'recovery']);
      for (const field of ['inputs', 'outputs', 'gates']) assert.ok(c[field].length && c[field].every(v => typeof v === 'string' && v));
      assert.equal(typeof c.backend, 'string');
      assert.equal(c.effects.sourceMutation, false);
      assert.ok(['required', 'optional', 'query', 'none'].includes(c.effects.requestId));
      for (const field of ['resourceKeys', 'budgets']) {
        if (field === 'resourceKeys' && module.id === 'images' && ['image_info', 'image_result'].includes(tool.definition.name)) assert.deepEqual(c.execution[field], [], 'read-only image ports acquire no write resource');
        else assert.ok(c.execution[field].length && c.execution[field].every(v => typeof v === 'string' && v));
      }
      for (const field of ['serialization', 'cancellation']) assert.equal(typeof c.execution[field], 'string');
      assert.ok(c.recovery.method && c.recovery.scope);
    });
  }
  assert.equal(existsSync(imagePath), false);
  assert.equal(existsSync(structurePath), false);
});

test('every image entry forwards exact arguments, signal and existing MCP response', async () => {
  const calls = [], response = {content: [{type: 'text', text: 'unchanged'}]}, signal = new AbortController().signal;
  const runtime = {...fake(), call: (name, args, passedSignal) => { calls.push([name, args, passedSignal]); return response; }};
  const module = createImageModule({imageWorkspace: runtime});
  assert.equal(module.workspace, runtime);
  for (const tool of module.tools) {
    const args = {object_id: 'original-object', request_id: 'saved-before-dispatch'};
    assert.equal(await tool.execute(args, {signal}), response);
    assert.deepEqual(calls.at(-1), [tool.definition.name, args, signal]);
    assert.equal(calls.at(-1)[1], args);
  }
});

test('image adapter does not translate original failures or call another backend', () => {
  const original = new Error('REQUEST_CONFLICT: original worker failure');
  const module = createImageModule({imageWorkspace: {...fake(), call() { throw original; }}});
  assert.throws(() => entry(module, 'image_frame').execute({}), value => value === original);
});

test('panel inspector preserves server image_info/isError semantics and creates no directories', async () => {
  const calls = [], runtime = {...fake(), call: async (...args) => { calls.push(args); return {content: []}; }};
  const module = createImagePanelModule({imageWorkspace: runtime});
  await module.manager.inspect('retained-image');
  assert.deepEqual(calls, [['image_info', {object_id: 'retained-image'}]]);
  assert.equal(existsSync(runtime.workspace), false);
  runtime.call = async () => ({isError: true});
  await assert.rejects(module.manager.inspect('failed-image'), /Image object inspection failed/);
  assert.equal(existsSync(runtime.workspace), false);
});

test('injected panel manager receives exact calls and keeps its recovery namespace', async () => {
  const calls = [], response = {content: []}, signal = new AbortController().signal;
  const manager = {...fake(), call: (...args) => { calls.push(args); return response; }};
  const module = createImagePanelModule({manager});
  assert.equal(module.manager, manager);
  for (const tool of module.tools) {
    const args = {request_id: 'original-panel-request'};
    assert.equal(await tool.execute(args, {signal}), response);
    assert.deepEqual(calls.at(-1), [tool.definition.name, args, signal]);
    assert.equal(tool.contract.recovery.tool, tool.definition.name);
  }
});

test('noninteractive structure entries preserve scientific response and worker calls', async () => {
  const calls = [], response = {content: []}, signal = new AbortController().signal;
  const runtime = {...fake(), call: (...args) => { calls.push(args); return response; }};
  const module = createStructureModule({structureWorkspace: runtime, attachViewer() { assert.fail('unexpected viewer'); }, closeViewer() { assert.fail('unexpected close'); }});
  assert.equal(module.workspace, runtime);
  for (const definition of structureTools) {
    const args = {object_id: 'explicit-object', request_id: 'original-scientific-request'};
    assert.equal(await entry(module, definition.name).execute(args, {signal}), response);
    assert.deepEqual(calls.at(-1), [definition.name, args, signal]);
  }
});

test('interactive structure view attaches only after science and uses the original snapshot inspector', async () => {
  const calls = [], signal = new AbortController().signal, response = {content: []}, attached = {content: [{type: 'text', text: 'attached'}]};
  const runtime = {...fake(), call: async (...args) => { calls.push(args); return response; }};
  let attachment;
  const module = createStructureModule({structureWorkspace: runtime, viewerAssetPath: 'configured-local-asset', attachViewer: async (result, options) => {
    assert.equal(result, response);
    assert.deepEqual(calls[0], ['structure_view', {interactive: true}, signal]);
    attachment = options;
    assert.equal(await options.inspect('fixed-structure'), response);
    return attached;
  }});
  assert.equal(await entry(module, 'structure_view').execute({interactive: true}, {signal}), attached);
  assert.deepEqual(calls[1], ['structure_info', {object_id: 'fixed-structure', include_atoms: true}]);
  assert.equal(attachment.workspace, runtime.workspace);
  assert.equal(attachment.assetPath, 'configured-local-asset');
  assert.equal(attachment.signal, signal);
});

test('owned viewer close uses its existing handler, never the scientific result queue', async () => {
  const signal = new AbortController().signal, runtime = fake(), args = {object_id: 'exact-view', request_id: 'close-original'}, response = {content: []};
  let passed;
  const module = createStructureModule({structureWorkspace: runtime, closeViewer: (value, options) => {passed = [value, options]; return response; }});
  const tool = entry(module, 'structure_viewer_close');
  assert.equal(await tool.execute(args, {signal}), response);
  assert.equal(passed[0], args);
  assert.deepEqual(passed[1], {workspace: runtime.workspace, signal});
  assert.equal(tool.contract.recovery.tool, 'structure_viewer_close');
  assert.equal(entry(module, 'structure_simulate').contract.recovery.tool, 'structure_result');
});

test('scientific contracts retain distinct domains, existing queues and no qualification claim', () => {
  const images = createImageModule({imageWorkspace: fake()}), structures = createStructureModule({structureWorkspace: fake()});
  assert.match(JSON.stringify(entry(images, 'image_fft').contract), /cycles\/pixel/);
  assert.match(JSON.stringify(entry(images, 'image_center').contract), /no external complex FFT/);
  assert.match(JSON.stringify(entry(images, 'image_remeasure').contract), /FFT-producer grid/);
  assert.equal(entry(images, 'image_info').contract.effects.requestId, 'none');
  assert.equal(entry(images, 'image_result').contract.effects.requestId, 'query');
  assert.deepEqual(entry(images, 'image_info').contract.execution.resourceKeys, []);
  assert.deepEqual(entry(images, 'image_result').contract.execution.resourceKeys, []);
  assert.deepEqual(entry(images, 'image_fft').contract.execution.resourceKeys, ['image-workspace:' + images.workspace.workspace]);
  assert.match(entry(images, 'image_result').contract.execution.serialization, /bypass/);
  assert.match(JSON.stringify(entry(structures, 'structure_register').contract), /scale=1/);
  assert.match(JSON.stringify(entry(structures, 'structure_register').contract), /caller assertion/);
  assert.match(JSON.stringify(entry(structures, 'structure_compare').contract), /source_change_basis/);
  assert.match(JSON.stringify(entry(structures, 'structure_simulate').contract), /analytic reciprocal-enumeration certificate/);
  assert.match(entry(structures, 'structure_simulate').contract.gates[0], /Delegated per-call/);
});
