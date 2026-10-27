// Portable execution mechanics only: controlled provider lifetimes, no DM,
// Python, scientific algorithm, durable journal or real-host qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync, copyFileSync, writeFileSync, readFileSync, existsSync, rmSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ExecutionCoordinator} from '../lib/runtime/execution_coordinator.mjs';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
};
const turn = () => new Promise(resolve => setImmediate(resolve));
const spec = (requestId, resourceKeys = ['opaque-provider-resource'], extra = {}) => ({
  operation: 'fixture_operation', requestId, parameters: {source_ref: 'fixed-synthetic-ref', request_id: requestId},
  resourceKeys, timeoutMs: 1000, ...extra,
});
function provider() {
  const output = deferred(), lifetime = deferred(), starts = [];
  return {output, lifetime, starts,
    start: parameters => {starts.push(parameters); return {result: output.promise, closed: lifetime.promise};},
    finish(value = {fixture_only: true}) {output.resolve(value); lifetime.resolve();},
  };
}
function call(coordinator, request, port, options) {
  const result = coordinator.invoke(request, port, options);
  // Tests intentionally reject/defer waits; observe them immediately.
  result.catch(() => {}); return result;
}

test('FIFO writes retain resources after output until actual closure; independent inspection proceeds', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), b = provider(), c = provider(), read = provider();
  const first = call(coordinator, spec('first'), a), second = call(coordinator, spec('second'), b);
  const third = call(coordinator, spec('third'), c), inspection = call(coordinator, spec(null, []), read);
  assert.equal(a.starts.length, 1); assert.equal(b.starts.length, 0); assert.equal(c.starts.length, 0);
  assert.equal(read.starts.length, 1, 'resource-free read bypasses blocked writes');
  a.output.resolve('first-value'); assert.equal(await first, 'first-value');
  await turn(); assert.equal(b.starts.length, 0, 'a successful result is not child close');
  assert.equal(first.receipt().closed, false);
  read.finish('read-value'); assert.equal(await inspection, 'read-value');
  a.lifetime.resolve(); await first.workerDone;
  assert.equal(b.starts.length, 1); assert.equal(c.starts.length, 0);
  b.finish('second-value'); assert.equal(await second, 'second-value'); await second.workerDone;
  assert.equal(c.starts.length, 1); c.finish('third-value'); assert.equal(await third, 'third-value');
  await coordinator.whenIdle();
});

test('multi-resource FIFO prevents bypass of an older blocked request but permits unrelated work', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), both = provider(), b = provider(), c = provider();
  const first = call(coordinator, spec('holds-a', ['a']), a);
  const blocked = call(coordinator, spec('needs-a-b', ['b', 'a', 'a']), both);
  const laterB = call(coordinator, spec('later-b', ['b']), b);
  const separate = call(coordinator, spec('separate-c', ['c']), c);
  assert.equal(both.starts.length, 0); assert.equal(b.starts.length, 0, 'cannot overtake the earlier a+b waiter');
  assert.equal(c.starts.length, 1); assert.deepEqual(blocked.receipt().resourceKeys, ['a', 'b']);
  c.finish(); await separate; a.finish(); await first.workerDone;
  assert.equal(both.starts.length, 1); assert.equal(b.starts.length, 0);
  both.finish(); await blocked.workerDone; assert.equal(b.starts.length, 1);
  b.finish(); await laterB; await coordinator.whenIdle();
});

test('reentrant provider cancellation removes the queued task without losing its following peer', async () => {
  const coordinator = new ExecutionCoordinator(), holder = provider(), b = provider(), c = provider(), d = provider();
  const controller = new AbortController();
  const first = call(coordinator, spec('holds-x-y', ['x', 'y']), holder);
  const second = call(coordinator, spec('starts-and-cancels', ['x']), {start: parameters => {controller.abort(); return b.start(parameters);}});
  const cancelled = call(coordinator, spec('cancelled-peer', ['y']), c, {signal: controller.signal});
  const following = call(coordinator, spec('following-peer', ['y']), d);
  holder.finish(); await first.workerDone;
  await assert.rejects(cancelled, /not started/); await cancelled.workerDone;
  assert.equal(c.starts.length, 0, 'a stale pump snapshot cannot submit the cancelled task');
  assert.equal(d.starts.length, 1, 'removing cancelled work cannot splice out its live successor');
  assert.equal(cancelled.receipt().state, 'not_started');
  b.finish(); d.finish(); await second; await following; await coordinator.whenIdle();
});

