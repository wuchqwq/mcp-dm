// Actual stdio + existing NumPy/ASE/diffsims tools, with current-reference CAS.
// Synthetic science only; no DM, browser, human/model viewing or phase proof.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DM_STRUCTURE_PYTHON || process.env.DM_TEST_PYTHON || 'python';
const optional = {skip: !process.env.DM_STRUCTURE_PYTHON && 'Set DM_STRUCTURE_PYTHON to the independent image/ASE/diffsims environment', timeout: 360000};
const hash = filename => createHash('sha256').update(readFileSync(filename)).digest('hex');
const json = filename => JSON.parse(readFileSync(filename, 'utf8'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const closeTo = (value, expected, tolerance = 1e-12) => assert.ok(Math.abs(value - expected) <= tolerance, `${value} differs from ${expected}`);
async function until(predicate, label, timeoutMs = 30000) {
  const deadline = performance.now() + timeoutMs;
  while (!predicate()) {if (performance.now() >= deadline) throw Error('Timed out waiting for ' + label); await sleep(15);}
}
function client(bootstrap) {
  const child = spawn(process.execPath, [bootstrap], {windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  const pending = new Map(), replies = [], errors = [];
  let next = 0, buffer = '', stderr = '';
  const fail = error => {for (const item of pending.values()) {clearTimeout(item.timer); item.reject(error);} pending.clear();};
  child.stderr.on('data', part => {stderr = (stderr + part).slice(-16384);}); child.stdin.on('error', () => {});
  child.once('error', fail); child.once('exit', () => fail(Error('Owned Context MCP exited: ' + stderr)));
  child.stdout.on('data', part => {
    buffer += part; let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1); let reply;
      try {reply = JSON.parse(line);} catch (error) {errors.push(line); fail(error); continue;}
      replies.push(reply); const item = pending.get(reply.id);
      if (item) {pending.delete(reply.id); clearTimeout(item.timer); item.resolve(reply);}
    }
  });
  function rpc(method, params = {}) {
    const id = ++next; const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {pending.delete(id); reject(Error('Context test MCP response deadline: ' + stderr));}, 180000);
      pending.set(id, {resolve, reject, timer}); child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    }); promise.catch(() => {}); return {id, promise};
  }
  return {replies, errors, rpc: (method, params) => rpc(method, params).promise,
    raw: (name, args) => rpc('tools/call', {name, arguments: args}),
    async tool(name, args) {
      const response = await rpc('tools/call', {name, arguments: args}).promise;
      assert.equal(response.error, undefined, JSON.stringify(response));
      assert.notEqual(response.result?.isError, true, JSON.stringify(response));
      return {data: JSON.parse(response.result.content.find(part => part.type === 'text').text), content: response.result.content};
    },
    async cancel(handle) {
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', method: 'notifications/cancelled', params: {requestId: handle.id}}) + '\n');
      const item = pending.get(handle.id);
      if (item) {pending.delete(handle.id); clearTimeout(item.timer); item.resolve({testWaitAbandoned: true});}
      await rpc('ping').promise;
    },
    async close() {
      if (child.exitCode !== null) return;
      await new Promise((resolve, reject) => {const timer = setTimeout(() => {child.kill(); reject(Error('Owned Context MCP close deadline'));}, 10000);
        child.once('exit', () => {clearTimeout(timer); resolve();}); child.stdin.end();});
      assert.deepEqual(errors, []);
    }};
}
function picture(response) {
  const image = response.content.find(part => part.type === 'image'); assert.ok(image, 'actual MCP image content');
  assert.equal(image.mimeType, 'image/png'); assert.deepEqual(Buffer.from(image.data, 'base64'), readFileSync(response.data.image_path));
}
function fixture(t) {
  const directory = mkdtempSync(path.join(tmpdir(), 'context-science-mcp-'));
  const imageWorkspace = path.join(directory, 'images'), structureWorkspace = path.join(directory, 'structures'), contextDirectory = path.join(directory, 'contexts');
  const tiff = path.join(directory, 'periodic.tiff'), cif = path.join(directory, 'copper.cif');
  const made = spawnSync(python, ['-B', '-c', [
    'import sys,numpy as np,tifffile', 'from ase.build import bulk', 'from ase.io import write',
    'y,x=np.indices((48,48))', 'a=1000+80*np.cos(2*np.pi*x/4)+60*np.cos(2*np.pi*y/4)+40*np.cos(2*np.pi*(x+y)/4)+20*np.cos(2*np.pi*(x-y)/4)',
    "tifffile.imwrite(sys.argv[1],a.round().astype(np.uint16),photometric='minisblack',metadata=None)",
    "write(sys.argv[2],bulk('Cu','fcc',a=4,cubic=True),format='cif')"].join('\n'), tiff, cif], {encoding: 'utf8', windowsHide: true});
  assert.equal(made.status, 0, made.stderr);
  const controlledWorker = path.join(directory, 'controlled_structure.py');
  writeFileSync(controlledWorker,
    `import json,os,pathlib,sys,time\nsys.path.insert(0,${JSON.stringify(root)})\nfrom crystallography import structure_tools as science\nfrom tools import structure_worker as module\nfolder=pathlib.Path(${JSON.stringify(directory)})\noriginal=science.StructureWorkspace.action\n` +
    `def controlled(self,request):\n rid=request['request_id']\n with (folder/'structure-actions.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps({'request_id':rid,'action':request['action']})+'\\n')\n if rid=='long-simulation':\n  saved=json.loads((self.root/'requests'/(rid+'.json')).read_text(encoding='utf-8'))\n  assert saved['state']=='prepared'\n  (folder/'long-accepted').write_text(str(os.getpid()),encoding='ascii')\n  deadline=time.monotonic()+120\n  while not (folder/'release-long').is_file():\n   if time.monotonic()>deadline: raise RuntimeError('Test-only simulation barrier deadline')\n   time.sleep(.01)\n return original(self,request)\nscience.StructureWorkspace.action=controlled\nraise SystemExit(module.main())\n`);
  const href = relative => pathToFileURL(path.join(root, relative)).href, bootstrap = path.join(directory, 'server.mjs');
  writeFileSync(bootstrap,
    `import {startMcpServer} from ${JSON.stringify(href('server.mjs'))};\nimport {ToolRegistry} from ${JSON.stringify(href('lib/runtime/tool_registry.mjs'))};\n` +
    `import {ExecutionCoordinator} from ${JSON.stringify(href('lib/runtime/execution_coordinator.mjs'))};\nimport {ImageWorkspace} from ${JSON.stringify(href('lib/image_workspace.mjs'))};\nimport {StructureWorkspace} from ${JSON.stringify(href('lib/structure_workspace.mjs'))};\n` +
    `import {createImageModule} from ${JSON.stringify(href('lib/tools/image_module.mjs'))};\nimport {createStructureModule} from ${JSON.stringify(href('lib/tools/structure_module.mjs'))};\nimport {createAnalysisContextModule} from ${JSON.stringify(href('lib/tools/analysis_context_module.mjs'))};\nimport {createExecutionModule} from ${JSON.stringify(href('lib/tools/execution_module.mjs'))};\n` +
    `import {spawn} from 'node:child_process';import {appendFileSync} from 'node:fs';const folder=${JSON.stringify(directory)};\n` +
    `const spawnProcess=(...args)=>{const child=spawn(...args);appendFileSync(folder+'/processes.jsonl',JSON.stringify({event:'spawn',pid:child.pid})+'\\n');child.once('close',()=>appendFileSync(folder+'/processes.jsonl',JSON.stringify({event:'close',pid:child.pid})+'\\n'));return child;};\n` +
    `const coordinator=new ExecutionCoordinator({capacity:{work:2,query:1}});const image=new ImageWorkspace({workspace:${JSON.stringify(imageWorkspace)},python:${JSON.stringify(python)},coordinator,spawnProcess});\nconst structure=new StructureWorkspace({workspace:${JSON.stringify(structureWorkspace)},python:${JSON.stringify(python)},workerPath:${JSON.stringify(controlledWorker)},coordinator,spawnProcess});\n` +
    `const providers={image,structure};const registry=new ToolRegistry().register(createImageModule({imageWorkspace:image})).register(createStructureModule({structureWorkspace:structure})).register(createAnalysisContextModule({directory:${JSON.stringify(contextDirectory)},providers})).register(createExecutionModule({coordinator,providers:{image:image.requestScope,structure:structure.requestScope}})).seal();\nstartMcpServer({runtime:{registry,instructions:registry.instructions(),close:()=>registry.close()}});\n`);
  const clients = [], file = name => path.join(directory, name);
  const rows = name => existsSync(file(name)) ? readFileSync(file(name), 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const release = () => writeFileSync(file('release-long'), 'release');
  let completed = false;
  t.after(async () => {
    release(); await until(() => {const events = rows('processes.jsonl'), closed = new Set(events.filter(row => row.event === 'close').map(row => row.pid));
      return events.filter(row => row.event === 'spawn').every(row => closed.has(row.pid));}, 'all owned Context science workers to close');
    for (const c of clients) await c.close();
    if (completed) rmSync(directory, {recursive: true, force: true}); else t.diagnostic('Retained synthetic failure fixture: ' + directory);
  });
  return {directory, imageWorkspace, structureWorkspace, contextDirectory, tiff, cif, file, rows, release,
    createClient: () => {const c = client(bootstrap); clients.push(c); return c;}, complete: () => {completed = true;}};
}
const imageRef = object => ({provider: 'image', object_id: object.object_id});
const structureRef = object => ({provider: 'structure', object_id: object.object_id});
const slotEntries = selection => selection === null || selection === undefined ? [] : Array.isArray(selection) ? selection : [selection];
function stateOf(context, role, state) {assert.ok(slotEntries(context.slots[role]).length); assert.ok(slotEntries(context.slots[role]).every(entry => entry.status === state), role + ' should be ' + state);}

test('actual current analysis survives display/scale/point corrections, cancelled long work and client restart without recomputing FFT', optional, async t => {
  const f = fixture(t); let c = f.createClient();
  const sourceHash = hash(f.tiff), structureHash = hash(f.cif), analysisId = 'synthetic-current-task';
  const opened = (await c.tool('image_open', {source_path: f.tiff, request_id: 'open'})).data;
  const frame = (await c.tool('image_frame', {object_id: opened.object_id, frame_index: 0, request_id: 'frame'})).data;
  const calibrated = (await c.tool('image_calibrate', {object_id: frame.object_id, scope: 'image', xy_scale: {x: .05, y: -.05, unit: 'nm'},
    source_text: 'Synthetic signed calibration; no experimental parameter', request_id: 'scale'})).data;
  const fftArgs = {object_id: calibrated.object_id, rect: [8, 4, 40, 36], window: 'none', subtract_mean: true, max_size: 64, request_id: 'local-fft'};
  const fftResponse = await c.tool('image_fft', fftArgs), fft = fftResponse.data; picture(fftResponse);
  const spectrumHash = hash(fft.array_path);
  const created = (await c.tool('analysis_create', {analysis_id: analysisId, request_id: 'context-create', reason: 'Synthetic composable current task'})).data;
  assert.equal(created.backend, 'external-analysis-context'); assert.equal(created.state, 'advanced');
  let current = created.context;
  async function promote(selections, requestId, reason, expectedRevision = current.revision) {
    const response = (await c.tool('analysis_update', {analysis_id: analysisId, expected_revision: expectedRevision,
      request_id: requestId, reason, selections})).data;
    if (response.state === 'advanced') current = response.context;
    return response;
  }
  await promote({experiment: imageRef(frame), fft: imageRef(fft), calibration: imageRef(fft)}, 'select-experiment-fft', 'Bind frame, exact local spectrum and its sourced scale');
  stateOf(current, 'fft', 'active');
  const peaks = [[.25, 0], [0, -.25], [.25, -.25]], measurements = [];
  for (let index = 0; index < peaks.length; index++) {
    const measured = (await c.tool('image_measure', {object_id: fft.object_id, coordinate_space: 'frequency_cycles_per_pixel',
      points: [[0, 0], peaks[index]], request_id: 'peak-' + index})).data;
    closeTo(measured.physical_vector_xy[0], peaks[index][0] / .05); closeTo(measured.physical_vector_xy[1], peaks[index][1] / -.05);
    measurements.push(measured);
  }
  closeTo(measurements[0].d_spacing, .2);
  await promote({points: measurements.map(imageRef), measurements: measurements.map(imageRef)}, 'select-measurements', 'Bind committed measured anchors to original spectrum');
  const reference = (await c.tool('structure_open', {source_path: f.cif, request_id: 'cif'})).data;
  const orientation = (await c.tool('structure_orient', {object_id: reference.object_id, zone_axis_uvw: [0, 0, 1], in_plane_direction_uvw: [1, 0, 0], request_id: 'zone'})).data;
  const simulateArgs = {object_id: reference.object_id, orientation_id: orientation.object_id, voltage_kv: 200,
    reciprocal_radius_inv_angstrom: 1.1, max_excitation_error_inv_angstrom: .02, size: 64};
  const simulationResponse = await c.tool('structure_simulate', {...simulateArgs, request_id: 'simulation'}), simulation = simulationResponse.data;
  picture(simulationResponse); assert.equal(simulation.phase_identified, false);
  await promote({reference: structureRef(reference), orientation: structureRef(orientation), simulation: structureRef(simulation)}, 'select-reference-simulation', 'Use candidate CIF and actual shared-axis kinematic simulation');
  const registrationArgs = {object_id: simulation.object_id, current_image_object_id: fft.object_id, measurement_paths: measurements.map(row => row.manifest_path),
    fit_correspondences: [{measurement_index: 0, hkl: [2, 0, 0]}, {measurement_index: 1, hkl: [0, 2, 0]}],
    validation_correspondences: [{measurement_index: 2, hkl: [2, 2, 0]}],
    screen_axes: {flip_y: false, basis: 'Signed synthetic calibration already supplies known axes'},
    confirmation: {source: 'synthetic_fixture', source_text: 'Predeclared periodic synthetic reference, not experimental confirmation'},
    experimental_kind: 'real_space_fft', max_residual_inv_angstrom: 1e-12};
  const registration = (await c.tool('structure_register', {...registrationArgs, request_id: 'registration'})).data;
  assert.equal(registration.held_out_validation_passed, true); assert.equal(registration.fit_evidence.length, 2); assert.equal(registration.validation_evidence.length, 1);
  const compareArgs = {object_id: simulation.object_id, current_image_object_id: fft.object_id, measurement_paths: registrationArgs.measurement_paths,
    registration_object_id: registration.object_id, experimental_kind: 'real_space_fft', max_residual_inv_angstrom: 1e-12};
  const firstComparison = (await c.tool('structure_compare', {...compareArgs, request_id: 'comparison'})).data;
  assert.equal(firstComparison.matched.length, 3); assert.equal(firstComparison.intensity_comparison_performed, false);
  await promote({registration: structureRef(registration), comparison: structureRef(firstComparison)}, 'select-initial-comparison', 'Select independent held-out comparison evidence');
  const beforeDisplay = structuredClone(current), previewResponse = await c.tool('image_preview', {object_id: fft.object_id, gamma: .8, max_size: 256, spectrum_axes: true, request_id: 'display-only'});
  picture(previewResponse); assert.equal(previewResponse.data.fft_recomputed, false);
  await promote({display: imageRef(previewResponse.data)}, 'select-display-only', 'Display-only gamma change leaves science valid');
  assert.equal(current.fingerprints.measurements, beforeDisplay.fingerprints.measurements);
  stateOf(current, 'measurements', 'active'); stateOf(current, 'registration', 'active'); stateOf(current, 'comparison', 'active');
  const oldRevision = current.revision, oldContext = structuredClone(current);
  const long = c.raw('structure_simulate', {...simulateArgs, request_id: 'long-simulation'});
  await until(() => existsSync(f.file('long-accepted')), 'actual post-fsync long simulation acceptance');
  await c.cancel(long);
  const pending = await c.raw('structure_result', {request_id: 'long-simulation'}).promise;
  assert.equal(pending.result.isError, true); assert.match(pending.result.content[0].text, /INCOMPLETE_REQUEST/);
  const revised = (await c.tool('image_calibrate', {object_id: fft.object_id, scope: 'image', xy_scale: {x: .1, y: -.05, unit: 'nm'},
    source_text: 'Synthetic anisotropic correction independent of candidate structure', request_id: 'scale-revised'})).data;
  assert.equal(revised.scientific_data_changed, false); assert.equal(hash(fft.array_path), spectrumHash);
  await promote({calibration: imageRef(revised)}, 'select-revised-scale', 'User correction stales physical measurements and old fit');
  stateOf(current, 'fft', 'active'); stateOf(current, 'points', 'active');
  for (const role of ['display', 'measurements', 'registration', 'comparison']) stateOf(current, role, 'stale');
  assert.equal(current.slots.fft.ref.objectId, fft.object_id);
  const correctedRevision = current.revision;
  f.release();
  await until(() => {try {return json(path.join(f.structureWorkspace, 'requests', 'long-simulation.json')).state === 'completed';} catch {return false;}}, 'late original simulation completion');
  const lateSimulation = (await c.tool('structure_result', {request_id: 'long-simulation'})).data;
  const late = await promote({simulation: structureRef(lateSimulation)}, 'late-old-basis-simulation', 'Persist late result only if original context is still current', oldRevision);
  assert.equal(late.state, 'historical'); assert.ok(late.proposal);
  assert.equal(late.context.revision, correctedRevision);
  const currentAfterLate = (await c.tool('analysis_read', {analysis_id: analysisId})).data.context;
  assert.equal(currentAfterLate.revision, correctedRevision); assert.equal(currentAfterLate.slots.simulation.ref.objectId, simulation.object_id);
  assert.notEqual(currentAfterLate.slots.simulation.ref.objectId, lateSimulation.object_id);
  assert.equal(c.replies.some(row => row.id === long.id), false, 'cancelled RPC does not receive a late response');
  await c.close(); c = f.createClient();
  current = (await c.tool('analysis_read', {analysis_id: analysisId})).data.context;
  assert.equal(current.revision, correctedRevision); stateOf(current, 'measurements', 'stale'); stateOf(current, 'points', 'active');
  const historicalContext = (await c.tool('analysis_read', {analysis_id: analysisId, revision: oldRevision})).data.context;
  assert.equal(historicalContext.revisionHash, oldContext.revisionHash); stateOf(historicalContext, 'comparison', 'active');
  const recoveredLate = (await c.tool('structure_result', {request_id: 'long-simulation'})).data;
  assert.equal(recoveredLate.object_id, lateSimulation.object_id);
  const recoveredContextMutation = (await c.tool('analysis_read', {analysis_id: analysisId, request_id: 'select-revised-scale'})).data;
  assert.equal(recoveredContextMutation.context.revision, correctedRevision);
  const updated = [];
  for (let index = 0; index < measurements.length; index++) updated.push((await c.tool('image_remeasure', {object_id: revised.object_id, measurement_object_id: measurements[index].object_id,
    ...(index === 0 ? {points: [[0, 0], [.3125, 0]], source_text: 'Synthetic corrected first reflection, original anchor remains historical'} : {}), request_id: 'revised-peak-' + index})).data);
  closeTo(updated[0].physical_vector_xy[0], 3.125); assert.deepEqual(updated[1].points, measurements[1].points);
  await promote({points: updated.map(imageRef), measurements: updated.map(imageRef)}, 'select-remeasured-points', 'Update corrected anchor and physical measurements on unchanged complex spectrum');
  stateOf(current, 'measurements', 'active'); stateOf(current, 'registration', 'stale'); stateOf(current, 'comparison', 'stale');
  const revisedRegistration = (await c.tool('structure_register', {...registrationArgs, current_image_object_id: revised.object_id, measurement_paths: updated.map(row => row.manifest_path), request_id: 'registration-revised'})).data;
  assert.equal(revisedRegistration.held_out_validation_passed, false); assert.equal(revisedRegistration.registration.scale, 1);
  const revisedComparison = (await c.tool('structure_compare', {...compareArgs, current_image_object_id: revised.object_id, measurement_paths: updated.map(row => row.manifest_path),
    registration_object_id: revisedRegistration.object_id, previous_comparison_id: firstComparison.object_id, request_id: 'comparison-revised'})).data;
  assert.equal(revisedComparison.all_experimental_reflections_matched_within_tolerance, false); assert.equal(revisedComparison.unchanged_scientific_array_reused, true);
  await promote({registration: structureRef(revisedRegistration), comparison: structureRef(revisedComparison)}, 'select-revised-comparison', 'Keep valid new geometric comparison including real mismatch');
  stateOf(current, 'comparison', 'active'); assert.equal(revisedComparison.phase_identified, false);
  const finalView = await c.tool('image_preview', {object_id: revised.object_id, gamma: .9, max_size: 256, spectrum_axes: true, upscale: true, request_id: 'final-view'});
  picture(finalView); assert.equal(finalView.data.fft_recomputed, false); assert.equal(hash(finalView.data.array_path), spectrumHash);
  await promote({display: imageRef(finalView.data)}, 'select-final-display', 'Render corrected axes without scientific recomputation');
  stateOf(current, 'measurements', 'active'); stateOf(current, 'comparison', 'active');
  const output = path.join(f.directory, 'new-export');
  await c.tool('image_export', {object_id: finalView.data.object_id, output_dir: output, request_id: 'export'});
  assert.equal(hash(path.join(output, 'data.npy')), spectrumHash); assert.equal(json(path.join(output, 'manifest.json')).xy_calibration.revision, 2);
  const oracle = spawnSync(python, ['-B', '-c', [
    'import sys,numpy as np,tifffile', 'a=tifffile.imread(sys.argv[1]);y,x=np.indices((48,48));q=np.array([1,0,-1,0])',
    'expected=1000+80*q[x%4]+60*q[y%4]+40*q[(x+y)%4]+20*q[(x-y)%4]', 'np.testing.assert_array_equal(a,expected.astype(np.uint16))',
    's=np.load(sys.argv[2],allow_pickle=False);assert s.shape==(32,32) and s.dtype==np.complex128', 'f=np.zeros((32,32),dtype=np.complex128)',
    'pairs=[((16,24),40960),((16,8),40960),((24,16),30720),((8,16),30720),((24,24),20480),((8,8),20480),((8,24),10240),((24,8),10240)]',
    'for ij,v in pairs:f[ij]=v', 'np.testing.assert_allclose(s,f,rtol=0,atol=1e-9)',
    'np.testing.assert_array_equal(np.load(sys.argv[3],allow_pickle=False),s)'].join('\n'), f.tiff, fft.array_path, path.join(output, 'data.npy')], {encoding: 'utf8', windowsHide: true});
  assert.equal(oracle.status, 0, oracle.stderr);
  const fftJournals = readdirSync(path.join(f.imageWorkspace, 'requests')).map(name => json(path.join(f.imageWorkspace, 'requests', name))).filter(record => record.parameters?.action === 'fft');
  assert.equal(fftJournals.length, 1, 'display/scale/point/context/recovery never submits another FFT');
  assert.equal(f.rows('structure-actions.jsonl').filter(row => row.request_id === 'long-simulation').length, 1);
  assert.equal(hash(f.tiff), sourceHash); assert.equal(hash(f.cif), structureHash); assert.equal(hash(fft.array_path), spectrumHash);
  const files = readdirSync(f.contextDirectory, {recursive: true, withFileTypes: true}).filter(entry => entry.isFile());
  assert.ok(files.length > 3); assert.ok(files.every(entry => entry.name.endsWith('.json')), 'Context storage contains only reference/history JSON, not copied scientific arrays');
  f.complete();
});
