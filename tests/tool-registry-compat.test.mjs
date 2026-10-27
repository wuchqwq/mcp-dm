// Actual stdio compatibility against a legacy capture. Directory operations do
// not connect to DM or start scientific Python. TCP execution below is a stub.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, readFileSync, rmSync, existsSync} from 'node:fs';
import net from 'node:net';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const baseline = JSON.parse(readFileSync(new URL('./fixtures/tool-registry-legacy.json', import.meta.url), 'utf8'));
const hash = value => createHash('sha256').update(value).digest('hex');
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const digest = value => hash(JSON.stringify(canonical(value)));

function client(mode, folder, extra = {}) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('DM_')));
  Object.assign(env, {
    DM_MCP_BACKEND:mode.environment.DM_MCP_BACKEND, DM_NATIVE_SESSION:'a'.repeat(32),
    DM_IMAGE_PYTHON:'__catalog_test_must_not_start_python__',
    DM_STRUCTURE_PYTHON:'__catalog_test_must_not_start_python__',
  });
  if (mode.image_opt_in) env.DM_IMAGE_WORKSPACE = path.join(folder, 'images');
  if (mode.structure_opt_in) env.DM_STRUCTURE_WORKSPACE = path.join(folder, 'structures');
  Object.assign(env, extra);
  const child = spawn(process.execPath, [path.join(root, 'server.mjs')], {
    cwd:root, env, stdio:['pipe', 'pipe', 'pipe'], windowsHide:true,
  });
  let next = 1, buffer = '', stderr = '';
  const pending = new Map();
  child.stderr.setEncoding('utf8'); child.stdout.setEncoding('utf8');
  child.stderr.on('data', chunk => {stderr += chunk;});
  child.stdin.on('error', () => {});
  child.stdout.on('data', chunk => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const row = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
      assert.equal(row.jsonrpc, '2.0', 'stdout remains strict MCP JSON-RPC');
      const wait = pending.get(row.id);
      if (wait) {pending.delete(row.id); clearTimeout(wait.timer); wait.resolve(row);}
    }
  });
  const exited = new Promise((resolve, reject) => {
    child.once('error', reject); child.once('exit', (code, signal) => resolve({code, signal}));
  });
  const rpc = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++;
    const timer = setTimeout(() => {pending.delete(id); reject(new Error(`${method} timeout: ${stderr}`));}, 30000);
    pending.set(id, {resolve, reject, timer});
    child.stdin.write(JSON.stringify({jsonrpc:'2.0', id, method, params}) + '\n');
  });
  return {
    rpc, tool:(name, args = {}) => rpc('tools/call', {name, arguments:args}),
    exited, stderr:() => stderr,
    async close() {
      child.stdin.end();
      const ended = await exited;
      for (const entry of pending.values()) {clearTimeout(entry.timer); entry.reject(new Error('Client closed'));}
      pending.clear();
      return ended;
    },
  };
}

assert.equal(baseline.schema_version, 1);
assert.equal(baseline.modes.length, 12, 'all backend/opt-in combinations were captured');
for (const mode of baseline.modes) {
  test(`legacy stdio catalog and initialization remain exact: ${mode.mode}`, async () => {
    const folder = mkdtempSync(path.join(tmpdir(), 'registry-compat-'));
    const c = client(mode, folder);
    try {
      if (mode.expected_startup !== 'ready') {
        assert.deepEqual(await c.exited, {code:mode.exit_code, signal:null});
        assert.ok(c.stderr().includes(mode.error_contains));
        return;
      }
      const init = await c.rpc('initialize', {
        protocolVersion:'2024-11-05', capabilities:{}, clientInfo:{name:'registry-compat', version:'1'},
      });
      assert.equal(init.error, undefined);
      assert.equal(init.result.protocolVersion, mode.protocol_version);
      assert.deepEqual(init.result.serverInfo, mode.server_info);
      assert.deepEqual(init.result.capabilities, mode.capabilities);
      assert.equal(hash(init.result.instructions), mode.instructions_sha256, 'initialization instructions are unchanged');
      const listed = await c.rpc('tools/list');
      assert.equal(listed.error, undefined);
      const tools = listed.result.tools;
      assert.deepEqual(tools.map(tool => tool.name), mode.tools.map(tool => tool.name), 'names and order are unchanged');
      for (let i = 0; i < tools.length; i++) {
        assert.equal(digest(tools[i]), mode.tools[i].canonical_json_sha256,
          `complete canonical definition changed for ${tools[i].name}`);
      }
      assert.equal(digest(tools), mode.ordered_definitions_sha256);
      assert.deepEqual((await c.rpc('ping')).result, {});
      assert.equal(existsSync(path.join(folder, 'images')), false, 'catalog does not create scientific workspaces');
      assert.equal(existsSync(path.join(folder, 'structures')), false);
    } finally {
      const ended = await c.close();
      assert.equal(ended.signal, null);
      if (mode.expected_startup === 'ready') assert.equal(ended.code, 0);
      rmSync(folder, {recursive:true, force:true});
    }
  });
}

