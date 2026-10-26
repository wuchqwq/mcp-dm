// Actual registry-backed stdio MCP and independent scientific workers.
// This synthetic contract does not execute DM or establish model/browser viewing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, readdirSync, rmSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DM_STRUCTURE_PYTHON || process.env.DM_TEST_PYTHON || 'python';
const optional = {skip: !process.env.DM_STRUCTURE_PYTHON && 'Set DM_STRUCTURE_PYTHON to the independent image/ASE/diffsims environment'};
const hash = filename => createHash('sha256').update(readFileSync(filename)).digest('hex');
const closeTo = (actual, expected, tolerance = 1e-12) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);

function environment(folder) {
  const env = {...process.env, DM_MCP_BACKEND: 'images', DM_MCP_DISABLED_MODULES: '',
    DM_IMAGE_WORKSPACE: path.join(folder, 'images'), DM_STRUCTURE_WORKSPACE: path.join(folder, 'structures'),
    DM_IMAGE_PYTHON: python, DM_STRUCTURE_PYTHON: python};
  delete env.DM_NATIVE_SESSION;
  return env;
}

function client(env) {
  const child = spawn(process.execPath, [path.join(root, 'server.mjs')],
    {env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
  const pending = new Map();
  let next = 1, buffer = '', stderr = '';
  child.stderr.on('data', part => { stderr = (stderr + part).slice(-16384); });
  child.stdin.on('error', () => {});
  function failPending(error) {
    for (const item of pending.values()) { clearTimeout(item.timer); item.reject(error); }
    pending.clear();
  }
  child.once('error', failPending);
  child.once('exit', () => failPending(Error(`MCP exited before a response: ${stderr}`)));
  child.stdout.on('data', part => {
    buffer += part;
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      let reply;
      try { reply = JSON.parse(buffer.slice(0, end)); }
      catch (error) { failPending(error); return; }
      buffer = buffer.slice(end + 1);
      const item = pending.get(reply.id);
      if (item) { pending.delete(reply.id); clearTimeout(item.timer); item.resolve(reply); }
    }
  });
  function rpc(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = next++;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(Error(`MCP response deadline: ${stderr}`));
      }, 180000);
      pending.set(id, {resolve, reject, timer});
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    });
  }
  return {
    rpc,
    initialize: () => rpc('initialize', {protocolVersion: '2024-11-05', capabilities: {},
      clientInfo: {name: 'registry-cross-science-contract', version: '1'}}),
    raw: (name, args) => rpc('tools/call', {name, arguments: args}),
    async tool(name, args) {
      const reply = await rpc('tools/call', {name, arguments: args});
      assert.equal(reply.error, undefined, JSON.stringify(reply));
      assert.notEqual(reply.result.isError, true, JSON.stringify(reply));
      return {data: JSON.parse(reply.result.content.find(part => part.type === 'text').text),
        content: reply.result.content};
    },
    async close() {
      if (child.exitCode !== null) return;
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { child.kill(); reject(Error('Owned MCP server did not exit')); }, 10000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
        child.stdin.end();
      });
    },
  };
}

function picture(reply) {
  const image = reply.content.find(part => part.type === 'image' && part.mimeType === 'image/png');
  assert.ok(image, 'Actual MCP image content must accompany the text metadata');
  const png = Buffer.from(image.data, 'base64');
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.ok(png.readUInt32BE(16) > 0 && png.readUInt32BE(20) > 0);
  assert.deepEqual(png, readFileSync(reply.data.image_path));
}

function external(data, family) {
  assert.equal(data.backend, `external-${family}-workspace`);
  assert.equal(data.dm_called, false);
  assert.match(family === 'image' ? data.computation : data.computation_source, /external/);
  assert.match(data.software_provenance.numpy, /^\d+\./);
  if (family === 'structure') assert.match(data.software_provenance.ase, /^\d+\./);
}

function makeInputs(tiff, cif) {
  const script = [
    'import sys,numpy as np,tifffile',
    'from ase.build import bulk',
    'from ase.io import write',
    'y,x=np.indices((48,48))',
    'a=1000+80*np.cos(2*np.pi*x/4)+60*np.cos(2*np.pi*y/4)+40*np.cos(2*np.pi*(x+y)/4)+20*np.cos(2*np.pi*(x-y)/4)',
    "tifffile.imwrite(sys.argv[1],a.round().astype(np.uint16),photometric='minisblack',metadata=None)",
    "write(sys.argv[2],bulk('Cu','fcc',a=4,cubic=True),format='cif')",
  ].join('\n');
  const result = spawnSync(python, ['-B', '-c', script, tiff, cif], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr);
}

