// Deterministic registration/dispatch tests. The stdio fixture below is a
// constant test-only scientific-output envelope, not a scientific algorithm,
// public tool, DM connection, Python worker or browser interaction.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync, copyFileSync, mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ToolRegistry, checkSchema} from '../lib/runtime/tool_registry.mjs';
import {RpcError, tool} from '../lib/runtime/schema.mjs';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';
import {builtinModules} from '../lib/tools/builtin_modules.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const serverFile = path.join(root, 'server.mjs');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const schema = () => ({type: 'object', properties: {value: {type: 'number', minimum: -10, maximum: 10}}, required: ['value'], additionalProperties: false});
const contract = () => ({
  backend: 'test-fixture-only', inputs: ['ScalarFixtureRef:image pixel coordinates'], outputs: ['ConstantScientificFixture:not a scientific calculation'],
  effects: {kind: 'inspect-fixture', sourceMutation: false, requestId: 'none'},
  gates: ['Fixture only; runtime qualification remains delegated and unprobed'],
  execution: {resourceKeys: ['test-fixture'], serialization: 'Test-local handler only; no worker queue', budgets: ['One finite scalar in -10..10'], cancellation: 'Signal is forwarded unchanged'},
  recovery: {method: 'Read the same test fixture; no mutation', tool: null, idField: null, scope: 'This test only'},
});
const entry = (name = 'test_core', execute = args => ({content: [{type: 'text', text: JSON.stringify(args)}]})) => ({
  definition: {name, description: 'Test-only immutable scalar fixture', inputSchema: schema()}, contract: contract(), execute,
});
const moduleFor = (id = 'test-core', entries = [entry()]) => ({id, enabled: true, instructions: 'Test-only module instruction', tools: entries});

function assertUnchanged(registry, baseline, name = 'test_core') {
  assert.deepEqual(registry.listTools(), baseline);
  assert.equal(registry.describe(name)?.moduleId, 'test-core');
}

test('duplicate module rejection leaves the original catalog/handler and rejects the entire candidate', async () => {
  const response = {content: [{type: 'text', text: 'original'}]};
  const registry = new ToolRegistry().register(moduleFor('test-core', [entry('test_core', () => response)]));
  const before = registry.listTools();
  assert.throws(() => registry.register(moduleFor('test-core', [entry('test_other')])), /duplicate module/);
  assertUnchanged(registry, before);
  assert.equal(registry.describe('test_other'), null);
  assert.equal(await registry.call('test_core', {value: 1}), response);
});

test('duplicate existing tool after a valid new entry rejects registration atomically', async () => {
  const registry = new ToolRegistry().register(moduleFor()), before = registry.listTools();
  assert.throws(() => registry.register(moduleFor('test-candidate', [entry('test_new'), entry('test_core')])), /duplicate tool/);
  assertUnchanged(registry, before);
  assert.equal(registry.describe('test_new'), null);
  await assert.rejects(registry.call('test_new', {value: 1}), error => error instanceof RpcError && error.code === -32602);
  registry.register(moduleFor('test-candidate', [entry('test_new')]));
  assert.equal(registry.describe('test_new').moduleId, 'test-candidate', 'a rejected candidate did not retain its module ID');
});

test('duplicate names inside one candidate cannot partially register its first handler', () => {
  const registry = new ToolRegistry();
  assert.throws(() => registry.register(moduleFor('test-candidate', [entry('test_new'), entry('test_new')])), /duplicate tool/);
  assert.deepEqual(registry.listTools(), []);
  assert.equal(registry.describe('test_new'), null);
});

