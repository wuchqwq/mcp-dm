// Synthetic named-pipe protocol tests; no Gatan process or experimental data.
import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import {randomUUID} from "node:crypto";
import {NativeBridge, NativeBridgeError, validRequestId} from "../lib/native_bridge.mjs";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sessionId = () => randomUUID().replaceAll("-", "");

async function fakeHost(handler, timeoutMs = 1000) {
  const session = sessionId(), bridge = new NativeBridge({session, timeoutMs, pollMs: 5});
  const sockets = new Set(), requests = [];
  const server = net.createServer(socket => {
    sockets.add(socket);
    socket.on("error", () => {});
    socket.on("close", () => sockets.delete(socket));
    let buffer = "";
    socket.on("data", chunk => {
      buffer += chunk.toString("ascii");
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      const [protocol, requestSession, id, operation, ...args] = buffer.slice(0, newline).split(" ");
      assert.equal(buffer.indexOf("\n"), buffer.length - 1, "one ASCII request per connection");
      assert.equal(protocol, "NB1"); assert.equal(requestSession, session);
      const request = {id, operation, args}; requests.push(request);
      const reply = (state = "completed", result = {}, extra = {}) => ({
        protocol: "NB1", session, id, state, host_pid: 121, worker_tid: 122,
        exec_tid: state === "completed" ? 123 : 0, timings_us: {queue: 10, execute: 20},
        ...(state === "completed" ? {result} : {}), ...extra,
      });
      handler({socket, request, reply, requests});
      buffer = "";
    });
  });
  await new Promise((resolve, reject) => {server.once("error", reject); server.listen(bridge.pipePath, resolve);});
  return {bridge, requests, session, server, async close() {
    bridge.close(); for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  }};
}

test("native session and request IDs are bounded ASCII, including final newline rejection", () => {
  for (const value of [undefined, "", "A".repeat(32), "a".repeat(31), "a".repeat(32) + "\n", "a".repeat(33)]) assert.throws(() => new NativeBridge({session: value}), /DM_NATIVE_SESSION/);
  for (const value of ["", "a\n", "a\r", "a b", "x".repeat(65), 1, "图"]) assert.equal(validRequestId(value), false);
  for (const value of ["a", "a_B-12", "x".repeat(64)]) assert.equal(validRequestId(value), true);
});

test("submit once then QUERY same ID, split UTF-8, honest backend and negative fractional mean", async () => {
  const host = await fakeHost(({socket, request, reply, requests}) => {
    if (request.operation === "MEAN") socket.write(JSON.stringify(reply("queued")) + "\n");
    else if (requests.length === 2) socket.write(JSON.stringify(reply("running")) + "\n");
    else {
      const data = Buffer.from(JSON.stringify(reply("completed", {backend: "mock-native", label: "测试", mean: -3.25})) + "\n");
      const middle = data.indexOf(Buffer.from("测")) + 1;
      socket.write(data.subarray(0, middle));
      setTimeout(() => { if (!socket.destroyed) socket.write(data.subarray(middle)); }, 5);
    }
  });
  try {
    const result = await host.bridge.execute("MEAN", [34]);
    assert.equal(result.result.mean, -3.25); assert.equal(result.result.backend, "mock-native");
    assert.equal(result.result.label, "测试");
    assert.deepEqual(host.requests.map(r => r.operation), ["MEAN", "QUERY", "QUERY"]);
    assert.deepEqual(host.requests[0].args, ["34"]);
    assert.match(host.requests[0].id, /^[0-9a-f-]{36}$/);
    assert.ok(host.requests.every(r => r.id === host.requests[0].id));
  } finally {await host.close();}
});

test("unknown and failed are terminal records, never successful completed results", async () => {
  for (const state of ["unknown", "failed"]) {
    const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply(state, {}, state === "failed" ? {code: "UNSUPPORTED_TYPE", error: "unsupported source"} : {})) + "\n"));
    try {
      const reply = await host.bridge.execute("MEAN", [1], {requestId: "known-id"});
      assert.equal(reply.state, state); assert.equal(Object.hasOwn(reply, "result"), false);
      assert.equal(host.requests.length, 1);
    } finally {await host.close();}
  }
});

