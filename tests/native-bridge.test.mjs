// Synthetic named-pipe protocol tests; no Gatan process or experimental data.
import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import {randomUUID} from "node:crypto";
import {NativeBridge, NativeBridgeError, validRequestId} from "../lib/native_bridge.mjs";
import {fourierFixture, readFixture, imageMetadata} from "./fixtures/native-operations.mjs";

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const sessionId = () => randomUUID().replaceAll("-", "");
const resultTypes = {STATUS: "status", DATASETS: "datasets", INFO: "image_info", MEAN: "native_mean", SUMMARY: "native_summary", CROP: "image_crop", SHOW: "image_delivery", STOP: "ipc_stop", UNARY: "native_image_operation", BINARY: "native_image_operation"};
Object.assign(resultTypes, {FILTER: "native_image_operation", PREVIEW: "native_preview", READ: "native_data_snapshot", FFT: "native_fourier_operation", IFFT: "native_fourier_operation", REAL: "native_fourier_operation", IMAG: "native_fourier_operation", VENDOR_ARG: "native_fourier_operation", VENDOR_NORM: "native_fourier_operation"});
const identity = (operation, args) => ({original_operation: operation, normalized_args: args.map(Number), result_type: resultTypes[operation], result_version: 1});

// A hand-built protocol fixture, never a vendor computation or DM acceptance.
function summaryFixture(imageId = 77) {
  return {backend: "digitalmicrograph-native", image_id: imageId,
    image: {id: imageId, name: "synthetic", ndim: 2, data_type_code: 2, dtype: "float32", packing_style: 1, shape: [3, 4], dm_dimensions: [4, 3],
      shape_order: "numpy (last axis is X)", pixels: 12,
      calibration: [
        {dm_dimension: 0, numpy_axis: 1, size: 4, origin: 2, calibrated_value_at_pixel_zero: 0.5, scale: -0.25, unit: "nm", usable: true, issue: null},
        {dm_dimension: 1, numpy_axis: 0, size: 3, origin: -1, calibrated_value_at_pixel_zero: 0.5, scale: 0.5, unit: "nm", usable: true, issue: null},
      ], calibration_complete: true, native_mean_supported: true, native_summary_supported: true,
      coordinate_rule: "physical(i)=calibrated_value_at_pixel_zero+i*scale"},
    minimum: -3.25, maximum: 8.5, sum: -0.75, mean: -0.0625,
    operators: ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum", "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"],
    computation: "DM native", intensity_calibration_applied: false, intensity_semantics: "raw pixel intensity",
    source_write_requested: false, snapshot_atomic: false};
}

