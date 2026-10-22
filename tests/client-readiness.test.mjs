// Synthetic protocol/lifecycle checks. No real client, DM host or private data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter, once} from 'node:events';
import {readFileSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import vm from 'node:vm';

const serverFile = fileURLToPath(new URL('../server.mjs', import.meta.url));
const source = readFileSync(serverFile, 'utf8');

// Inject process events into the actual launcher without adding test switches
// to production or starting any host. Protocol tests below use the real stdio.
function launcher() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
  child.stdin = new EventEmitter(); child.stdin.end = () => {};
  let spawned = 0, killed = 0;
  child.kill = () => { killed++; return true; };
  const timers = [];
  const start = source.indexOf('function runAnalysisWorker(payload, signal) {');
  const end = source.indexOf('\nfunction requireFile(', start);
  assert.ok(start >= 0 && end > start, 'launcher boundary must be present');
  const context = {
    Buffer,
    ANALYSIS_PYTHON: 'test-only', ANALYSIS_WORKER: 'test-only', ANALYSIS_WORKER_TIMEOUT_MS: 1000,
    spawn: () => { spawned++; return child; },
    setTimeout: fn => { const t = {fn, cleared: false}; timers.push(t); return t; },
    clearTimeout: t => { t.cleared = true; },
    requireFile: () => Buffer.from('89504e470d0a1a0a', 'hex'),
  };
  const run = vm.runInNewContext(source.slice(start, end) + '\nrunAnalysisWorker;', context);
  return {child, timers, run, spawned: () => spawned, killed: () => killed};
}

test('cancelled local wait keeps the worker hard deadline until close', async () => {
  const h = launcher(), controller = new AbortController();
  const pending = h.run({action: 'analyze'}, controller.signal);
  const rejected = assert.rejects(pending, /状态未知/);
  controller.abort();
  await rejected;
  assert.equal(h.timers[0].cleared, false, 'cancelling a wait must not disable the running child deadline');
  assert.equal(h.killed(), 0, 'cancellation alone does not claim/force termination');
  h.timers[0].fn();
  assert.equal(h.killed(), 1);
  h.child.emit('close', 1);
  assert.equal(h.timers[0].cleared, true);
});

test('worker stdin errors become rejected tool calls, not uncaught errors', async () => {
  const h = launcher();
  const pending = h.run({action: 'result'});
  assert.ok(h.child.stdin.listenerCount('error') > 0, 'EPIPE needs an explicit listener');
  const rejected = assert.rejects(pending, /输入管道.*EPIPE/);
  assert.doesNotThrow(() => h.child.stdin.emit('error', new Error('EPIPE')));
  await rejected;
  assert.equal(h.killed(), 1);
  h.child.emit('close', 1);
  assert.equal(h.timers[0].cleared, true);
});

test('worker runtime timeout settles even before an exit notification', {timeout: 1500}, async () => {
  const h = launcher();
  const pending = h.run({action: 'analyze'});
  const rejected = assert.rejects(pending, /运行时限.*状态未知/);
  h.timers[0].fn();
  await rejected;
  assert.equal(h.killed(), 1);
  h.child.emit('close', 1);
});

test('oversized worker requests are rejected before spawning', async () => {
  const h = launcher();
  await assert.rejects(h.run({action: 'analyze', note: 'x'.repeat(1024 * 1024)}), /1 MiB/);
  assert.equal(h.spawned(), 0);
});

test('aborted requests do not start a worker', async () => {
  const h = launcher(), controller = new AbortController();
  controller.abort();
  await assert.rejects(h.run({action: 'result'}, controller.signal), /尚未启动/);
  assert.equal(h.spawned(), 0);
});

test('invalid worker envelopes cannot throw out of a close callback', async () => {
  for (const reply of ['null', '[]', '{', '{"ok":true,"result":null}', '{"ok":true,"result":[]}']) {
    const h = launcher();
    const pending = h.run({action: 'result'});
    const rejected = assert.rejects(pending);
    h.child.stdout.emit('data', Buffer.from(reply));
    assert.doesNotThrow(() => h.child.emit('close', 0), reply);
    await rejected;
    assert.equal(h.timers[0].cleared, true);
  }
});

test('worker output overflow stops retaining additional chunks', async () => {
  const h = launcher();
  const rejected = assert.rejects(h.run({action: 'result'}), /4 MiB/);
  h.child.stdout.emit('data', Buffer.alloc(4 * 1024 * 1024 + 1));
  await rejected;
  for (let i = 0; i < 10; i++) h.child.stdout.emit('data', Buffer.from('x'));
  assert.equal(h.killed(), 1, 'later chunks must be drained without repeated buffering/kill');
  h.child.emit('close', 1);
});

test('spawn failure reports the interpreter and cleans its deadline', async () => {
  const h = launcher();
  const rejected = assert.rejects(h.run({action: 'result'}), /DM_ANALYSIS_PYTHON.*ENOENT/);
  h.child.emit('error', new Error('ENOENT'));
  await rejected;
  assert.equal(h.timers[0].cleared, true);
  h.child.emit('close', -2);
});

