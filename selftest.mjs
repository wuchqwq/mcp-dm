#!/usr/bin/env node
/**
 * selftest.mjs -- end-to-end check of the DM-MCP analysis chain without
 * DigitalMicrograph.
 *
 * Starts dm_bridge.py in mock mode, then drives server.mjs over stdio the
 * way an MCP client does, and asserts every tool's contract.
 *
 *   node selftest.mjs
 */

import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import net from "node:net";
import os from "node:os";
import { randomUUID } from "node:crypto";

const here = path.dirname(fileURLToPath(import.meta.url));
const PYTHON =
  process.env.DM_TEST_PYTHON ||
  "python";
const reservation = net.createServer();
await new Promise((resolve, reject) => { reservation.once("error", reject); reservation.listen(0, "127.0.0.1", resolve); });
const PORT = String(reservation.address().port);
await new Promise(resolve => reservation.close(resolve));

const bridge = spawn(PYTHON, [path.join(here, "bridge", "dm_bridge.py")], {
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", DM_BRIDGE_MOCK: "1", DM_BRIDGE_PORT: PORT, DM_BRIDGE_VERBOSE: "0" },
  stdio: ["ignore", "ignore", "pipe"],
});
let bridgeErr = "";
bridge.stderr.on("data", (d) => (bridgeErr += d.toString()));
bridge.on("error", e => { bridgeErr += e.message; });

const server = spawn(process.execPath, [path.join(here, "server.mjs")], {
  env: { ...process.env, DM_BRIDGE_PORT: PORT, DM_MCP_TIMEOUT_MS: "8000" },
  stdio: ["pipe", "pipe", "pipe"],
});
let serverErr = "";
server.stderr.on("data", (d) => (serverErr += d.toString()));
server.on("error", e => { serverErr += e.message; });

const waiters = new Map();
let buf = "";
server.stdout.setEncoding("utf8");
server.stdout.on("data", (chunk) => {
  buf += chunk;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { serverErr += "Invalid JSON response: " + line; continue; }
    const w = waiters.get(msg.id);
    if (w) {
      waiters.delete(msg.id);
      w(msg);
    }
  }
});

let nextId = 1;
function rpc(method, params) {
  const id = nextId++;
  server.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { waiters.delete(id); reject(new Error(`timeout: ${method}`)); }, 10000);
    waiters.set(id, (msg) => {
      clearTimeout(timer);
      resolve(msg);
    });
  });
}

async function call(name, args = {}) {
  const r = await rpc("tools/call", { name, arguments: args });
  const res = r.result || {};
  const text = res.content?.[0]?.text || "";
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* error text */
  }
  return { isError: res.isError === true, text, json };
}