for (const [label, alter] of [
  ['missing handler', candidate => {delete candidate.tools[1].execute;}],
  ['nonfunction handler', candidate => {candidate.tools[1].execute = true;}],
  ['missing contract', candidate => {delete candidate.tools[1].contract;}],
  ['missing backend', candidate => {delete candidate.tools[1].contract.backend;}],
  ['invalid source-mutation declaration', candidate => {candidate.tools[1].contract.effects.sourceMutation = 'false';}],
  ['invalid request-identity declaration', candidate => {candidate.tools[1].contract.effects.requestId = 'generate-later';}],
  ['missing execution constraints', candidate => {delete candidate.tools[1].contract.execution;}],
  ['missing original recovery namespace', candidate => {delete candidate.tools[1].contract.recovery.tool;}],
  ['nonfinite metadata', candidate => {candidate.tools[1].contract.extra = Infinity;}],
  ['executable metadata', candidate => {candidate.tools[1].contract.extra = () => 'forbidden';}],
  ['cyclic metadata', candidate => {candidate.tools[1].contract.extra = candidate.tools[1].contract;}],
  ['undefined object metadata', candidate => {candidate.tools[1].contract.extra = undefined;}],
  ['undefined array metadata', candidate => {candidate.tools[1].contract.extra = [undefined];}],
  ['Date metadata', candidate => {candidate.tools[1].definition.inputSchema.properties.value.enum = [new Date('2020-01-01T00:00:00Z')];}],
  ['Map metadata', candidate => {candidate.tools[1].contract.extra = new Map([['key', 'value']]);}],
  ['Set metadata', candidate => {candidate.tools[1].contract.extra = new Set(['value']);}],
  ['RegExp metadata', candidate => {candidate.tools[1].contract.extra = /not-json/;}],
  ['class-instance metadata', candidate => {candidate.tools[1].contract.extra = new (class Record { constructor() {this.value = 1;} })();}],
  ['sparse metadata array', candidate => {candidate.tools[1].contract.extra = ['value', , 'other'];}],
  ['sparse gate array', candidate => {candidate.tools[1].contract.gates = new Array(1);}],
]) {
  test(`invalid second entry rejects every candidate entry atomically: ${label}`, () => {
    const registry = new ToolRegistry().register(moduleFor()), before = registry.listTools();
    const candidate = moduleFor('test-candidate', [entry('test_first'), entry('test_invalid')]);
    alter(candidate);
    assert.throws(() => registry.register(candidate), TypeError);
    assertUnchanged(registry, before);
    assert.equal(registry.describe('test_first'), null);
    assert.equal(registry.describe('test_invalid'), null);
    assert.equal(registry.instructions(), 'Test-only module instruction');
  });
}

for (const enabled of [undefined, false, 1, 'true']) {
  test(`module must be explicitly enabled with boolean true: ${String(enabled)}`, () => {
    const registry = new ToolRegistry(), candidate = moduleFor();
    if (enabled === undefined) delete candidate.enabled;
    else candidate.enabled = enabled;
    assert.throws(() => registry.register(candidate), /explicitly enabled/);
    assert.deepEqual(registry.listTools(), []);
  });
}

for (const [label, invalid] of [
  ['nonobject tool arguments', {type: 'string'}],
  ['missing root type', {properties: {}}],
  ['invalid scalar type', {type: 'object', properties: {x: {type: 'float'}}}],
  ['empty property schema', {type: 'object', properties: {x: {}}}],
  ['untyped property schema', {type: 'object', properties: {x: {minimum: 0}}}],
  ['array without items', {type: 'object', properties: {x: {type: 'array'}}}],
  ['empty array item schema', {type: 'object', properties: {x: {type: 'array', items: {}}}}],
  ['required nonexistent field', {type: 'object', properties: {}, required: ['x']}],
  ['duplicate required field', {type: 'object', properties: {x: {type: 'number'}}, required: ['x', 'x']}],
  ['reversed numeric budget', {type: 'object', properties: {x: {type: 'number', minimum: 2, maximum: 1}}}],
  ['fractional length bound', {type: 'object', properties: {x: {type: 'string', minLength: .5}}}],
  ['nonboolean additionalProperties', {type: 'object', properties: {}, additionalProperties: 'false'}],
  ['empty enum', {type: 'object', properties: {x: {type: 'string', enum: []}}}],
  ['invalid pattern', {type: 'object', properties: {x: {type: 'string', pattern: '['}}}],
  ['empty oneOf', {type: 'object', properties: {}, oneOf: []}],
]) {
  test(`bad schema rejected before publication: ${label}`, () => {
    const registry = new ToolRegistry().register(moduleFor()), before = registry.listTools();
    const bad = entry('test_invalid'); bad.definition.inputSchema = invalid;
    assert.throws(() => registry.register(moduleFor('test-invalid', [entry('test_partial'), bad])));
    assertUnchanged(registry, before);
    assert.equal(registry.describe('test_partial'), null);
    assert.equal(registry.describe('test_invalid'), null);
  });
}

