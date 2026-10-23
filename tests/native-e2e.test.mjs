// Fully synthetic Windows E2E: real Node MCP -> real NB1 named pipe -> real
// C++ Core/message window/fake_adapter. No Gatan DLL, DM process or UI is used.
// Set DM_NATIVE_TEST_CXX to a local clang++ (never downloaded), or explicitly
// provide DM_NATIVE_FAKE_HOST_EXE built from the current fake sources.
import test from "node:test";
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {randomUUID} from "node:crypto";
import {mkdir, access} from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const mvp = path.join(root, "experiments", "native-bridge", "mvp");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function ownedProcess(command, args, env = process.env) {
  const child = spawn(command, args, {env, windowsHide: true, stdio: ["pipe", "pipe", "pipe"]});
  child.stdin.on("error", () => {});
  let stderr = "", buffer = "", failure;
  const messages = [], waiters = new Set();
  let exitResult;
  const fail = error => {
    failure = error;
    for (const waiter of waiters) waiter.reject(error);
    waiters.clear();
  };
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", chunk => {stderr = (stderr + chunk).slice(-16384);});
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", chunk => {
    buffer += chunk;
    if (Buffer.byteLength(buffer) > 2 * 1024 * 1024) return fail(new Error("owned child output exceeded bound"));
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
      try {
        const message = JSON.parse(line);
        assert.equal(typeof message, "object"); assert.notEqual(message, null);
        assert.ok(messages.length < 1000, "bounded child message count");
        messages.push(message);
        for (const waiter of [...waiters]) if (waiter.matches(message)) {
          waiters.delete(waiter); waiter.resolve(message);
        }
      } catch (error) {fail(error);}
    }
  });
  const exited = new Promise(resolve => {
    child.once("error", error => {fail(error); exitResult = {code: null, signal: null, error}; resolve(exitResult);});
    child.once("close", (code, signal) => {
      exitResult = {code, signal};
      if (buffer) fail(new Error("owned child ended with an incomplete JSON line"));
      for (const waiter of waiters) waiter.reject(new Error(`owned child exited (${code}/${signal}): ${stderr}`));
      waiters.clear(); resolve(exitResult);
    });
  });
  const wait = (matches, timeoutMs = 3000) => {
    if (failure) return Promise.reject(failure);
    const existing = messages.find(matches);
    if (existing) return Promise.resolve(existing);
    if (exitResult) return Promise.reject(new Error(`owned child already exited: ${stderr}`));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {waiters.delete(waiter); reject(new Error(`owned child event deadline: ${stderr}`));}, timeoutMs);
      const waiter = {matches, resolve: value => {clearTimeout(timer); resolve(value);}, reject: error => {clearTimeout(timer); reject(error);}};
      waiters.add(waiter);
    });
  };
  const exit = async (timeoutMs = 3000) => {
    let timer;
    try {return await Promise.race([exited, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error(`owned child exit deadline: ${stderr}`)), timeoutMs);})]);}
    finally {clearTimeout(timer);}
  };
  return {child, messages, wait, exit, exited, assertHealthy() {if (failure) throw failure;}, get stderr() {return stderr;},
    async close() {
      child.stdin.end();
      const result = await exit();
      assert.equal(result.code, 0, stderr); assert.equal(result.signal, null); if (failure) throw failure;
    }, async terminateOwnedOnly() {
      if (child.exitCode === null && child.signalCode === null) child.kill();
      await exit(3000);
    }};
}

