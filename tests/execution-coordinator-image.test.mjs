// ImageWorkspace -> portable Coordinator -> injected child transport only.
// EventEmitter/PassThrough lifetimes are controlled test doubles: no actual
// Python/DM process, scientific computation, journal or host qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {ImageWorkspace} from '../lib/image_workspace.mjs';

const turn = () => new Promise(resolve => setImmediate(resolve));
let fixtureSequence = 0;
function fixture(t, {pid = 12345, throwFirst = false} = {}) {
  const children = [];
  const spawnError = new Error('controlled synchronous spawn refusal');
  let attempts = 0;
  const spawnProcess = () => {
    attempts++;
    if (throwFirst && attempts === 1) throw spawnError;
    const child = new EventEmitter();
    child.pid = pid;
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.sent = []; child.closed = false; child.killCalls = 0;
    child.stdin.on('data', chunk => child.sent.push(Buffer.from(chunk)));
    child.request = () => JSON.parse(Buffer.concat(child.sent).toString('utf8'));
    child.kill = () => {child.killCalls++; return false;};
    child.close = (code = 0) => {if (!child.closed) {child.closed = true; child.emit('close', code);}};
    child.reply = (value, code = 0) => {child.stdout.write(JSON.stringify(value)); child.close(code);};
    children.push(child); return child;
  };
  const workspace = path.join(tmpdir(), 'image-coordinator-transport-' + process.pid + '-' + ++fixtureSequence);
  const instance = new ImageWorkspace({workspace, spawnProcess, timeoutMs: 10000});
  t.after(async () => {
    // A failing assertion cannot leave fixture timers/resource guards running.
    // Closing each current child can dispatch another queued fixture child.
    for (let index = 0; index < children.length; index++) {children[index].close(9); await turn();}
    await instance.queue;
    await turn();
  });
  return {instance, children, spawnError, attempts: () => attempts};
}
const open = (f, requestId, extra = {}, signal) => {
  const waiting = f.instance.call('image_open', {source_path: 'unused-transport-fixture', request_id: requestId, ...extra}, signal);
  waiting.catch(() => {}); return waiting;
};
const completed = (requestId, objectId = 'object-' + requestId) => ({ok: true, result: {
  backend: 'external-image-workspace', state: 'completed', request_id: requestId, object_id: objectId,
}});
const result = value => JSON.parse(value.content[0].text);

test('image invocation and recovery refuse a different original request identity', async t => {
  const f = fixture(t), first = open(f, 'expected-original');
  f.children[0].reply(completed('different-original'));
  await assert.rejects(first, /different original request identity/); await first.workerDone;
  const query = f.instance.call('image_result', {request_id: 'expected-original'}); query.catch(() => {});
  assert.deepEqual(f.children[1].request(), {action: 'result', query_request_id: 'expected-original', workspace: f.instance.workspace});
  f.children[1].reply(completed('different-original'));
  await assert.rejects(query, /different original request identity/); await query.workerDone;
  assert.equal(query.receipt().mode, 'recover');
  assert.equal(f.attempts(), 2, 'only one invoke and one read-only query, never an automatic replay');
});

test('image inspection refuses a different requested scientific object identity', async t => {
  const f = fixture(t), waiting = f.instance.call('image_info', {object_id: 'requested-object'}); waiting.catch(() => {});
  assert.equal(f.children[0].request().object_id, 'requested-object');
  f.children[0].reply(completed('historical-creator', 'another-object'));
  await assert.rejects(waiting, /different requested object identity/); await waiting.workerDone;
});

test('already-aborted image request never reaches the child transport', async t => {
  const f = fixture(t), controller = new AbortController(); controller.abort();
  const waiting = open(f, 'never-submitted', {}, controller.signal);
  await assert.rejects(waiting, /Cancelled while queued.*not started/); await waiting.workerDone;
  assert.equal(f.attempts(), 0); assert.equal(waiting.receipt().state, 'not_started');
  assert.equal(waiting.receipt().closed, true);
});

test('queued image cancellation never spawns and cannot block the following write', async t => {
  const f = fixture(t), holding = open(f, 'holding'), controller = new AbortController();
  const cancelled = open(f, 'cancelled-while-queued', {}, controller.signal), next = open(f, 'next-write');
  assert.equal(f.attempts(), 1); controller.abort();
  await assert.rejects(cancelled, /Cancelled while queued.*not started/); await cancelled.workerDone;
  assert.equal(f.attempts(), 1, 'cancellation cannot release the predecessor resource');
  f.children[0].reply(completed('holding')); await holding.workerDone;
  assert.equal(f.attempts(), 2); assert.equal(f.children[1].request().request_id, 'next-write');
  f.children[1].reply(completed('next-write')); assert.equal(result(await next).request_id, 'next-write');
  await holding; await next.workerDone;
  assert.equal(cancelled.receipt().state, 'not_started');
});