test('overdeep schema is rejected without changing the prior module', () => {
  const registry = new ToolRegistry().register(moduleFor()), bad = entry('test_deep'), before = registry.listTools();
  let nested = {type: 'number'};
  for (let i = 0; i < 34; i++) nested = {type: 'array', items: nested};
  bad.definition.inputSchema.properties.value = nested;
  assert.throws(() => registry.register(moduleFor('test-deep', [bad])), /overdeep/);
  assertUnchanged(registry, before);
});

test('legacy compound-schema fragments are admitted without claiming new cross-field enforcement', () => {
  const value = {type: 'object', properties: {left: {type: 'number'}, right: {type: 'number'}},
    oneOf: [{required: ['left'], not: {required: ['right']}}, {required: ['right'], not: {required: ['left']}}]};
  assert.doesNotThrow(() => checkSchema(value));
  // Existing worker-specific oneOf/scientific validation remains delegated;
  // the extracted legacy scalar validator is deliberately unchanged.
});

test('registration snapshots definitions/contracts deeply and returned metadata cannot alter dispatch', async () => {
  const response = {content: [{type: 'text', text: 'original-handler'}]}, candidate = moduleFor('test-core', [entry('test_core', () => response)]);
  const registry = new ToolRegistry().register(candidate), before = registry.listTools(), description = registry.describe('test_core');
  candidate.id = 'changed'; candidate.instructions = 'changed'; candidate.tools[0].definition.name = 'renamed';
  candidate.tools[0].definition.inputSchema.properties.value.minimum = 100;
  candidate.tools[0].contract.inputs[0] = 'wrong-grid';
  candidate.tools[0].contract.execution.budgets.push('invented-budget');
  candidate.tools[0].contract.effects.sourceMutation = true;
  candidate.tools[0].execute = () => assert.fail('replacement handler');
  const listed = registry.listTools(), described = registry.describe('test_core'), all = registry.describeAll();
  listed[0].inputSchema.properties.value.maximum = -100;
  described.outputs.push('invented-output'); described.execution.resourceKeys[0] = 'wrong-resource';
  described.availability.runtimeQualification = 'supported';
  all[0].recovery.scope = 'wrong-scope';
  assertUnchanged(registry, before);
  assert.deepEqual(registry.describe('test_core'), description);
  assert.equal(registry.instructions(), 'Test-only module instruction');
  assert.equal(registry.describe('renamed'), null);
  assert.equal(await registry.call('test_core', {value: 1}), response);
});

test('contract extras cannot spoof the registry-owned tool/module identity, version or qualification', () => {
  const candidate = moduleFor();
  Object.assign(candidate.tools[0].contract, {name: 'spoofed_tool', moduleId: 'spoofed-module', contractVersion: 999,
    availability: {registered: true, runtimeQualification: 'supported', authority: 'untrusted assertion'}});
  const registry = new ToolRegistry().register(candidate);
  const described = registry.describe('test_core');
  assert.equal(described.name, 'test_core');
  assert.equal(described.moduleId, 'test-core');
  assert.equal(described.contractVersion, 1);
  assert.deepEqual(described.availability, {registered: true, runtimeQualification: 'not_probed', authority: 'Existing adapter validates each actual call; catalog presence is not qualification'});
  assert.equal(registry.describe('spoofed_tool'), null);
  assert.deepEqual(registry.listTools().map(tool => tool.name), ['test_core']);
});

test('schema refusals happen before handlers and preserve legacy RpcError diagnostics', async () => {
  let calls = 0;
  const registry = new ToolRegistry().register(moduleFor('test-core', [entry('test_core', () => {calls++;})]));
  for (const [args, message] of [
    [{}, /arguments.value: 缺少必填参数/],
    [{value: '1'}, /arguments.value: 类型应为 number/],
    [{value: 11}, /arguments.value: 超出允许范围/],
    [{value: 1, unrelated: true}, /arguments.unrelated: 未知参数/],
  ]) {
    await assert.rejects(registry.call('test_core', args), error => error instanceof RpcError && error.code === -32602 && message.test(error.message));
  }
  assert.equal(calls, 0);
});

