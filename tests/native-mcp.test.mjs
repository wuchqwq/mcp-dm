// Real Node stdio MCP with synthetic named-pipe hosts only; no DM acceptance.
import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import {spawn} from "node:child_process";
import {once} from "node:events";
import {randomUUID} from "node:crypto";
import {fileURLToPath} from "node:url";
import {NativeBridge} from "../lib/native_bridge.mjs";

const serverPath = fileURLToPath(new URL("../server.mjs", import.meta.url));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function mcpClient(extraEnv = {}, defaultBackend = false) {
  const env = {...process.env, DM_MCP_TIMEOUT_MS: "150", ...extraEnv};
  if (defaultBackend) delete env.DM_MCP_BACKEND;
  const child = spawn(process.execPath, [serverPath], {env, stdio: ["pipe", "pipe", "pipe"]});
  child.stdin.on("error", () => {});
  let buffer = "", stderr = "", next = 1;
  const pending = new Map(), messages = [];
  child.stderr.on("data", chunk => {stderr += chunk;});
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", chunk => {
    buffer += chunk; let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const message = JSON.parse(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1);
      assert.equal(message.jsonrpc, "2.0", "stdout contains only MCP JSON-RPC");
      assert.notEqual(Object.hasOwn(message, "result"), Object.hasOwn(message, "error"), "strict response envelope");
      messages.push(message);
      const waiter = pending.get(message.id); if (waiter) {pending.delete(message.id); waiter(message);}
    }
  });
  const send = message => child.stdin.write(JSON.stringify({jsonrpc: "2.0", ...message}) + "\n");
  const rpc = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++;
    const timer = setTimeout(() => {pending.delete(id); reject(new Error(`MCP timeout ${method}: ${stderr}`));}, 4000);
    pending.set(id, message => {clearTimeout(timer); resolve(message);});
    send({id, method, params});
  });
  const tool = (name, args = {}) => rpc("tools/call", {name, arguments: args});
  return {child, messages, rpc, tool, send, async init() {
    const response = await rpc("initialize", {protocolVersion: "2024-11-05", capabilities: {}, clientInfo: {name: "strict-synthetic-native", version: "1"}});
    assert.equal(response.error, undefined); assert.equal(response.result.protocolVersion, "2024-11-05");
    send({method: "notifications/initialized"}); return response.result;
  }, async close() {
    if (child.exitCode === null && child.signalCode === null) {const done = once(child, "exit"); child.kill(); await done;}
  }};
}

function toolOutput(message, expectedError = false) {
  assert.equal(message.error, undefined, "RPC envelope must be successful before tool result is inspected");
  assert.equal(Boolean(message.result.isError), expectedError, "MCP tool isError must be inspected separately");
  assert.equal(message.result.content[0].type, "text");
  return JSON.parse(message.result.content[0].text);
}

async function nativeHost(handler) {
  const session = randomUUID().replaceAll("-", ""), bridge = new NativeBridge({session});
  const requests = [], sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket); socket.on("error", () => {}); socket.on("close", () => sockets.delete(socket));
    let input = "";
    socket.on("data", chunk => {
      input += chunk.toString("ascii"); const newline = input.indexOf("\n"); if (newline < 0) return;
      const [protocol, requestSession, id, operation, ...args] = input.slice(0, newline).split(" ");
      assert.equal(protocol, "NB1"); assert.equal(requestSession, session);
      const request = {id, operation, args}; requests.push(request);
      const reply = (state, result, extra = {}) => ({protocol: "NB1", session, id, state, host_pid: 301, worker_tid: 302,
        exec_tid: state === "completed" ? 303 : 0, timings_us: {queue: 4, execute: 5}, ...(state === "completed" ? {result} : {}), ...extra});
      handler({socket, request, requests, reply}); input = "";
    });
  });
  await new Promise((resolve, reject) => {server.once("error", reject); server.listen(bridge.pipePath, resolve);});
  return {session, requests, async close() {for (const socket of sockets) socket.destroy(); await new Promise(resolve => server.close(resolve));}};
}