async function fakeHost(handler, timeoutMs = 1000) {
  const session = sessionId(), bridge = new NativeBridge({session, timeoutMs, pollMs: 5});
  const sockets = new Set(), requests = [], records = new Map();
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
      assert.equal(protocol, "NB2"); assert.equal(requestSession, session);
      const request = {id, operation, args}; requests.push(request);
      if (operation !== "QUERY" && !records.has(id)) records.set(id, request);
      const original = records.get(id) || {operation: "STATUS", args: []};
      const reply = (state = "completed", result = {}, extra = {}) => ({
        protocol: "NB2", session, id, state, host_pid: 121, worker_tid: 122,
        exec_tid: state === "completed" || state === "running" ? 123 : 0, timings_us: {queue: 10, execute: 20},
        ...(state === "unknown" ? {original_operation: null, normalized_args: null, result_type: null, result_version: null} : identity(original.operation, original.args)),
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
    {protocol: "NB1"}, {session: "f".repeat(32)}, {id: "other"}, {state: "ok"},
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
      socket.end(JSON.stringify({protocol: "NB2", session, id, state: "completed", host_pid: 123, worker_tid: 124, ...identity("STATUS", []),
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
    await assert.rejects(host.bridge.execute("STOP"), /Unsupported NB2/);
    await assert.rejects(host.bridge.execute("MEAN", [1], {requestId: "inject\nSTOP"}), /request_id/);
    assert.equal(host.requests.length, 0);
  } finally {await host.close();}
});

test("low-level CROP forwards five explicit unsigned arguments", async () => {
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", {backend: "mock-native", image_id: 99, source_image_id: 7, effective_rect: [1, 2, 4, 6]})) + "\n"));
  try {
    const reply = await host.bridge.execute("CROP", [7, 1, 2, 4, 6], {requestId: "explicit-crop"});
    assert.equal(reply.result.image_id, 99);
    assert.deepEqual(host.requests[0], {operation: "CROP", args: ["7", "1", "2", "4", "6"], id: "explicit-crop"});
    for (const args of [[7, 1, 2, 4], [7, 1, 2, 4, -1], [7, 1.5, 2, 4, 6]]) await assert.rejects(host.bridge.execute("CROP", args), /unsigned 32-bit/);
    assert.equal(host.requests.length, 1);
  } finally {await host.close();}
});

test("low-level SHOW submits one explicit unsigned image ID once before same-ID QUERY", async () => {
  const result = {backend: "mock-native", image_id: 99, delivery: "visible_dm_document", document_visible: true};
  const host = await fakeHost(({socket, request, reply}) => socket.end(JSON.stringify(
    request.operation === "SHOW" ? reply("queued") : reply("completed", result)) + "\n"));
  try {
    assert.deepEqual((await host.bridge.execute("SHOW", [99], {requestId: "explicit-show"})).result, result);
    assert.deepEqual(host.requests, [
      {operation: "SHOW", args: ["99"], id: "explicit-show"},
      {operation: "QUERY", args: [], id: "explicit-show"},
    ]);
    for (const args of [[], [99, 100], [-1], [0.5], [4294967296], ["99"]]) {
      await assert.rejects(host.bridge.execute("SHOW", args, {requestId: "bad-show"}), /unsigned 32-bit/);
    }
    assert.equal(host.requests.length, 2, "invalid SHOW arguments must not reach the host");
  } finally {await host.close();}
});

test("SUMMARY submits one explicit ID once, polls its original ID and validates complete raw metadata", async () => {
  const expected = summaryFixture();
  const host = await fakeHost(({socket, request, reply}) => socket.end(JSON.stringify(
    request.operation === "SUMMARY" ? reply("queued") : reply("completed", expected)) + "\n"));
  try {
    assert.deepEqual((await host.bridge.execute("SUMMARY", [77], {requestId: "summary-known"})).result, expected);
    assert.deepEqual(host.requests, [
      {operation: "SUMMARY", args: ["77"], id: "summary-known"},
      {operation: "QUERY", args: [], id: "summary-known"},
    ]);
    for (const args of [[], [77, 88], [-1], [0.5], [4294967296], ["77"], [true]]) {
      await assert.rejects(host.bridge.execute("SUMMARY", args), /unsigned 32-bit/);
    }
    assert.equal(host.requests.length, 2);
  } finally {await host.close();}
});

test("SUMMARY accepts explicit missing or invalid spatial calibration without applying intensity calibration", async () => {
  const cases = [
    axis => {axis.unit = null; axis.usable = false; axis.issue = "unknown_units";},
    axis => {axis.scale = null; axis.usable = false; axis.issue = "invalid_calibration";},
    axis => {axis.origin = null; axis.unit = null; axis.usable = false; axis.issue = "invalid_calibration_and_unknown_units";},
    // Raw/native scale disagreement can be reported while serialized numbers
    // themselves remain finite; do not invent a usable spatial calibration.
    axis => {axis.usable = false; axis.issue = "invalid_calibration";},
  ];
  const host = await fakeHost(({socket, request, reply}) => {
    const result = summaryFixture(); cases[Number(request.id.at(-1))](result.image.calibration[0]);
    result.image.calibration_complete = false;
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const reply = await host.bridge.execute("SUMMARY", [77], {requestId: "uncalibrated-" + index});
      assert.equal(reply.result.image.calibration_complete, false);
      assert.equal(reply.result.minimum, -3.25); assert.equal(reply.result.sum, -0.75);
      assert.equal(reply.result.intensity_calibration_applied, false);
    }
  } finally {await host.close();}
});

test("SUMMARY rejects malformed values, identity, shape, dtype and raw semantics without replay", async () => {
  const cases = [
    [r => {r.image_id = 78;}, /image\/backend identity/],
    [r => {r.image_id = "77";}, /image\/backend identity/],
    [r => {r.backend = "mock-native";}, /image\/backend identity/],
    ...["minimum", "maximum", "sum", "mean"].flatMap(key => [
      [r => {delete r[key];}, /four finite/], [r => {r[key] = "1.5";}, /four finite/],
      [r => {r[key] = null;}, /four finite/],
    ]),
    [r => {delete r.image;}, /image metadata/],
    [r => {r.image.id = 78;}, /image metadata/],
    [r => {r.image.dtype = "uint16";}, /image metadata/],
    [r => {r.image.data_type_code = 1;}, /image metadata/],
    [r => {r.image.ndim = 3;}, /image metadata/],
    [r => {r.image.shape = [4, 3];}, /image metadata/],
    [r => {r.image.shape = [0, 4];}, /image metadata/],
    [r => {r.image.pixels = 13;}, /image metadata/],
    [r => {r.image.shape = [2049, 2049]; r.image.dm_dimensions = [2049, 2049]; r.image.pixels = 2049 ** 2;}, /image metadata/],
    [r => {r.image.native_summary_supported = false;}, /image metadata/],
    [r => {r.image.shape_order = "X,Y";}, /image metadata/],
    [r => {r.image.coordinate_rule = "origin+i*scale";}, /image metadata/],
    [r => {r.image.calibration = [];}, /spatial calibration/],
    [r => {r.image.calibration[0].size = 3;}, /spatial calibration/],
    [r => {r.image.calibration[0].numpy_axis = 0;}, /spatial calibration/],
    [r => {r.image.calibration[0].scale = null;}, /spatial calibration/],
    [r => {r.image.calibration[0].unit = null;}, /spatial calibration/],
    [r => {r.image.calibration[0].unit = "";}, /spatial calibration/],
    [r => {r.image.calibration_complete = false;}, /spatial calibration/],
    [r => {r.image.calibration[0].usable = false; r.image.calibration[0].issue = "missing"; r.image.calibration_complete = false;}, /spatial calibration/],
    [r => {r.operators.reverse();}, /raw intensity semantics/],
    [r => {r.operators.pop();}, /raw intensity semantics/],
    [r => {r.computation = "Python";}, /raw intensity semantics/],
    [r => {r.intensity_calibration_applied = true;}, /raw intensity semantics/],
    [r => {r.intensity_semantics = "calibrated";}, /raw intensity semantics/],
    [r => {r.source_write_requested = true;}, /raw intensity semantics/],
    [r => {r.snapshot_atomic = true;}, /raw intensity semantics/],
  ];
  const host = await fakeHost(({socket, request, reply}) => {
    const result = summaryFixture(); cases[Number(request.id.split("-").at(-1))][0](result);
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      await assert.rejects(host.bridge.execute("SUMMARY", [77], {requestId: "bad-summary-" + index}), error => {
        assert.equal(error.details.code, "NATIVE_PROTOCOL"); assert.equal(error.details.sent, true);
        assert.match(error.message, cases[index][1]); return true;
      }, "case " + index);
    }
    assert.equal(host.requests.length, cases.length);
  } finally {await host.close();}
});

test("SUMMARY QUERY validates recognizable recovered data, while failure and unknown stay terminal", async () => {
  const host = await fakeHost(({socket, request, reply}) => {
    let response;
    if (request.id === "summary-failed") response = reply("failed", undefined, {code: "native_summary_nonfinite_result", error: "nonfinite reduction"});
    else if (request.id === "summary-unknown") response = reply("unknown");
    else {const result = summaryFixture(); if (request.id === "summary-bad-query") delete result.mean; response = reply("completed", result, identity("SUMMARY", [77]));}
    socket.end(JSON.stringify(response) + "\n");
  });
  try {
    assert.equal((await host.bridge.query("summary-recovered")).result.minimum, -3.25);
    await assert.rejects(host.bridge.query("summary-bad-query"), /four finite/);
    for (const state of ["failed", "unknown"]) {
      const result = await host.bridge.execute("SUMMARY", [77], {requestId: "summary-" + state});
      assert.equal(result.state, state); assert.equal(Object.hasOwn(result, "result"), false);
    }
    assert.deepEqual(host.requests.map(request => request.operation), ["QUERY", "QUERY", "SUMMARY", "SUMMARY"]);
  } finally {await host.close();}
});

test("NB2 rejects absent, forged or unsupported immutable operation/result identities", async () => {
  const cases = [
    [{original_operation: undefined}, /operation\/result schema/],
    [{normalized_args: undefined}, /operation\/result schema/],
    [{original_operation: "QUERY"}, /operation\/result schema/],
    [{original_operation: "GetProcAddress"}, /operation\/result schema/],
    [{normalized_args: [1]}, /operation\/result schema/],
    [{result_type: "native_summary"}, /operation\/result schema/],
    [{result_version: 2}, /operation\/result schema/],
    [{result_version: null}, /operation\/result schema/],
    [{result_version: true}, /operation\/result schema/],
    [{original_operation: null, normalized_args: null, result_type: null, result_version: null}, /missing-record identity/],
  ];
  for (const [fields, expected] of cases) {
    const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", {}, fields)) + "\n"));
    try {await assert.rejects(host.bridge.query("fresh-client-query"), error => error.details.code === "NATIVE_PROTOCOL" && expected.test(error.message));}
    finally {await host.close();}
  }
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("queued", undefined, identity("MEAN", [2]))) + "\n"));
  try {
    await assert.rejects(host.bridge.execute("MEAN", [1], {requestId: "bound-before-poll"}), /differ from submitted request/);
    assert.equal(host.requests.length, 1, "wrong queued identity must not initiate polling");
  } finally {await host.close();}
});