test('provider can enqueue unrelated work reentrantly without waiting for its own closure', async () => {
  const coordinator = new ExecutionCoordinator(), outer = provider(), inner = provider(); let nested;
  const first = call(coordinator, spec('outer', ['outer-resource']), {start: parameters => {
    nested = call(coordinator, spec('inner', ['independent-inner-resource']), inner);
    return outer.start(parameters);
  }});
  assert.equal(inner.starts.length, 1, 'the pump must revisit work registered during a start port');
  assert.equal(first.receipt().closed, false); inner.finish('inner-result'); assert.equal(await nested, 'inner-result');
  outer.finish(); await first; await coordinator.whenIdle();
});

test('pre-aborted and queued-aborted calls never enter the provider and do not poison later work', async () => {
  const coordinator = new ExecutionCoordinator(), holding = provider(), queued = provider(), later = provider(), pre = provider();
  const first = call(coordinator, spec('holder'), holding), cancellation = new AbortController();
  const waiting = call(coordinator, spec('queued'), queued, {signal: cancellation.signal});
  cancellation.abort();
  await assert.rejects(waiting, error => error.executionCategory === 'cancelled_before_start');
  await waiting.workerDone;
  assert.deepEqual([waiting.receipt().state, waiting.receipt().waitState, waiting.receipt().closed], ['not_started', 'cancelled', true]);
  const controller = new AbortController(); controller.abort();
  const before = call(coordinator, spec('preabort', ['independent']), pre, {signal: controller.signal});
  await assert.rejects(before, /not started/); await before.workerDone;
  const next = call(coordinator, spec('later'), later);
  holding.finish(); await first.workerDone;
  assert.equal(queued.starts.length, 0); assert.equal(pre.starts.length, 0); assert.equal(later.starts.length, 1);
  later.finish(); await next; await coordinator.whenIdle();
});

test('running abort detaches only its waiter and late completion preserves the original result receipt', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), b = provider(), controller = new AbortController();
  let stopCalls = 0;
  const first = call(coordinator, spec('accepted'), {start: value => ({...a.start(value), requestStop: () => {stopCalls++;}})}, {signal: controller.signal});
  controller.abort(); await assert.rejects(first, error => error.executionCategory === 'cancelled_wait');
  const second = call(coordinator, spec('next'), b);
  assert.equal(first.receipt().state, 'running'); assert.equal(first.receipt().waitState, 'cancelled');
  assert.equal(stopCalls, 0, 'client cancellation must not request worker termination'); assert.equal(b.starts.length, 0);
  a.output.resolve({request_id: 'accepted', object_id: 'one-object'}); await turn();
  assert.equal(first.receipt().state, 'completed'); assert.equal(first.receipt().waitState, 'cancelled');
  assert.equal(b.starts.length, 0); a.lifetime.resolve(); await first.workerDone;
  b.finish(); await second; await coordinator.whenIdle();
});

for (const mode of ['false', 'throw', 'reject']) test(`deadline with stop ${mode} cannot release a still-live provider`, async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), b = provider(); let stops = 0;
  const stop = () => {stops++; if (mode === 'throw') throw new Error('synthetic stop denied'); if (mode === 'reject') return Promise.reject(new Error('synthetic async stop denied')); return false;};
  const first = call(coordinator, spec('deadline', ['shared'], {timeoutMs: 15}), {start: value => ({...a.start(value), requestStop: stop})});
  const second = call(coordinator, spec('after-deadline', ['shared']), b);
  await assert.rejects(first, error => error.executionCategory === 'deadline'); await turn();
  assert.equal(stops, 1); assert.equal(first.receipt().waitState, 'timed_out'); assert.equal(first.receipt().closed, false);
  assert.equal(first.receipt().deadlineReached, true); assert.equal(first.receipt().stopRequested, true);
  assert.equal(b.starts.length, 0); if (mode !== 'false') assert.match(first.receipt().stopError, /stop denied/);
  a.finish({request_id: 'deadline', fixture_only: true}); await first.workerDone;
  assert.equal(first.receipt().state, 'completed'); assert.equal(first.receipt().waitState, 'timed_out');
  assert.equal(b.starts.length, 1); b.finish(); await second; await coordinator.whenIdle();
});

test('worker guard remains active after running cancellation', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), controller = new AbortController(), stopped = deferred();
  const first = call(coordinator, spec('cancel-then-deadline', [], {timeoutMs: 15}), {start: value => ({...a.start(value), requestStop: () => stopped.resolve()})}, {signal: controller.signal});
  controller.abort(); await assert.rejects(first, /Stopped waiting/);
  await stopped.promise; assert.equal(first.receipt().waitState, 'cancelled', 'deadline does not overwrite the earlier waiter outcome');
  a.finish(); await first.workerDone; await coordinator.whenIdle();
});