test("default backend retains v0.6 and all original 21 tool schemas", async () => {
  const client = mcpClient({}, true);
  try {
    const init = await client.init(); assert.equal(init.serverInfo.version, "0.6.0");
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.equal(catalog.length, 21);
    assert.deepEqual(catalog.map(entry => entry.name), ["dm_status", "dm_open", "dm_datasets", "dm_metadata", "dm_stats", "dm_profile", "dm_fft", "dm_2d_capture", "dm_2d_preview", "dm_2d_analyze", "dm_2d_result", "dm_export", "dm_crop", "dm_spectrum_info", "dm_spectrum", "dm_spectrum_integrate", "dm_spectrum_export", "dm_4dstem_open", "dm_4dstem_read", "dm_4dstem_virtual", "dm_run_script"]);
    assert.deepEqual(catalog[0].inputSchema.properties, {});
    assert.equal((await client.tool("dm_native_mean", {image_id: 1})).error.code, -32602);
  } finally {await client.close();}
});

test("unknown backend and malformed native session refuse startup without fallback", async () => {
  for (const extraEnv of [{DM_MCP_BACKEND: ""}, {DM_MCP_BACKEND: "tcp-typo"}, {DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: "bad"}]) {
    const child = spawn(process.execPath, [serverPath], {env: {...process.env, ...extraEnv}, stdio: ["pipe", "pipe", "pipe"]});
    let stdout = "", stderr = ""; child.stdout.on("data", chunk => {stdout += chunk;}); child.stderr.on("data", chunk => {stderr += chunk;});
    const [code] = await once(child, "exit");
    assert.notEqual(code, 0); assert.equal(stdout, ""); assert.match(stderr, /DM_MCP_BACKEND|DM_NATIVE_SESSION/);
  }
});

test("native MCP exposes only implemented tools, strict IDs and real host fields", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    const result = request.operation === "STATUS" ? {backend: "mock-native", build: "synthetic-only"}
      : request.operation === "DATASETS" ? {backend: "mock-native", datasets: [{image_id: 77, name: "合成图"}]}
      : {backend: "mock-native", image_id: 77, mean: -3.25};
    socket.write(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_BRIDGE_HOST: "invalid-unused", DM_BRIDGE_PORT: "invalid-unused", DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    const init = await client.init(); assert.match(init.instructions, /空闲/); assert.match(init.instructions, /不回退/);
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.deepEqual(catalog.map(entry => entry.name), ["dm_status", "dm_datasets", "dm_native_mean", "dm_native_result", "dm_crop"]);
    for (const name of ["dm_stats", "dm_run_script", "dm_2d_preview", "dm_open", "no_such_tool"]) {
      const response = await client.tool(name); assert.equal(response.error.code, -32602); assert.match(response.error.message, /不支持工具/);
    }
    for (const image_id of ["front", "77", -1, 1.5, 4294967296]) assert.equal((await client.tool("dm_native_mean", {image_id})).error.code, -32602);
    for (const request_id of ["", "x\n", "x y", "x".repeat(65)]) assert.equal((await client.tool("dm_status", {request_id})).error.code, -32602);
    assert.equal((await client.tool("dm_native_mean", {})).error.code, -32602);
    assert.equal((await client.tool("dm_native_result", {})).error.code, -32602);
    assert.equal(host.requests.length, 0, "unimplemented tools/invalid IDs never reach any bridge");
    assert.equal(toolOutput(await client.tool("dm_status")).backend, "mock-native");
    assert.equal(toolOutput(await client.tool("dm_datasets", {request_id: "datasets-fixed"})).datasets[0].name, "合成图");
    const output = toolOutput(await client.tool("dm_native_mean", {image_id: 77, request_id: "mean-fixed"}));
    assert.equal(output.mean, -3.25); assert.equal(output.backend, "mock-native");
    assert.deepEqual(Object.keys(output).sort(), ["backend", "image_id", "mean", "native_receipt"]);
    assert.equal(output.native_receipt.session, host.session); assert.equal(output.native_receipt.request_id, "mean-fixed");
    assert.equal(output.native_receipt.host_pid, 301); assert.equal(output.native_receipt.exec_tid, 303);
    assert.deepEqual(host.requests.map(request => request.operation), ["STATUS", "DATASETS", "MEAN"]);
  } finally {await client.close(); await host.close();}
});