test("NB2 new-client QUERY dispatches SUMMARY validator even when every summary payload marker is absent", async () => {
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", {}, identity("SUMMARY", [77]))) + "\n"));
  const fresh = new NativeBridge({session: host.session});
  try {
    await assert.rejects(fresh.query("saved-summary"), /SUMMARY image\/backend identity mismatch/);
    assert.deepEqual(host.requests.map(request => request.operation), ["QUERY"]);
  } finally {fresh.close(); await host.close();}
});

test("NB2 unknown is explicitly unbound, conflict exposes original identity and STOP may execute on no host thread", async () => {
  const host = await fakeHost(({socket, request, reply}) => {
    const response = request.id === "unknown" ? reply("unknown") : request.id === "stop" ?
      reply("completed", {ipc_stopped: true}, {...identity("STOP", []), exec_tid: 0}) :
      reply("failed", undefined, {...identity("MEAN", [1]), code: "id_conflict", error: "original request differs"});
    socket.end(JSON.stringify(response) + "\n");
  });
  try {
    const unknown = await host.bridge.query("unknown");
    for (const key of ["original_operation", "normalized_args", "result_type", "result_version"]) assert.equal(unknown[key], null);
    const conflict = await host.bridge.execute("SUMMARY", [2], {requestId: "conflict"});
    assert.equal(conflict.code, "id_conflict"); assert.equal(conflict.original_operation, "MEAN"); assert.deepEqual(conflict.normalized_args, [1]);
    assert.equal((await host.bridge.query("stop")).result.ipc_stopped, true);
  } finally {await host.close();}
});

