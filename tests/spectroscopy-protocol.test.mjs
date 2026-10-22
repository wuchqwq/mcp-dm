import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

// This test exercises the MCP facade against an isolated, ephemeral echo bridge.
// It does not connect to DM and cannot establish real EDS/EELS support.
test('experimental spectrum MCP catalog, exact bridge mapping and rejection before dispatch', async () => {
  const received = [], sockets = new Set();
  const fake = net.createServer(socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => {});
    socket.setEncoding('utf8');
    let input = '';
    socket.on('data', chunk => {
      input += chunk;
      let index;
      while ((index = input.indexOf('\n')) >= 0) {
        const request = JSON.parse(input.slice(0, index));
        input = input.slice(index + 1);
        received.push(request);
        socket.write(JSON.stringify({ id: request.id, ok: true, result: {
          backend: 'test-only-echo', op: request.op, args: request.args,
        } }) + '\n');
      }
    });
  });
  await new Promise((resolve, reject) => {
    fake.once('error', reject);
    fake.listen(0, '127.0.0.1', resolve);
  });
  const child = spawn(process.execPath, [fileURLToPath(new URL('../server.mjs', import.meta.url))], {
    env: { ...process.env, DM_BRIDGE_HOST: '127.0.0.1', DM_BRIDGE_PORT: String(fake.address().port), DM_MCP_TIMEOUT_MS: '2000' },
    stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
  });
  const pending = new Map();
  let buffer = '', stderr = '', nextId = 1;
  child.stderr.on('data', chunk => { stderr += chunk; });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    buffer += chunk;
    let index;
    while ((index = buffer.indexOf('\n')) >= 0) {
      const message = JSON.parse(buffer.slice(0, index));
      buffer = buffer.slice(index + 1);
      const resolve = pending.get(message.id);
      if (resolve) { pending.delete(message.id); resolve(message); }
    }
  });
  const rpc = (method, params, transform = line => line) => new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`MCP spectrum protocol test timed out (${method}): ${stderr}`));
    }, 5000);
    pending.set(id, result => { clearTimeout(timer); resolve(result); });
    child.stdin.write(transform(JSON.stringify({ jsonrpc: '2.0', id, method, params })) + '\n');
  });
  try {
    const init = await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'spectrum-protocol-test', version: '1' } });
    assert.equal(init.result.serverInfo.version, '0.6.0');
    assert.match(init.result.instructions, /NOT_TESTED/);
    const catalog = (await rpc('tools/list', {})).result.tools;
    const names = ['dm_spectrum_info', 'dm_spectrum', 'dm_spectrum_integrate', 'dm_spectrum_export'];
    assert.equal(catalog.length, 21, 'retain image and spectrum tools alongside the task-A tools and three 4D-STEM tools');
    assert.deepEqual(catalog.filter(tool => tool.name.startsWith('dm_spectrum')).map(tool => tool.name), names);
    for (const name of names) {
      const entry = catalog.find(tool => tool.name === name);
      assert.match(entry.description, /NOT_TESTED/);
      assert.match(entry.description, /合成数据/);
      assert.equal(entry.inputSchema.additionalProperties, false);
      assert.equal(entry.inputSchema.properties.image_id.type, 'integer');
      assert.equal(entry.inputSchema.properties.image_id.minimum, 0);
      assert.equal(entry.inputSchema.properties.energy_axis.maximum, 2);
      assert.match(entry.inputSchema.properties.energy_axis.description, /NumPy/);
      assert.ok(entry.inputSchema.required.includes('image_id'));
      assert.ok(entry.inputSchema.required.includes('energy_axis'));
    }
    assert.ok(catalog.find(tool => tool.name === 'dm_spectrum_integrate').inputSchema.required.includes('energy_window_eV'));
    assert.ok(catalog.find(tool => tool.name === 'dm_spectrum_export').inputSchema.required.includes('path'));

    // Include non-square selections, descending/negative energies, fractional
    // centres and zero-dimensional spatial bounds to catch axis/argument loss.
    const valid = [
      ['dm_spectrum_info', 'spectrum_info', { image_id: 17, energy_axis: 2, spatial_bounds: [[2, 8], [3, 5]] }],
      ['dm_spectrum_info', 'spectrum_info', { image_id: 0, energy_axis: 0, spatial_bounds: [] }],
      ['dm_spectrum', 'spectrum', { image_id: 18, energy_axis: 1, reduction: 'mean', spatial_bounds: [[0, 7]], energy_window_eV: [-2.5, 4.125] }],
      ['dm_spectrum', 'spectrum', { image_id: 18, energy_axis: 0 }],
      ['dm_spectrum', 'spectrum', { image_id: 18, energy_axis: 2, reduction: 'sum' }],
      ['dm_spectrum_integrate', 'spectrum_integrate', { image_id: 19, energy_axis: 0, spatial_bounds: [[1, 6], [2, 9]], energy_window_eV: [0.25, 12.5] }],
      ['dm_spectrum_export', 'spectrum_export', { image_id: 20, energy_axis: 1, path: 'F:\\new-results\\spectrum.csv', reduction: 'mean', spatial_bounds: [[3, 11]], energy_window_eV: [500, 750] }],
      ['dm_spectrum_export', 'spectrum_export', { image_id: 20, energy_axis: 0, path: '\\\\host\\share\\SPECTRUM.CSV' }],
    ];
    for (const [name, op, args] of valid) {
      const response = await rpc('tools/call', { name, arguments: args });
      assert.equal(response.result.isError, undefined);
      const value = JSON.parse(response.result.content[0].text);
      assert.equal(value.backend, 'test-only-echo');
      assert.equal(value.op, op);
      assert.deepEqual(value.args, args, `${name} must preserve explicit arguments without clipping or defaults`);
    }
    assert.equal(received.length, valid.length);

    const base = { image_id: 7, energy_axis: 1 };
    const invalid = [
      ['dm_spectrum_info', {}],
      ['dm_spectrum_info', { energy_axis: 0 }],
      ['dm_spectrum_info', { image_id: 1 }],
      ...['front', '7', -1, 1.5, null].map(image_id => ['dm_spectrum', { ...base, image_id }]),
      ...[-1, 3, 0.5, '1', null].map(energy_axis => ['dm_spectrum', { ...base, energy_axis }]),
      ...['median', 'SUM', 0, null].map(reduction => ['dm_spectrum', { ...base, reduction }]),
      ...[
        [[0, 2], [0, 2], [0, 2]], [0, 2], [[0, 1, 2]], [[0]],
        [[-1, 2]], [[1.5, 4]], [['0', 2]], [[2, 2]], [[5, 2]], null,
      ].map(spatial_bounds => ['dm_spectrum', { ...base, spatial_bounds }]),
      ...[
        [], [1], [1, 2, 3], [2, 2], [4, 2], ['1', 2], [null, 2], [1, null], null,
      ].map(energy_window_eV => ['dm_spectrum', { ...base, energy_window_eV }]),
      ['dm_spectrum', { ...base, unexpected: true }],
      ['dm_spectrum_info', { ...base, reduction: 'sum' }],
      ['dm_spectrum_info', { ...base, energy_window_eV: [0, 10] }],
      ['dm_spectrum_integrate', base],
      ['dm_spectrum_integrate', { ...base, energy_window_eV: [0, 10], reduction: 'mean' }],
      ['dm_spectrum_export', base],
      ['dm_spectrum_export', { ...base, path: 'relative.csv' }],
      ['dm_spectrum_export', { ...base, path: 'F:\\out.npy' }],
      ['dm_spectrum_export', { ...base, path: 'F:\\out.csv\u0000' }],
      ['dm_spectrum_export', { ...base, path: 'F:\\out.csv', format: 'csv' }],
    ];
    for (const [name, args] of invalid) {
      const response = await rpc('tools/call', { name, arguments: args });
      assert.equal(response.error?.code, -32602, `${name} must reject ${JSON.stringify(args)}`);
    }
    // JSON numeric overflow is still parsable JSON, and must not reach DM.
    const overflow = await rpc('tools/call', { name: 'dm_spectrum', arguments: { ...base, energy_window_eV: [0, 987654321] } }, line => line.replace('987654321', '1e400'));
    assert.equal(overflow.error?.code, -32602);
    assert.equal(received.length, valid.length, 'all invalid arguments must be rejected before bridge dispatch');
    // A final acknowledged request proves no queued invalid operation leaked.
    const final = await rpc('tools/call', { name: 'dm_spectrum_info', arguments: base });
    assert.deepEqual(JSON.parse(final.result.content[0].text).args, base);
    assert.equal(received.length, valid.length + 1);
  } finally {
    const exited = once(child, 'exit');
    child.kill();
    await exited;
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => fake.close(resolve));
  }
});
