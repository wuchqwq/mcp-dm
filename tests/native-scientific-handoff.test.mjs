// Metadata-only regressions. Hand-built Fourier receipts are not DM evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {nativeScientificSemantics, validateNativeDataSnapshot} from '../lib/native_bridge.mjs';
import {handoff, validateSavedSnapshot} from '../tools/native_snapshot_handoff.mjs';
import {fourierFixture, readFixture} from './fixtures/native-operations.mjs';

function fixture(operation = 'REAL', {spatial = false, crop = [0, 0], shape, roi} = {}) {
  const producer = fourierFixture(operation, 77, {spatial});
  const source = structuredClone(producer.image);
  if (crop.some(Boolean) || shape) {
    source.id = 101; source.shape = shape || [3, 6];
    source.dm_dimensions = [...source.shape].reverse(); source.pixels = source.shape[0] * source.shape[1];
    source.calibration.forEach((axis, i) => {
      axis.size = source.dm_dimensions[i]; axis.origin -= crop[i];
      axis.calibrated_value_at_pixel_zero += crop[i] * axis.scale;
    });
  }
  const args = [source.id, ...(roi || [0, 0, source.shape[1], source.shape[0]])];
  const provenance = {operation: source.id === producer.image_id ? operation : 'CROP',
    request_id: source.id === producer.image_id ? 'component-1' : 'crop-1',
    source_image_ids: [source.id === producer.image_id ? 77 : producer.image_id], semantics: 'test-only'};
  const read = readFixture(args, {source, provenance});
  read.scientific_context = {schema_version: 1, status: 'tracked_fourier', original_operation: operation,
    request_id: 'component-1', normalized_args: [77], result_version: 2, result: producer,
    source_offset_xy: crop, postprocessing: []};
  const receipt = {protocol: 'NB2', session: 'a'.repeat(32), id: 'read-1', request_id: 'read-1',
    original_operation: 'READ', normalized_args: args, result_type: 'native_data_snapshot', result_version: 1,
    state: 'completed', host_pid: 123, exec_tid: 10, worker_tid: 20, timings_us: {queue: 0, execute: 1}};
  return {read, args, saved: {...read, native_receipt: receipt}};
}
function temp(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'scientific-handoff-'));
  t.after(() => fs.rmSync(root, {recursive: true})); return root;
}

test('mathematical DC remains zero while both signed native half-bin offsets remain unchanged', () => {
  const {read, args} = fixture(); validateNativeDataSnapshot(read, args);
  const semantics = nativeScientificSemantics(read);
  assert.equal(semantics.domain, 'frequency'); assert.equal(semantics.representation, 'real_component');
  for (const axis of semantics.coordinate_axes) {
    assert.equal(axis.calibrated_value_at_pixel_zero + axis.dc_index_in_roi * axis.scale, 0);
    assert.equal(axis.native_minus_mathematical_zero, -0.5 * axis.scale);
    assert.equal(axis.native_calibrated_value_at_pixel_zero, read.roi_calibration[axis.dm_dimension].calibrated_value_at_pixel_zero);
  }
});

test('crop then READ ROI accumulates offsets, including DC outside a selected region', () => {
  const {read, args} = fixture('IMAG', {crop: [1, 1], shape: [3, 6], roi: [2, 1, 5, 3]});
  validateNativeDataSnapshot(read, args); const semantic = nativeScientificSemantics(read);
  assert.deepEqual(semantic.coordinate_axes.map(a => a.source_index_offset), [3, 2]);
  assert.deepEqual(semantic.coordinate_axes.map(a => a.dc_index_in_roi), [1, 0]);
  const outside = fixture('REAL', {roi: [5, 0, 8, 2]}).read;
  assert.equal(nativeScientificSemantics(outside).coordinate_axes[0].dc_index_in_roi, -1);
});

for (const [operation, representation, phase] of [
  ['REAL', 'real_component', null], ['IMAG', 'imaginary_component', null],
  ['VENDOR_ARG', 'phase_radians', 'radians'], ['VENDOR_NORM', 'squared_magnitude', null],
]) test(`${operation} retains an explicit quantity, not a guessed intensity unit`, () => {
  const semantic = nativeScientificSemantics(fixture(operation).read);
  assert.equal(semantic.representation, representation); assert.equal(semantic.phase_units, phase);
  assert.deepEqual(semantic.transform_signs, {forward: '+', inverse: '-'});
});

test('inverse component remains spatial with explicit no-restoration policy', () => {
  const {read, args} = fixture('REAL', {spatial: true, roi: [1, 1, 4, 3]});
  validateNativeDataSnapshot(read, args); const semantic = nativeScientificSemantics(read);
  assert.equal(semantic.domain, 'spatial'); assert.equal(semantic.inverse_restores_source_origin, false);
  assert.equal(semantic.coordinate_axes[0].dc_index_in_roi, null);
  assert.equal(semantic.coordinate_axes[0].calibrated_value_at_pixel_zero, read.roi_calibration[0].calibrated_value_at_pixel_zero);
});