test("native MCP marks failed/unknown/queued/running and malformed mean as tool errors", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    let message;
    if (request.id === "failed") message = reply("failed", undefined, {code: "INVALID_IMAGE", error: "missing image"});
    else if (request.id === "unknown") message = reply("unknown");
    else if (["queued", "running"].includes(request.id)) message = reply(request.id);
    else message = reply("completed", {backend: "mock-native", mean: "not a number"});
    socket.end(JSON.stringify(message) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (const request_id of ["failed", "unknown", "queued", "running"]) {
      const output = toolOutput(await client.tool("dm_native_result", {request_id}), true);
      assert.equal(output.native_receipt.state, request_id);
    }
    const invalid = toolOutput(await client.tool("dm_native_mean", {image_id: 77, request_id: "bad-mean"}), true);
    assert.equal(invalid.code, "NATIVE_PROTOCOL"); assert.equal(invalid.request_id, "bad-mean");
  } finally {await client.close(); await host.close();}
});

test("native MCP timeout and cancellation are recovered by QUERY without re-execution", async () => {
  const done = new Set();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "MEAN") {
      done.add(request.id); // A silent reply does not prevent execution.
      return;
    }
    socket.write(JSON.stringify(reply(done.has(request.id) ? "completed" : "unknown", {backend: "mock-native", mean: 2.75})) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const timeout = toolOutput(await client.tool("dm_native_mean", {image_id: 3, request_id: "timeout-known"}), true);
    assert.equal(timeout.code, "NATIVE_TIMEOUT"); assert.equal(timeout.request_id, "timeout-known"); assert.equal(timeout.session, host.session);
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: timeout.request_id})).mean, 2.75);
    client.send({id: 900, method: "tools/call", params: {name: "dm_native_mean", arguments: {image_id: 3, request_id: "cancel-known"}}});
    await sleep(30);
    client.send({method: "notifications/cancelled", params: {requestId: 900}});
    await sleep(180);
    assert.equal(client.messages.some(message => message.id === 900), false, "standard MCP cancellation suppresses response: " + JSON.stringify(client.messages.find(message => message.id === 900)));
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: "cancel-known"})).mean, 2.75);
    assert.equal(host.requests.filter(request => request.operation === "MEAN").length, 2);
    assert.equal(host.requests.filter(request => request.id === "timeout-known" && request.operation === "MEAN").length, 1);
    assert.equal(host.requests.filter(request => request.id === "cancel-known" && request.operation === "MEAN").length, 1);
  } finally {await client.close(); await host.close();}
});

test("native dm_crop validates explicit half-open bounds and preserves the host's independent-image metadata", async () => {
  const rect = [1, 2, 4, 6];
  const source = {id: 77, shape: [7, 11], calibration: [{dm_dimension: 0, scale: -0.25, calibrated_value_at_pixel_zero: 1.25, unit: "nm"}]};
  const image = {id: 88, shape: [4, 3], calibration: [{dm_dimension: 0, scale: -0.25, calibrated_value_at_pixel_zero: 1, unit: "nm"}]};
  const result = {backend: "mock-native", source_image_id: 77, image_id: 88, requested_rect: rect, effective_rect: rect,
    source, image, operator: "GMS::Image::GetSubSliceAsImage", source_write_requested: false,
    ownership: "plugin-retained until normal native STOP/cleanup; no visible DM document"};
  const records = new Map(); let executions = 0;
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "CROP") {
      const previous = records.get(request.id);
      if (previous && JSON.stringify(previous.args) !== JSON.stringify(request.args)) {
        socket.end(JSON.stringify(reply("failed", undefined, {code: "id_conflict", error: "request ID already bound"})) + "\n"); return;
      }
      if (!previous) {records.set(request.id, {args: request.args, complete: false}); executions++;}
      socket.end(JSON.stringify(records.get(request.id).complete ? reply("completed", result) : reply("queued")) + "\n");
    } else {
      records.get(request.id).complete = true;
      socket.end(JSON.stringify(reply("completed", result)) + "\n");
    }
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const crop = (await client.rpc("tools/list")).result.tools.find(tool => tool.name === "dm_crop");
    assert.match(crop.description, /不创建可见 DM 文档/);
    assert.deepEqual(crop.inputSchema.required, ["image_id", "rect", "request_id"]);
    for (const request_id of [undefined, "", "bad id", "x".repeat(65), 123]) {
      const args = {image_id: 77, rect};
      if (request_id !== undefined) args.request_id = request_id;
      assert.equal((await client.tool("dm_crop", args)).error?.code, -32602);
    }
    assert.equal(host.requests.length, 0, "missing/invalid recovery IDs never dispatch");
    for (const args of [
      {}, {image_id: 77}, {rect}, {image_id: "front", rect}, {image_id: "77", rect}, {image_id: -1, rect},
      {image_id: 77, rect: null}, {image_id: 77, rect: []}, {image_id: 77, rect: [1, 2, 1, 6]},
      {image_id: 77, rect: [4, 2, 1, 6]}, {image_id: 77, rect: [1, 6, 4, 2]},
      {image_id: 77, rect: [-1, 2, 4, 6]}, {image_id: 77, rect: [1, 2, 4.5, 6]},
      {image_id: 77, rect: [1, 2, "4", 6]}, {image_id: 77, rect: [1, 2, 4294967296, 6]},
      {image_id: 77, rect, name: "unsupported custom name"},
    ]) assert.equal((await client.tool("dm_crop", {...args, request_id: "invalid-crop"})).error?.code, -32602, JSON.stringify(args));
    assert.equal(host.requests.length, 0, "invalid crops must fail before any native dispatch");
    const first = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "crop-id"}));
    const {native_receipt, ...original} = first;
    assert.deepEqual(original, result, "return host metadata exactly without fabricated fields");
    assert.equal(native_receipt.request_id, "crop-id"); assert.equal(native_receipt.session, host.session);
    assert.deepEqual(host.requests.map(request => request.operation), ["CROP", "QUERY"]);
    assert.deepEqual(host.requests[0].args, ["77", "1", "2", "4", "6"]);
    const repeated = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "crop-id"}));
    assert.equal(repeated.image_id, 88); assert.equal(executions, 1, "an explicit repeated ID returns the same host record");
    const conflict = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [2, 2, 4, 6], request_id: "crop-id"}), true);
    assert.equal(conflict.native_receipt.code, "id_conflict"); assert.equal(executions, 1);
  } finally {await client.close(); await host.close();}
});