test('registered image and structure tools preserve one revisable scientific task through actual MCP', optional, async t => {
  const folder = mkdtempSync(path.join(tmpdir(), 'registry-science-'));
  const env = environment(path.join(folder, 'workspace'));
  const tiff = path.join(folder, 'periodic.tiff'), cif = path.join(folder, 'copper.cif');
  const fftArgs = {rect: [8, 4, 40, 36], window: 'none', subtract_mean: true, max_size: 64, request_id: 'local-fft'};
  let c, completed = false;
  try {
    // Registry metadata is queried internally; no extra MCP tool or probe is needed.
    const runtime = createServerRuntime({env});
    try {
      for (const [name, backend] of [['image_fft', 'external-image-workspace'], ['structure_simulate', 'external-structure-workspace']]) {
        const contract = runtime.registry.describe(name);
        assert.equal(contract.backend, backend);
        assert.equal(contract.effects.sourceMutation, false);
        assert.equal(contract.effects.requestId, 'required');
        assert.equal(contract.availability.runtimeQualification, 'not_probed');
      }
      assert.equal(existsSync(env.DM_IMAGE_WORKSPACE), false);
      assert.equal(existsSync(env.DM_STRUCTURE_WORKSPACE), false);
    } finally { await runtime.close(); }

    makeInputs(tiff, cif);
    const sourceHash = hash(tiff), structureHash = hash(cif);
    c = client(env);
    await c.initialize();
    const tools = (await c.rpc('tools/list')).result.tools;
    const names = tools.map(tool => tool.name);
    assert.equal(new Set(names).size, names.length);
    for (const name of ['image_open', 'image_calibrate', 'image_fft', 'image_remeasure', 'structure_orient', 'structure_simulate', 'structure_register', 'structure_compare'])
      assert.ok(names.includes(name), name);
    assert.ok(!names.includes('dm_status'));
    assert.ok(!names.some(name => name.startsWith('tool_registry')));

    const source = (await c.tool('image_open', {source_path: tiff, source_kind: 'tiff', request_id: 'open'})).data;
    const frame = (await c.tool('image_frame', {object_id: source.object_id, frame_index: 0, request_id: 'frame'})).data;
    const pixel = (await c.tool('image_measure', {object_id: frame.object_id, points: [[8, 4], [11, 8]], request_id: 'pixel-only'})).data;
    assert.equal(pixel.distance_pixels, 5);
    assert.equal(pixel.physical_distance, null);
    assert.equal(pixel.physical_angle, false);
    const calibrated = (await c.tool('image_calibrate', {object_id: frame.object_id, scope: 'image',
      xy_scale: {x: .05, y: -.05, unit: 'nm'}, source_text: 'Synthetic declared signed XY, not an experimental scale', request_id: 'scale'})).data;
    fftArgs.object_id = calibrated.object_id;
    const fftReply = await c.tool('image_fft', fftArgs), fft = fftReply.data;
    picture(fftReply); external(fft, 'image');
    assert.deepEqual(fft.source_rect_xyxy, fftArgs.rect);
    assert.deepEqual(fft.shape_yx, [32, 32]);
    assert.equal(fft.window, 'none'); assert.equal(fft.subtract_mean, true); assert.equal(fft.removed_mean, 1000);
    assert.equal(fft.frequency_unit, 'cycles/pixel'); assert.equal(fft.physical_frequency_unit, 'cycles/nm');
    const fftHash = hash(fft.array_path);
    const peaks = [[.25, 0], [0, -.25], [.25, -.25]], measurements = [];
    for (let i = 0; i < peaks.length; i++) {
      const measured = (await c.tool('image_measure', {object_id: fft.object_id, coordinate_space: 'frequency_cycles_per_pixel',
        points: [[0, 0], peaks[i]], request_id: `peak-${i}`})).data;
      closeTo(measured.physical_vector_xy[0], peaks[i][0] / .05);
      closeTo(measured.physical_vector_xy[1], peaks[i][1] / -.05);
      measurements.push(measured);
    }
    closeTo(measurements[0].d_spacing, .2); assert.equal(measurements[0].d_spacing_unit, 'nm');

    const structure = (await c.tool('structure_open', {source_path: cif, request_id: 'cif'})).data;
    const orientation = (await c.tool('structure_orient', {object_id: structure.object_id, zone_axis_uvw: [0, 0, 1],
      in_plane_direction_uvw: [1, 0, 0], request_id: 'zone'})).data;
    const simulatedReply = await c.tool('structure_simulate', {object_id: structure.object_id, orientation_id: orientation.object_id,
      voltage_kv: 200, reciprocal_radius_inv_angstrom: 1.1, max_excitation_error_inv_angstrom: .02, size: 64, request_id: 'simulation'});
    const simulation = simulatedReply.data;
    picture(simulatedReply); external(simulation, 'structure');
    assert.match(simulation.engine, /^diffsims\./);
    assert.equal(simulation.software_provenance.diffsims, '0.7.0');
    assert.equal(simulation.reflections.reciprocal_convention, 'cycles_per_angstrom_no_2pi');
    assert.equal(simulation.phase_identified, false);

    const registrationArgs = {object_id: simulation.object_id, current_image_object_id: fft.object_id,
      measurement_paths: measurements.map(row => row.manifest_path),
      fit_correspondences: [{measurement_index: 0, hkl: [2, 0, 0]}, {measurement_index: 1, hkl: [0, 2, 0]}],
      validation_correspondences: [{measurement_index: 2, hkl: [2, 2, 0]}],
      screen_axes: {flip_y: false, basis: 'Signed source calibration already supplies the fixed common laboratory axes'},
      confirmation: {source: 'synthetic_fixture', source_text: 'Predeclared analytic periodic fixture; no experimental confirmation claim'},
      experimental_kind: 'real_space_fft', max_residual_inv_angstrom: 1e-12, request_id: 'registration'};
    const registration = (await c.tool('structure_register', registrationArgs)).data;
    assert.equal(registration.registration.scale, 1); assert.deepEqual(registration.registration.translation_inv_angstrom, [0, 0]);
    assert.equal(registration.fit_evidence.length, 2); assert.equal(registration.validation_evidence.length, 1);
    assert.equal(registration.held_out_validation_passed, true);
    const compareArgs = {object_id: simulation.object_id, current_image_object_id: fft.object_id,
      measurement_paths: registrationArgs.measurement_paths, registration_object_id: registration.object_id,
      experimental_kind: 'real_space_fft', max_residual_inv_angstrom: 1e-12, request_id: 'comparison'};
    const first = (await c.tool('structure_compare', compareArgs)).data;
    assert.equal(first.matched.length, 3); assert.ok(first.unmatched_simulated.length > 0);
    assert.equal(first.intensity_comparison_performed, false); assert.equal(first.phase_identified, false);
    assert.equal(first.registration.proposal_object_id, registration.object_id);
    assert.equal(first.comparison_is_not_new_independent_validation, true);
    assert.match(first.registration.parameter_source, /saved constrained/);

    const revised = (await c.tool('image_calibrate', {object_id: fft.object_id, scope: 'image',
      xy_scale: {x: .1, y: -.05, unit: 'nm'}, source_text: 'Synthetic anisotropic scale correction; retained independently of the candidate CIF', request_id: 'scale-revised'})).data;
    assert.equal(revised.xy_calibration.revision, 2);
    assert.equal(revised.scientific_data_changed, false); assert.equal(revised.raw_metadata_modified, false);
    assert.deepEqual(revised.files_sha256, {}); assert.equal(hash(fft.array_path), fftHash);
    const stale = await c.raw('structure_compare', {...compareArgs, current_image_object_id: revised.object_id, request_id: 'reject-old-scale'});
    assert.equal(stale.result.isError, true); assert.match(stale.result.content[0].text, /remeasure/);
    const updated = [];
    for (let i = 0; i < measurements.length; i++) updated.push((await c.tool('image_remeasure', {
      object_id: revised.object_id, measurement_object_id: measurements[i].object_id,
      ...(i === 0 ? {points: [[0, 0], [.3125, 0]], source_text: 'Synthetic corrected first peak; original coordinates remain historical'} : {}),
      request_id: `revised-peak-${i}`})).data);
    closeTo(updated[0].physical_vector_xy[0], 3.125);
    assert.deepEqual(updated[1].points, measurements[1].points);
    const oldFit = await c.raw('structure_compare', {...compareArgs, current_image_object_id: revised.object_id,
      measurement_paths: updated.map(row => row.manifest_path), request_id: 'reject-old-fit'});
    assert.equal(oldFit.result.isError, true); assert.match(oldFit.result.content[0].text, /different points/);
    const revisedRegistration = (await c.tool('structure_register', {...registrationArgs, current_image_object_id: revised.object_id,
      measurement_paths: updated.map(row => row.manifest_path), request_id: 'registration-revised'})).data;
    assert.equal(revisedRegistration.held_out_validation_passed, false);
    assert.equal(revisedRegistration.registration.scale, 1);
    const second = (await c.tool('structure_compare', {...compareArgs, current_image_object_id: revised.object_id,
      measurement_paths: updated.map(row => row.manifest_path), registration_object_id: revisedRegistration.object_id,
      previous_comparison_id: first.object_id, request_id: 'comparison-revised'})).data;
    assert.equal(second.analysis_revision, 2); assert.equal(second.analysis_root_id, first.object_id);
    assert.equal(second.unchanged_scientific_array_reused, true); assert.equal(second.phase_identified, false);
    assert.equal(second.all_experimental_reflections_matched_within_tolerance, false);

    const viewReply = await c.tool('image_preview', {object_id: revised.object_id, gamma: .9, spectrum_axes: true,
      max_size: 256, upscale: true, request_id: 'revised-view'});
    const view = viewReply.data;
    picture(viewReply); assert.equal(view.fft_recomputed, false); assert.equal(hash(view.array_path), fftHash);
    const output = path.join(folder, 'new-export');
    const exported = (await c.tool('image_export', {object_id: view.object_id, output_dir: output, request_id: 'export'})).data;
    assert.equal(exported.dm_save_as_called, false); assert.equal(hash(path.join(output, 'data.npy')), fftHash);
    const manifest = JSON.parse(readFileSync(path.join(output, 'manifest.json')));
    assert.equal(manifest.xy_calibration.revision, 2); assert.equal(manifest.scientific_NPY_is_not_display_PNG, true);

    // Independent literal DFT reference; no second FFT implementation/oracle is invoked.
    const oracle = spawnSync(python, ['-B', '-c', [
      'import sys,numpy as np,tifffile',
      'a=tifffile.imread(sys.argv[1]); y,x=np.indices((48,48)); q=np.array([1,0,-1,0])',
      'expected=1000+80*q[x%4]+60*q[y%4]+40*q[(x+y)%4]+20*q[(x-y)%4]',
      'np.testing.assert_array_equal(a,expected.astype(np.uint16))',
      's=np.load(sys.argv[2],allow_pickle=False); assert s.shape==(32,32) and s.dtype==np.complex128',
      'f=np.zeros((32,32),dtype=np.complex128)',
      'pairs=[((16,24),40960),((16,8),40960),((24,16),30720),((8,16),30720),((24,24),20480),((8,8),20480),((8,24),10240),((24,8),10240)]',
      'for ij,v in pairs: f[ij]=v',
      'np.testing.assert_allclose(s,f,rtol=0,atol=1e-9)',
      'np.testing.assert_array_equal(np.load(sys.argv[3],allow_pickle=False),s)',
    ].join('\n'), tiff, fft.array_path, path.join(output, 'data.npy')], {encoding: 'utf8'});
    assert.equal(oracle.status, 0, oracle.stderr);

    await c.close(); c = client(env); await c.initialize();
    const recovered = (await c.tool('image_result', {request_id: 'local-fft'})).data;
    assert.equal(recovered.object_id, fft.object_id); assert.equal(hash(recovered.array_path), fftHash);
    assert.equal(recovered.xy_calibration.revision, 1);
    const recoveredFit = (await c.tool('structure_result', {request_id: 'registration'})).data;
    assert.equal(recoveredFit.object_id, registration.object_id); assert.equal(recoveredFit.held_out_validation_passed, true);
    assert.equal((await c.tool('image_fft', fftArgs)).data.object_id, fft.object_id);
    const conflict = await c.raw('image_fft', {...fftArgs, rect: [4, 4, 36, 36]});
    assert.equal(conflict.result.isError, true);
    const fftJournals = readdirSync(path.join(env.DM_IMAGE_WORKSPACE, 'requests')).map(filename =>
      JSON.parse(readFileSync(path.join(env.DM_IMAGE_WORKSPACE, 'requests', filename))))
      .filter(record => record.parameters?.action === 'fft');
    assert.equal(fftJournals.length, 1, 'Scale, point, display and recovery must not submit another FFT');
    assert.equal(hash(fft.array_path), fftHash); assert.equal(hash(tiff), sourceHash); assert.equal(hash(cif), structureHash);
    completed = true;
  } finally {
    try { if (c) await c.close(); }
    catch (error) { completed = false; throw error; }
    finally {
      if (completed) rmSync(folder, {recursive: true, force: true});
      else t.diagnostic(`Synthetic fixture retained for failure review: ${folder}`);
    }
  }
});