let failures = 0;
function check(name, cond, detail) {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${cond ? "" : "  -> " + String(detail).slice(0, 300)}`);
  if (!cond) failures++;
}

try {
  const started = Date.now();
  while (true) {
    if (bridge.exitCode !== null || bridgeErr.includes("ENOENT")) throw new Error("Mock bridge failed: " + bridgeErr);
    try {
      await new Promise((resolve, reject) => {
        const s = net.createConnection({ host: "127.0.0.1", port: Number(PORT) });
        s.once("connect", () => { s.destroy(); resolve(); });
        s.once("error", reject);
        s.setTimeout(250, () => { s.destroy(); reject(new Error("not ready")); });
      });
      break;
    } catch (e) {
      if (Date.now() - started > 10000) throw e;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
  const init = await rpc("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "selftest", version: "0" },
  });
  check("initialize", init.result?.serverInfo?.name === "digitalmicrograph", JSON.stringify(init).slice(0, 200));
  check("initialize 带 instructions", (init.result?.instructions || "").includes("dm_run_script"), "no instructions");

  server.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");

  const list = await rpc("tools/list", {});
  const names = (list.result?.tools || []).map((t) => t.name);
  check("tools/list 返回 17 个工具", names.length === 17, names.join(","));
  console.log("      " + names.join(", "));

  const status = await call("dm_status");
  check("dm_status 连通且标注 analysis-only", status.json?.backend === "mock" && status.json?.scope === "analysis-only", status.text);

  const ds = await call("dm_datasets");
  check("dm_datasets 返回图像与两个显式合成谱数据集", ds.json?.count === 4, ds.text.slice(0, 200));
  check("dm_datasets 带标定", Array.isArray(ds.json?.datasets?.[0]?.calibration), ds.text.slice(0, 200));

  const md = await call("dm_metadata", { image_id: 1000, max_depth: 4 });
  check("dm_metadata 有元数据树", !!md.json?.tags?.Acquisition, md.text.slice(0, 200));

  const mdSub = await call("dm_metadata", { image_id: 1000, prefix: "Acquisition/Instrument" });
  check("dm_metadata 支持子树", mdSub.json?.tags?.Name === "MOCK-TEM", mdSub.text.slice(0, 200));

  const st = await call("dm_stats", { image_id: 1000, rect: [0, 0, 64, 32] });
  check("dm_stats 限定区域生效", st.json?.rect?.[2] === 64 && st.json?.rect?.[3] === 32, st.text.slice(0, 200));

  const pr = await call("dm_profile", { image_id: 1000, x0: 0, y0: 10, x1: 200, y1: 10, width: 3 });
  check("dm_profile 返回序列", pr.json?.n === 201 && Array.isArray(pr.json?.values), pr.text.slice(0, 200));

  const ff = await call("dm_fft", { image_id: 1000, rect: [0, 0, 128, 128], top_n: 5 });
  check("dm_fft 返回峰", Array.isArray(ff.json?.peaks) && ff.json.peaks.length === 5, ff.text.slice(0, 200));

  const exportPath = path.join(os.tmpdir(), `dm-mcp-synthetic-${randomUUID()}_selftest_out.tif`);
  const ex = await call("dm_export", { image_id: 1000, path: exportPath });
  check("dm_export 到达后端", ex.json?.path === exportPath, ex.text.slice(0, 200));

  const cr = await call("dm_crop", { image_id: 1000, rect: [0, 0, 128, 96], name: "selftest_crop" });
  check("dm_crop 返回新图像", cr.json?.new_image?.shape?.[0] === 96 && cr.json?.new_image?.shape?.[1] === 128, cr.text.slice(0, 300));

  const crStats = await call("dm_stats", { image_id: cr.json?.new_image?.id });
  check("裁剪后的图像可继续分析", crStats.json?.shape?.[0] === 96, crStats.text.slice(0, 200));

  const blocked = await call("dm_run_script", { script: 'OkDialog("x")' });
  check("dm_run_script 默认被拒绝", blocked.isError === true, blocked.text);

  const missing = await call("dm_stats", { image_id: 999 });
  check("不存在的 image_id 报错", missing.isError === true, missing.text);
  const invalid = await rpc("tools/call", { name: "dm_crop", arguments: { rect: [1, 1, 0, 0] } });
  check("无效矩形在入口拒绝", invalid.error?.code === -32602, JSON.stringify(invalid));
  const unknown = await rpc("tools/call", { name: "not_a_tool", arguments: {} });
  check("未知工具返回协议错误", unknown.error?.code === -32602, JSON.stringify(unknown));
  const invalidType = await rpc("tools/call", { name: "dm_stats", arguments: null });
  check("拒绝错误参数类型", invalidType.error?.code === -32602, JSON.stringify(invalidType));
  const concurrent = await Promise.all([call("dm_status"), call("dm_datasets"), call("dm_stats", {image_id:1000,rect:[0,0,8,4]})]);
  check("并发请求按队列完成", concurrent.every(v => !v.isError && v.json), JSON.stringify(concurrent));
} catch (err) {
  failures++;
  console.error("FAIL  未处理的测试异常: " + (err.stack || err));
} finally {
  server.kill();
  bridge.kill();
  console.log(failures === 0 ? "\n全部通过。" : `\n${failures} 项失败。`);
  if (failures && bridgeErr) console.log("bridge stderr:\n" + bridgeErr);
  if (failures && serverErr) console.log("server stderr:\n" + serverErr);
  process.exitCode = failures === 0 ? 0 : 1;
}