test('dispatch forwards exact argument reference, AbortSignal, error and response without fallback', async () => {
  const signal = new AbortController().signal, args = {value: 2}, failure = new Error('scientific contract refused'), response = {content: []};
  let primary = 0, unrelated = 0, received;
  const registry = new ToolRegistry().register(moduleFor('test-core', [entry('test_core', (value, context) => {
    primary++; received = [value, context.signal]; throw failure;
  })])).register(moduleFor('test-unrelated', [entry('test_other_backend', () => {unrelated++; return response;})]));
  await assert.rejects(registry.call('test_core', args, {signal}), error => error === failure);
  assert.equal(received[0], args); assert.equal(received[1], signal);
  assert.equal(primary, 1); assert.equal(unrelated, 0);
  await assert.rejects(registry.call('unknown_tool', {value: 2}, {signal}), error => error instanceof RpcError && error.code === -32602);
  assert.equal(primary, 1); assert.equal(unrelated, 0);
  assert.equal(await registry.call('test_other_backend', args, {signal}), response);
});

test('registered handler sees the original signal abort rather than a replacement cancellation object', async () => {
  const controller = new AbortController(), cancellation = new Error('original handler abort'), args = {value: 1};
  let received;
  const registry = new ToolRegistry().register(moduleFor('test-core', [entry('test_core', (value, {signal}) => {
    received = [value, signal];
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(cancellation), {once: true}));
  })]));
  const pending = registry.call('test_core', args, {signal: controller.signal});
  controller.abort();
  await assert.rejects(pending, error => error === cancellation);
  assert.equal(received[0], args); assert.equal(received[1], controller.signal);
});

test('adding/removing an optional module changes only its catalog and handler ownership', async () => {
  let closed = 0;
  const coreResponse = {content: [{type: 'text', text: 'core'}]}, optionalResponse = {content: [{type: 'text', text: 'optional'}]};
  const registry = new ToolRegistry().register(moduleFor('test-core', [entry('test_core', () => coreResponse)]));
  const before = registry.listTools();
  registry.register({...moduleFor('test-optional', [entry('test_optional', () => optionalResponse)]), instructions: 'Optional only', close() {closed++;}});
  assert.deepEqual(registry.listTools().map(t => t.name), ['test_core', 'test_optional']);
  assert.equal(await registry.call('test_optional', {value: 1}), optionalResponse);
  assert.equal(await registry.call('test_core', {value: 1}), coreResponse);
  assert.equal(registry.unregister('test-optional'), true);
  assert.equal(closed, 1); assertUnchanged(registry, before);
  assert.equal(registry.instructions(), 'Test-only module instruction');
  assert.equal(registry.unregister('test-optional'), false);
  assert.equal(closed, 1);
  await assert.rejects(registry.call('test_optional', {value: 1}), error => error instanceof RpcError && error.code === -32602);
  registry.register(moduleFor('test-optional', [entry('test_optional_replacement', () => optionalResponse)]));
  assert.deepEqual(registry.listTools().map(t => t.name), ['test_core', 'test_optional_replacement']);
  assert.equal(registry.describe('test_optional'), null);
});

test('sealed registry composition cannot add or remove handlers while dispatch stays usable', async () => {
  const registry = new ToolRegistry().register(moduleFor()).seal(), before = registry.listTools();
  assert.throws(() => registry.register(moduleFor('test-late', [entry('test_late')])), /sealed/);
  assert.throws(() => registry.unregister('test-core'), /sealed/);
  assertUnchanged(registry, before);
  assert.equal(registry.describe('test_late'), null);
  assert.deepEqual(JSON.parse((await registry.call('test_core', {value: 1})).content[0].text), {value: 1});
});

test('runtime seals explicit additional modules and rejects undeclared or core disables', () => {
  const env = {DM_MCP_BACKEND: 'images'}, disabledModules = ['images', 'image-panel', 'structures'];
  const runtime = createServerRuntime({env, disabledModules, additionalModules: [moduleFor()]});
  try {
    assert.deepEqual(runtime.registry.listTools().map(t => t.name), ['test_core']);
    assert.throws(() => runtime.registry.register(moduleFor('test-late', [entry('late')])), /sealed/);
    assert.throws(() => runtime.registry.unregister('test-core'), /sealed/);
    for (const id of ['unregistered-directory', 'dm-python', 'dm-native']) assert.throws(() => createServerRuntime({env, disabledModules: [id]}), /Cannot disable unknown or core module/);
    assert.throws(() => createServerRuntime({env, disabledModules, additionalModules: [moduleFor(), moduleFor()]}), /duplicate module/);
    assert.throws(() => createServerRuntime({env, disabledModules, additionalModules: {}}), /explicitly supplied trusted module/);
  } finally {runtime.close();}
});