test("reject response identity, state, receipt and success-shape mismatches", async () => {
  const cases = [
    {protocol: "NB2"}, {session: "f".repeat(32)}, {id: "other"}, {state: "ok"},
    {host_pid: 0}, {host_pid: 1.2}, {worker_tid: 0}, {exec_tid: -1},
    {exec_tid: 0}, {timings_us: {queue: -1, execute: 0}}, {timings_us: {queue: 1.5, execute: 0}},
    {result: null}, {result: []}, {error: "success with error"}, {code: "ERR"},
    {state: "running", result: {}}, {state: "failed", result: undefined},
    {state: "unknown", result: undefined, error: "unknown must not carry failure"},
  ];
  for (const extra of cases) {
    const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", {}, extra)) + "\n"));
    try {
      await assert.rejects(host.bridge.query("test-id"), error => {
        assert.ok(error instanceof NativeBridgeError);
        assert.equal(error.details.code, "NATIVE_PROTOCOL");
        assert.equal(error.details.request_id, "test-id"); assert.equal(error.details.session, host.session);
        return true;
      }, JSON.stringify(extra));
    } finally {await host.close();}
  }
});

test("reject host PID changes between accepted and queried records", async () => {
  const host = await fakeHost(({socket, request, reply}) => socket.end(JSON.stringify(request.operation === "MEAN" ? reply("queued") : reply("completed", {}, {host_pid: 999})) + "\n"));
  try {await assert.rejects(host.bridge.execute("MEAN", [1]), /host PID changed/);}
  finally {await host.close();}
});

test("bounded single newline JSON and strict UTF-8 framing", async () => {
  for (const makeBytes of [
    reply => Buffer.from(JSON.stringify(reply()) + "\n{}\n"),
    reply => Buffer.from(JSON.stringify(reply())),
    () => Buffer.from("null\n"),
    reply => Buffer.from(JSON.stringify(reply("completed", {mean: 0})).replace('"mean":0', '"mean":1e400') + "\n"),
    () => Buffer.from([123, 34, 120, 34, 58, 34, 255, 34, 125, 10]),
    () => Buffer.alloc(128 * 1024 + 1, 120),
  ]) {
    const host = await fakeHost(({socket, reply}) => socket.end(makeBytes(reply)));
    try {await assert.rejects(host.bridge.query("framing"), error => error.details.code === "NATIVE_PROTOCOL");}
    finally {await host.close();}
  }
});

test("deadline destroys silent receive sockets; late result is queryable without operation resend", async () => {
  const host = await fakeHost(({socket, request, reply}) => {
    if (request.operation === "QUERY") socket.end(JSON.stringify(reply("completed", {backend: "mock-native", mean: 2.5})) + "\n");
  }, 50);
  try {
    const start = Date.now();
    await assert.rejects(host.bridge.execute("MEAN", [9], {requestId: "late-id"}), error => {
      assert.equal(error.details.code, "NATIVE_TIMEOUT"); assert.equal(error.details.sent, true);
      assert.equal(error.details.request_id, "late-id"); assert.equal(error.details.session, host.session); return true;
    });
    assert.ok(Date.now() - start < 700);
    await sleep(10);
    assert.equal(host.bridge.sockets.size, 0);
    assert.equal((await host.bridge.query("late-id")).result.mean, 2.5);
    assert.deepEqual(host.requests.map(r => r.operation), ["MEAN", "QUERY"]);
  } finally {await host.close();}
});

test("accepted operation remains sent when a later QUERY deadline or connection fails", async () => {
  for (const failure of ["deadline", "connection"]) {
    const host = await fakeHost(({socket, reply}) => {
      socket.end(JSON.stringify(reply("queued")) + "\n");
      if (failure === "connection") host.server.close();
    }, 100);
    try {
      if (failure === "deadline") host.bridge._pause = async () => {await sleep(120);};
      await assert.rejects(host.bridge.execute("MEAN", [9], {requestId: "accepted-id"}), error => {
        assert.equal(error.details.sent, true, "the original MEAN was accepted even though QUERY was not sent");
        assert.equal(error.details.state, "unknown"); assert.equal(error.details.request_id, "accepted-id");
        assert.equal(error.details.code, "NATIVE_TIMEOUT");
        return true;
      });
      assert.deepEqual(host.requests.map(request => request.operation), ["MEAN"]);
    } finally {await host.close();}
  }
});