test('successful preview retains text and image blocks after split UTF-8 output', async () => {
  const h = launcher();
  const pending = h.run({action: 'preview'});
  const reply = Buffer.from(JSON.stringify({ok: true, result: {preview_path: 'C:/synthetic/图.png', preview_bytes: 8}}));
  const middle = reply.indexOf(Buffer.from('图')) + 1;
  h.child.stdout.emit('data', reply.subarray(0, middle));
  h.child.stdout.emit('data', reply.subarray(middle));
  h.child.emit('close', 0);
  const result = await pending;
  assert.equal(JSON.parse(result.content[0].text).preview_path, 'C:/synthetic/图.png');
  assert.equal(result.content[1].type, 'image');
  assert.equal(result.content[1].mimeType, 'image/png');
  assert.equal(h.timers[0].cleared, true);
});

test('ordinary stdio client rejects unsafe IDs and invalid selections before dispatch', {timeout: 20000}, async () => {
  const calls = [], sockets = new Set();
  const fake = net.createServer(socket => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
    socket.setEncoding('utf8'); let input = '';
    socket.on('data', chunk => {
      input += chunk; let i;
      while ((i = input.indexOf('\n')) >= 0) {
        const req = JSON.parse(input.slice(0, i)); input = input.slice(i + 1); calls.push(req);
        socket.write(JSON.stringify({id: req.id, ok: true, result: {backend: 'test-only', op: req.op, args: req.args}}) + '\n');
      }
    });
  });
  await new Promise((resolve, reject) => { fake.once('error', reject); fake.listen(0, '127.0.0.1', resolve); });
  const child = spawn(process.execPath, [serverFile], {
    env: {...process.env, DM_BRIDGE_PORT: String(fake.address().port), DM_MCP_ALLOW_DMSCRIPT: '0',
      DM_ANALYSIS_PYTHON: 'mcp-d0-no-such-interpreter.exe'}, stdio: ['pipe', 'pipe', 'pipe'],
  });
  child.stdin.on('error', () => {});
  let buffer = '', id = 1, stderr = '';
  const pending = new Map();
  child.stderr.on('data', c => { stderr += c; });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', c => {
    buffer += c; let i;
    while ((i = buffer.indexOf('\n')) >= 0) {
      const msg = JSON.parse(buffer.slice(0, i)); buffer = buffer.slice(i + 1);
      const w = pending.get(msg.id); if (w) { pending.delete(msg.id); w(msg); }
    }
  });
  const rpc = (method, params) => new Promise((resolve, reject) => {
    const current = id++;
    const timer = setTimeout(() => { pending.delete(current); reject(new Error('RPC timeout: ' + stderr)); }, 5000);
    pending.set(current, msg => { clearTimeout(timer); resolve(msg); });
    child.stdin.write(JSON.stringify({jsonrpc: '2.0', id: current, method, params}) + '\n');
  });
  const tool = (name, args) => rpc('tools/call', {name, arguments: args});
  try {
    const init = await rpc('initialize', {protocolVersion: '2025-11-25', capabilities: {}, clientInfo: {name: 'generic-d0-probe', version: '1'}});
    // The server deliberately negotiates its implemented legacy version; this
    // probe accepts it. Actual WorkBuddy negotiation is a separate local test.
    assert.equal(init.result.protocolVersion, '2024-11-05');
    child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/initialized'}) + '\n');
    const catalog = (await rpc('tools/list', {})).result.tools;
    assert.equal(catalog.length, 21, 'no new algorithm or workflow tools');
    for (const image_id of [-1, '-1', '9007199254740992', '9999999999999999999999999']) {
      assert.equal((await tool('dm_stats', {image_id})).error?.code, -32602, String(image_id));
    }
    for (const name of ['dm_2d_preview', 'dm_2d_analyze']) {
      const args = {capture_dir: 'C:/synthetic/capture'};
      if (name === 'dm_2d_analyze') Object.assign(args, {result_dir: 'C:/synthetic/result', operation_id: 'd0'});
      assert.equal((await tool(name, {...args, roi: [10, 10, 5, 12]})).error?.code, -32602);
      assert.equal((await tool(name, {...args, profile: {start: [1, 1], end: [1, 1]}})).error?.code, -32602);
    }
    assert.equal((await tool('dm_2d_analyze', {capture_dir: 'C:/synthetic/capture', result_dir: 'C:/synthetic/result', operation_id: '  '})).error?.code, -32602);
    assert.equal(calls.length, 0, 'invalid arguments must not reach DM');
    const valid = await tool('dm_stats', {image_id: '1234', rect: [0, 0, 1, 1]});
    assert.equal(JSON.parse(valid.result.content[0].text).args.image_id, '1234');
    assert.equal(calls.length, 1);
    const disabled = await tool('dm_run_script', {script: 'Result(1);'});
    assert.equal(disabled.result.isError, true);
    assert.equal(calls.length, 1, 'script gate still blocks before DM');
    const unavailable = await tool('dm_2d_result', {capture_dir: 'C:/synthetic/capture'});
    assert.equal(unavailable.result.isError, true);
    assert.match(unavailable.result.content[0].text, /DM_ANALYSIS_PYTHON/);
    assert.deepEqual((await rpc('ping', {})).result, {}, 'failed optional worker must not kill core MCP');
    assert.equal(calls.length, 1);
  } finally {
    if (child.exitCode === null && child.signalCode === null) { const done = once(child, 'exit'); child.kill(); await done; }
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => fake.close(resolve));
  }
});