test('early provider rejection preserves the original Error and deadline guard until closure', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), b = provider(), stopped = deferred();
  const error = Object.assign(new Error('synthetic input EPIPE'), {code: 'EPIPE'});
  const first = call(coordinator, spec('error-before-close', ['shared'], {timeoutMs: 15}), {start: value => ({...a.start(value), requestStop: () => stopped.resolve()})});
  const second = call(coordinator, spec('after-input-error', ['shared']), b);
  a.output.reject(error); await assert.rejects(first, actual => actual === error);
  assert.equal(b.starts.length, 0); await stopped.promise;
  assert.equal(first.receipt().waitState, 'failed'); assert.equal(first.receipt().closed, false);
  a.lifetime.resolve(); await first.workerDone; b.finish(); await second; await coordinator.whenIdle();
});

test('closed provider with an unresolved validation result still reaches its wait deadline without requesting stop', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(); let stops = 0;
  const waiting = call(coordinator, spec('closed-but-no-result', [], {timeoutMs: 15}), {start: parameters => ({...a.start(parameters), requestStop: () => {stops++;}})});
  a.lifetime.resolve(); await waiting.workerDone; await coordinator.whenIdle();
  assert.equal(waiting.receipt().closed, true);
  await assert.rejects(waiting, error => error.executionCategory === 'deadline');
  assert.equal(waiting.receipt().deadlineReached, true); assert.equal(stops, 0, 'cannot terminate an already closed provider');
  assert.notEqual(waiting.receipt().stopRequested, true);
  a.output.resolve('late-validation'); await turn();
  assert.equal(waiting.receipt().waitState, 'timed_out');
});

test('validation result may complete after closure and before its deadline', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(); let stops = 0;
  const waiting = call(coordinator, spec('closed-before-validation', [], {timeoutMs: 1000}), {start: parameters => ({...a.start(parameters), requestStop: () => {stops++;}})});
  a.lifetime.resolve(); await waiting.workerDone;
  assert.equal(waiting.receipt().closed, true); assert.equal(waiting.receipt().waitState, 'waiting');
  a.output.resolve('verified-after-close'); assert.equal(await waiting, 'verified-after-close');
  assert.equal(waiting.receipt().state, 'completed'); assert.equal(waiting.receipt().waitState, 'completed');
  assert.equal(stops, 0); await coordinator.whenIdle();
});

test('synchronous pre-start provider failure releases resources without replacing the original Error', async () => {
  const coordinator = new ExecutionCoordinator(), next = provider(), error = new Error('fixture cannot spawn');
  const failed = call(coordinator, spec('cannot-start'), {start: () => {throw error;}});
  await assert.rejects(failed, actual => actual === error); await failed.workerDone;
  assert.equal(failed.receipt().closed, true);
  const second = call(coordinator, spec('after-cannot-start'), next); assert.equal(next.starts.length, 1);
  next.finish(); await second; await coordinator.whenIdle();
});

test('a rejected closed promise fails closed and cannot be treated as a physical exit', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), next = provider(), controller = new AbortController();
  const first = call(coordinator, spec('bad-close', ['shared'], {timeoutMs: 10}), a);
  a.lifetime.reject(new Error('fixture close signal lost'));
  await assert.rejects(first, error => error.executionCategory === 'lifecycle');
  const second = call(coordinator, spec('blocked-by-lost-close', ['shared']), next, {signal: controller.signal});
  a.output.resolve('late-result'); await turn();
  assert.equal(first.receipt().state, 'unknown'); assert.equal(first.receipt().closed, false); assert.equal(next.starts.length, 0);
  controller.abort(); await assert.rejects(second, /not started/);
  // Unknown closure deliberately cannot be drained. Its finite guard expires;
  // a new coordinator does not pretend to prove this provider has exited.
});

test('malformed lifecycle rejects without submitting a successor on the retained resource', async () => {
  const coordinator = new ExecutionCoordinator(), next = provider(), controller = new AbortController();
  const first = call(coordinator, spec('malformed'), {start: () => ({result: Promise.resolve('not-trusted')})});
  await assert.rejects(first, /invalid execution lifecycle/);
  assert.equal(first.receipt().state, 'unknown'); assert.equal(first.receipt().closed, false);
  const second = call(coordinator, spec('must-not-start'), next, {signal: controller.signal});
  assert.equal(next.starts.length, 0); controller.abort(); await assert.rejects(second, /not started/);
});