test("pipe readiness waits before first write, with bounded deadline and cancellation", async () => {
  const session = sessionId(), bridge = new NativeBridge({session, timeoutMs: 300});
  const requests = [], sockets = new Set();
  const server = net.createServer(socket => {
    sockets.add(socket); socket.on("error", () => {}); socket.on("close", () => sockets.delete(socket));
    socket.once("data", chunk => {
      requests.push(chunk.toString("ascii"));
      const id = chunk.toString("ascii").split(" ")[2];
      socket.end(JSON.stringify({protocol: "NB1", session, id, state: "completed", host_pid: 123, worker_tid: 124,
        exec_tid: 125, timings_us: {queue: 0, execute: 1}, result: {backend: "mock-native"}}) + "\n");
    });
  });
  const startListening = setTimeout(() => server.listen(bridge.pipePath), 40);
  try {
    const reply = await bridge.execute("STATUS", [], {requestId: "late-pipe"});
    assert.equal(reply.state, "completed"); assert.equal(requests.length, 1);
  } finally {
    clearTimeout(startListening); bridge.close(); for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  }
  for (const mode of ["deadline", "cancel"]) {
    const absent = new NativeBridge({session: sessionId(), timeoutMs: 45});
    const controller = new AbortController();
    const cancellation = mode === "cancel" ? setTimeout(() => controller.abort(), 15) : null;
    try {
      await assert.rejects(absent.execute("MEAN", [1], {requestId: "not-written", signal: controller.signal}), error => {
        assert.equal(error.details.sent, false); assert.equal(error.details.request_id, "not-written");
        assert.equal(error.details.code, mode === "cancel" ? "NATIVE_CANCELLED" : "NATIVE_TIMEOUT"); return true;
      });
      assert.equal(absent.sockets.size, 0);
    } finally {clearTimeout(cancellation); absent.close();}
  }
});

test("cancel stops local waiting only and preserves ID for a later QUERY", async () => {
  const host = await fakeHost(({socket, request, reply}) => {
    if (request.operation === "MEAN") socket.write(JSON.stringify(reply("queued")) + "\n");
    else if (host.requests.length < 3) socket.write(JSON.stringify(reply("running")) + "\n");
    else socket.write(JSON.stringify(reply("completed", {mean: 5})) + "\n");
  });
  try {
    const controller = new AbortController();
    const operation = host.bridge.execute("MEAN", [9], {requestId: "cancel-id", signal: controller.signal});
    const rejection = assert.rejects(operation, error => error.details.code === "NATIVE_CANCELLED" && error.details.request_id === "cancel-id" && error.details.session === host.session);
    await sleep(8); controller.abort(); await rejection;
    const result = await host.bridge.query("cancel-id");
    // Depending on timer scheduling, the first query can still observe running.
    const final = result.state === "completed" ? result : await host.bridge.query("cancel-id");
    assert.equal(final.result.mean, 5);
    assert.equal(host.requests.filter(r => r.operation === "MEAN").length, 1);
  } finally {await host.close();}
});

test("pre-cancelled calls do not connect; invalid unsigned IDs do not dispatch", async () => {
  const host = await fakeHost(() => assert.fail("must not dispatch"));
  try {
    const controller = new AbortController(); controller.abort();
    await assert.rejects(host.bridge.execute("STATUS", [], {requestId: "pre", signal: controller.signal}), error => error.details.sent === false && error.details.code === "NATIVE_CANCELLED");
    for (const id of [-1, 0.5, 4294967296, "1", NaN]) await assert.rejects(host.bridge.execute("MEAN", [id]), /unsigned 32-bit/);
    await assert.rejects(host.bridge.execute("STOP"), /Unsupported NB1/);
    await assert.rejects(host.bridge.execute("MEAN", [1], {requestId: "inject\nSTOP"}), /request_id/);
    assert.equal(host.requests.length, 0);
  } finally {await host.close();}
});

test("low-level CROP forwards five explicit unsigned arguments", async () => {
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", {backend: "mock-native", image_id: 99})) + "\n"));
  try {
    const reply = await host.bridge.execute("CROP", [7, 1, 2, 4, 6], {requestId: "explicit-crop"});
    assert.equal(reply.result.image_id, 99);
    assert.deepEqual(host.requests[0], {operation: "CROP", args: ["7", "1", "2", "4", "6"], id: "explicit-crop"});
    for (const args of [[7, 1, 2, 4], [7, 1, 2, 4, -1], [7, 1.5, 2, 4, 6]]) await assert.rejects(host.bridge.execute("CROP", args), /unsigned 32-bit/);
    assert.equal(host.requests.length, 1);
  } finally {await host.close();}
});
