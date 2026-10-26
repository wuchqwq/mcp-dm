// End-to-end sparse edits: real Node stdio MCP -> external Python -> PNG/NPY.
// Fixtures are synthetic; no DM or private experimental data are used.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DM_IMAGE_PYTHON || process.env.DM_TEST_PYTHON || 'python';

function fixture() {
  const directory = mkdtempSync(path.join(tmpdir(), 'mcp-sparse-edit-'));
  const source = path.join(directory, 'source.tiff');
  const made = spawnSync(python, ['-c',
    "import sys,numpy as np,tifffile; a=np.arange(32*48,dtype=np.uint16).reshape(32,48); tifffile.imwrite(sys.argv[1],np.stack([a,a+100]),photometric='minisblack',metadata=None)", source], {encoding:'utf8'});
  assert.equal(made.status, 0, made.stderr);
  return {directory, source, workspace:path.join(directory, 'workspace')};
}

function client(workspace) {
  const child = spawn(process.execPath, [path.join(root, 'server.mjs')], {
    env:{...process.env, DM_MCP_BACKEND:'images', DM_IMAGE_WORKSPACE:workspace, DM_IMAGE_PYTHON:python},
    stdio:['pipe','pipe','pipe'], windowsHide:true,
  });
  let next = 1, buffer = '', stderr = '';
  const pending = new Map();
  child.stderr.on('data', chunk => {stderr += chunk;});
  child.stdin.on('error', () => {});
  child.stdout.on('data', chunk => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const response = JSON.parse(buffer.slice(0, end));
      buffer = buffer.slice(end + 1);
      const item = pending.get(response.id);
      if (item) {pending.delete(response.id); clearTimeout(item.timer); item.resolve(response);}
    }
  });
  const rpc = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++;
    const timer = setTimeout(() => {pending.delete(id); reject(new Error('MCP timeout: ' + stderr));}, 30000);
    pending.set(id, {resolve, timer});
    child.stdin.write(JSON.stringify({jsonrpc:'2.0', id, method, params}) + '\n');
  });
  return {
    rpc,
    tool:(name, args) => rpc('tools/call', {name, arguments:args}),
    async close() {
      if (child.exitCode === null) await new Promise(resolve => {child.once('exit', resolve); child.stdin.end();});
    },
  };
}

function result(message) {
  assert.equal(message.error, undefined);
  assert.notEqual(message.result.isError, true, JSON.stringify(message.result));
  return JSON.parse(message.result.content[0].text);
}

function picture(message) {
  const content = message.result.content.find(item => item.type === 'image');
  assert.ok(content, 'actual MCP image block must be returned');
  assert.equal(content.mimeType, 'image/png');
  const png = Buffer.from(content.data, 'base64');
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  return png;
}

test('sparse MCP edits preserve omitted marks, scientific anchors, pixels and original request recovery', async () => {
  const f = fixture(); let c = client(f.workspace);
  try {
    const sourceBefore = readFileSync(f.source);
    const initialized = await c.rpc('initialize', {protocolVersion:'2024-11-05', capabilities:{}, clientInfo:{name:'sparse-edit-trial', version:'1'}});
    assert.ok(initialized.result.serverInfo);
    const catalog = (await c.rpc('tools/list')).result.tools;
    const schema = catalog.find(tool => tool.name === 'image_annotate').inputSchema;
    assert.ok(schema.properties.updates);
    assert.deepEqual(schema.properties.updates.items.required, ['annotation_id']);
    const opened = result(await c.tool('image_open', {source_path:f.source, request_id:'sparse-open'}));
    const frame = result(await c.tool('image_frame', {object_id:opened.object_id, frame_index:0, request_id:'sparse-frame'}));
    const view = result(await c.tool('image_preview', {object_id:frame.object_id, max_size:96, upscale:true, request_id:'sparse-view'}));
    const markedMessage = await c.tool('image_annotate', {object_id:view.object_id, request_id:'sparse-original', annotations:[
      {annotation_id:'candidate-a', kind:'arrow', coordinates:[3,3,20,10], coordinate_space:'source_pixels', source_object_id:frame.object_id, status:'hypothesized'},
      {annotation_id:'keep-b', kind:'point', coordinates:[40,25], coordinate_space:'source_pixels', source_object_id:frame.object_id, status:'user_confirmed'},
    ]});
    const marked = result(markedMessage);
    const originalPNG = picture(markedMessage);
    const originalManifest = readFileSync(marked.manifest_path);
    const args = {object_id:marked.object_id, request_id:'saved-sparse-update', updates:[
      {annotation_id:'candidate-a', coordinates:[4,4,22,11], text:'user-corrected candidate', color:'orange'},
    ]};
    const changedMessage = await c.tool('image_annotate', args);
    const changed = result(changedMessage); const changedPNG = picture(changedMessage);
    assert.notDeepEqual(changedPNG, originalPNG, 'changed coordinates/text must change actual image bytes');
    assert.equal(changed.annotation_edit_mode, 'update');
    assert.equal(changed.scientific_data_changed, false);
    assert.equal(changed.annotations[0].status, 'hypothesized', 'orange does not confirm a phase');
    assert.deepEqual(changed.annotations[0].anchor, {coordinate_space:'source_pixels', source_object_id:frame.object_id, coordinates:[4,4,22,11]});
    assert.deepEqual(changed.annotations[1], marked.annotations[1]);
    assert.deepEqual(readFileSync(marked.manifest_path), originalManifest);
    const decoded = spawnSync(python, ['-c',
      "import sys,numpy as np; from PIL import Image; a=np.asarray(Image.open(sys.argv[1]).convert('RGB')); b=np.asarray(Image.open(sys.argv[2]).convert('RGB')); assert a.shape==b.shape; cyan=(69,232,255); orange=(255,140,50); assert np.any(np.all(a==cyan,axis=2)); assert not np.any(np.all(b==cyan,axis=2)); assert np.any(np.all(b==orange,axis=2)); assert np.array_equal(a[45:60,75:90],b[45:60,75:90])",
      marked.image_path, changed.image_path], {encoding:'utf8'});
    assert.equal(decoded.status, 0, 'independent PNG decoding must see the revised arrow and untouched second marker: ' + decoded.stderr);
    const resized = result(await c.tool('image_preview', {object_id:changed.object_id, max_size:192, request_id:'sparse-resize'}));
    assert.deepEqual(resized.annotations[0].anchor, changed.annotations[0].anchor);
    assert.deepEqual(resized.annotations[1].anchor, marked.annotations[1].anchor);
    const destination = path.join(f.directory, 'export');
    result(await c.tool('image_export', {object_id:changed.object_id, output_dir:destination, request_id:'sparse-export'}));
    assert.deepEqual(readFileSync(path.join(destination, 'data.npy')), readFileSync(frame.array_path));
    assert.deepEqual(readFileSync(path.join(destination, 'preview.png')), changedPNG);
    const manifest = JSON.parse(readFileSync(path.join(destination, 'manifest.json')));
    assert.deepEqual(manifest.display_object.annotations, changed.annotations);
    await c.close(); c = client(f.workspace);
    const recoveredMessage = await c.tool('image_result', {request_id:'saved-sparse-update'});
    assert.equal(result(recoveredMessage).object_id, changed.object_id);
    assert.deepEqual(picture(recoveredMessage), changedPNG);
    assert.equal(result(await c.tool('image_annotate', args)).object_id, changed.object_id);
    assert.equal((await c.tool('image_annotate', {...args, updates:[{annotation_id:'candidate-a', text:'conflict'}]})).result.isError, true);
    assert.deepEqual(readFileSync(f.source), sourceBefore);
  } finally {await c.close(); rmSync(f.directory, {recursive:true, force:true});}
});