test("native dm_crop rejects wrong new/source identities or inconsistent reported rectangles", async () => {
  const rect = [1, 2, 4, 6];
  const mutations = [
    {image_id: 77}, {image_id: -1}, {image_id: 4294967296}, {image_id: 1.5}, {image_id: "88"}, {image_id: true},
    {source_image_id: 78}, {source_image_id: "77"}, {effective_rect: undefined}, {effective_rect: [1, 2, 3, 6]},
    {effective_rect: [1, 2, 4, 6, 8]}, {effective_rect: ["1", 2, 4, 6]}, {rect: [2, 2, 4, 6]}, {requested_rect: [1, 3, 4, 6]},
  ];
  const host = await nativeHost(({socket, request, reply}) => {
    const mutation = mutations[Number(request.id.slice(4))];
    socket.end(JSON.stringify(reply("completed", {backend: "mock-native", source_image_id: 77, image_id: 88, effective_rect: rect, ...mutation})) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (let index = 0; index < mutations.length; index++) {
      const output = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "bad-" + index}), true);
      assert.equal(output.code, "NATIVE_PROTOCOL"); assert.equal(output.sent, true);
      assert.equal(output.request_id, "bad-" + index); assert.equal(output.session, host.session);
    }
    assert.equal(host.requests.length, mutations.length, "a malformed completed crop is never automatically resubmitted");
  } finally {await client.close(); await host.close();}
});

test("native dm_crop accepts the rect alias and propagates host ROI failures without retry", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    const response = request.id === "rect-alias" ? reply("completed", {backend: "mock-native", source_image_id: 77, image_id: 88, rect: [1, 2, 4, 6]})
      : reply("failed", undefined, {code: "roi_out_of_bounds", error: "rectangle is outside source"});
    socket.end(JSON.stringify(response) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const aliased = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [1, 2, 4, 6], request_id: "rect-alias"}));
    assert.deepEqual(aliased.rect, [1, 2, 4, 6]); assert.equal(Object.hasOwn(aliased, "effective_rect"), false);
    const failure = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [1, 2, 400, 600], request_id: "outside"}), true);
    assert.equal(failure.native_receipt.code, "roi_out_of_bounds");
    assert.deepEqual(host.requests.map(request => request.operation), ["CROP", "CROP"]);
  } finally {await client.close(); await host.close();}
});