test("UNARY/BINARY use closed opcodes and common metadata validators", async () => {
  const cases = [["UNARY", [77, 1], "negate", "GMSImageProcessing::Negate"], ["UNARY", [77, 2], "abs", "GMSImageProcessing::Abs"],
    ["UNARY", [77, 3], "square", "GMSImageProcessing::Square"], ["BINARY", [77, 78, 1], "add", "GMSImageProcessing::operator+"],
    ["BINARY", [77, 78, 2], "subtract", "GMSImageProcessing::operator-"], ["BINARY", [77, 78, 3], "multiply", "GMSImageProcessing::operator*"]];
  const host = await fakeHost(({socket, request, reply}) => {
    const [operation, args, name, operator] = cases[Number(request.id.split("-").at(-1))];
    const ids = args.slice(0, -1), image = summaryFixture(99).image;
    const result = {backend: "digitalmicrograph-native", image_id: 99, image, operation: name, opcode: args.at(-1),
      source_image_ids: ids, sources: ids.map(id => summaryFixture(id).image), operator, computation: "DM native",
      intensity_calibration_applied: false, intensity_semantics: "raw pixel intensity", source_write_requested: false,
      snapshot_atomic: false, ownership: "synthetic contract emulation only"};
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const [operation, args, name] = cases[index];
      assert.equal((await host.bridge.execute(operation, args, {requestId: "prepared-" + index})).result.operation, name);
    }
    await assert.rejects(host.bridge.execute("UNARY", [77]), /unsigned 32-bit/);
    await assert.rejects(host.bridge.execute("BINARY", [77, 78, -1]), /unsigned 32-bit/);
  } finally {await host.close();}
});

function derivedFixture(operation, args) {
  const definitions = {FFT: ["Real_FFT", "full_complex"], IFFT: ["IFFT", "full_complex"], REAL: ["Real", "real_component"],
    IMAG: ["Imag", "imaginary_component"], VENDOR_ARG: ["Arg", "vendor_arg"], VENDOR_NORM: ["Norm", "vendor_norm"]};
  const source = summaryFixture(args[0]).image, image = summaryFixture(99).image;
  const fourier = operation !== "FILTER", complex = operation === "FFT" || operation === "IFFT";
  if (!fourier) for (const metadata of [source, image]) {
    metadata.shape = [5, 7]; metadata.dm_dimensions = [7, 5]; metadata.pixels = 35;
    metadata.calibration.forEach((axis, index) => {axis.size = metadata.dm_dimensions[index];});
  }
  for (const [metadata, isComplex] of [[source, fourier && operation !== "FFT"], [image, complex]]) {
    if (isComplex) Object.assign(metadata, {dtype: "complex64", data_type_code: 3, native_mean_supported: false, native_summary_supported: false});
  }
  return {backend: "digitalmicrograph-native", operation, image_id: 99, source_image_id: args[0], source, image,
    operator: "GMSImageProcessing::" + (fourier ? definitions[operation][0] : {1: "SmoothFilter", 2: "SobelFilter", 3: "LaplaceFilter", 4: "SharpenFilter"}[args[1]]),
    computation: "DM native", ownership: "synthetic contract emulation only", semantics: "synthetic protocol fixture; native conventions unqualified",
    visible_dm_document: false, source_write_requested: false, snapshot_atomic: false,
    output_bytes: image.pixels * (complex ? 8 : 4), validation_peak_new_image_bytes: image.pixels * (complex ? 12 : !fourier && args[1] === 2 ? 8 : 4),
    ...(fourier ? {representation: definitions[operation][1], normalization: "vendor_defined", centering: "vendor_defined", phase_units: "vendor_defined"}
      : {filter_kind: args[1], kernel: "vendor_defined", edge_behavior: "vendor_defined"})};
}

