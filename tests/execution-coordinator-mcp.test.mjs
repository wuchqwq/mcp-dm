// Actual stdio MCP + the actual external image worker and durable journal.
// A test-only wrapper pauses Workspace.action AFTER the real prepared record
// was fsynced. It neither replaces scientific algorithms nor creates receipts.
// No DM, private image, browser or model-viewing qualification is implied.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, writeFileSync, readFileSync, readdirSync, existsSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DM_IMAGE_PYTHON || process.env.DM_TEST_PYTHON || 'python';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = filename => createHash('sha256').update(readFileSync(filename)).digest('hex');
async function until(predicate, label, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw Error('Timed out waiting for ' + label);
    await sleep(15);
  }
}
function json(filename) { return JSON.parse(readFileSync(filename, 'utf8')); }
function successful(reply) {
  assert.equal(reply.error, undefined, JSON.stringify(reply));
  assert.notEqual(reply.result?.isError, true, JSON.stringify(reply));
  const data = JSON.parse(reply.result.content.find(part => part.type === 'text').text);
  assert.equal(data.backend, 'external-image-workspace');
  assert.equal(data.state, 'completed');
  return data;
}
function failed(reply, pattern) {
  assert.equal(reply.error, undefined, JSON.stringify(reply));
  assert.equal(reply.result?.isError, true, JSON.stringify(reply));
  assert.match(reply.result.content[0].text, pattern);
}
function picture(reply, imagePath) {
  const image = reply.result.content.find(part => part.type === 'image');
  assert.ok(image, 'MCP must return image content, not just its path');
  assert.equal(image.mimeType, 'image/png');
  assert.deepEqual(Buffer.from(image.data, 'base64'), readFileSync(imagePath));
}
function fixture(t, {timeoutMs = 30000, denyTermination = false, holds = []} = {}) {
  const directory = mkdtempSync(path.join(tmpdir(), 'dm-coordinator-mcp-'));
  const workspace = path.join(directory, 'workspace');
  const source = path.join(directory, 'source.tiff');
  const workerPath = path.join(directory, 'controlled_worker.py');
  const serverPath = path.join(directory, 'composed_server.mjs');
  const made = spawnSync(python, ['-B', '-c',
    'import numpy as np,tifffile,sys; y,x=np.indices((16,16)); a=(1000+(x%8)*31+(y%4)*17).astype(np.uint16); tifffile.imwrite(sys.argv[1],np.stack([a,a+50]),photometric="minisblack",metadata=None)', source],
    {encoding: 'utf8', windowsHide: true});
  assert.equal(made.status, 0, made.stderr);
  // The wrapper logs worker launches separately from actual action execution.
  // Same-ID replay/query bypasses Workspace.action in the shipping journal.
  writeFileSync(workerPath, `import importlib.util,json,os,pathlib,sys,time\n` +
    `worker=pathlib.Path(${JSON.stringify(path.join(root, 'tools', 'image_workspace.py'))})\n` +
    `sys.path.insert(0,str(worker.parent))\n` +
    `spec=importlib.util.spec_from_file_location('coordinator_real_image_worker',worker)\n` +
    `module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n` +
    `folder=pathlib.Path(${JSON.stringify(directory)}); holds=set(${JSON.stringify(holds)})\n` +
    `execute=module.execute\n` +
    `def observed(request):\n` +
    ` with (folder/'received.jsonl').open('a',encoding='utf-8') as log: log.write(json.dumps({'action':request.get('action'),'request_id':request.get('request_id'),'query_request_id':request.get('query_request_id'),'pid':os.getpid()})+'\\n')\n` +
    ` return execute(request)\n` +
    `module.execute=observed\n` +
    `original=module.Workspace.action\n` +
    `def controlled(self,action,request,ident):\n` +
    ` rid=request['request_id']\n` +
    ` with (folder/'actions.jsonl').open('a',encoding='utf-8') as log: log.write(json.dumps({'action':action,'request_id':rid,'pid':os.getpid()})+'\\n')\n` +
    ` if rid in holds:\n` +
    `  saved=json.loads((self.root/'requests'/(rid+'.json')).read_text(encoding='utf-8'))\n` +
    `  assert saved['state']=='prepared' and saved['request_id']==rid\n` +
    `  (folder/('accepted-'+rid)).write_text(str(os.getpid()),encoding='ascii')\n` +
    `  deadline=time.monotonic()+45\n` +
    `  while not (folder/('release-'+rid)).is_file():\n` +
    `   if time.monotonic()>deadline: raise RuntimeError('Test-only release deadline expired')\n` +
    `   time.sleep(.01)\n` +
    ` return original(self,action,request,ident)\n` +
    `module.Workspace.action=controlled\n` +
    `raise SystemExit(module.main())\n`);
  const imports = {
    server: pathToFileURL(path.join(root, 'server.mjs')).href,
    registry: pathToFileURL(path.join(root, 'lib', 'runtime', 'tool_registry.mjs')).href,
    images: pathToFileURL(path.join(root, 'lib', 'tools', 'image_module.mjs')).href,
    workspace: pathToFileURL(path.join(root, 'lib', 'image_workspace.mjs')).href,
  };
  writeFileSync(serverPath, `import {startMcpServer} from ${JSON.stringify(imports.server)};\n` +
    `import {ToolRegistry} from ${JSON.stringify(imports.registry)};\n` +
    `import {createImageModule} from ${JSON.stringify(imports.images)};\n` +
    `import {ImageWorkspace} from ${JSON.stringify(imports.workspace)};\n` +
    `import {spawn} from 'node:child_process';\nimport {appendFileSync} from 'node:fs';\n` +
    `const spawnProcess=(...args)=>{const child=spawn(...args);` +
    `appendFileSync(${JSON.stringify(path.join(directory, 'spawns.jsonl'))},JSON.stringify({pid:child.pid})+'\\n');` +
    `child.once('close',()=>appendFileSync(${JSON.stringify(path.join(directory, 'closes.jsonl'))},JSON.stringify({pid:child.pid})+'\\n'));` +
    (denyTermination ? `child.kill=()=>{appendFileSync(${JSON.stringify(path.join(directory, 'kill-attempts.txt'))},'attempt\\n');queueMicrotask(()=>child.emit('error',Object.assign(Error('test-only termination denied'),{code:'EPERM'})));return false;};` : '') +
    `return child;};\n` +
    `const images=createImageModule({imageWorkspace:new ImageWorkspace({workspace:${JSON.stringify(workspace)},python:${JSON.stringify(python)},workerPath:${JSON.stringify(workerPath)},timeoutMs:${timeoutMs},spawnProcess})});\n` +
    `const registry=new ToolRegistry().register(images).seal();\n` +
    `startMcpServer({runtime:{registry,instructions:registry.instructions(),close:()=>registry.close()}});\n`);
  const clients = [];
  const file = name => path.join(directory, name);
  const journal = id => path.join(workspace, 'requests', id + '.json');
  const actions = () => existsSync(file('actions.jsonl')) ? readFileSync(file('actions.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const received = () => existsSync(file('received.jsonl')) ? readFileSync(file('received.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const release = id => writeFileSync(file('release-' + id), 'release');
  const createClient = () => { const instance = client(serverPath); clients.push(instance); return instance; };
  t.after(async () => {
    for (const id of holds) release(id);
    await until(() => {
      const launched = existsSync(file('spawns.jsonl')) ? readFileSync(file('spawns.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
      const closed = new Set(existsSync(file('closes.jsonl')) ? readFileSync(file('closes.jsonl'), 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line).pid) : []);
      return launched.every(item => closed.has(item.pid));
    }, 'all owned Python processes to actually close before fixture cleanup');
    for (const instance of clients) await instance.close();
    rmSync(directory, {recursive: true, force: true});
  });
  return {directory, workspace, source, createClient, file, journal, actions, received, release};
}
function client(serverPath) {
  const child = spawn(process.execPath, [serverPath], {windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  let next = 1, buffer = '', stderr = '';
  const pending = new Map(), replies = [], protocolErrors = [];
  child.stderr.on('data', part => { stderr = (stderr + part).slice(-16384); });
  child.stdin.on('error', () => {});
  const finishPending = error => {
    for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
    pending.clear();
  };
  child.once('error', finishPending);
  child.once('exit', () => finishPending(Error('Owned MCP server exited: ' + stderr)));
  child.stdout.on('data', part => {
    buffer += part;
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      let reply;
      try { reply = JSON.parse(line); }
      catch (error) { protocolErrors.push(line); finishPending(error); continue; }
      replies.push(reply);
      const item = pending.get(reply.id);
      if (item) { pending.delete(reply.id); clearTimeout(item.timer); item.resolve(reply); }
    }
  });
  function request(method, params = {}) {
    const id = next++;
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(Error('MCP test response deadline: ' + stderr)); }, 60000);
      pending.set(id, {resolve, reject, timer});
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    });
    return {id, promise};
  }
  return {
    replies, protocolErrors,
    raw: (name, args) => request('tools/call', {name, arguments: args}),
    rpc: (method, params) => request(method, params).promise,
    tool: (name, args) => request('tools/call', {name, arguments: args}).promise,
    async cancel(handle) {
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/cancelled', params: {requestId: handle.id}}) + '\n');
      // The shipping MCP facade suppresses a cancelled RPC response. Settle
      // only the test's waiter; this marker is never a server acknowledgement.
      const item = pending.get(handle.id);
      if (item) { pending.delete(handle.id); clearTimeout(item.timer); item.resolve({testWaitAbandoned: true}); }
      await request('ping').promise; // notification processed before this fence
    },
    async close() {
      if (child.exitCode !== null) return;
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { child.kill(); reject(Error('Owned MCP server close deadline')); }, 10000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
        child.stdin.end();
      });
      assert.deepEqual(protocolErrors, []);
    },
  };
}
async function prepared(f, id) {
  await until(() => existsSync(f.file('accepted-' + id)), 'actual fsynced prepared journal ' + id);
  assert.equal(json(f.journal(id)).state, 'prepared');
}
async function setupImage(f, c) {
  const opened = successful(await c.tool('image_open', {source_path: f.source, request_id: 'setup-open'}));
  const frame = successful(await c.tool('image_frame', {object_id: opened.object_id, frame_index: 1, request_id: 'setup-frame'}));
  return successful(await c.tool('image_calibrate', {object_id: frame.object_id, scope: 'image', xy_scale: {x: .2, y: -.5, unit: 'nm'},
    source_text: 'Synthetic source: signed X=.2 nm/px and Y=-.5 nm/px; uncertainty not supplied', request_id: 'setup-calibration'}));
}
function checkFFT(filename) {
  const bytes = readFileSync(filename);
  assert.equal(bytes.subarray(0, 6).toString('hex'), '934e554d5059');
  const major = bytes[6], lengthBytes = major === 1 ? 2 : 4;
  const headerLength = lengthBytes === 2 ? bytes.readUInt16LE(8) : bytes.readUInt32LE(8);
  const offset = 8 + lengthBytes + headerLength;
  const header = bytes.subarray(8 + lengthBytes, offset).toString('ascii');
  assert.match(header, /'descr': '<c16'/); assert.match(header, /'fortran_order': False/); assert.match(header, /'shape': \(12, 12\)/);
  assert.equal(bytes.length - offset, 12 * 12 * 16);
  const values = Array.from({length: 12}, (_, y) => Array.from({length: 12}, (_, x) => 1050 + ((x + 2) % 8) * 31 + ((y + 3) % 4) * 17));
  const mean = values.flat().reduce((sum, value) => sum + value, 0) / 144;
  for (let sy = 0; sy < 12; sy++) for (let sx = 0; sx < 12; sx++) {
    const ky = (sy + 6) % 12, kx = (sx + 6) % 12;
    let re = 0, im = 0;
    for (let y = 0; y < 12; y++) for (let x = 0; x < 12; x++) {
      const phase = -2 * Math.PI * (kx * x + ky * y) / 12;
      re += (values[y][x] - mean) * Math.cos(phase); im += (values[y][x] - mean) * Math.sin(phase);
    }
    const position = offset + (sy * 12 + sx) * 16;
    assert.ok(Math.abs(bytes.readDoubleLE(position) - re) < 1e-8, 'independent DFT real component');
    assert.ok(Math.abs(bytes.readDoubleLE(position + 8) - im) < 1e-8, 'independent DFT imaginary component');
  }
}