test('queued accepted parameters and canonical hash do not follow caller mutation or key insertion order', async () => {
  const coordinator = new ExecutionCoordinator(), holding = provider(), queued = provider(), first = call(coordinator, spec('hold'), holding);
  const parameters = {z: [1, {a: 3}], a: {y: -0, x: 'source'}, request_id: 'accepted'};
  const expected = {a: {x: 'source', y: 0}, request_id: 'accepted', z: [1, {a: 3}]};
  const second = call(coordinator, spec('accepted', undefined, {parameters}), queued);
  const hash = createHash('sha256').update(JSON.stringify(expected)).digest('hex');
  parameters.z[1].a = 900; parameters.a.x = 'changed'; parameters.added = 'after acceptance';
  const snapshot = second.receipt(); snapshot.resourceKeys.push('fake'); snapshot.parametersSha256 = 'fake';
  assert.equal(second.receipt().parametersSha256, hash); assert.deepEqual(second.receipt().resourceKeys, ['opaque-provider-resource']);
  holding.finish(); await first.workerDone;
  assert.deepEqual(queued.starts[0], expected);
  assert.equal(Object.isFrozen(queued.starts[0]), true); assert.equal(Object.isFrozen(queued.starts[0].z), true);
  assert.equal(Object.isFrozen(queued.starts[0].z[1]), true);
  assert.throws(() => {queued.starts[0].z[1].a = 1000;}, TypeError);
  queued.finish(); await second; await coordinator.whenIdle();
});

test('recover invokes only the explicit query port and preserves original errors without retrying', async () => {
  const coordinator = new ExecutionCoordinator(); let queries = 0, starts = 0;
  const value = {request_id: 'original', object_id: 'same-original-object', calibration_ref: 'immutable-v1'};
  const query = parameters => {queries++; assert.equal(parameters.query_request_id, 'original'); return {result: Promise.resolve(value), closed: Promise.resolve()};};
  const recovered = coordinator.recover(spec('original', [], {operation: 'fixture_result', parameters: {query_request_id: 'original'}}), {query, start: () => {starts++; throw new Error('must not replay');}});
  assert.equal(await recovered, value); await recovered.workerDone;
  assert.equal(recovered.receipt().mode, 'recover'); assert.equal(recovered.receipt().operation, 'fixture_result');
  const error = Object.assign(new Error('Original incomplete; do not replay'), {code: 'INCOMPLETE_REQUEST'});
  const missing = coordinator.recover(spec('missing', []), {query: () => {queries++; return {result: Promise.reject(error), closed: Promise.resolve()};}, start: () => {starts++;}});
  await assert.rejects(missing, actual => actual === error); await missing.workerDone;
  assert.equal(queries, 2); assert.equal(starts, 0); await coordinator.whenIdle();
});

test('inspection/recovery do not wait for a write slot or release it', async () => {
  const coordinator = new ExecutionCoordinator(), writer = provider(), next = provider(), query = provider();
  const first = call(coordinator, spec('writing'), writer), second = call(coordinator, spec('waiting'), next);
  const recovered = coordinator.recover(spec('old-saved-request', []), {query: query.start});
  assert.equal(query.starts.length, 1); query.finish({original_request_id: 'old-saved-request'}); await recovered;
  assert.equal(next.starts.length, 0); writer.finish(); await first.workerDone; next.finish(); await second; await coordinator.whenIdle();
});

test('whenIdle observes only its selected resource while global drain includes independent queries', async () => {
  const coordinator = new ExecutionCoordinator(), a = provider(), b = provider();
  const first = call(coordinator, spec('a', ['a']), a), query = call(coordinator, spec(null, []), b);
  let allIdle = false, aIdle = false;
  const globalDrain = coordinator.whenIdle().then(() => {allIdle = true;});
  const selectedDrain = coordinator.whenIdle('a').then(() => {aIdle = true;});
  await coordinator.whenIdle('unused'); a.finish(); await first.workerDone; await selectedDrain;
  assert.equal(aIdle, true); assert.equal(allIdle, false);
  b.finish(); await query; await globalDrain; assert.equal(allIdle, true);
});

const invalidParameters = [
  ['undefined', undefined], ['nonfinite', {x: Infinity}], ['Date', {x: new Date(0)}], ['Map', {x: new Map()}],
  ['sparse', {x: Array(2)}], ['function', {x: () => 1}], ['symbol', {[Symbol('hidden')]: 1}],
  ['accessor', Object.defineProperty({}, 'x', {enumerable: true, get: () => 1})],
];
const cycle = {}; cycle.x = cycle; invalidParameters.push(['cycle', cycle]);
for (const [label, parameters] of invalidParameters) test('reject invalid execution parameters before provider start: ' + label, () => {
  const coordinator = new ExecutionCoordinator(); let starts = 0;
  assert.throws(() => coordinator.invoke(spec('invalid', [], {parameters}), {start: () => {starts++;}}), TypeError);
  assert.equal(starts, 0);
});