test('all built-in declared gates remain explicitly unprobed for Python/native/image compositions', () => {
  for (const backend of ['python', 'native', 'images']) {
    const folder = path.join(tmpdir(), 'registry-uncreated-' + backend + '-' + process.pid);
    const runtime = createServerRuntime({env: {DM_MCP_BACKEND: backend, DM_NATIVE_SESSION: 'a'.repeat(32), DM_IMAGE_WORKSPACE: path.join(folder, 'images'), DM_STRUCTURE_WORKSPACE: path.join(folder, 'structures')}});
    try {
      const descriptions = runtime.registry.describeAll();
      assert.ok(descriptions.length > 20);
      assert.deepEqual(runtime.registry.listTools().map(t => t.name), descriptions.map(t => t.name));
      for (const description of descriptions) {
        assert.equal(description.contractVersion, 1);
        assert.deepEqual(description.availability, {registered: true, runtimeQualification: 'not_probed', authority: 'Existing adapter validates each actual call; catalog presence is not qualification'});
        assert.ok(description.gates.length > 0, description.name);
      }
      assert.equal(existsSync(folder), false, 'catalog creation performs no workspace I/O');
    } finally {runtime.close();}
  }
});

test('explicit composition env isolates image/structure Python and absent viewer assets from ambient env', async () => {
  const keys = ['DM_IMAGE_PYTHON', 'DM_ANALYSIS_PYTHON', 'DM_STRUCTURE_PYTHON', 'DM_STRUCTURE_VIEWER_ASSET'];
  const saved = new Map(keys.map(key => [key, process.env[key]]));
  const folder = path.join(tmpdir(), 'registry-env-uncreated-' + process.pid);
  try {
    process.env.DM_IMAGE_PYTHON = '__ambient_image_python_must_not_be_used__';
    process.env.DM_ANALYSIS_PYTHON = '__ambient_analysis_python_must_not_be_used__';
    process.env.DM_STRUCTURE_PYTHON = '__ambient_structure_python_must_not_be_used__';
    process.env.DM_STRUCTURE_VIEWER_ASSET = '__ambient_viewer_asset_must_not_be_used__';
    const env = {DM_MCP_BACKEND: 'images', DM_IMAGE_WORKSPACE: path.join(folder, 'images'), DM_STRUCTURE_WORKSPACE: path.join(folder, 'structures'), DM_ANALYSIS_PYTHON: '__explicit_analysis_python__'};
    const modules = builtinModules({env, backend: 'images', disabled: new Set(['image-panel'])});
    const images = modules.find(module => module.id === 'images'), structures = modules.find(module => module.id === 'structures');
    assert.equal(images.workspace.python, env.DM_ANALYSIS_PYTHON, 'provided analysis Python is the image fallback');
    assert.equal(structures.workspace.python, 'python', 'missing structure Python uses its declared default, not ambient env');
    const metadata = {backend: 'external-structure-workspace', state: 'completed', kind: 'view', object_id: 'a'.repeat(32), structure_object_id: 'b'.repeat(32)};
    structures.workspace.call = async () => ({content: [{type: 'text', text: JSON.stringify(metadata)}]});
    const view = await structures.tools.find(tool => tool.definition.name === 'structure_view').execute({object_id: metadata.structure_object_id, request_id: 'test-env-view', interactive: true});
    assert.equal(JSON.parse(view.content[0].text).interactive_3d, 'NOT_CONFIGURED', 'absent provided asset does not inherit ambient asset and start a helper');
    const explicit = builtinModules({env: {...env, DM_IMAGE_PYTHON: '__explicit_image_python__', DM_STRUCTURE_PYTHON: '__explicit_structure_python__'}, backend: 'images', disabled: new Set(['image-panel'])});
    assert.equal(explicit.find(module => module.id === 'images').workspace.python, '__explicit_image_python__');
    assert.equal(explicit.find(module => module.id === 'structures').workspace.python, '__explicit_structure_python__');
    const defaults = builtinModules({env: {DM_MCP_BACKEND: 'images', DM_IMAGE_WORKSPACE: path.join(folder, 'default-images')}, backend: 'images', disabled: new Set(['image-panel'])});
    assert.equal(defaults[0].workspace.python, 'python', 'absent image and analysis env does not inherit ambient values');
    assert.equal(existsSync(folder), false);
  } finally {
    for (const [key, value] of saved) {if (value === undefined) delete process.env[key]; else process.env[key] = value;}
  }
});