test('postprocessing keeps coordinate domain but does not relabel square(phase) as a phase in radians', () => {
  const {read} = fixture('VENDOR_ARG', {crop: [1, 0], shape: [4, 6]});
  read.scientific_context.postprocessing = ['GMSImageProcessing::Square'];
  const semantic = nativeScientificSemantics(read);
  assert.equal(semantic.domain, 'frequency'); assert.equal(semantic.representation, 'processed_scalar');
  assert.equal(semantic.original_representation, 'phase_radians'); assert.equal(semantic.phase_units, null);
});

test('old known Fourier receipts fail scientific export before any output is created', t => {
  const root = temp(t), {saved} = fixture(); delete saved.scientific_context;
  const file = path.join(root, 'read.json'); fs.writeFileSync(file, JSON.stringify(saved));
  assert.throws(() => handoff({workspace: root, output: 'capture', requestId: 'save-1', snapshot: file}), /SCIENTIFIC_CONTEXT_REQUIRED/);
  assert.deepEqual(fs.readdirSync(root), ['read.json']);
});

test('raw or mixed/untracked lineage remains explicitly unknown, never inferred from reciprocal units', () => {
  const {read} = fixture(); read.source_provenance = null; delete read.scientific_context;
  assert.equal(nativeScientificSemantics(read).domain, 'unknown');
  read.scientific_context = {schema_version: 1, status: 'unresolved_lineage'};
  assert.equal(nativeScientificSemantics(read).status, 'unresolved_lineage');
  assert.equal(nativeScientificSemantics(read).coordinate_axes, null);
});

test('invalid context schema, sign, offset, unit, phase, identity and calibration are rejected', () => {
  for (const mutate of [
    v => v.scientific_context.schema_version = 99,
    v => v.scientific_context.request_id = '',
    v => v.scientific_context.result_version = 1,
    v => v.scientific_context.source_offset_xy[0] = -1,
    v => v.scientific_context.source_offset_xy[0] = 999,
    v => v.scientific_context.result.transform_signs.forward = '-',
    v => v.scientific_context.result.frequency_grid.axes[0].unit = 'wrong',
    v => v.scientific_context.result.phase_units = 'degrees',
    v => v.scientific_context.result.image.calibration[0].scale *= 2,
    v => v.scientific_context.postprocessing = ['arbitrary operation'],
    v => v.scientific_context.request_id = 'different',
  ]) {
    const {read, args} = fixture('VENDOR_ARG'); mutate(read);
    assert.throws(() => validateNativeDataSnapshot(read, args));
  }
});

test('NPY package independently reopens with bins, radians, provenance and unchanged pixel bytes', t => {
  const root = temp(t), {saved} = fixture('VENDOR_ARG', {crop: [1, 1], shape: [3, 6], roi: [2, 1, 5, 3]});
  const file = path.join(root, 'read.json'); fs.writeFileSync(file, JSON.stringify(saved));
  validateSavedSnapshot(Buffer.from(JSON.stringify(saved)));
  const options = {workspace: root, output: 'capture', requestId: 'save-1', snapshot: file};
  const first = handoff(options); assert.deepEqual(handoff(options), first);
  const script = String.raw`import base64,hashlib,json,sys,numpy as np
from pathlib import Path
r=Path(sys.argv[1]);i=json.loads((r/'capture/input.json').read_text());s=json.loads((r/'read.json').read_text())
a=np.load(r/'capture/input.npy',allow_pickle=False)
assert a.tobytes()==base64.b64decode(s['values_base64'])
q=i['scientific_semantics'];assert q['domain']=='frequency' and q['phase_units']=='radians'
assert q['representation']=='phase_radians' and q['inverse_restores_source_origin'] is False
assert i['scientific_context']==s['scientific_context']
for axis in q['coordinate_axes']:
 assert axis['calibrated_value_at_pixel_zero']+axis['dc_index_in_roi']*axis['scale']==0
 assert axis['native_minus_mathematical_zero']==-0.5*axis['scale']
 assert i['working_calibration_xy'][axis['dm_dimension']]['calibrated_value_at_pixel_zero']==axis['native_calibrated_value_at_pixel_zero']
m=json.loads((r/'capture/capture.json').read_text())
assert hashlib.sha256(json.dumps(i,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()==m['input_metadata_sha256']
print('independent scientific metadata and byte preservation PASS')`;
  assert.match(execFileSync('python', ['-c', script, root], {encoding: 'utf8'}), /preservation PASS/);
});

test('actual C++ adapter-surrogate READ packet passes Node and saved-snapshot validation', {skip: !process.env.DM_NATIVE_SCIENTIFIC_FIXTURE}, () => {
  const packet = JSON.parse(fs.readFileSync(process.env.DM_NATIVE_SCIENTIFIC_FIXTURE, 'utf8'));
  validateNativeDataSnapshot(packet.result, packet.args);
  const semantic = nativeScientificSemantics(packet.result);
  assert.equal(semantic.domain, 'frequency'); assert.equal(semantic.representation, 'phase_radians');
  assert.deepEqual(semantic.coordinate_axes.map(a => a.source_index_offset), [3, 2]);
});