test('coordinated stdio cancellation preserves actual FFT identity while queued cancellation never submits; fresh client recovers science', {timeout: 90000}, async t => {
  const f = fixture(t, {holds: ['held-fft']}), c = f.createClient();
  const sourceHash = hash(f.source), calibrated = await setupImage(f, c);
  const fftArgs = {object_id: calibrated.object_id, rect: [2, 3, 14, 15], window: 'none', subtract_mean: true, request_id: 'held-fft'};
  const fftCall = c.raw('image_fft', fftArgs);
  await prepared(f, 'held-fft');
  await c.cancel(fftCall);
  const cancelled = c.raw('image_context', {object_id: calibrated.object_id, metadata: {source_text: 'This queued write must not run'}, request_id: 'cancelled-queued'});
  await c.cancel(cancelled);
  const after = c.raw('image_preview', {object_id: calibrated.object_id, max_size: 64, request_id: 'after-held'});
  assert.equal(successful(await c.tool('image_info', {object_id: calibrated.object_id})).object_id, calibrated.object_id);
  failed(await c.tool('image_result', {request_id: 'held-fft'}), /INCOMPLETE_REQUEST/);
  assert.equal(existsSync(f.journal('after-held')), false, 'cancelled wait retains the real worker slot');
  assert.equal(existsSync(f.journal('cancelled-queued')), false, 'queued cancellation has no journal or plugin/worker call');
  f.release('held-fft');
  const afterReply = await after.promise; picture(afterReply, successful(afterReply).image_path);
  assert.equal(json(f.journal('held-fft')).state, 'completed');
  await c.rpc('ping');
  assert.ok(!c.replies.some(reply => [fftCall.id, cancelled.id].includes(reply.id)), 'late worker completion cannot send suppressed RPC replies');
  assert.equal(f.actions().filter(entry => entry.request_id === 'held-fft').length, 1);
  assert.equal(f.actions().filter(entry => entry.request_id === 'cancelled-queued').length, 0);
  assert.equal(f.received().filter(entry => entry.request_id === 'cancelled-queued').length, 0, 'no real Python worker receives the cancelled queued operation');
  assert.equal(existsSync(f.journal('cancelled-queued')), false);
  await c.close();
  const fresh = f.createClient(), recoveredReply = await fresh.tool('image_result', {request_id: 'held-fft'});
  const recovered = successful(recoveredReply); picture(recoveredReply, recovered.image_path);
  assert.equal(recovered.object_id, json(f.journal('held-fft')).response.object_id);
  assert.deepEqual(recovered.xy_calibration, calibrated.xy_calibration);
  assert.deepEqual(recovered.shape_yx, [12, 12]);
  checkFFT(recovered.array_path);
  const originalRecordHash = hash(f.journal('held-fft')), spectrumHash = hash(recovered.array_path);
  assert.equal(successful(await fresh.tool('image_fft', fftArgs)).object_id, recovered.object_id);
  failed(await fresh.tool('image_fft', {...fftArgs, rect: [1, 3, 13, 15]}), /REQUEST_CONFLICT/);
  assert.equal(hash(f.journal('held-fft')), originalRecordHash);
  assert.equal(hash(recovered.array_path), spectrumHash);
  assert.equal(f.actions().filter(entry => entry.request_id === 'held-fft').length, 1, 'replay/query/conflict do not recompute FFT');
  const matching = readdirSync(path.join(f.workspace, 'objects')).map(id => json(path.join(f.workspace, 'objects', id, 'object.json'))).filter(object => object.request_id === 'held-fft');
  assert.deepEqual(matching.map(object => object.object_id), [recovered.object_id], 'one scientific object, never a second cancelled-result copy');
  const exported = path.join(f.directory, 'fft-export');
  successful(await fresh.tool('image_export', {object_id: recovered.object_id, output_dir: exported, request_id: 'export-recovered'}));
  assert.equal(hash(path.join(exported, 'data.npy')), spectrumHash);
  const manifest = json(path.join(exported, 'manifest.json'));
  assert.deepEqual(manifest.xy_calibration, calibrated.xy_calibration);
  assert.equal(hash(f.source), sourceHash);
});

