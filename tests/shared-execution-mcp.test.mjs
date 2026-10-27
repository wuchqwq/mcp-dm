// Actual stdio MCP plus the shipping image/ASE scientific workers. Test-only
// barriers pause AFTER each worker fsyncs its own prepared journal. They do not
// calculate scientific results or manufacture request completion records.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DM_STRUCTURE_PYTHON || process.env.DM_TEST_PYTHON || 'python';
const optional = {skip: !process.env.DM_STRUCTURE_PYTHON && 'Set DM_STRUCTURE_PYTHON to the independent image/ASE scientific environment', timeout: 120000};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const json = filename => JSON.parse(readFileSync(filename, 'utf8'));
const hash = filename => createHash('sha256').update(readFileSync(filename)).digest('hex');
async function until(predicate, label, timeoutMs = 30000) {
  const deadline = performance.now() + timeoutMs;
  while (!predicate()) {
    if (performance.now() >= deadline) throw Error('Timed out waiting for ' + label);
    await sleep(15);
  }
}
function successful(reply, backend) {
  assert.equal(reply.error, undefined, JSON.stringify(reply));
  assert.notEqual(reply.result?.isError, true, JSON.stringify(reply));
  const data = JSON.parse(reply.result.content.find(part => part.type === 'text').text);
  if (backend) assert.equal(data.backend, backend);
  assert.equal(data.state, 'completed');
  return data;
}
function failed(reply, pattern) {
  assert.equal(reply.error, undefined, JSON.stringify(reply));
  assert.equal(reply.result?.isError, true, JSON.stringify(reply));
  assert.match(reply.result.content[0].text, pattern);
}
function client(serverPath) {
  const child = spawn(process.execPath, [serverPath], {windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  const pending = new Map(), replies = [], protocolErrors = [];
  let sequence = 0, buffer = '', stderr = '';
  child.stderr.on('data', chunk => {stderr = (stderr + chunk).slice(-16384);});
  child.stdin.on('error', () => {});
  const failPending = error => {for (const item of pending.values()) {clearTimeout(item.timer); item.reject(error);} pending.clear();};
  child.once('error', failPending); child.once('exit', () => failPending(Error('Owned stdio server exited: ' + stderr)));
  child.stdout.on('data', chunk => {
    buffer += chunk; let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      let value; try {value = JSON.parse(line);} catch (error) {protocolErrors.push(line); failPending(error); continue;}
      replies.push(value); const item = pending.get(value.id);
      if (item) {pending.delete(value.id); clearTimeout(item.timer); item.resolve(value);}
    }
  });
  function request(method, params = {}) {
    const id = ++sequence;
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {pending.delete(id); reject(Error('MCP test response deadline: ' + stderr));}, 60000);
      pending.set(id, {resolve, reject, timer});
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    });
    promise.catch(() => {}); return {id, promise};
  }
  return {replies, protocolErrors,
    raw: (name, args) => request('tools/call', {name, arguments: args}),
    tool: (name, args) => request('tools/call', {name, arguments: args}).promise,
    rpc: (method, params) => request(method, params).promise,
    async cancel(handle) {
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/cancelled', params: {requestId: handle.id}}) + '\n');
      // Settle only this test's abandoned waiter, never claim cancellation ACK.
      const item = pending.get(handle.id);
      if (item) {pending.delete(handle.id); clearTimeout(item.timer); item.resolve({testWaitAbandoned: true});}
      await request('ping').promise;
    },
    async close() {
      if (child.exitCode !== null) return;
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {child.kill(); reject(Error('Owned stdio server close deadline'));}, 10000);
        child.once('exit', () => {clearTimeout(timer); resolve();}); child.stdin.end();
      });
      assert.deepEqual(protocolErrors, []);
    },
  };
}
function fixture(t, {timeoutMs = 30000, imageHolds = [], structureHolds = []} = {}) {
  const directory = mkdtempSync(path.join(tmpdir(), 'shared-science-execution-'));
  const imageWorkspace = path.join(directory, 'images'), structureWorkspace = path.join(directory, 'structures');
  const secondaryWorkspace = path.join(directory, 'secondary-images');
  const source = path.join(directory, 'synthetic.tiff'), cif = path.join(directory, 'copper.cif');
  const made = spawnSync(python, ['-B', '-c',
    "import sys,numpy as np,tifffile;from ase.build import bulk;from ase.io import write;a=np.arange(256,dtype=np.uint16).reshape(16,16);tifffile.imwrite(sys.argv[1],a,metadata=None);write(sys.argv[2],bulk('Cu','fcc',a=3.6,cubic=True),format='cif')",
    source, cif], {encoding: 'utf8', windowsHide: true});
  assert.equal(made.status, 0, made.stderr);
  const workers = {};
  for (const family of ['image', 'structure']) {
    const worker = path.join(directory, family + '_controlled.py'); workers[family] = worker;
    const holds = family === 'image' ? imageHolds : structureHolds;
    const setup = family === 'image'
      ? `import importlib.util\nsys.path.insert(0,${JSON.stringify(path.join(root, 'tools'))})\nspec=importlib.util.spec_from_file_location('shared_actual_image',${JSON.stringify(path.join(root, 'tools', 'image_workspace.py'))})\nmodule=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\ncls=module.Workspace\noriginal=cls.action\n`
      : `sys.path.insert(0,${JSON.stringify(root)})\nfrom crystallography import structure_tools as science\nfrom tools import structure_worker as module\ncls=science.StructureWorkspace\noriginal=cls.action\n`;
    const signature = family === 'image' ? 'self,action,request,ident' : 'self,request';
    const originalCall = family === 'image' ? 'original(self,action,request,ident)' : 'original(self,request)';
    writeFileSync(worker,
      `import json,os,pathlib,sys,time\n${setup}folder=pathlib.Path(${JSON.stringify(directory)});family=${JSON.stringify(family)};holds=set(${JSON.stringify(holds)})\n` +
      `execute=module.execute\ndef observed(request):\n with (folder/'received.jsonl').open('a',encoding='utf-8') as log: log.write(json.dumps({'family':family,'action':request.get('action'),'request_id':request.get('request_id'),'query_request_id':request.get('query_request_id'),'workspace':request.get('workspace'),'pid':os.getpid()})+'\\n')\n return execute(request)\nmodule.execute=observed\n` +
      `def controlled(${signature}):\n rid=request['request_id']\n with (folder/'actions.jsonl').open('a',encoding='utf-8') as log: log.write(json.dumps({'family':family,'request_id':rid,'pid':os.getpid()})+'\\n')\n if rid in holds:\n  saved=json.loads((self.root/'requests'/(rid+'.json')).read_text(encoding='utf-8'))\n  assert saved['state']=='prepared' and saved['request_id']==rid\n  (folder/('accepted-'+family+'-'+rid)).write_text(str(os.getpid()),encoding='ascii')\n  deadline=time.monotonic()+60\n  while not (folder/('release-'+family+'-'+rid)).is_file():\n   if time.monotonic()>deadline: raise RuntimeError('Test-only release deadline expired')\n   time.sleep(.01)\n return ${originalCall}\ncls.action=controlled\nraise SystemExit(module.main())\n`);
  }
  const href = relative => pathToFileURL(path.join(root, relative)).href;
  const bootstrap = path.join(directory, 'server.mjs');
  writeFileSync(bootstrap,
    `import {startMcpServer} from ${JSON.stringify(href('server.mjs'))};\n` +
    `import {ToolRegistry} from ${JSON.stringify(href('lib/runtime/tool_registry.mjs'))};\n` +
    `import {ExecutionCoordinator} from ${JSON.stringify(href('lib/runtime/execution_coordinator.mjs'))};\n` +
    `import {ImageWorkspace,imageTools} from ${JSON.stringify(href('lib/image_workspace.mjs'))};\n` +
    `import {StructureWorkspace} from ${JSON.stringify(href('lib/structure_workspace.mjs'))};\n` +
    `import {createImageModule} from ${JSON.stringify(href('lib/tools/image_module.mjs'))};\n` +
    `import {createStructureModule} from ${JSON.stringify(href('lib/tools/structure_module.mjs'))};\n` +
    `import {createExecutionModule} from ${JSON.stringify(href('lib/tools/execution_module.mjs'))};\n` +
    `import {spawn} from 'node:child_process';import {appendFileSync} from 'node:fs';\n` +
    `const folder=${JSON.stringify(directory)};const coordinator=new ExecutionCoordinator({capacity:{work:2,query:1}});\n` +
    `const scopedSpawn=family=>(...args)=>{const child=spawn(...args);appendFileSync(folder+'/processes.jsonl',JSON.stringify({event:'spawn',family,pid:child.pid})+'\\n');child.once('close',()=>appendFileSync(folder+'/processes.jsonl',JSON.stringify({event:'close',family,pid:child.pid})+'\\n'));const kill=child.kill.bind(child);child.kill=(...values)=>{appendFileSync(folder+'/processes.jsonl',JSON.stringify({event:'kill-request',family,pid:child.pid})+'\\n');return kill(...values);};return child;};\n` +
    `const image=new ImageWorkspace({workspace:${JSON.stringify(imageWorkspace)},python:${JSON.stringify(python)},workerPath:${JSON.stringify(workers.image)},spawnProcess:scopedSpawn('image'),timeoutMs:${timeoutMs},coordinator});\n` +
    `const structure=new StructureWorkspace({workspace:${JSON.stringify(structureWorkspace)},python:${JSON.stringify(python)},workerPath:${JSON.stringify(workers.structure)},spawnProcess:scopedSpawn('structure'),timeoutMs:${timeoutMs},coordinator});\n` +
    `const secondary=new ImageWorkspace({workspace:${JSON.stringify(secondaryWorkspace)},python:${JSON.stringify(python)},workerPath:${JSON.stringify(workers.image)},spawnProcess:scopedSpawn('secondary'),timeoutMs:${timeoutMs},coordinator});\n` +
    `const imageModule=createImageModule({imageWorkspace:image});const registry=new ToolRegistry().register(imageModule).register(createStructureModule({structureWorkspace:structure})).register(createExecutionModule({coordinator,providers:{image:{provider:'external-image-workspace',workspace:image.workspace,session:'workspace-journal-v1'},structure:{provider:'external-structure-workspace',workspace:structure.workspace,session:'workspace-journal-v1'}}}));\n` +
    `const original=imageModule.tools.find(t=>t.definition.name==='image_open');registry.register({id:'test-secondary-science-port',enabled:true,instructions:'Test-only second resource, not a public supported tool',tools:[{definition:{...original.definition,name:'test_secondary_image_open'},contract:original.contract,execute:(args,{signal}={})=>secondary.call('image_open',args,signal)}]});registry.seal();\n` +
    `startMcpServer({runtime:{registry,instructions:registry.instructions(),close:()=>registry.close()}});\n`);
  const file = name => path.join(directory, name), clients = [];
  const rows = name => existsSync(file(name)) ? readFileSync(file(name), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const release = (family, id) => writeFileSync(file('release-' + family + '-' + id), 'release');
  const createClient = () => {const c = client(bootstrap); clients.push(c); return c;};
  t.after(async () => {
    for (const id of imageHolds) release('image', id);
    for (const id of structureHolds) release('structure', id);
    await until(() => {
      const events = rows('processes.jsonl'); const closed = new Set(events.filter(row => row.event === 'close').map(row => row.pid));
      return events.filter(row => row.event === 'spawn').every(row => closed.has(row.pid));
    }, 'all owned actual workers to close before cleanup');
    for (const c of clients) await c.close();
    rmSync(directory, {recursive: true, force: true});
  });
  return {directory, source, cif, imageWorkspace, structureWorkspace, secondaryWorkspace, file, rows, release, createClient,
    journal: (family, id) => path.join(family === 'image' ? imageWorkspace : structureWorkspace, 'requests', id + '.json')};
}
async function accepted(f, family, id) {
  await until(() => existsSync(f.file('accepted-' + family + '-' + id)), 'real fsynced ' + family + ' prepared journal ' + id);
  assert.equal(json(f.journal(family, id)).state, 'prepared');
}
async function observation(c, provider, requestId, predicate = () => true) {
  let selected;
  for (let attempt = 0; attempt < 100; attempt++) {
    const data = successful(await c.tool('execution_list', {provider, request_id: requestId, limit: 100}), 'execution-observer');
    selected = data.observations.filter(row => row.mode === 'invoke').find(predicate);
    if (selected) return selected;
    await sleep(15);
  }
  throw Error('Missing observed execution for ' + provider + '/' + requestId);
}
function checkTiming(value) {
  assert.equal(value.receiptVersion, 1);
  assert.ok(value.requestRef.provider && value.requestRef.workspace && value.requestRef.session);
  for (const name of ['queueMs', 'startMs', 'runMs', 'totalMs', 'waitMs']) {
    const duration = value.timing[name]; assert.ok(duration === null || Number.isFinite(duration) && duration >= 0, name);
  }
  assert.ok(value.timing.startedAtMs >= value.timing.queuedAtMs);
}

test('normal composition explicitly shares one coordinator and observations remain opt-in', async () => {
  const folder = path.join(tmpdir(), 'shared-composition-no-io-' + process.pid);
  const env = {DM_MCP_BACKEND: 'images', DM_IMAGE_WORKSPACE: path.join(folder, 'images'),
    DM_STRUCTURE_WORKSPACE: path.join(folder, 'structures')};
  for (const enabled of [false, true]) {
    const runtime = createServerRuntime({env: {...env, ...(enabled ? {DM_MCP_EXECUTION_OBSERVABILITY: '1'} : {})}});
    try {
      assert.equal(runtime.providers.image.coordinator, runtime.coordinator);
      assert.equal(runtime.providers.structure.coordinator, runtime.coordinator);
      assert.deepEqual(runtime.providers.image.requestScope, {provider: 'external-image-workspace', workspace: path.resolve(env.DM_IMAGE_WORKSPACE), session: 'workspace-journal-v1'});
      assert.deepEqual(runtime.providers.structure.requestScope, {provider: 'external-structure-workspace', workspace: path.resolve(env.DM_STRUCTURE_WORKSPACE), session: 'workspace-journal-v1'});
      const names = runtime.registry.listTools().map(tool => tool.name);
      assert.equal(names.includes('execution_list'), enabled); assert.equal(names.includes('execution_info'), enabled);
      if (enabled) {
        const response = await runtime.registry.call('execution_list', {provider: 'structure'});
        assert.deepEqual(JSON.parse(response.content[0].text).observations, []);
      }
      assert.equal(existsSync(folder), false, 'composition and observation do not create workers or scientific storage');
    } finally {await runtime.close();}
  }
});

test('actual image and structure share bounded work capacity while scoped recovery remains responsive', optional, async t => {
  const f = fixture(t, {imageHolds: ['same-original-id'], structureHolds: ['same-original-id']}), c = f.createClient();
  const sourceHash = hash(f.source), structureHash = hash(f.cif);
  const structure = successful(await c.tool('structure_open', {source_path: f.cif, request_id: 'structure-source'}), 'external-structure-workspace');
  const common = {object_id: structure.object_id, kind: 'd_spacing', hkls: [[2, 0, 0]]};
  const baseline = successful(await c.tool('structure_measure', {...common, request_id: 'normal-measurement'}), 'external-structure-workspace');
  assert.ok(Math.abs(baseline.measurement.value - 1.8) < 1e-13);
  const normal = await observation(c, 'structure', 'normal-measurement', row => row.closed);
  const image = c.raw('image_open', {source_path: f.source, request_id: 'same-original-id'});
  const heldStructure = c.raw('structure_measure', {...common, request_id: 'same-original-id'});
  await Promise.all([accepted(f, 'image', 'same-original-id'), accepted(f, 'structure', 'same-original-id')]);
  const third = c.raw('test_secondary_image_open', {source_path: f.source, request_id: 'capacity-blocked'});
  await c.rpc('ping');
  assert.equal(f.rows('received.jsonl').some(row => row.workspace === f.secondaryWorkspace), false, 'disjoint resource cannot bypass the shared two-worker work budget');
  const queued = c.raw('structure_measure', {...common, request_id: 'loaded-measurement'});
  const queuedObservation = await observation(c, 'structure', 'loaded-measurement', row => row.state === 'queued');
  assert.equal(queuedObservation.lane, 'work');
  const beforeQuery = performance.now();
  failed(await c.tool('structure_result', {request_id: 'same-original-id'}), /INCOMPLETE_REQUEST/);
  failed(await c.tool('image_result', {request_id: 'same-original-id'}), /INCOMPLETE_REQUEST/);
  const queryMs = performance.now() - beforeQuery;
  const imageObservation = await observation(c, 'image', 'same-original-id');
  const structureObservation = await observation(c, 'structure', 'same-original-id');
  assert.notEqual(imageObservation.executionToken, structureObservation.executionToken);
  assert.equal(imageObservation.requestRef.requestId, structureObservation.requestRef.requestId);
  assert.notEqual(imageObservation.requestRef.provider, structureObservation.requestRef.provider);
  assert.notEqual(imageObservation.requestRef.workspace, structureObservation.requestRef.workspace);
  failed(await c.tool('execution_info', {provider: 'image', execution_id: structureObservation.executionToken}), /scope|found|match/i);
  await c.cancel(third); await c.cancel(heldStructure);
  f.release('image', 'same-original-id'); successful(await image.promise, 'external-image-workspace');
  assert.equal(f.rows('received.jsonl').some(row => row.request_id === 'capacity-blocked'), false, 'cancelled capacity queue never launches');
  f.release('structure', 'same-original-id');
  const loaded = successful(await queued.promise, 'external-structure-workspace');
  assert.deepEqual(loaded.measurement, baseline.measurement);
  const observed = await observation(c, 'structure', 'loaded-measurement', row => row.closed);
  checkTiming(normal); checkTiming(observed);
  assert.ok(observed.timing.queueMs > normal.timing.queueMs, 'same science input records controlled queue waiting separately from execution');
  const cancelled = await observation(c, 'structure', 'same-original-id', row => row.closed);
  assert.equal(cancelled.waitState, 'cancelled'); assert.equal(cancelled.state, 'completed');
  assert.equal(c.replies.some(row => row.id === heldStructure.id), false);
  await c.close();
  const fresh = f.createClient();
  const recovered = successful(await fresh.tool('structure_result', {request_id: 'same-original-id'}), 'external-structure-workspace');
  assert.deepEqual(recovered.measurement, baseline.measurement);
  assert.equal(f.rows('actions.jsonl').filter(row => row.family === 'structure' && row.request_id === 'same-original-id').length, 1);
  assert.equal(f.rows('processes.jsonl').filter(row => row.event === 'kill-request').length, 0);
  assert.equal(hash(f.source), sourceHash); assert.equal(hash(f.cif), structureHash);
  t.diagnostic(JSON.stringify({scope: 'same-input synthetic normal versus controlled barrier load; not a speed benchmark', normal: normal.timing, loaded: observed.timing, twoReservedRecoveryQueriesMs: queryMs}));
});

test('shared execution preserves structure wait-only timeout and image termination policy', optional, async t => {
  const f = fixture(t, {timeoutMs: 4000, imageHolds: ['image-deadline'], structureHolds: ['structure-deadline']}), c = f.createClient();
  const structure = c.raw('structure_open', {source_path: f.cif, request_id: 'structure-deadline'});
  const image = c.raw('image_open', {source_path: f.source, request_id: 'image-deadline'});
  await Promise.all([accepted(f, 'structure', 'structure-deadline'), accepted(f, 'image', 'image-deadline')]);
  failed(await structure.promise, /deadline.*may still finish/);
  failed(await image.promise, /time limit.*incomplete/);
  assert.equal(f.rows('processes.jsonl').some(row => row.event === 'kill-request' && row.family === 'structure'), false, 'existing structure deadline never kills its child');
  assert.equal(f.rows('processes.jsonl').filter(row => row.event === 'kill-request' && row.family === 'image').length, 1);
  const stillRunning = await observation(c, 'structure', 'structure-deadline');
  assert.equal(stillRunning.closed, false); assert.equal(stillRunning.waitState, 'timed_out');
  failed(await c.tool('structure_result', {request_id: 'structure-deadline'}), /INCOMPLETE_REQUEST/);
  f.release('structure', 'structure-deadline');
  await observation(c, 'structure', 'structure-deadline', row => row.closed);
  const recovered = successful(await c.tool('structure_result', {request_id: 'structure-deadline'}), 'external-structure-workspace');
  assert.equal(recovered.object_id, json(f.journal('structure', 'structure-deadline')).response.object_id);
  failed(await c.tool('image_result', {request_id: 'image-deadline'}), /INCOMPLETE_REQUEST/);
  assert.equal(json(f.journal('image', 'image-deadline')).state, 'prepared');
  assert.equal(f.rows('actions.jsonl').filter(row => row.family === 'structure' && row.request_id === 'structure-deadline').length, 1);
  assert.equal(f.rows('actions.jsonl').filter(row => row.family === 'image' && row.request_id === 'image-deadline').length, 1);
  await c.rpc('ping'); assert.deepEqual(c.protocolErrors, []);
});