async function command(command, args, env = process.env, timeoutMs = 30000) {
  const child = spawn(command, args, {env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"]});
  let output = "";
  for (const stream of [child.stdout, child.stderr]) stream.on("data", chunk => {output = (output + chunk).slice(-32768);});
  let timer;
  try {
    return await new Promise((resolve, reject) => {
      timer = setTimeout(() => {child.kill(); reject(new Error(`owned command deadline: ${output}`));}, timeoutMs);
      child.once("error", reject);
      child.once("close", (code, signal) => resolve({code, signal, output}));
    });
  } finally {clearTimeout(timer);}
}

async function fakeExecutable(t) {
  if (process.platform !== "win32") {t.skip("Windows named-pipe/message-window E2E requires Windows"); return null;}
  if (process.env.DM_NATIVE_FAKE_HOST_EXE) {
    const exe = path.resolve(process.env.DM_NATIVE_FAKE_HOST_EXE); await access(exe); return exe;
  }
  const output = path.join(mvp, "build", "node-e2e-" + randomUUID());
  await mkdir(output, {recursive: true});
  const exe = path.join(output, "fake_host.exe"), compiler = process.env.DM_NATIVE_TEST_CXX || "clang++.exe";
  let built;
  try {
    built = await command(compiler, ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-static", "-D_WIN32_WINNT=0x0602", "-I", mvp,
      ...["core.cpp", "bridge.cpp", "fake_adapter.cpp", "fake_host.cpp"].map(file => path.join(mvp, file)), "-ladvapi32", "-luser32", "-o", exe]);
  } catch (error) {
    if (error.code === "ENOENT" && !process.env.DM_NATIVE_TEST_CXX) {
      t.skip("No local clang++; set DM_NATIVE_TEST_CXX or DM_NATIVE_FAKE_HOST_EXE. No compiler is downloaded."); return null;
    }
    throw error;
  }
  assert.equal(built.code, 0, built.output); assert.equal(built.signal, null);
  return exe;
}

function mcp(session, timeoutMs) {
  const owned = ownedProcess(process.execPath, [path.join(root, "server.mjs")], {
    ...process.env, DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: session, DM_MCP_TIMEOUT_MS: String(timeoutMs),
    DM_ANALYSIS_PYTHON: "synthetic-e2e-must-not-start-python.exe",
  });
  let next = 1;
  const issued = new Set();
  const send = message => owned.child.stdin.write(JSON.stringify({jsonrpc: "2.0", ...message}) + "\n");
  const begin = (method, params) => {
    const id = next++; issued.add(id); send({id, method, params}); return id;
  };
  const response = async id => {
    const value = await owned.wait(message => message.id === id, 3000);
    assert.equal(value.jsonrpc, "2.0"); assert.ok(issued.has(value.id));
    assert.notEqual(Object.hasOwn(value, "result"), Object.hasOwn(value, "error"));
    return value;
  };
  const rpc = (method, params = {}) => response(begin(method, params));
  return {...owned, send, begin, rpc, tool: (name, args) => rpc("tools/call", {name, arguments: args}),
    async init() {
      const value = await rpc("initialize", {protocolVersion: "2024-11-05", capabilities: {}, clientInfo: {name: "synthetic-cpp-e2e", version: "1"}});
      assert.equal(value.error, undefined); assert.equal(value.result.protocolVersion, "2024-11-05");
      send({method: "notifications/initialized"});
    }, assertProtocol() {
      owned.assertHealthy();
      const seen = new Set();
      for (const message of owned.messages) {
        assert.equal(message.jsonrpc, "2.0"); assert.ok(issued.has(message.id));
        assert.equal(seen.has(message.id), false, "one response per MCP request"); seen.add(message.id);
        assert.notEqual(Object.hasOwn(message, "result"), Object.hasOwn(message, "error"));
      }
    }};
}

function toolOutput(message, isError = false) {
  assert.equal(message.error, undefined, "must inspect RPC errors before tool results");
  assert.equal(Boolean(message.result.isError), isError);
  assert.equal(message.result.content.length, 1); assert.equal(message.result.content[0].type, "text");
  return JSON.parse(message.result.content[0].text);
}

function receipt(output, session, requestId, host, state = "completed") {
  const value = output.native_receipt;
  assert.equal(value.protocol, "NB1"); assert.equal(value.session, session);
  assert.equal(value.id, requestId); assert.equal(value.request_id, requestId); assert.equal(value.state, state);
  assert.equal(value.host_pid, host.pid); assert.ok(Number.isInteger(value.worker_tid) && value.worker_tid > 0);
  if (state === "completed" || state === "running") assert.equal(value.exec_tid, host.host_tid);
  assert.notEqual(value.worker_tid, host.host_tid);
  if (state === "completed") {assert.equal(output.backend, "synthetic_mock"); assert.equal(output.synthetic_only, true);}
  return value;
}

async function stop(session, pid) {
  return new Promise((resolve, reject) => {
    const id = "e2e-stop";
    let socket, retry, data = Buffer.alloc(0), done = false, wrote = false;
    const timer = setTimeout(() => finish(new Error("synthetic STOP deadline")), 2500);
    function finish(error, value) {if (done) return; done = true; clearTimeout(timer); clearTimeout(retry); socket?.destroy(); error ? reject(error) : resolve(value);}
    const connect = () => {
    if (done) return;
    const attempt = net.createConnection(`\\\\.\\pipe\\dm_mcp_native_${session}`); socket = attempt;
    attempt.once("connect", () => {if (!done) {wrote = true; attempt.write(`NB1 ${session} ${id} STOP\n`, "ascii");}});
    attempt.on("data", chunk => {
      if (done) return;
      data = Buffer.concat([data, chunk]);
      if (data.length > 128 * 1024) return finish(new Error("STOP response exceeded bound"));
      if (!data.includes(10)) return;
      try {
        assert.equal(data.indexOf(10), data.length - 1);
        const reply = JSON.parse(data.toString("utf8"));
        assert.equal(reply.protocol, "NB1"); assert.equal(reply.session, session); assert.equal(reply.id, id);
        assert.equal(reply.host_pid, pid); assert.equal(reply.state, "completed"); assert.equal(reply.exec_tid, 0);
        assert.deepEqual(reply.result, {ipc_stopped: true}); finish(null, reply);
      } catch (error) {finish(error);}
    });
    attempt.once("error", error => {
      // Readiness waiting before the first byte is safe; never resubmit STOP
      // after connect/write, even when its acknowledgement is lost.
      if (!done && !wrote && ["ENOENT", "EBUSY"].includes(error.code)) {
        socket = null; attempt.destroy(); retry = setTimeout(connect, 5);
      } else finish(error);
    });
    attempt.once("close", () => {if (!done && socket === attempt) finish(new Error("STOP response incomplete"));});
    };
    connect();
  });
}

test("synthetic C++ E2E: cancel/timeout recover across Node clients with no crop replay or duplicate document", {timeout: 60000}, async t => {
  const exe = await fakeExecutable(t); if (!exe) return;
  t.diagnostic("synthetic C++ executable: " + exe);
  const session = randomUUID().replaceAll("-", ""), cancelId = "cancel-crop", lateId = "late-crop", nextId = "next-crop";
  const env = {...process.env};
  for (const key of Object.keys(env)) if (key.startsWith("NB_FAKE_")) delete env[key];
  Object.assign(env, {DM_NATIVE_SESSION: session, NB_FAKE_E2E: "1", NB_FAKE_E2E_GATE_IDS: `${cancelId},${lateId}`, NB_FAKE_CLOSE_AFTER_MS: "25000"});
  const host = ownedProcess(exe, [], env), clients = [], released = new Set();
  const release = async id => {
    const value = await command(exe, ["--release-gate", session, id], env, 2000);
    assert.equal(value.code, 0, value.output); assert.deepEqual(JSON.parse(value.output), {synthetic_gate_released: true, request_id: id});
    released.add(id);
  };
  const query = async (client, id) => {
    const deadline = Date.now() + 2500;
    while (Date.now() < deadline) {
      const message = await client.tool("dm_native_result", {request_id: id});
      const output = toolOutput(message, Boolean(message.result?.isError));
      if (output.native_receipt.state === "completed") return output;
      assert.ok(["queued", "running"].includes(output.native_receipt.state), JSON.stringify(output));
      await delay(5); // Bounded receipt polling, never an operation resend.
    }
    assert.fail("synthetic result did not complete after releasing its gate");
  };
  try {
    const identity = await host.wait(message => message.fake_host === true);
    assert.equal(identity.pid, host.child.pid);
    await host.wait(message => message.synthetic_event === "host_ready");
    const first = mcp(session, 5000); clients.push(first); await first.init();
    const status = toolOutput(await first.tool("dm_status", {request_id: "e2e-ready"}));
    receipt(status, session, "e2e-ready", identity);
    assert.equal(status.host_tid, identity.host_tid);
    const cropArgs = {image_id: 1, rect: [1, 0, 4, 2], request_id: cancelId};
    const cancelledRpcId = first.begin("tools/call", {name: "dm_crop", arguments: cropArgs});
    const started = await host.wait(message => message.synthetic_event === "crop_running" && message.request_id === cancelId);
    assert.equal(started.gate_created, true); assert.equal(started.exec_tid, identity.host_tid);
    receipt(toolOutput(await first.tool("dm_native_result", {request_id: cancelId}), true), session, cancelId, identity, "running");
    // An unrelated/nonexistent event cannot release this operation's gate.
    for (const [gateSession, gateId, enabled] of [["f".repeat(32), cancelId, "1"], [session, "bad/id", "1"], [session, cancelId, "0"]]) {
      const wrong = await command(exe, ["--release-gate", gateSession, gateId], {...env, NB_FAKE_E2E: enabled}, 2000);
      assert.equal(wrong.code, 2);
      assert.doesNotMatch(wrong.output, /fake_host|mock_lifecycle|synthetic_gate_released/, "rejected helper must not initialize a host or signal a gate");
    }
    receipt(toolOutput(await first.tool("dm_native_result", {request_id: cancelId}), true), session, cancelId, identity, "running");
    first.send({method: "notifications/cancelled", params: {requestId: cancelledRpcId}});
    assert.deepEqual((await first.rpc("ping")).result, {}); // Cancellation notification has been processed.
    await first.close(); first.assertProtocol();
    assert.equal(first.messages.some(message => message.id === cancelledRpcId), false, "MCP cancellation suppresses the response");
    assert.equal(host.messages.some(message => message.synthetic_event === "crop_created"), false, "C++ has not created an image before gate release");

    const second = mcp(session, 500); clients.push(second); await second.init();
    receipt(toolOutput(await second.tool("dm_native_result", {request_id: cancelId}), true), session, cancelId, identity, "running");
    await release(cancelId);
    const created = await host.wait(message => message.synthetic_event === "crop_created" && message.request_id === cancelId);
    const recovered = await query(second, cancelId);
    receipt(recovered, session, cancelId, identity); assert.equal(recovered.image_id, created.image_id);
    assert.equal(created.creation_count, 1); assert.deepEqual(recovered.effective_rect, cropArgs.rect);
    assert.deepEqual(toolOutput(await second.tool("dm_crop", cropArgs)), recovered, "explicit same-ID duplicate returns the old record");
    const conflict = toolOutput(await second.tool("dm_crop", {...cropArgs, rect: [0, 0, 1, 1]}), true);
    assert.equal(receipt(conflict, session, cancelId, identity, "failed").code, "id_conflict");
    assert.deepEqual(toolOutput(await second.tool("dm_native_result", {request_id: cancelId})), recovered);
    const absent = toolOutput(await second.tool("dm_native_result", {request_id: "absent-crop"}), true);
    receipt(absent, session, "absent-crop", identity, "unknown");

    const late = second.tool("dm_crop", {...cropArgs, request_id: lateId});
    assert.equal((await host.wait(message => message.synthetic_event === "crop_running" && message.request_id === lateId)).gate_created, true);
    const timeout = toolOutput(await late, true);
    assert.equal(timeout.code, "NATIVE_TIMEOUT"); assert.equal(timeout.request_id, lateId);
    assert.equal(timeout.session, session); assert.equal(timeout.sent, true);
    assert.equal(host.messages.some(message => message.synthetic_event === "crop_created" && message.request_id === lateId), false);
    const busy = toolOutput(await second.tool("dm_crop", {...cropArgs, request_id: nextId}), true);
    assert.equal(receipt(busy, session, nextId, identity, "failed").code, "busy");
    await release(lateId);
    const lateCreated = await host.wait(message => message.synthetic_event === "crop_created" && message.request_id === lateId);
    const lateRecovered = await query(second, lateId); receipt(lateRecovered, session, lateId, identity);
    assert.equal(lateRecovered.image_id, lateCreated.image_id); assert.notEqual(lateRecovered.image_id, recovered.image_id);
    const next = toolOutput(await second.tool("dm_crop", {...cropArgs, rect: [0, 0, 2, 3], request_id: nextId}));
    receipt(next, session, nextId, identity); assert.notEqual(next.image_id, lateRecovered.image_id);
    assert.deepEqual(toolOutput(await second.tool("dm_native_result", {request_id: lateId})), lateRecovered, "late completion stays bound to its original ID");

    const showArgs = {image_id: recovered.image_id, request_id: "show-crop"};
    const shown = toolOutput(await second.tool("dm_native_show", showArgs));
    receipt(shown, session, showArgs.request_id, identity); assert.equal(shown.image_id, recovered.image_id);
    assert.equal(shown.delivery, "visible_dm_document"); assert.equal(shown.document_visible, true);
    assert.equal(shown.file_saved, false); assert.equal(shown.model_visual_verification, false);
    assert.deepEqual(toolOutput(await second.tool("dm_native_show", showArgs)), shown);
    assert.deepEqual(toolOutput(await second.tool("dm_native_result", {request_id: showArgs.request_id})), shown);
    const shownAgain = toolOutput(await second.tool("dm_native_show", {...showArgs, request_id: "show-same-image-new-id"}));
    assert.equal(shownAgain.image_id, recovered.image_id);
    const counters = toolOutput(await second.tool("dm_status", {request_id: "e2e-counters"}));
    receipt(counters, session, "e2e-counters", identity);
    assert.equal(counters.synthetic_crops_created, 3); assert.equal(counters.synthetic_documents_created, 1);
    assert.equal(counters.synthetic_show_calls, 2, "same-ID duplicate never dispatches another SHOW");
    await second.close(); second.assertProtocol();
    await stop(session, identity.pid);
    const exit = await host.exit(); assert.equal(exit.code, 0, host.stderr); assert.equal(exit.signal, null);
    host.assertHealthy();
    const lifecycle = host.messages.find(message => message.mock_lifecycle === true);
    assert.equal(lifecycle.synthetic_e2e, true); assert.equal(lifecycle.initialize, 1); assert.equal(lifecycle.shutdown, 1);
    assert.equal(lifecycle.shutdown_during_execute, 0); assert.equal(lifecycle.owned_resources_released, true);
    assert.equal(lifecycle.worker_cleanup_dispatched, true);
    assert.equal(lifecycle.synthetic_crops_created, 3); assert.equal(lifecycle.synthetic_documents_created, 1);
    assert.equal(lifecycle.synthetic_show_calls, 2); assert.equal(lifecycle.synthetic_gates_started, 2);
    assert.equal(lifecycle.synthetic_gates_released, 2);
    assert.equal(lifecycle.synthetic_gates_closed, 2); assert.equal(lifecycle.synthetic_gate_close_failures, 0);
    assert.deepEqual(lifecycle.synthetic_creations, [
      {request_id: cancelId, image_id: recovered.image_id},
      {request_id: lateId, image_id: lateRecovered.image_id},
      {request_id: nextId, image_id: next.image_id},
    ], "creation IDs and counts are emitted by C++, never assigned by the JS test");
    t.diagnostic("synthetic C++ final lifecycle: " + JSON.stringify(lifecycle));
  } finally {
    // A failing assertion must not strand our blocked fake host. Release only
    // its UUID-namespaced gates, then request normal IPC STOP before any own-
    // subprocess termination fallback. Never inspect or target another PID.
    for (const event of host.messages.filter(message => message.synthetic_event === "crop_running")) {
      if (!released.has(event.request_id)) await release(event.request_id).catch(() => {});
    }
    for (const client of clients) await client.close().catch(async () => {await client.terminateOwnedOnly();});
    if (host.child.exitCode === null && host.child.signalCode === null) {
      await stop(session, host.child.pid).catch(() => {});
      await host.exit().catch(async () => {await host.terminateOwnedOnly();});
    }
  }
});
