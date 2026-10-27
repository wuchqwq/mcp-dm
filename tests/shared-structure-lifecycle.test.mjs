// Structure transport/Coordinator contract only. Controlled child doubles do
// not prove ASE/diffsims arithmetic, durable journals, browser or DM behavior.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {StructureWorkspace} from '../lib/structure_workspace.mjs';
import {ImageWorkspace} from '../lib/image_workspace.mjs';
import {ExecutionCoordinator} from '../lib/runtime/execution_coordinator.mjs';
import {createStructureModule} from '../lib/tools/structure_module.mjs';

const turn = () => new Promise(resolve => setImmediate(resolve));
let sequence = 0;
function transport() {
  const children = [];
  return {children, spawnProcess() {
    const child = new EventEmitter();
    child.pid = 12345; child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.sent = []; child.closed = false; child.killCalls = 0;
    child.stdin.on('data', chunk => child.sent.push(Buffer.from(chunk)));
    child.request = () => JSON.parse(Buffer.concat(child.sent).toString('utf8'));
    child.kill = () => {child.killCalls++; return true;};
    child.close = (code = 0) => {if (!child.closed) {child.closed = true; child.emit('close', code);}};
    child.reply = (result, code = 0) => {child.stdout.write(JSON.stringify({ok: true, result})); child.close(code);};
    children.push(child); return child;
  }};
}
function fixture(t, options = {}) {
  const tr = transport(), specs = [], coordinator = options.coordinator ?? new ExecutionCoordinator();
  const observed = {
    invoke(spec, port, config) {specs.push(spec); return coordinator.invoke(spec, port, config);},
    recover(spec, port, config) {specs.push(spec); return coordinator.recover(spec, port, config);},
    whenIdle: key => coordinator.whenIdle(key),
  };
  const workspace = path.join(tmpdir(), 'structure-coordinator-transport-' + process.pid + '-' + ++sequence);
  const instance = new StructureWorkspace({workspace, spawnProcess: tr.spawnProcess, timeoutMs: 10000, ...options, coordinator: observed});
  t.after(async () => {
    // A failing assertion cannot leave active guards or queued fixture children.
    for (let index = 0; index < tr.children.length; index++) {tr.children[index].close(9); await turn();}
    await instance.queue;
  });
  return {...tr, instance, coordinator, specs};
}
function opened(id, backend = 'external-structure-workspace') {
  return {backend, state: 'completed', request_id: id, object_id: 'object-' + id};
}
function call(f, id, signal) {
  const wait = f.instance.call('structure_open', {source_path: 'unused-transport-fixture.xyz', request_id: id}, signal);
  wait.catch(() => {}); return wait;
}
const unpack = value => JSON.parse(value.content[0].text);

test('structure writes and queries provide explicit provider/workspace/session scope and separate lanes', async t => {
  const f = fixture(t), write = call(f, 'same-id');
  const query = f.instance.call('structure_result', {request_id: 'same-id'}); query.catch(() => {});
  assert.equal(f.children.length, 2, 'recovery bypasses a held scientific write resource');
  assert.deepEqual(f.specs[0].requestScope, {provider: 'external-structure-workspace', workspace: f.instance.workspace, session: 'workspace-journal-v1'});
  assert.deepEqual(f.specs[1].requestScope, f.specs[0].requestScope);
  assert.deepEqual(f.specs.map(spec => [spec.operation, spec.lane, spec.requestId]), [['structure_open', 'work', 'same-id'], ['structure_result', 'query', 'same-id']]);
  assert.deepEqual(f.specs[0].resourceKeys, [f.instance.resourceKey]); assert.deepEqual(f.specs[1].resourceKeys, []);
  assert.deepEqual(f.children[1].request(), {workspace: f.instance.workspace, action: 'result', query_request_id: 'same-id'});
  f.children[1].reply(opened('same-id')); assert.equal(unpack(await query).object_id, 'object-same-id');
  assert.equal(write.receipt().closed, false); f.children[0].reply(opened('same-id')); await write; await write.workerDone;
});