test('coordinated stdio deadline leaves an actual prepared request unknown and recover never replays it', {timeout: 60000}, async t => {
  const f = fixture(t, {timeoutMs: 3000, holds: ['deadline-open']}), c = f.createClient();
  const before = hash(f.source);
  const call = c.raw('image_open', {source_path: f.source, request_id: 'deadline-open'});
  await prepared(f, 'deadline-open');
  failed(await call.promise, /time limit.*incomplete.*original request_id/);
  // A later write crosses the same resource queue only after actual close.
  const after = successful(await c.tool('image_open', {source_path: f.source, request_id: 'after-deadline'}));
  assert.ok(after.object_id);
  const recordHash = hash(f.journal('deadline-open'));
  await c.close();
  const fresh = f.createClient();
  failed(await fresh.tool('image_result', {request_id: 'deadline-open'}), /INCOMPLETE_REQUEST/);
  assert.equal(json(f.journal('deadline-open')).state, 'prepared');
  assert.equal(hash(f.journal('deadline-open')), recordHash);
  assert.equal(f.actions().filter(entry => entry.request_id === 'deadline-open').length, 1);
  assert.equal(hash(f.source), before);
  assert.ok(!readdirSync(path.join(f.workspace, 'objects')).some(id => json(path.join(f.workspace, 'objects', id, 'object.json')).request_id === 'deadline-open'));
});