test('nonenumerable array-index accessor is rejected without reading it', () => {
  const coordinator = new ExecutionCoordinator(), array = []; let reads = 0, starts = 0;
  Object.defineProperty(array, '0', {enumerable: false, get: () => {reads++; return 'unsafe-read';}});
  assert.equal(array.length, 1);
  assert.throws(() => coordinator.invoke(spec('array-accessor', [], {parameters: {array}}), {start: () => {starts++;}}), TypeError);
  assert.equal(reads, 0); assert.equal(starts, 0);
});

test('invalid execution/recovery contracts reject before any provider invocation', () => {
  const coordinator = new ExecutionCoordinator(); let starts = 0; const port = {start: () => {starts++;}, query: () => {starts++;}};
  for (const patch of [{operation: ''}, {requestId: undefined}, {resourceKeys: null}, {resourceKeys: [1]}, {timeoutMs: 0}, {timeoutMs: Infinity}, {timeoutMs: 1.2}, {timeoutMs: 2147483648}])
    assert.throws(() => coordinator.invoke(spec('invalid', [], patch), port), TypeError);
  assert.throws(() => coordinator.invoke(spec('invalid', []), {}), /start/);
  assert.throws(() => coordinator.recover(spec(null, []), port), /original saved/);
  assert.throws(() => coordinator.recover(spec('invalid', ['write']), port), /write resource/);
  assert.throws(() => coordinator.recover(spec('invalid', []), {start: port.start}), /query/);
  assert.equal(starts, 0);
});

test('copying the coordinator file alone is enough to import, invoke and recover without a DM/provider tree', () => {
  const folder = mkdtempSync(path.join(tmpdir(), 'portable-execution-core-'));
  const source = fileURLToPath(new URL('../lib/runtime/execution_coordinator.mjs', import.meta.url));
  copyFileSync(source, path.join(folder, 'execution_coordinator.mjs'));
  writeFileSync(path.join(folder, 'smoke.mjs'), [
    "import {ExecutionCoordinator} from './execution_coordinator.mjs';",
    "const coordinator=new ExecutionCoordinator();",
    "let starts=0,queries=0;const spec={operation:'fixture_compute',requestId:'before-submit',parameters:{source_ref:'synthetic-v1'},resourceKeys:['opaque-resource'],timeoutMs:1000};",
    "const result=coordinator.invoke(spec,{start:p=>{starts++;return {result:Promise.resolve({source_ref:p.source_ref,backend:'fixture-only'}),closed:Promise.resolve()};}});",
    "const value=await result;await result.workerDone;",
    "const recovered=coordinator.recover({...spec,operation:'fixture_query',resourceKeys:[]},{query:p=>{queries++;return {result:Promise.resolve(value),closed:Promise.resolve()};}});",
    "console.log(JSON.stringify({value,recovered:await recovered,receipt:result.receipt(),starts,queries,dmKeys:Object.keys(process.env).filter(k=>k.startsWith('DM_'))}));await coordinator.whenIdle();",
  ].join('\n'));
  try {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('DM_')));
    const observed = JSON.parse(execFileSync(process.execPath, [path.join(folder, 'smoke.mjs')], {cwd: folder, env, encoding: 'utf8', windowsHide: true, timeout: 10000}));
    assert.deepEqual(observed.value, {source_ref: 'synthetic-v1', backend: 'fixture-only'});
    assert.deepEqual(observed.recovered, observed.value); assert.equal(observed.starts, 1); assert.equal(observed.queries, 1);
    assert.deepEqual(observed.dmKeys, []); assert.equal(observed.receipt.receiptVersion, 1); assert.equal(observed.receipt.closed, true);
    for (const absent of ['server.mjs', 'lib', 'tools', 'GMS', 'node_modules']) assert.equal(existsSync(path.join(folder, absent)), false);
    assert.doesNotMatch(readFileSync(source, 'utf8'), /process\.env|server\.mjs|from ['"]\.\./);
  } finally {
    assert.ok(path.resolve(folder).startsWith(path.resolve(tmpdir()) + path.sep));
    assert.ok(path.basename(folder).startsWith('portable-execution-core-'));
    rmSync(folder, {recursive: true, force: true});
  }
});