test("historical Fourier v1 QUERY and current filters preserve their separate typed contracts", async () => {
  const cases = [["FFT", [77]], ["IFFT", [77]], ["REAL", [77]], ["IMAG", [77]], ["VENDOR_ARG", [77]], ["VENDOR_NORM", [77]],
    ...[1, 2, 3, 4].map(kind => ["FILTER", [77, kind]])];
  const host = await fakeHost(({socket, request, reply}) => {
    const [operation, args] = cases[Number(request.id.split("-").at(-1))];
    socket.end(JSON.stringify(reply("completed", derivedFixture(operation, args), identity(operation, args))) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const [operation, args] = cases[index];
      const result = (await (operation === "FILTER" ? host.bridge.execute(operation, args, {requestId: "vendor-defined-" + index})
        : host.bridge.query("vendor-defined-" + index))).result;
      assert.equal(result.operation, operation); assert.equal(result.visible_dm_document, false);
    }
  } finally {await host.close();}
});

test("prepared Fourier/filter malformed schemas fail by declared original operation, never payload guessing", async () => {
  const cases = [
    ["FFT", [77], r => {r.image.dtype = null;}, /image metadata/],
    ["FFT", [77], r => {r.image.packing_style = 2;}, /packing\/shape/],
    ["FFT", [77], r => {r.source_image_id = 78;}, /identity\/ownership/],
    ["FFT", [77], r => {r.normalization = "normalized";}, /Fourier representation/],
    ["REAL", [77], r => {r.representation = "full_complex";}, /Fourier representation/],
    ["IFFT", [77], r => {r.output_bytes++;}, /Fourier representation/],
    ["FILTER", [77, 2], r => {r.validation_peak_new_image_bytes = r.output_bytes;}, /filter kind\/budget/],
    ["FILTER", [77, 1], r => {r.filter_kind = 2;}, /filter kind\/budget/],
    ["FILTER", [77, 1], r => {r.image.calibration[0].scale *= -1;}, /filter kind\/budget/],
  ];
  const host = await fakeHost(({socket, request, reply}) => {
    const [operation, args, change] = cases[Number(request.id.split("-").at(-1))];
    const result = derivedFixture(operation, args); change(result);
    socket.end(JSON.stringify(reply("completed", result, identity(operation, args))) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const [operation, args, unused, expected] = cases[index];
      await assert.rejects(operation === "FILTER" ? host.bridge.execute(operation, args, {requestId: "bad-derived-" + index})
        : host.bridge.query("bad-derived-" + index), error => error.details.code === "NATIVE_PROTOCOL" && expected.test(error.message));
    }
  } finally {await host.close();}
});

function previewFixture() {
  return {backend: "digitalmicrograph-native", operation: "PREVIEW", image_id: 77, source: summaryFixture(77).image,
    width: 2, height: 2, sample_count: 4, gray8_hex: "001180ff", sampled_minimum: -2.5, sampled_maximum: 8,
    constant_range_gray8: 0, range_source: "sampled native point values",
    mapping: "x=floor(px*source_width/width);y=floor(py*source_height/height)",
    orientation: "row-major [y,x], x increases right, y increases down", sampling: "nearest source integer index, no averaging",
    quantitative: false, source_write_requested: false, snapshot_atomic: false,
    operator: "GMS::Image::GetRealValue", computation: "DM native value reads; display adaptation only"};
}

test("prepared PREVIEW validates bounded display-only gray8 without exposing a native image/file claim", async () => {
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", previewFixture())) + "\n"));
  try {
    const result = (await host.bridge.execute("PREVIEW", [77, 2, 2], {requestId: "preview-explicit"})).result;
    assert.equal(result.gray8_hex, "001180ff"); assert.equal(result.quantitative, false);
    for (const key of ["png", "path", "image"]) assert.equal(Object.hasOwn(result, key), false);
  } finally {await host.close();}
});

test("PREVIEW remains available without optional native statistics bindings", async () => {
  const result = previewFixture(); result.source.native_mean_supported = false; result.source.native_summary_supported = false;
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", result)) + "\n"));
  try {
    const original = await host.bridge.execute("PREVIEW", [77, 2, 2], {requestId: "preview-without-stats"});
    assert.equal(original.result.source.native_mean_supported, false); assert.equal(original.result.source.native_summary_supported, false);
    assert.equal(original.result.gray8_hex, "001180ff"); assert.equal(original.result.quantitative, false);
    assert.deepEqual((await host.bridge.query("preview-without-stats")).result, result);
  } finally {await host.close();}
});

test("PREVIEW optional statistics eligibility still requires explicit boolean flags", async () => {
  const cases = [["native_mean_supported", "false"], ["native_summary_supported", 0], ["native_mean_supported", null], ["native_summary_supported", undefined]];
  const host = await fakeHost(({socket, request, reply}) => {
    const result = previewFixture(), [key, value] = cases[Number(request.id.at(-1))];
    result.source[key] = value; socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const requestId = "preview-bad-stats-" + index;
      for (const attempt of [() => host.bridge.execute("PREVIEW", [77, 2, 2], {requestId}), () => host.bridge.query(requestId)]) {
        await assert.rejects(attempt(), error => error.details.code === "NATIVE_PROTOCOL" && /image metadata/.test(error.message));
      }
    }
  } finally {await host.close();}
});

test("prepared PREVIEW rejects wrong identity, size, packing, range and quantitative/display semantics", async () => {
  const changes = [r => {r.image_id = 78;}, r => {r.width = 3;}, r => {r.sample_count = 5;}, r => {r.gray8_hex = "001180FF";},
    r => {r.gray8_hex = "00";}, r => {r.sampled_maximum = -3;}, r => {r.quantitative = true;},
    r => {r.source.packing_style = 2;}, r => {r.mapping = "averaged";}, r => {r.constant_range_gray8 = 127;},
    r => {r.sampled_maximum = r.sampled_minimum;}, r => {r.operator = "NumPy::array";}];
  const host = await fakeHost(({socket, request, reply}) => {
    const result = previewFixture(); changes[Number(request.id.split("-").at(-1))](result);
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < changes.length; index++) {
      await assert.rejects(host.bridge.execute("PREVIEW", [77, 2, 2], {requestId: "bad-preview-" + index}), error => error.details.code === "NATIVE_PROTOCOL" && /Native PREVIEW/.test(error.message));
    }
  } finally {await host.close();}
});

test("new Fourier submissions reject old v1 immediately while historical QUERY remains explicit", async () => {
  for (const state of ["queued", "running", "completed", "failed"]) {
    const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply(state,
      state === "completed" ? derivedFixture("FFT", [77]) : undefined,
      state === "failed" ? {code: "old_candidate", error: "old candidate failure"} : {})) + "\n"));
    try {
      await assert.rejects(host.bridge.execute("FFT", [77], {requestId: "old-v1"}), error => error.details.code === "NATIVE_PROTOCOL" && /version 1 is historical QUERY only/.test(error.message));
      assert.deepEqual(host.requests.map(request => request.operation), ["FFT"], "old version rejection does not poll, retry or fall back");
      const historical = await host.bridge.query("old-v1");
      assert.equal(historical.result_version, 1); assert.equal(historical.original_operation, "FFT");
    } finally {await host.close();}
  }
});