const imageNames = baseline.modes.find(mode => mode.mode === 'images-image1-structure0').tools.map(tool => tool.name);
const structureNames = baseline.modes.find(mode => mode.mode === 'python-image0-structure1').tools
  .map(tool => tool.name).filter(name => name.startsWith('structure_'));

async function syntheticBridge() {
  const requests = [], sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.setEncoding('utf8');
    let buffer = '';
    socket.on('data', chunk => {
      buffer += chunk; let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const message = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
        requests.push(message);
        socket.write(JSON.stringify({id:message.id, ok:true,
          result:{backend:'synthetic-registry-compat-stub', operation:message.op}}) + '\n');
      }
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {requests, port:server.address().port,
    async close() {await new Promise(resolve => server.close(resolve)); assert.equal(sockets.size, 0, 'MCP stdin closure releases its own stub connection');}};
}

const explicitDisableCases = [
  {backend:'python', disabled:'images', expected:'python-image0-structure1'},
  {backend:'python', disabled:'structures', expected:'python-image1-structure0'},
  {backend:'python', disabled:'images,image-panel,structures', expected:'python-image0-structure0'},
  {backend:'native', disabled:'images,structures', expected:'native-image0-structure0'},
  {backend:'images', disabled:'structures', expected:'images-image1-structure0'},
  {backend:'python', disabled:'image-panel', expected:'python-image1-structure1', omitPanel:true},
];
for (const config of explicitDisableCases) {
  test(`explicit registry disable flags remove catalog and dispatch without disabling peers: ${config.backend}/${config.disabled}`, async () => {
    const mode = baseline.modes.find(item => item.mode === `${config.backend}-image1-structure1`);
    const reference = baseline.modes.find(item => item.mode === config.expected);
    const expected = reference.tools.filter(tool => !config.omitPanel || !tool.name.startsWith('image_panel_'));
    const folder = mkdtempSync(path.join(tmpdir(), 'registry-flags-'));
    const stub = config.backend === 'python' ? await syntheticBridge() : null;
    const c = client(mode, folder, {
      DM_MCP_DISABLED_MODULES:config.disabled,
      ...(stub ? {DM_BRIDGE_HOST:'127.0.0.1', DM_BRIDGE_PORT:String(stub.port)} : {}),
    });
    try {
      const init = await c.rpc('initialize');
      assert.equal(init.error, undefined);
      if (!config.omitPanel) assert.equal(hash(init.result.instructions), reference.instructions_sha256);
      else assert.ok(!init.result.instructions.includes('Use image_panel_open'), 'a disabled panel supplies no panel instruction');
      const catalog = (await c.rpc('tools/list')).result.tools;
      assert.deepEqual(catalog.map(tool => tool.name), expected.map(tool => tool.name));
      for (let i = 0; i < catalog.length; i++) assert.equal(digest(catalog[i]), expected[i].canonical_json_sha256);
      const omitted = mode.tools.filter(tool => !expected.some(item => item.name === tool.name));
      assert.ok(omitted.length > 0);
      for (const tool of omitted) {
        const response = await c.tool(tool.name);
        assert.equal(response.error?.code, -32602, `disabled ${tool.name} is refused before execution`);
        assert.equal(response.result, undefined);
      }
      if (stub) {
        assert.equal(stub.requests.length, 0, 'disabled optional calls do not reach the DM adapter');
        const response = await c.tool('dm_status');
        assert.equal(JSON.parse(response.result.content[0].text).backend, 'synthetic-registry-compat-stub');
        assert.equal(stub.requests.length, 1);
      }
      assert.deepEqual((await c.rpc('ping')).result, {});
      assert.equal(existsSync(path.join(folder, 'images')), false);
      assert.equal(existsSync(path.join(folder, 'structures')), false);
    } finally {
      assert.deepEqual(await c.close(), {code:0, signal:null});
      if (stub) await stub.close();
      rmSync(folder, {recursive:true, force:true});
    }
  });
}

for (const config of [
  {backend:'python', disabled:'unknown-module', message:/unknown-module/},
  {backend:'python', disabled:'dm-python', message:/dm-python/},
  {backend:'native', disabled:'dm-native', message:/dm-native/},
]) {
  test(`registry configuration refuses unknown or selected core disable before protocol startup: ${config.backend}/${config.disabled}`, async () => {
    const mode = baseline.modes.find(item => item.mode === `${config.backend}-image1-structure1`);
    const folder = mkdtempSync(path.join(tmpdir(), 'registry-config-refusal-'));
    const c = client(mode, folder, {DM_MCP_DISABLED_MODULES:config.disabled});
    try {
      const ended = await c.exited;
      assert.notEqual(ended.code, 0);
      assert.equal(ended.signal, null);
      assert.match(c.stderr(), config.message);
      assert.equal(existsSync(path.join(folder, 'images')), false);
      assert.equal(existsSync(path.join(folder, 'structures')), false);
    } finally {
      await c.close();
      rmSync(folder, {recursive:true, force:true});
    }
  });
}

for (const modeName of ['python-image0-structure0', 'python-image0-structure1', 'python-image1-structure0']) {
  test(`disabled optional modules refuse direct dispatch while Python module still executes: ${modeName}`, async () => {
    const mode = baseline.modes.find(item => item.mode === modeName);
    const folder = mkdtempSync(path.join(tmpdir(), 'registry-disabled-'));
    const stub = await syntheticBridge();
    const c = client(mode, folder, {DM_BRIDGE_HOST:'127.0.0.1', DM_BRIDGE_PORT:String(stub.port)});
    try {
      const names = (await c.rpc('tools/list')).result.tools.map(tool => tool.name);
      const disabled = [...(!mode.image_opt_in ? imageNames : []), ...(!mode.structure_opt_in ? structureNames : [])];
      assert.ok(disabled.length > 0);
      for (const name of disabled) {
        assert.ok(!names.includes(name), `disabled ${name} is absent from composition`);
        const response = await c.tool(name);
        assert.equal(response.error?.code, -32602, `disabled ${name} is a protocol refusal`);
        assert.equal(response.result, undefined, 'an error cannot be hidden as a successful tool response');
      }
      assert.equal(stub.requests.length, 0, 'disabled modules never reach the selected DM transport');
      if (mode.image_opt_in) assert.equal((await c.tool('image_open')).error?.code, -32602);
      if (mode.structure_opt_in) assert.equal((await c.tool('structure_open')).error?.code, -32602);
      assert.equal(existsSync(path.join(folder, 'images')), false, 'invalid arguments never start the poisoned worker');
      assert.equal(existsSync(path.join(folder, 'structures')), false);
      const status = await c.tool('dm_status');
      assert.equal(status.error, undefined); assert.notEqual(status.result.isError, true);
      const data = JSON.parse(status.result.content[0].text);
      assert.equal(data.backend, 'synthetic-registry-compat-stub');
      // The legacy dm_status facade intentionally maps to the Python ping op.
      assert.equal(stub.requests.length, 1); assert.equal(stub.requests[0].op, 'ping');
      assert.deepEqual((await c.rpc('ping')).result, {});
    } finally {
      assert.deepEqual(await c.close(), {code:0, signal:null});
      await stub.close();
      rmSync(folder, {recursive:true, force:true});
    }
  });
}