test('structure cancellation stops waiting only; successor waits for actual close while reads stay available', async t => {
  const f = fixture(t), cancellation = new AbortController(), first = call(f, 'first', cancellation.signal);
  cancellation.abort(); await assert.rejects(first, /Stopped waiting.*structure operation may still finish/);
  const next = call(f, 'second'), info = f.instance.call('structure_info', {object_id: 'fixed-object'}); info.catch(() => {});
  assert.equal(f.children.length, 2); assert.equal(f.children[0].killCalls, 0);
  assert.equal(f.children[1].request().action, 'get');
  f.children[1].reply({...opened('creator'), object_id: 'fixed-object'}); await info;
  assert.equal(f.children.length, 2); f.children[0].reply(opened('first')); await first.workerDone;
  assert.equal(f.children.length, 3); assert.equal(f.children[2].request().request_id, 'second');
  f.children[2].reply(opened('second')); await next; await next.workerDone;
  assert.ok(f.children.every(child => child.killCalls === 0));
});

test('structure timeout NEVER terminates work and cannot release resource before actual close', async t => {
  const f = fixture(t, {timeoutMs: 25}), first = call(f, 'deadline');
  await assert.rejects(first, /Structure worker deadline; it may still finish.*original request_id/);
  assert.equal(f.children[0].killCalls, 0); assert.equal(first.receipt().closed, false);
  const next = call(f, 'after-deadline'); assert.equal(f.children.length, 1);
  f.children[0].reply(opened('deadline')); await first.workerDone;
  assert.equal(f.children.length, 2); f.children[1].reply(opened('after-deadline')); await next; await next.workerDone;
  assert.ok(f.children.every(child => child.killCalls === 0));
});

test('structure response overflow stops waiting without terminating or releasing the worker', async t => {
  const f = fixture(t), first = call(f, 'oversized'), next = call(f, 'after-oversized');
  f.children[0].stdout.write(Buffer.alloc(4 * 1024 * 1024 + 1, 32));
  await assert.rejects(first, /Structure response exceeds4MiB/);
  assert.equal(f.children.length, 1); assert.equal(f.children[0].killCalls, 0); assert.equal(first.receipt().closed, false);
  f.children[0].close(7); await first.workerDone;
  assert.equal(f.children.length, 2); f.children[1].reply(opened('after-oversized')); await next; await next.workerDone;
});

test('pre-aborted and queued-cancelled structure calls never submit and cannot remove their successor', async t => {
  const f = fixture(t), before = new AbortController(); before.abort();
  const pre = call(f, 'never-started', before.signal); await assert.rejects(pre, /Cancelled while queued/); await pre.workerDone;
  assert.equal(f.children.length, 0);
  const holder = call(f, 'holder'), controller = new AbortController(), cancelled = call(f, 'queued', controller.signal), next = call(f, 'following');
  controller.abort(); await assert.rejects(cancelled, /Cancelled while queued.*not started/); await cancelled.workerDone;
  assert.equal(f.children.length, 1); f.children[0].reply(opened('holder')); await holder; await holder.workerDone;
  assert.equal(f.children.length, 2); assert.equal(f.children[1].request().request_id, 'following');
  f.children[1].reply(opened('following')); await next; await next.workerDone;
});

for (const kind of ['process-error', 'stdin-error']) test('structure ' + kind + ' retains resource until close', async t => {
  const f = fixture(t), first = call(f, kind), next = call(f, 'after-error');
  if (kind === 'process-error') f.children[0].emit('error', new Error('controlled live process refusal'));
  else f.children[0].stdin.emit('error', new Error('controlled EPIPE'));
  await assert.rejects(first, kind === 'process-error' ? /could not start.*controlled live process refusal/ : /input failed.*controlled EPIPE/);
  await turn(); assert.equal(f.children.length, 1); assert.equal(first.receipt().closed, false);
  f.children[0].close(9); await first.workerDone;
  assert.equal(f.children.length, 2); f.children[1].reply(opened('after-error')); await next; await next.workerDone;
  assert.ok(f.children.every(child => child.killCalls === 0));
});

