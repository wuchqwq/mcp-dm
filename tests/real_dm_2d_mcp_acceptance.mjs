// Fixed acceptance against an already-running real DM Bridge and a small
// synthetic 2D image created in DM. This never opens experimental files.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const imageId = Number(process.env.DM_ANALYSIS_TEST_IMAGE_ID);
const switchImageId = Number(process.env.DM_ANALYSIS_TEST_SWITCH_IMAGE_ID);
const captureDir = process.env.DM_ANALYSIS_TEST_CAPTURE_DIR;
const resultDir = process.env.DM_ANALYSIS_TEST_RESULT_DIR;
const expectedBridgeHash = process.env.DM_EXPECTED_BRIDGE_SHA256;
if (!Number.isSafeInteger(imageId) || !Number.isSafeInteger(switchImageId) || !captureDir || !resultDir || !expectedBridgeHash) {
  throw new Error('Set fixed synthetic image IDs, output directories, and expected bridge hash');
}
const server = spawn(process.execPath, ['server.mjs'], {cwd:process.cwd(), stdio:['pipe','pipe','pipe'], windowsHide:true});
let stderr = '';
server.stderr.setEncoding('utf8');
server.stderr.on('data', chunk => { if (stderr.length < 8192) stderr += chunk.slice(0, 8192-stderr.length); });
const waiters = new Map();
createInterface({input:server.stdout}).on('line', line => {
  let msg;
  try { msg = JSON.parse(line); } catch { stderr += '\ninvalid JSON from MCP server'; return; }
  const callback = waiters.get(msg.id);
  if (callback) { waiters.delete(msg.id); callback(msg); }
});
let id = 1;
function rpc(method, params) {
  const current = id++;
  return new Promise((resolve,reject) => {
    const timer = setTimeout(() => { waiters.delete(current); reject(new Error('timeout: '+method+'\n'+stderr)); }, 120000);
    waiters.set(current, msg => { clearTimeout(timer); resolve(msg); });
    server.stdin.write(JSON.stringify({jsonrpc:'2.0',id:current,method,params})+'\n');
  });
}
async function tool(name, args={}) {
  const response = await rpc('tools/call',{name,arguments:args});
  if (response.error) throw new Error(response.error.message);
  if (response.result?.isError) throw new Error(response.result.content?.[0]?.text || name+' failed');
  return response.result;
}

try {
  const initialized = await rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'real-dm-task-a-acceptance',version:'1'}});
  assert.equal(initialized.result.serverInfo.name,'digitalmicrograph');
  const status = JSON.parse((await tool('dm_status')).content[0].text);
  assert.equal(status.backend,'digitalmicrograph');
  assert.equal(status.bridge_code_sha256,expectedBridgeHash);
  const datasets = JSON.parse((await tool('dm_datasets')).content[0].text).datasets;
  const source = datasets.find(item => item.id === imageId);
  assert.ok(source,'fixed synthetic source is available in real DM');
  assert.deepEqual(source.shape,[48,64]);
  const capture = JSON.parse((await tool('dm_2d_capture',{image_id:imageId,output_dir:captureDir})).content[0].text);
  assert.equal(capture.state,'captured');
  assert.deepEqual(capture.shape_yx,[48,64]);
  const previewResponse = await tool('dm_2d_preview',{capture_dir:captureDir,max_side:32,
    roi:[8,12,40,36],profile:{start:[8,24],end:[39,24],width:3}});
  const previewMeta = JSON.parse(previewResponse.content.find(block=>block.type==='text').text);
  const image = previewResponse.content.find(block=>block.type==='image');
  assert.ok(image,'MCP returned inline image content');
  assert.equal(image.mimeType,'image/png');
  assert.equal(Buffer.from(image.data,'base64').subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  assert.deepEqual(previewMeta.mapping.preview_shape_yx,[24,32]);
  assert.deepEqual(previewMeta.mapping.overlay.roi_source_xyxy,[8,12,40,36]);
  const frontSwitch = JSON.parse((await tool('dm_crop',{image_id:switchImageId,rect:[0,0,10,8],name:'mcp synthetic switch crop'})).content[0].text);
  assert.ok(frontSwitch.new_image?.id,'synthetic second image crop created to change the DM front window');
  const operationId = 'real-synthetic-task-a-1';
  const analysisResponse = await tool('dm_2d_analyze',{capture_dir:captureDir,result_dir:resultDir,
    operation_id:operationId,roi:[8,12,40,36],profile:{start:[8,24],end:[39,24],width:1},top_n:4});
  const analysis = JSON.parse(analysisResponse.content[0].text);
  assert.equal(analysis.state,'succeeded');
  assert.ok(Math.abs(analysis.stats.mean-100)<1e-5);
  assert.ok(Math.abs(analysis.stats.stddev-Math.SQRT2)<1e-5);
  assert.equal(analysis.profile_points,32);
  assert.deepEqual(analysis.fft_shape_yx,[24,32]);
  const fft = JSON.parse(readFileSync(path.join(resultDir,'fft.json'),'utf8'));
  const positiveBin = fft.peaks.find(p=>p.dx===8 && p.dy===0);
  assert.ok(positiveBin);
  assert.ok(Math.abs(positiveBin.magnitude-768)<1e-3);
  assert.equal(positiveBin.fx,-1);
  const profileRows = readFileSync(path.join(resultDir,'profile.csv'),'utf8').trim().split(/\r?\n/).slice(1);
  assert.equal(profileRows.length,32);
  const firstProfile = Number(profileRows[0].split(',')[1]);
  assert.ok(Math.abs(firstProfile-102)<1e-5);
  const query = JSON.parse((await tool('dm_2d_result',{result_dir:resultDir})).content[0].text);
  assert.equal(query.state,'succeeded');
  const captureQuery = JSON.parse((await tool('dm_2d_result',{capture_dir:captureDir})).content[0].text);
  assert.equal(captureQuery.state,'captured');
  const replay = spawn(process.env.DM_ANALYSIS_PYTHON || 'python',
    [path.join(resultDir,'replay.py'),'--verify'],{stdio:['ignore','pipe','pipe'],windowsHide:true});
  let replayOut='',replayErr='';
  replay.stdout.setEncoding('utf8'); replay.stderr.setEncoding('utf8');
  replay.stdout.on('data',chunk=>replayOut+=chunk); replay.stderr.on('data',chunk=>replayErr+=chunk);
  const [replayCode] = await once(replay,'close');
  assert.equal(replayCode,0,replayErr+replayOut);
  assert.equal(JSON.parse(replayOut).result.state,'verified');
  process.stdout.write(JSON.stringify({state:'PASS',backend:status.backend,host_pid:status.host_pid,
    bridge_sha256:status.bridge_code_sha256,capture_id:capture.capture_id,
    preview_image_block:'PASS',front_window_changed_before_analysis:true,
    stats_mean:analysis.stats.mean,stats_stddev:analysis.stats.stddev,
    profile_points:analysis.profile_points,fft_shape_yx:analysis.fft_shape_yx,
    fft_bin_magnitude:positiveBin.magnitude,fft_fx:positiveBin.fx,
    replay:'PASS',capture_dir:captureDir,result_dir:resultDir})+'\n');
} finally {
  server.kill();
  await once(server,'exit').catch(()=>{});
}