test('queued image payload retains nested accepted parameters despite caller mutation', async t => {
  const f = fixture(t), holding = open(f, 'snapshot-holder');
  const metadata = {source_text: 'accepted source statement', nested: {values: [1, 2, 3]}};
  const queued = open(f, 'accepted-snapshot', {metadata});
  const before = queued.receipt().parametersSha256;
  metadata.nested.values[0] = 999; metadata.source_text = 'later caller change';
  f.children[0].reply(completed('snapshot-holder')); await holding.workerDone;
  assert.deepEqual(f.children[1].request().metadata, {source_text: 'accepted source statement', nested: {values: [1, 2, 3]}});
  assert.equal(queued.receipt().parametersSha256, before);
  f.children[1].reply(completed('accepted-snapshot')); await holding; await queued; await queued.workerDone;
});

test('synchronous image spawn refusal releases its resource and preserves the original error', async t => {
  const f = fixture(t, {throwFirst: true}), failed = open(f, 'spawn-throws');
  await assert.rejects(failed, error => error === f.spawnError); await failed.workerDone;
  assert.equal(failed.receipt().closed, true);
  const next = open(f, 'after-spawn-throws'); assert.equal(f.attempts(), 2);
  f.children[0].reply(completed('after-spawn-throws')); await next; await next.workerDone;
});

test('asynchronous no-PID image spawn error retains resource until actual close', async t => {
  const f = fixture(t, {pid: undefined}), failed = open(f, 'async-spawn-error'), next = open(f, 'after-async-error');
  // Unlike a thrown spawn call, a returned child has an explicit close event.
  delete f.children[0].pid;
  f.children[0].emit('error', Object.assign(new Error('controlled ENOENT'), {code: 'ENOENT'}));
  await assert.rejects(failed, /Cannot start independent image Python.*controlled ENOENT/);
  assert.equal(f.attempts(), 1); assert.equal(failed.receipt().closed, false);
  f.children[0].close(-2); await failed.workerDone;
  assert.equal(f.attempts(), 2); f.children[1].reply(completed('after-async-error'));
  await next; await next.workerDone;
});

for (const kind of ['live-process-error', 'stdin-error']) test(kind + ' cannot release a still-live image transport', async t => {
  const f = fixture(t), failed = open(f, kind), next = open(f, 'after-' + kind);
  if (kind === 'stdin-error') f.children[0].stdin.emit('error', Object.assign(new Error('controlled EPIPE'), {code: 'EPIPE'}));
  else f.children[0].emit('error', Object.assign(new Error('controlled live process error'), {code: 'EPERM'}));
  await assert.rejects(failed, kind === 'stdin-error' ? /input failed.*controlled EPIPE/ : /process error.*controlled live process error/);
  await turn(); assert.equal(f.attempts(), 1); assert.equal(failed.receipt().closed, false);
  f.children[0].close(7); await failed.workerDone;
  assert.equal(f.attempts(), 2); assert.equal(f.children[1].request().request_id, 'after-' + kind);
  f.children[1].reply(completed('after-' + kind)); await next; await next.workerDone;
});

test('malformed image JSON is rejected and the next write progresses only after close', async t => {
  const f = fixture(t), failed = open(f, 'malformed-json'), next = open(f, 'after-malformed');
  f.children[0].stdout.write('{this is not JSON');
  assert.equal(f.attempts(), 1); f.children[0].close();
  await assert.rejects(failed, SyntaxError); await failed.workerDone;
  assert.equal(f.attempts(), 2); f.children[1].reply(completed('after-malformed'));
  await next; await next.workerDone;
});

test('oversize image response requests termination but retains resource until actual close', async t => {
  const f = fixture(t), failed = open(f, 'oversize-response'), next = open(f, 'after-oversize');
  f.children[0].stdout.write(Buffer.alloc(4 * 1024 * 1024 + 1, 32));
  await assert.rejects(failed, /response exceeds 4 MiB/);
  assert.equal(f.children[0].killCalls, 1); assert.equal(f.attempts(), 1);
  assert.equal(failed.receipt().closed, false, 'kill returning false is not closure');
  f.children[0].close(9); await failed.workerDone;
  assert.equal(f.attempts(), 2); f.children[1].reply(completed('after-oversize'));
  await next; await next.workerDone;
});