test('structure queued parameters are immutable accepted snapshots, not later caller edits', async t => {
  const f = fixture(t), holder = call(f, 'snapshot-holder'), metadata = {nested: [1, 2, 3]};
  const next = f.instance.call('structure_open', {source_path: 'unused-fixture.xyz', request_id: 'snapshot', metadata}); next.catch(() => {});
  metadata.nested[0] = 999;
  f.children[0].reply(opened('snapshot-holder')); await holder; await holder.workerDone;
  assert.deepEqual(f.children[1].request().metadata, {nested: [1, 2, 3]});
  f.children[1].reply(opened('snapshot')); await next; await next.workerDone;
});

test('one explicit coordinator organizes image and structure without mixing equal request IDs', async t => {
  const coordinator = new ExecutionCoordinator(), structures = fixture(t, {coordinator}), images = transport();
  const image = new ImageWorkspace({workspace: path.join(tmpdir(), 'same-request-image-' + ++sequence), spawnProcess: images.spawnProcess, coordinator, timeoutMs: 10000});
  t.after(async () => {for (let i = 0; i < images.children.length; i++) {images.children[i].close(9); await turn();} await image.queue;});
  const a = call(structures, 'shared-id'), b = image.call('image_open', {source_path: 'unused-fixture.tiff', request_id: 'shared-id'}); b.catch(() => {});
  assert.equal(structures.children.length, 1); assert.equal(images.children.length, 1, 'different resource keys may execute concurrently');
  const next = call(structures, 'structure-next');
  images.children[0].reply(opened('shared-id', 'external-image-workspace')); assert.equal(unpack(await b).backend, 'external-image-workspace'); await b.workerDone;
  assert.equal(structures.children.length, 1, 'image close cannot release structure resource');
  structures.children[0].reply(opened('shared-id')); assert.equal(unpack(await a).backend, 'external-structure-workspace'); await a.workerDone;
  structures.children[1].reply(opened('structure-next')); await next; await next.workerDone;
});

test('structure scientific admission and original response guards remain in the adapter', async t => {
  const f = fixture(t);
  assert.throws(() => f.instance.call('structure_simulate', {request_id: 'missing-direction'}), /exactly one/);
  assert.equal(f.children.length, 0);
  const first = call(f, 'expected-id'); f.children[0].reply(opened('wrong-id'));
  await assert.rejects(first, /different original request identity/); await first.workerDone;
  const query = f.instance.call('structure_info', {object_id: 'requested-object'}); query.catch(() => {});
  f.children[1].reply({...opened('creator'), object_id: 'wrong-object'});
  await assert.rejects(query, /different requested object identity/); await query.workerDone;
});

test('structure module declares actual read/write resources and no-termination semantics', () => {
  const workspace = path.join(tmpdir(), 'structure-contract-fixture'), module = createStructureModule({structureWorkspace: {workspace, call() {throw Error('not called');}}});
  const entry = name => module.tools.find(tool => tool.definition.name === name).contract;
  for (const name of ['structure_info', 'structure_result']) assert.deepEqual(entry(name).execution.resourceKeys, []);
  for (const name of ['structure_open', 'structure_simulate', 'structure_view']) {
    assert.deepEqual(entry(name).execution.resourceKeys, ['structure-workspace:' + workspace]);
    assert.match(entry(name).execution.cancellation, /NEVER terminates/);
  }
  assert.deepEqual(entry('structure_viewer_close').execution.resourceKeys, ['structure-viewer-registry:' + workspace]);
});