function stdioClient(bootstrap, enabled) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('DM_')));
  Object.assign(env, {DM_MCP_BACKEND: 'images', DM_IMAGE_PYTHON: '__must_not_launch_python__', DM_STRUCTURE_PYTHON: '__must_not_launch_python__', REGISTRY_FIXTURE_ENABLED: enabled ? '1' : '0'});
  const child = spawn(process.execPath, [bootstrap], {cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true});
  const pending = new Map(), observed = [];
  let next = 1, buffer = '', stderr = '';
  child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => {stderr += chunk;}); child.stdin.on('error', () => {});
  child.stdout.on('data', chunk => {
    buffer += chunk; let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      let row;
      try {row = JSON.parse(line);} catch (error) {for (const wait of pending.values()) {clearTimeout(wait.timer); wait.reject(error);} pending.clear(); continue;}
      observed.push(row);
      const wait = pending.get(row.id);
      if (wait) {pending.delete(row.id); clearTimeout(wait.timer); wait.resolve(row);}
    }
  });
  const ended = new Promise((resolve, reject) => {child.once('error', reject); child.once('exit', (code, signal) => resolve({code, signal}));});
  const rpc = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++, timer = setTimeout(() => {pending.delete(id); reject(new Error('stdio fixture timeout: ' + stderr));}, 10000);
    pending.set(id, {resolve, reject, timer}); child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
  });
  return {rpc, observed, async close() {child.stdin.end(); const result = await ended; for (const wait of pending.values()) {clearTimeout(wait.timer); wait.reject(new Error('stdio fixture closed'));} pending.clear(); return result;}};
}

test('real stdio bootstrap adds/removes an explicit trusted fixture without a server dispatch edit', async t => {
  const before = sha(readFileSync(serverFile));
  const folder = mkdtempSync(path.join(tmpdir(), 'mcp-dm-registry-bootstrap-'));
  const bootstrap = path.join(folder, 'bootstrap.mjs');
  const definition = tool('test_registry_science_fixture', 'Test-only constant scientific-output envelope; no algorithm or public support claim', {sample_ref: {type: 'string', enum: ['constant-2x2']}}, ['sample_ref']);
  const fixture = {definition, contract: contract()};
  writeFileSync(bootstrap, [
    `import {startMcpServer} from ${JSON.stringify(pathToFileURL(serverFile).href)};`,
    `import {createServerRuntime} from ${JSON.stringify(pathToFileURL(path.join(root, 'lib/tools/create_server_runtime.mjs')).href)};`,
    `const fixture = ${JSON.stringify(fixture)};`,
    `let calls=0; fixture.execute=async args=>({content:[{type:'text',text:JSON.stringify({backend:'test-fixture-only',fixture_only:true,scientific_calculation:false,dm_called:false,worker_started:false,call_number:++calls,input_ref:args.sample_ref,scientific_array_ref:{kind:'ConstantFixtureRef',dtype:'float32',shape_yx:[2,2],axes:['y','x'],coordinate_domain:'image_pixels',values:[1,2,3,4]}})}]});`,
    `const module={id:'test-only-science-fixture',enabled:true,instructions:'Test-only explicit fixture; not scientific qualification',tools:[fixture]};`,
    `const runtime=createServerRuntime({env:process.env,disabledModules:['images','image-panel','structures'],additionalModules:process.env.REGISTRY_FIXTURE_ENABLED==='1'?[module]:[]});`,
    `startMcpServer({runtime});`,
  ].join('\n'));
  try {
    for (const enabled of [true, false]) {
      const client = stdioClient(bootstrap, enabled);
      try {
        const initialized = await client.rpc('initialize');
        assert.equal(initialized.error, undefined);
        assert.equal(initialized.result.instructions.includes('Test-only explicit fixture'), enabled);
        const listed = await client.rpc('tools/list');
        assert.deepEqual(listed.result.tools, enabled ? [definition] : []);
        const called = await client.rpc('tools/call', {name: definition.name, arguments: {sample_ref: 'constant-2x2'}});
        if (enabled) {
          assert.equal(called.error, undefined); assert.equal(called.result.isError, undefined);
          const result = JSON.parse(called.result.content[0].text);
          assert.deepEqual(result.scientific_array_ref, {kind: 'ConstantFixtureRef', dtype: 'float32', shape_yx: [2, 2], axes: ['y', 'x'], coordinate_domain: 'image_pixels', values: [1, 2, 3, 4]});
          assert.equal(result.call_number, 1); assert.equal(result.fixture_only, true); assert.equal(result.scientific_calculation, false);
          assert.equal(result.dm_called, false); assert.equal(result.worker_started, false);
          const invalid = await client.rpc('tools/call', {name: definition.name, arguments: {sample_ref: 'different-fixture'}});
          assert.equal(invalid.error?.code, -32602);
          const again = await client.rpc('tools/call', {name: definition.name, arguments: {sample_ref: 'constant-2x2'}});
          assert.equal(JSON.parse(again.result.content[0].text).call_number, 2, 'invalid arguments never dispatched');
        } else {
          assert.equal(called.error?.code, -32602, 'removed fixture is refused by unchanged generic dispatch');
        }
        for (const name of ['dm_status', 'image_info', 'structure_info']) {
          const absent = await client.rpc('tools/call', {name, arguments: {}});
          assert.equal(absent.error?.code, -32602, 'no optional or DM fallback: ' + name);
        }
        assert.deepEqual((await client.rpc('ping')).result, {});
        assert.ok(client.observed.every(row => row.jsonrpc === '2.0'));
      } finally {assert.deepEqual(await client.close(), {code: 0, signal: null});}
    }
    assert.equal(sha(readFileSync(serverFile)), before);
    t.diagnostic('Unchanged server.mjs SHA-256 before/after explicit stdio module add/remove: ' + before);
  } finally {
    const resolved = path.resolve(folder), expectedRoot = path.resolve(tmpdir()) + path.sep;
    assert.ok(resolved.startsWith(expectedRoot) && path.basename(resolved).startsWith('mcp-dm-registry-bootstrap-'), 'cleanup stays inside the test temporary directory');
    rmSync(resolved, {recursive: true, force: true});
  }
});