test('sparse MCP FFT moves retain original frequencies and full complex export; identity changes refuse', async () => {
  const f = fixture(); const c = client(f.workspace);
  try {
    const opened = result(await c.tool('image_open', {source_path:f.source, request_id:'frequency-open'}));
    const frame = result(await c.tool('image_frame', {object_id:opened.object_id, frame_index:1, request_id:'frequency-frame'}));
    const fft = result(await c.tool('image_fft', {object_id:frame.object_id, rect:[0,0,40,20], request_id:'frequency-fft'}));
    const complexBefore = readFileSync(fft.array_path);
    const marked = result(await c.tool('image_annotate', {object_id:fft.object_id, request_id:'frequency-mark', annotations:[
      {annotation_id:'peak-a', kind:'point', coordinates:[.1,.1], coordinate_space:'frequency_cycles_per_pixel', source_object_id:fft.object_id, status:'hypothesized'},
    ]}));
    const parentBefore = readFileSync(marked.manifest_path);
    const invalid = [
      {updates:[]}, {updates:[{annotation_id:'missing', text:'x'}]},
      {updates:[{annotation_id:'peak-a'}]},
      {updates:[{annotation_id:'peak-a', text:'a'},{annotation_id:'peak-a', text:'b'}]},
      {updates:[{annotation_id:'peak-a', coordinates:[2,2]}]},
      {updates:[{annotation_id:'peak-a', text:'x'}], annotations:[]}, {},
    ];
    for (const [index, fields] of invalid.entries()) {
      const reply = await c.tool('image_annotate', {object_id:marked.object_id, request_id:'invalid-' + index, ...fields});
      assert.ok(reply.error || reply.result?.isError, JSON.stringify(fields));
    }
    for (const field of ['kind','coordinate_space','source_object_id','anchor']) {
      const reply = await c.tool('image_annotate', {object_id:marked.object_id, request_id:'identity-' + field,
        updates:[{annotation_id:'peak-a', [field]:'changed'}]});
      assert.equal(reply.error?.code, -32602, field + ' must fail strict MCP schema');
    }
    assert.deepEqual(readFileSync(marked.manifest_path), parentBefore);
    const movedMessage = await c.tool('image_annotate', {object_id:marked.object_id, request_id:'frequency-move',
      updates:[{annotation_id:'peak-a', coordinates:[.15,.05], text:'revised peak'}]});
    const moved = result(movedMessage); picture(movedMessage);
    assert.deepEqual(moved.annotations[0].anchor, {coordinate_space:'frequency_cycles_per_pixel', source_object_id:fft.object_id, coordinates:[.15,.05]});
    const destination = path.join(f.directory, 'frequency-export');
    result(await c.tool('image_export', {object_id:moved.object_id, output_dir:destination, request_id:'frequency-export'}));
    assert.deepEqual(readFileSync(path.join(destination, 'data.npy')), complexBefore);
    assert.deepEqual(readFileSync(fft.array_path), complexBefore);
    const retracted = result(await c.tool('image_annotate', {object_id:moved.object_id, request_id:'frequency-retract', updates:[{annotation_id:'peak-a', status:'retracted'}]}));
    assert.equal(retracted.annotations[0].status, 'retracted');
    assert.deepEqual(retracted.annotations[0].anchor, moved.annotations[0].anchor);
  } finally {await c.close(); rmSync(f.directory, {recursive:true, force:true});}
});