test('failed termination plus late science completion retains the slot and original result without corrupting the MCP stream', {timeout: 60000}, async t => {
  const f = fixture(t, {timeoutMs: 3000, denyTermination: true, holds: ['late-open']}), c = f.createClient();
  const before = hash(f.source);
  const first = c.raw('image_open', {source_path: f.source, request_id: 'late-open'});
  await prepared(f, 'late-open');
  failed(await first.promise, /time limit|process error/);
  assert.ok(existsSync(f.file('kill-attempts.txt')));
  const second = c.raw('image_open', {source_path: f.source, request_id: 'after-late'});
  failed(await c.tool('image_result', {request_id: 'late-open'}), /INCOMPLETE_REQUEST/);
  assert.equal(existsSync(f.journal('after-late')), false, 'kill attempt and process error are not process closure');
  f.release('late-open');
  successful(await second.promise);
  const recovered = successful(await c.tool('image_result', {request_id: 'late-open'}));
  assert.equal(recovered.object_id, json(f.journal('late-open')).response.object_id);
  assert.equal(c.replies.filter(reply => reply.id === first.id).length, 1, 'late output never produces another deadline response');
  assert.equal(f.actions().filter(entry => entry.request_id === 'late-open').length, 1);
  await c.rpc('ping');
  assert.deepEqual(c.protocolErrors, []);
  assert.equal(hash(f.source), before);
});
