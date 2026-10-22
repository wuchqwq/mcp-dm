import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';

// Isolated stdio -> ephemeral TCP echo only. No connection to the DM bridge,
// original DM4 files, or port 8765. This establishes protocol behavior only.
test('4D-STEM catalog, exact forwarding and invalid-input rejection before dispatch', async () => {
  const received = [], sockets = new Set();
  const fake = net.createServer(socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
    socket.on('error', () => {});
    socket.setEncoding('utf8');
    let input = '';
    socket.on('data', chunk => {
      input += chunk;
      let newline;
      while ((newline = input.indexOf('\n')) >= 0) {
        const request = JSON.parse(input.slice(0, newline));
        input = input.slice(newline + 1);
        received.push(request);
        socket.write(JSON.stringify({id: request.id, ok: true,
          result: {backend: 'synthetic-echo-only', op: request.op, args: request.args}}) + '\n');
      }
    });
  });
  await new Promise((resolve, reject) => {
    fake.once('error', reject);
    fake.listen(0, '127.0.0.1', resolve);
  });
  assert.notEqual(fake.address().port, 8765);
  const child = spawn(process.execPath, [fileURLToPath(new URL('../server.mjs', import.meta.url))], {
    env: {...process.env, DM_BRIDGE_HOST: '127.0.0.1',
      DM_BRIDGE_PORT: String(fake.address().port), DM_MCP_TIMEOUT_MS: '2000'},
    stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
  });
  const pending = new Map();
  let buffer = '', stderr = '', nextId = 1;
  child.stderr.on('data', chunk => { stderr += chunk; });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    buffer += chunk;
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const reply = JSON.parse(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
      const resolve = pending.get(reply.id);
      if (resolve) { pending.delete(reply.id); resolve(reply); }
    }
  });
  const rpc = (method, params, transform = value => value) => new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`4D protocol timeout (${method}): ${stderr}`));
    }, 5000);
    pending.set(id, value => { clearTimeout(timer); resolve(value); });
    child.stdin.write(transform(JSON.stringify({jsonrpc: '2.0', id, method, params})) + '\n');
  });
  const detector = {label: 'BF', center_q: [0.125, -0.375], r_inner: 0, r_outer: 2.5};
  const source = {dataset_id: '4d-17', scan_bounds: [[2, 5], [7, 11]]};
  const virtual = {...source, detectors: [detector], chunk_patterns: 17};
  try {
    const init = await rpc('initialize', {protocolVersion: '2024-11-05', capabilities: {},
      clientInfo: {name: '4dstem-protocol-test', version: '1'}});
    assert.equal(init.result.serverInfo.version, '0.6.0');
    const catalog = (await rpc('tools/list', {})).result.tools;
    assert.equal(catalog.length, 17);
    const names = ['dm_4dstem_open', 'dm_4dstem_read', 'dm_4dstem_virtual'];
    assert.deepEqual(catalog.filter(item => item.name.startsWith('dm_4dstem_')).map(item => item.name), names);
    for (const name of names) {
      const tool = catalog.find(item => item.name === name);
      assert.equal(tool.inputSchema.additionalProperties, false);
      assert.match(tool.description, /只读|不修改原文件|分块/);
    }
    const open = catalog.find(item => item.name === names[0]);
    assert.deepEqual(open.inputSchema.required, ['path', 'scan_axes', 'detector_axes']);
    assert.match(open.description, /不整文件OpenImage/);
    assert.match(open.description, /uint8/);
    const read = catalog.find(item => item.name === names[1]);
    assert.deepEqual(read.inputSchema.required, ['dataset_id', 'scan_bounds']);
    assert.match(read.inputSchema.properties.scan_bounds.description, /右端排除/);
    const reduction = catalog.find(item => item.name === names[2]);
    assert.match(reduction.description, /uint64/);
    assert.match(reduction.description, /HAADF/);
    assert.equal(reduction.inputSchema.properties.detectors.items.additionalProperties, false);
    assert.equal(reduction.inputSchema.properties.detectors.maxItems, 8);

    const valid = [
      ['dm_4dstem_open', 'fourdstem_open', {path: 'C:\\synthetic-样例\\example.dm4', scan_axes: [0, 1], detector_axes: [2, 3]}],
      ['dm_4dstem_open', 'fourdstem_open', {path: '\\\\host\\share\\synthetic.dm4', scan_axes: [0, 1], detector_axes: [2, 3]}],
      ['dm_4dstem_read', 'fourdstem_read', source],
      ['dm_4dstem_read', 'fourdstem_read', {dataset_id: '4d-1', scan_bounds: [[399, 400], [199, 200]]}],
      ['dm_4dstem_virtual', 'fourdstem_virtual', virtual],
      ['dm_4dstem_virtual', 'fourdstem_virtual', {...source, detectors: [
        detector, {label: 'ADF_outer-1', center_q: [-0.125, 0.375], r_inner: 2.5, r_outer: 8.125},
      ]}],
    ];
    for (const [name, op, args] of valid) {
      const response = await rpc('tools/call', {name, arguments: args});
      assert.equal(response.result?.isError, undefined, JSON.stringify(response));
      const value = JSON.parse(response.result.content[0].text);
      assert.equal(value.backend, 'synthetic-echo-only');
      assert.equal(value.op, op);
      assert.deepEqual(value.args, args, 'preserve coordinate order, fractional centres and half-open bounds');
    }
    assert.equal(received.length, valid.length);

    const invalid = [
      ['dm_4dstem_open', {}],
      ['dm_4dstem_open', {path: 'C:\\synthetic-fixtures\\example.dm4', scan_axes: [0, 1]}],
      ['dm_4dstem_open', {path: 'relative.dm4', scan_axes: [0, 1], detector_axes: [2, 3]}],
      ['dm_4dstem_open', {path: 'C:\\synthetic-fixtures\\example.dm4\u0000', scan_axes: [0, 1], detector_axes: [2, 3]}],
      ...[[0], [0, 1, 2], [0, 0], [1, 0], [2, 3], [-1, 1], ['0', 1], [0.5, 1], null].map(scan_axes =>
        ['dm_4dstem_open', {path: 'C:\\synthetic-fixtures\\example.dm4', scan_axes, detector_axes: [2, 3]}]),
      ...[[2, 2], [3, 2], [0, 1], [2, 4], [2], null].map(detector_axes =>
        ['dm_4dstem_open', {path: 'C:\\synthetic-fixtures\\example.dm4', scan_axes: [0, 1], detector_axes}]),
      ['dm_4dstem_open', {path: 'C:\\synthetic-fixtures\\example.dm4', scan_axes: [0, 1], detector_axes: [2, 3], show: true}],
      ['dm_4dstem_read', {}],
      ['dm_4dstem_read', {dataset_id: '4d-1'}],
      ...['', 'front', '4d-0', '4d--1', '4d-1;anything', 1, null].map(dataset_id =>
        ['dm_4dstem_read', {...source, dataset_id}]),
      ...[[], [[0, 2]], [[0, 2], [0, 2], [0, 2]], [0, 2], [[0, 1, 2], [0, 2]],
        [[-1, 2], [0, 2]], [[0, 0], [0, 2]], [[2, 1], [0, 2]],
        [[0, 2], [1, 1]], [[0, 2], [3, 1]], [[0.5, 2], [0, 2]],
        [['0', 2], [0, 2]], [[0, Number.MAX_SAFE_INTEGER + 1], [0, 2]], null].map(scan_bounds =>
        ['dm_4dstem_read', {...source, scan_bounds}]),
      ['dm_4dstem_read', {...source, detectors: [detector]}],
      ['dm_4dstem_virtual', source],
      ...[[], Array.from({length: 9}, (_, i) => ({...detector, label: `D${i}`})), null,
        [detector, {...detector}], [{...detector, extra: true}], [{label: 'BF'}]].map(detectors =>
        ['dm_4dstem_virtual', {...virtual, detectors}]),
      ...['', ' ', 'total', 'sum_dp', 'mean_dp', 'mean_diffraction', 'sum_diffraction',
        '../BF', 'A/B', '中文', 'B'.repeat(33), null].map(label =>
        ['dm_4dstem_virtual', {...virtual, detectors: [{...detector, label}]}]),
      ...[[], [0], [0, 0, 0], ['0', 0], [null, 0], null].map(center_q =>
        ['dm_4dstem_virtual', {...virtual, detectors: [{...detector, center_q}]}]),
      ...[-1, '0', null].map(r_inner =>
        ['dm_4dstem_virtual', {...virtual, detectors: [{...detector, r_inner}]}]),
      ...[-1, 0, '1', null].map(r_outer =>
        ['dm_4dstem_virtual', {...virtual, detectors: [{...detector, r_outer}]}]),
      ['dm_4dstem_virtual', {...virtual, detectors: [{...detector, r_inner: 3, r_outer: 2}]}],
      ...[0, 129, 1.5, '1', null].map(chunk_patterns =>
        ['dm_4dstem_virtual', {...virtual, chunk_patterns}]),
      ['dm_4dstem_virtual', {...virtual, max_chunk_bytes: 1e9}],
    ];
    for (const [name, args] of invalid) {
      const reply = await rpc('tools/call', {name, arguments: args});
      assert.equal(reply.error?.code, -32602, `${name} must reject before dispatch: ${JSON.stringify(args)}`);
    }
    const overflow = await rpc('tools/call', {name: 'dm_4dstem_virtual', arguments: {
      ...virtual, detectors: [{...detector, center_q: [987654321, 0]}],
    }}, line => line.replace('987654321', '1e400'));
    assert.equal(overflow.error?.code, -32602);
    assert.equal(received.length, valid.length, 'invalid input never reaches the fake bridge');
    await rpc('tools/call', {name: 'dm_4dstem_read', arguments: source});
    assert.equal(received.length, valid.length + 1, 'final acknowledged request proves no invalid request leaked');
    console.log(`4D protocol checks: 3 catalog entries, ${valid.length} exact forwards, ${invalid.length + 1} invalid rejections`);
  } finally {
    const exited = once(child, 'exit');
    child.kill();
    await exited;
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => fake.close(resolve));
  }
});