test("Fourier v2 validates exact transform semantics and separate mathematical/native frequency coordinates", async () => {
  const cases = [["FFT", false], ["IFFT", false], ...["REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"].flatMap(op => [[op, false], [op, true]])];
  const host = await fakeHost(({socket, request, reply}) => {
    const [operation, spatial] = cases[Number(request.id.split("-").at(-1))];
    const result = fourierFixture(operation, 77, {spatial});
    socket.end(JSON.stringify(reply("completed", result, {...identity(operation, [77]), result_version: 2})) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const [operation, spatial] = cases[index], id = "fourier-v2-" + index;
      const reply = await host.bridge.execute(operation, [77], {requestId: id});
      assert.equal(reply.result_version, 2); assert.deepEqual(reply.result, fourierFixture(operation, 77, {spatial}));
      assert.deepEqual((await host.bridge.query(id)).result, reply.result);
      if (reply.result.frequency_grid) for (const axis of reply.result.frequency_grid.axes) {
        assert.notEqual(axis.frequency_at_index_zero, axis.native_calibrated_value_at_pixel_zero);
        assert.notEqual(axis.native_calibration_dc_value, 0, "native half-bin calibration is not mathematical DC");
        assert.equal(axis.dc_index, axis.size / 2);
      }
    }
  } finally {await host.close();}
});

test("Fourier v2 uses exact float32 reciprocal calibration and preserves the actual native zero", async () => {
  const result = fourierFixture("FFT"), source = result.source.calibration[0], native = result.image.calibration[0], axis = result.frequency_grid.axes[0];
  source.scale = Math.fround(0.3);
  native.scale = Math.fround(1 / Math.fround(native.size * source.scale));
  native.calibrated_value_at_pixel_zero = Math.fround(-native.origin * native.scale);
  const refresh = () => Object.assign(axis, {physical_frequency_step: native.scale, frequency_at_index_zero: -native.size / 2 * native.scale,
    native_calibrated_value_at_pixel_zero: native.calibrated_value_at_pixel_zero,
    native_calibration_dc_value: native.calibrated_value_at_pixel_zero + native.size / 2 * native.scale});
  refresh();
  assert.notEqual(axis.native_calibration_dc_value, -0.5 * native.scale, "the fixture intentionally contains native float32 zero rounding");
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", result, {...identity("FFT", [77]), result_version: 2})) + "\n"));
  try {
    assert.deepEqual((await host.bridge.execute("FFT", [77], {requestId: "rounded-native-zero"})).result.frequency_grid, result.frequency_grid);
    const bits = new Uint32Array(1), floats = new Float32Array(bits.buffer);
    floats[0] = native.scale; bits[0] += 1; native.scale = floats[0];
    native.calibrated_value_at_pixel_zero = Math.fround(-native.origin * native.scale); refresh();
    await assert.rejects(host.bridge.execute("FFT", [77], {requestId: "wrong-one-ulp"}), error => error.details.code === "NATIVE_PROTOCOL" && /mathematical frequency grid/.test(error.message));
  } finally {await host.close();}
});

test("Fourier v2 rejects wrong signs, normalization, phase/power, calibration lineage and frequency identity", async () => {
  const cases = [
    ["FFT", false, r => {r.transform_signs.forward = "-";}, /v2 convention/],
    ["IFFT", false, r => {r.normalization = "none";}, /v2 convention/],
    ["VENDOR_ARG", false, r => {r.phase_units = "degrees";}, /v2 convention/],
    ["VENDOR_NORM", false, r => {r.representation = "magnitude";}, /Fourier representation/],
    ["FFT", false, r => {r.source_spatial_origin_used = true;}, /v2 convention/],
    ["IFFT", false, r => {r.inverse_restores_source_origin = true;}, /v2 convention/],
    ["FFT", false, r => {r.intensity_calibration_applied = true;}, /v2 convention/],
    ["FFT", false, r => {r.input_index_origin = "physical";}, /v2 convention/],
    ["FFT", false, r => {r.intensity_calibration_policy = "";}, /v2 convention/],
    ["FFT", false, r => {r.frequency_grid = null;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes.reverse();}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].dc_index += 0.5;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].cycles_per_pixel_step *= -1;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].unit = "nm";}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].frequency_at_index_zero = r.frequency_grid.axes[0].native_calibrated_value_at_pixel_zero;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].native_calibration_dc_value = 0;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].physical_frequency_step *= -1;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.axes[0].coordinate_rule = "f(i)=native_zero+i*scale";}, /mathematical frequency grid/],
    ["FFT", false, r => {r.frequency_grid.native_calibration_has_half_bin_offset = false;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.image.calibration[0].origin -= 0.5;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.source.calibration[0].scale *= -1;}, /mathematical frequency grid/],
    ["FFT", false, r => {r.source.calibration[0].unit = null; r.source.calibration[0].usable = false; r.source.calibration[0].issue = "unknown_units"; r.source.calibration_complete = false;}, /v2 convention/],
    ["IFFT", false, r => {r.frequency_grid = {};}, /spatial origin/],
    ["IFFT", false, r => {r.image.calibration[0].origin = 2;}, /spatial origin/],
    ["IFFT", false, r => {r.image.calibration[0].scale *= -1;}, /spatial origin/],
    ["REAL", false, r => {r.image.calibration[0].scale *= -1;}, /component calibration/],
    ["IMAG", true, r => {r.centering = "fftshift_data";}, /mathematical frequency grid/],
  ];
  const host = await fakeHost(({socket, request, reply}) => {
    const [operation, spatial, change] = cases[Number(request.id.split("-").at(-1))];
    const result = fourierFixture(operation, 77, {spatial}); change(result);
    socket.end(JSON.stringify(reply("completed", result, {...identity(operation, [77]), result_version: 2})) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const [operation, , , expected] = cases[index], id = "bad-v2-" + index;
      for (const attempt of [() => host.bridge.execute(operation, [77], {requestId: id}), () => host.bridge.query(id)]) {
        await assert.rejects(attempt(), error => error.details.code === "NATIVE_PROTOCOL" && expected.test(error.message), "specific target: " + index);
      }
    }
  } finally {await host.close();}
});

