// Offline MCP-client acceptance for task A. Uses a previously prepared
// synthetic capture package; the server's image content is decoded here.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import process from 'node:process';

const captureDir = process.env.DM_ANALYSIS_TEST_CAPTURE_DIR;
const resultDir = process.env.DM_ANALYSIS_TEST_RESULT_DIR;
if (!captureDir || !resultDir) throw new Error('Set DM_ANALYSIS_TEST_CAPTURE_DIR and DM_ANALYSIS_TEST_RESULT_DIR');
const server = spawn(process.execPath, ['server.mjs'], {
  cwd: process.cwd(),
  env: {...process.env, DM_BRIDGE_HOST: '127.0.0.1', DM_BRIDGE_PORT: '18765'},
  stdio: ['pipe', 'pipe', 'pipe'],
});
let stderr = '';
server.stderr.setEncoding('utf8');
server.stderr.on('data', chunk => { if (stderr.length < 8192) stderr += chunk.slice(0, 8192 - stderr.length); });
const pending = new Map();
const lines = createInterface({input: server.stdout});
lines.on('line', line => {
  let message;
  try { message = JSON.parse(line); } catch { stderr += '\ninvalid server JSON'; return; }
  const resolve = pending.get(message.id);
  if (resolve) { pending.delete(message.id); resolve(message); }
});
let requestId = 1;
function rpc(method, params) {
  const id = requestId++;
  const promise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('MCP call timeout: ' + method + '\n' + stderr)); }, 120000);
    pending.set(id, message => { clearTimeout(timer); resolve(message); });
  });
  server.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
  return promise;
}

try {
  const initialized = await rpc('initialize', {protocolVersion:'2024-11-05', capabilities:{}, clientInfo:{name:'task-a-test',version:'1'}});
  assert.equal(initialized.result.serverInfo.name, 'digitalmicrograph');
  const catalog = await rpc('tools/list', {});
  assert.equal(catalog.result.tools.length, 21);
  for (const name of ['dm_2d_capture','dm_2d_preview','dm_2d_analyze','dm_2d_result']) {
    assert.ok(catalog.result.tools.some(tool => tool.name === name), name);
  }
  const preview = await rpc('tools/call', {name:'dm_2d_preview', arguments:{
    capture_dir:captureDir, max_side:32, roi:[18,32,50,56],
    profile:{start:[18,44],end:[49,44],width:3},
  }});
  assert.equal(preview.result.isError, undefined);
  const content = preview.result.content;
  const metadata = JSON.parse(content.find(block => block.type === 'text').text);
  const image = content.find(block => block.type === 'image');
  assert.ok(image, 'MCP image block returned');
  assert.equal(image.mimeType, 'image/png');
  const png = Buffer.from(image.data, 'base64');
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(metadata.mapping.preview_shape_yx[0], 24);
  const analysis = await rpc('tools/call', {name:'dm_2d_analyze', arguments:{
    capture_dir:captureDir, result_dir:resultDir, operation_id:'mcp-protocol-task-a',
    roi:[18,32,50,56], profile:{start:[18,44],end:[49,44],width:1}, top_n:4,
  }});
  assert.notEqual(analysis.result.isError, true, analysis.result.content?.[0]?.text);
  const analysisResult = JSON.parse(analysis.result.content[0].text);
  assert.equal(analysisResult.state, 'succeeded');
  const status = await rpc('tools/call', {name:'dm_2d_result', arguments:{result_dir:resultDir}});
  assert.equal(JSON.parse(status.result.content[0].text).state, 'succeeded');
  process.stdout.write(JSON.stringify({state:'PASS', tools:catalog.result.tools.length,
    preview_image_block:'PASS', preview_path:metadata.preview_path,
    analysis_state:analysisResult.state, result_dir:analysisResult.result_dir}) + '\n');
} finally {
  server.kill();
  await once(server, 'exit').catch(() => {});
}
