// Dependency-free MCP stdio transport; the caller supplies a science or DM runtime.
/** Stdio MCP facade. Trusted tool composition lives in lib/tools; scientific
 * execution, provenance and recovery stay in the existing backend adapters. */
import process from 'node:process';
import {RpcError} from './schema.mjs';

export function startStdioMcpServer({runtime,input=process.stdin,output=process.stdout,exit=code=>process.exit(code),serverName='microscopy-core',serverVersion='0.1.0'}={}){
if(!runtime||!runtime.registry||typeof runtime.registry.call!=='function'||typeof runtime.registry.listTools!=='function'||typeof runtime.close!=='function')throw new TypeError('MCP stdio facade requires an explicitly composed runtime');
const SERVER_NAME=serverName;
const SERVER_VERSION=serverVersion;
const PROTOCOL_VERSION='2024-11-05';
function send(msg) {
  output.write(JSON.stringify(msg) + "\n");
}

function ok(id, result) {
  send({ jsonrpc: "2.0", id, result });
}

function fail(id, code, message) {
  send({ jsonrpc: "2.0", id, error: { code, message } });
}

const running = new Map();
async function handle(msg) {
  if (!msg || typeof msg !== "object" || Array.isArray(msg) || msg.jsonrpc !== "2.0" || typeof msg.method !== "string"
      || (Object.hasOwn(msg, "id") && !(typeof msg.id === "string" || Number.isSafeInteger(msg.id)))) {
    return fail(null, -32600, "Invalid Request");
  }
  const { id, method, params } = msg;
  if (id === undefined) {
    if (method === "notifications/cancelled") running.get(params?.requestId)?.abort();
    return;
  }
  if (params !== undefined && (params === null || typeof params !== "object" || Array.isArray(params))) return fail(id, -32602, "params 必须是对象");
  if (method === "initialize") {
    return ok(id, {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      instructions: runtime.instructions,
    });
  }
  if (method === "ping") return ok(id, {});
  if (method === "tools/list") return ok(id, { tools: runtime.registry.listTools() });
  if (method === "tools/call") {
    if (!params || typeof params.name !== "string") return fail(id, -32602, "需要工具名称");
    if (running.has(id)) return fail(id, -32600, "Duplicate in-flight request id");
    const controller = new AbortController();
    running.set(id, controller);
    try {
      const result = await runtime.registry.call(params.name, params.arguments, {signal: controller.signal});
      if (!controller.signal.aborted) return ok(id, result);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof RpcError) return fail(id, err.code, err.message);
      return ok(id, {
        content: [{ type: "text", text: `错误: ${err.message}` }],
        isError: true,
      });
    } finally {
      running.delete(id);
    }
    // A cancelled waiter may resolve later; do not fall through to Method not found.
    return;
  }
  if (method === "resources/list") return ok(id, { resources: [] });
  if (method === "prompts/list") return ok(id, { prompts: [] });
  return fail(id, -32601, `Method not found: ${method}`);
}

let stdinBuffer = "";
input.setEncoding("utf8");
input.on("data", (chunk) => {
  stdinBuffer += chunk;
  if (Buffer.byteLength(stdinBuffer, "utf8") > 2 * 1024 * 1024) {
    stdinBuffer = "";
    fail(null, -32600, "Request exceeds 2 MiB");
    return;
  }
  let idx;
  while ((idx = stdinBuffer.indexOf("\n")) >= 0) {
    const line = stdinBuffer.slice(0, idx).trim();
    stdinBuffer = stdinBuffer.slice(idx + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      fail(null, -32700, "Parse error");
      continue;
    }
    handle(msg).catch((err) => {
      if (msg && msg.id !== undefined) fail(msg.id, -32603, err.message);
    });
  }
});

let closed=false;
function close(){if(closed)return;closed=true;runtime.close();process.off('SIGINT',close);exit(0);}
input.on('end',close);
process.on('SIGINT',close);
return {close};
}