test("READ snapshots preserve exact finite float32 bytes, signed zero, ROI coordinates and immutable QUERY identity", async () => {
  const args = [77, 1, 1, 4, 3], expected = readFixture(args), host = await fakeHost(({socket, request, reply}) => {
    socket.end(JSON.stringify(request.operation === "READ" ? reply("queued") : reply("completed", expected)) + "\n");
  });
  try {
    const output = await host.bridge.execute("READ", args, {requestId: "saved-read"});
    assert.equal(output.result_type, "native_data_snapshot"); assert.equal(output.result_version, 1); assert.deepEqual(output.normalized_args, args);
    assert.deepEqual(output.result, expected); assert.deepEqual((await host.bridge.query("saved-read")).result, expected);
    const bytes = Buffer.from(output.result.values_base64, "base64");
    assert.equal(bytes.toString("hex"), "00000080000020c00000003e0000004100000080000020c0");
    assert.ok(Object.is(bytes.readFloatLE(0), -0)); assert.equal(bytes.readFloatLE(4), -2.5); assert.equal(bytes.readFloatLE(8), 0.125);
    assert.deepEqual(output.result.roi_calibration.map(axis => [axis.origin, axis.calibrated_value_at_pixel_zero, axis.scale, axis.unit]), [[1, 0.25, -0.25, "nm"], [-2, 1, 0.5, "nm"]]);
    assert.deepEqual(host.requests.map(request => [request.operation, request.args]), [["READ", args.map(String)], ["QUERY", []], ["QUERY", []]]);
    for (const key of ["image_id", "image", "path", "png"]) assert.equal(Object.hasOwn(output.result, key), false);
  } finally {await host.close();}
});