test('generic registry/schema run after copying only their two files into an isolated directory', t => {
  const folder = mkdtempSync(path.join(tmpdir(), 'portable-tool-contracts-'));
  const runtime = path.join(folder, 'runtime'); mkdirSync(runtime);
  copyFileSync(path.join(root, 'lib/runtime/schema.mjs'), path.join(runtime, 'schema.mjs'));
  copyFileSync(path.join(root, 'lib/runtime/tool_registry.mjs'), path.join(runtime, 'tool_registry.mjs'));
  const smoke = path.join(folder, 'smoke.mjs');
  writeFileSync(smoke, [
    `import {ToolRegistry} from './runtime/tool_registry.mjs';`,
    `import {tool} from './runtime/schema.mjs';`,
    `const definition=tool('portable_fixture','Portable test only',{value:{type:'number'}},['value']);`,
    `const contract=${JSON.stringify(contract())};`,
    `const registry=new ToolRegistry().register({id:'portable-fixture',enabled:true,instructions:'Portable fixture only',tools:[{definition,contract,execute:args=>({fixture_only:true,observed_value:args.value})}]}).seal();`,
    `const result=await registry.call('portable_fixture',{value:3});`,
    `console.log(JSON.stringify({result,catalog:registry.listTools(),description:registry.describe('portable_fixture')}));`,
  ].join('\n'));
  try {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('DM_')));
    const result = JSON.parse(execFileSync(process.execPath, [smoke], {cwd: folder, env, encoding: 'utf8', windowsHide: true, timeout: 10000, maxBuffer: 1024 * 1024}));
    assert.deepEqual(result.result, {fixture_only: true, observed_value: 3});
    assert.deepEqual(result.catalog.map(tool => tool.name), ['portable_fixture']);
    assert.equal(result.description.contractVersion, 1);
    assert.equal(result.description.backend, 'test-fixture-only');
    assert.equal(result.description.availability.runtimeQualification, 'not_probed');
    for (const absent of ['server.mjs', 'lib', 'tools', 'node_modules', 'GMS']) assert.equal(existsSync(path.join(folder, absent)), false, absent + ' is not copied or required');
    t.diagnostic('Portable smoke used only copied schema.mjs and tool_registry.mjs, with no server/tools/GMS tree');
  } finally {
    const resolved = path.resolve(folder), expectedRoot = path.resolve(tmpdir()) + path.sep;
    assert.ok(resolved.startsWith(expectedRoot) && path.basename(resolved).startsWith('portable-tool-contracts-'));
    rmSync(resolved, {recursive: true, force: true});
  }
});