test("READ reports recognized unknown or invalid spatial calibration without inventing units", async () => {
  const args = [77, 1, 1, 4, 3], cases = ["unknown_units", "invalid_calibration", "invalid_calibration_and_unknown_units"];
  const host = await fakeHost(({socket, request, reply}) => {
    const issue = cases[Number(request.id.at(-1))], source = imageMetadata(77);
    source.calibration_complete = false;
    for (const axis of source.calibration) {
      axis.usable = false; axis.issue = issue;
      if (issue !== "invalid_calibration") axis.unit = null;
      if (issue !== "unknown_units") axis.scale = null;
    }
    socket.end(JSON.stringify(reply("completed", readFixture(args, {source}))) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const result = (await host.bridge.execute("READ", args, {requestId: "raw-read-" + index})).result;
      assert.equal(result.calibration_complete, false); assert.equal(result.roi_calibration[0].issue, cases[index]);
      assert.equal(result.roi_calibration[0].origin, index === 0 ? 1 : null);
      assert.equal(result.roi_calibration[0].calibrated_value_at_pixel_zero, index === 0 ? 0.25 : null);
      assert.equal(result.roi_calibration[0].unit, index === 1 ? "nm" : null);
      assert.equal(Buffer.from(result.values_base64, "base64").readFloatLE(4), -2.5);
    }
  } finally {await host.close();}
});

test("READ binds retained-source provenance to explicit immutable creation fields", async () => {
  const provenance = {operation: "BINARY", request_id: "creator-saved", source_image_ids: [12, 14], semantics: "immutable synthetic creation record"};
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", readFixture(undefined, {provenance}))) + "\n"));
  try {
    const result = (await host.bridge.execute("READ", [77, 1, 1, 4, 3])).result;
    assert.deepEqual(result.source_provenance, provenance);
  } finally {await host.close();}
});

test("READ eligibility does not require optional native statistics bindings", async () => {
  const source = imageMetadata(77); source.native_mean_supported = false; source.native_summary_supported = false;
  const expected = readFixture(undefined, {source});
  const host = await fakeHost(({socket, reply}) => socket.end(JSON.stringify(reply("completed", expected)) + "\n"));
  try {
    const result = (await host.bridge.execute("READ", [77, 1, 1, 4, 3])).result;
    assert.equal(result.source.native_mean_supported, false); assert.equal(result.source.native_summary_supported, false);
    assert.equal(Buffer.from(result.values_base64, "base64").readFloatLE(4), -2.5);
  } finally {await host.close();}
});

test("READ accepts the exact source/ROI byte budgets and rejects noncanonical padding without changing decoded bytes", async () => {
  const args = [77, 17, 23, 145, 151], source = imageMetadata(77, {shape: [2048, 2048]});
  const host = await fakeHost(({socket, request, reply}) => {
    const small = request.id === "noncanonical-padding", result = readFixture(small ? [77, 0, 0, 1, 1] : args, {source});
    if (small) {
      const original = Buffer.from(result.values_base64, "base64");
      assert.equal(result.values_base64, "AAAAgA=="); result.values_base64 = "AAAAgB==";
      assert.deepEqual(Buffer.from(result.values_base64, "base64"), original, "invalid pad bits decode to the same bytes");
    }
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    const output = (await host.bridge.execute("READ", args, {requestId: "maximum-read"})).result;
    assert.equal(output.source.pixels, 4194304); assert.equal(output.sample_count, 16384); assert.equal(output.raw_bytes, 65536);
    assert.equal(Buffer.from(output.values_base64, "base64").length, 65536);
    await assert.rejects(host.bridge.execute("READ", [77, 0, 0, 1, 1], {requestId: "noncanonical-padding"}), error => error.details.code === "NATIVE_PROTOCOL" && /canonical base64 bytes/.test(error.message));
  } finally {await host.close();}
});

test("READ rejects malformed ROI/array/base64/calibration/provenance at the declared snapshot checks", async () => {
  const nonfinite = bits => result => {const bytes = Buffer.from(result.values_base64, "base64"); bytes.writeUInt32LE(bits, 0); result.values_base64 = bytes.toString("base64");};
  const cases = [
    [r => {r.source_image_id = 78;}, /identity\/ROI\/array/], [r => {r.operation = "PREVIEW";}, /identity\/ROI\/array/],
    [r => {r.backend = "synthetic_mock";}, /identity\/ROI\/array/], [r => {r.effective_rect[0] = 0;}, /identity\/ROI\/array/],
    [r => {r.requested_rect[2] = 5;}, /identity\/ROI\/array/], [r => {r.shape.reverse();}, /identity\/ROI\/array/],
    [r => {r.dtype = "float64";}, /identity\/ROI\/array/], [r => {r.byte_order = "big";}, /identity\/ROI\/array/],
    [r => {r.axes.reverse();}, /identity\/ROI\/array/], [r => {r.array_order = "F";}, /identity\/ROI\/array/],
    [r => {r.sample_count++;}, /identity\/ROI\/array/], [r => {r.raw_bytes -= 4;}, /identity\/ROI\/array/],
    [r => {r.data_encoding = "hex";}, /identity\/ROI\/array/], [r => {r.intensity_calibration_applied = true;}, /identity\/ROI\/array/],
    [r => {r.snapshot_atomic = true;}, /identity\/ROI\/array/], [r => {r.source_write_requested = true;}, /identity\/ROI\/array/],
    [r => {r.coordinate_mapping_policy = "physical coordinates";}, /identity\/ROI\/array/],
    [r => {r.source_provenance_scope = "immutable image pixels";}, /identity\/ROI\/array/],
    [r => {r.image_id = 99;}, /identity\/ROI\/array/], [r => {r.path = "not-permitted.npy";}, /identity\/ROI\/array/],
    [r => {r.values_base64 += "\n";}, /base64 encoding\/byte length/], [r => {r.values_base64 = r.values_base64.slice(4);}, /base64 encoding\/byte length/],
    [r => {r.values_base64 = "_" + r.values_base64.slice(1);}, /base64 encoding\/byte length/],
    [nonfinite(0x7fc00000), /finite little-endian/], [nonfinite(0x7f800000), /finite little-endian/], [nonfinite(0xff800000), /finite little-endian/],
    [r => {r.source.packing_style = 2;}, /source packing\/bounds/],
    [r => {r.roi_calibration[0].source_offset = 0;}, /translated ROI calibration/], [r => {r.roi_calibration[0].origin = 2;}, /translated ROI calibration/],
    [r => {r.roi_calibration[0].calibrated_value_at_pixel_zero = 0.5;}, /translated ROI calibration/],
    [r => {r.roi_calibration[0].scale *= -1;}, /translated ROI calibration/], [r => {r.roi_calibration[0].unit = "pixel";}, /translated ROI calibration/],
    [r => {r.roi_calibration[0].source_origin = 3;}, /translated ROI calibration/], [r => {r.roi_calibration.reverse();}, /translated ROI calibration/],
    [r => {r.calibration_complete = false;}, /translated ROI calibration/],
    [r => {delete r.source_provenance;}, /retained source provenance/],
    [r => {r.source_provenance = {operation: "QUERY", request_id: "saved", source_image_ids: [12], semantics: "not creation"};}, /retained source provenance/],
    [r => {r.source_provenance = {operation: "CROP", request_id: "bad id", source_image_ids: [12], semantics: "synthetic"};}, /retained source provenance/],
    [r => {r.source_provenance = {operation: "BINARY", request_id: "saved", source_image_ids: [12], semantics: "synthetic"};}, /retained source provenance/],
    [r => {r.source_provenance = {operation: "CROP", request_id: "saved", source_image_ids: [77], semantics: "alias"};}, /retained source provenance/],
  ];
  const host = await fakeHost(({socket, request, reply}) => {
    const result = readFixture(), [change] = cases[Number(request.id.split("-").at(-1))]; change(result);
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  try {
    for (let index = 0; index < cases.length; index++) {
      const requestId = "bad-read-" + index, expected = cases[index][1];
      for (const attempt of [() => host.bridge.execute("READ", [77, 1, 1, 4, 3], {requestId}), () => host.bridge.query(requestId)]) {
        await assert.rejects(attempt(), error => error.details.code === "NATIVE_PROTOCOL" && expected.test(error.message), "specific READ target: " + index);
      }
    }
  } finally {await host.close();}
});
