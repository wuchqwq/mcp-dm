// Synthetic saved receipts only; these tests do not contact a host or attest DM.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {handoff, strictJson, validateSavedSnapshot} from '../tools/native_snapshot_handoff.mjs';
import {readFixture, imageMetadata} from './fixtures/native-operations.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const readJson = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
function temporary(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'native-handoff-test-'));
  t.after(() => {
    const actual = fs.realpathSync(directory);
    assert.equal(path.dirname(actual), fs.realpathSync(os.tmpdir()));
    assert.ok(path.basename(actual).startsWith('native-handoff-test-'));
    fs.rmSync(actual, {recursive: true});
  });
  return directory;
}
function payload({source} = {}) {
  const args = [77, 1, 1, 4, 3];
  return {...readFixture(args, source ? {source} : {}), native_receipt: {
    protocol: 'NB2', session: 'a'.repeat(32), id: 'synthetic-read', request_id: 'synthetic-read',
    original_operation: 'READ', normalized_args: args, result_type: 'native_data_snapshot', result_version: 1,
    state: 'completed', host_pid: 1234, exec_tid: 10, worker_tid: 20,
    timings_us: {queue: 3, execute: 4},
  }};
}
function prepare(directory, value = payload()) {
  const filename = path.join(directory, 'saved.json'); fs.writeFileSync(filename, JSON.stringify(value)); return filename;
}
function invoke(directory, snapshot, overrides = {}) { return handoff({workspace: directory, output: 'capture', requestId: 'handoff-1', snapshot, ...overrides}); }

test('NPY reopens bitwise in independent NumPy; schema1 hash matches Python; raw -0 and calibration survive', t => {
  const directory = temporary(t), source = imageMetadata(77);
  // Exercise Python/JavaScript scientific-notation canonical spelling as well.
  source.calibration[0].scale = Math.fround(-1e-7);
  source.calibration[0].calibrated_value_at_pixel_zero = Math.fround(-2 * source.calibration[0].scale);
  const saved = prepare(directory, payload({source}));
  const result = invoke(directory, saved); assert.equal(result.state, 'captured');
  const output = path.join(directory, 'capture'); assert.deepEqual(fs.readdirSync(output).sort(), ['capture.json', 'input.json', 'input.npy']);
  const script = String.raw`import hashlib,json,sys,numpy as np
from pathlib import Path
p=Path(sys.argv[1]);i=json.loads((p/'input.json').read_text(encoding='utf-8'));m=json.loads((p/'capture.json').read_text(encoding='utf-8'))
a=np.load(p/'input.npy',allow_pickle=False); expected=np.array([[-0.,-2.5,.125],[8.,-0.,-2.5]],dtype='<f4')
assert a.dtype==np.dtype('<f4') and a.shape==(2,3) and a.flags.c_contiguous
assert np.array_equal(a.view('<u4'),expected.view('<u4'))
assert hashlib.sha256(a.tobytes()).hexdigest()==i['pixel_sha256']
assert hashlib.sha256((p/'input.npy').read_bytes()).hexdigest()==i['input_sha256']==m['input_sha256']
assert hashlib.sha256(json.dumps(i,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==m['input_metadata_sha256']
assert i['intensity_calibration']==dict(origin=None,scale=None,unit=None,status='NOT_READ')
assert i['source_calibration_dm'][0]['origin']==2 and i['working_calibration_xy'][0]['origin']==1
assert i['working_calibration_xy'][0]['source_offset']==1 and i['working_calibration_xy'][0]['scale']<0
assert i['working_calibration_xy'][0]['calibrated_value_at_pixel_zero']==i['source_calibration_dm'][0]['calibrated_value_at_pixel_zero']+i['working_calibration_xy'][0]['scale']
assert i['dm_file_save'] is False and i['pixel_capture_atomic'] is False
print('independent NumPy bitwise/schema1 PASS; synthetic fixture only')`;
  assert.match(execFileSync('python', ['-c', script, output], {encoding: 'utf8'}), /bitwise\/schema1 PASS/);
});

test('same caller ID returns exactly original receipt without rewriting; changed path or snapshot conflicts', t => {
  const directory = temporary(t), saved = prepare(directory), first = invoke(directory, saved);
  const files = [saved, path.join(directory, 'handoff-requests', 'handoff-1.json'), ...['input.npy', 'input.json', 'capture.json'].map(name => path.join(directory, 'capture', name))];
  const before = files.map(name => [sha(fs.readFileSync(name)), fs.statSync(name).mtimeMs]);
  assert.deepEqual(invoke(directory, saved), first);
  assert.deepEqual(files.map(name => [sha(fs.readFileSync(name)), fs.statSync(name).mtimeMs]), before);
  assert.throws(() => invoke(directory, saved, {output: 'other'}), /CONFLICT/);
  fs.appendFileSync(saved, '\n'); assert.throws(() => invoke(directory, saved), /CONFLICT/);
});

test('existing target and traversal refuse all overwrite; existing user files remain exact', t => {
  const directory = temporary(t), saved = prepare(directory), target = path.join(directory, 'capture'); fs.mkdirSync(target);
  const owned = path.join(target, 'input.npy'); fs.writeFileSync(owned, 'USER DATA');
  assert.throws(() => invoke(directory, saved), /exist/i); assert.equal(fs.readFileSync(owned, 'utf8'), 'USER DATA');
  assert.equal(readJson(path.join(directory, 'handoff-requests', 'handoff-1.json')).state, 'FAILED');
  for (const output of ['../escape', path.resolve(directory, 'absolute'), '.', 'foo/../bar', 'C:escape'])
    assert.throws(() => invoke(directory, saved, {requestId: 'other-id', output}));
});

test('a partial write records failed; retry preserves evidence as UNKNOWN_INCOMPLETE', t => {
  const directory = temporary(t), saved = prepare(directory), originalOpen = fs.openSync;
  let injected = false;
  fs.openSync = function(filename, ...args) {
    if (!injected && String(filename).endsWith(path.join('capture', 'input.npy'))) {
      injected = true; fs.writeFileSync(path.join(directory, 'capture', 'input.json'), 'RACED USER FILE');
    }
    return originalOpen.call(this, filename, ...args);
  };
  try { assert.throws(() => invoke(directory, saved), /exist/i); } finally { fs.openSync = originalOpen; }
  assert.equal(readJson(path.join(directory, 'capture', 'capture.json')).state, 'failed');
  assert.equal(fs.readFileSync(path.join(directory, 'capture', 'input.json'), 'utf8'), 'RACED USER FILE');
  const journal = path.join(directory, 'handoff-requests', 'handoff-1.json'), before = fs.readFileSync(journal);
  assert.equal(invoke(directory, saved).state, 'UNKNOWN_INCOMPLETE'); assert.deepEqual(fs.readFileSync(journal), before);
  fs.writeFileSync(journal, '{'); assert.equal(invoke(directory, saved).state, 'UNKNOWN_INCOMPLETE');
});

test('short writes complete and fsync the full PREPARED journal before output mkdir; zero progress fails closed', t => {
  const directory = temporary(t), saved = prepare(directory), originalWrite = fs.writeSync, originalMkdir = fs.mkdirSync, originalSync = fs.fsyncSync;
  const synced = new Set(); let writes = 0, sawPrepared = false;
  fs.writeSync = function(fd, buffer, offset, length, position) {
    ++writes; return originalWrite.call(this, fd, buffer, offset, Math.min(length, 17), position);
  };
  fs.fsyncSync = function(fd) { originalSync.call(this, fd); synced.add(fd); };
  fs.mkdirSync = function(filename, ...args) {
    if (filename === path.join(directory, 'capture')) {
      const journal = readJson(path.join(directory, 'handoff-requests', 'handoff-1.json'));
      assert.equal(journal.state, 'PREPARED'); assert.equal(journal.parameters.operation, 'READ');
      assert.ok(synced.size > 0); sawPrepared = true;
    }
    return originalMkdir.call(this, filename, ...args);
  };
  try { assert.equal(invoke(directory, saved).state, 'captured'); }
  finally { fs.writeSync = originalWrite; fs.mkdirSync = originalMkdir; fs.fsyncSync = originalSync; }
  assert.ok(sawPrepared && writes > 100);
  const directory2 = temporary(t), saved2 = prepare(directory2); let first = true;
  fs.writeSync = function(...args) { if (first) { first = false; return 0; } return originalWrite.apply(this, args); };
  try { assert.throws(() => invoke(directory2, saved2), /no progress/); } finally { fs.writeSync = originalWrite; }
  assert.ok(!fs.existsSync(path.join(directory2, 'capture')));
  assert.equal(readJson(path.join(directory2, 'handoff-requests', 'handoff-1.json')).state, 'FAILED');
  assert.equal(invoke(directory2, saved2).state, 'UNKNOWN_INCOMPLETE');
});

test('captured file or original native receipt hash modification never returns captured', t => {
  const directory = temporary(t), saved = prepare(directory); invoke(directory, saved);
  const journalPath = path.join(directory, 'handoff-requests', 'handoff-1.json'), journal = readJson(journalPath);
  journal.native_receipt_sha256 = '0'.repeat(64); fs.writeFileSync(journalPath, JSON.stringify(journal));
  assert.throws(() => invoke(directory, saved), /receipt hash mismatch/);
  journal.native_receipt_sha256 = readJson(path.join(directory, 'capture', 'input.json')).native_receipt_sha256;
  fs.writeFileSync(journalPath, JSON.stringify(journal)); fs.appendFileSync(path.join(directory, 'capture', 'input.npy'), 'x');
  assert.throws(() => invoke(directory, saved), /file hash mismatch/);
});

test('missing completed receipt remains UNKNOWN; calibration unknown units stay explicit rather than invented', t => {
  const directory = temporary(t), source = imageMetadata(77);
  source.calibration[0].unit = null; source.calibration[0].usable = false; source.calibration[0].issue = 'unknown_units'; source.calibration_complete = false;
  const saved = prepare(directory, payload({source})); invoke(directory, saved);
  const info = readJson(path.join(directory, 'capture', 'input.json')); assert.equal(info.working_calibration_xy[0].unit, null); assert.equal(info.calibration_complete, false);
  const journalPath = path.join(directory, 'handoff-requests', 'handoff-1.json'), journal = readJson(journalPath);
  delete journal.native_receipt; fs.writeFileSync(journalPath, JSON.stringify(journal));
  assert.equal(invoke(directory, saved).state, 'UNKNOWN_INCOMPLETE');
});

test('invalid dtype/base64/source/ROIcal/receipt/provenance/PNG all reject before output allocation', t => {
  const mutations = [p => p.dtype = 'float64', p => p.values_base64 = 'not-base64!', p => p.values_base64 += '=',
    p => p.source.id = 99, p => p.roi_calibration[0].origin += 1, p => p.source_provenance = {operation: 'RUN_SCRIPT'},
    p => p.native_receipt.result_version = 2, p => p.native_receipt.state = 'unknown', p => p.native_receipt.normalized_args[1] = 0,
    p => p.native_receipt.request_id = 'other', p => p.native_receipt.exec_tid = p.native_receipt.worker_tid,
    p => p.native_receipt.session = 'bad', p => p.png = 'preview', p => p.source.name = '\ud800', p => p.raw_bytes = 65540];
  mutations.push(p => delete p.native_receipt.timings_us, p => p.native_receipt.timings_us.execute = -1,
    p => p.native_receipt.timings_us.queue = .5, p => p.native_receipt.host_pid = 2 ** 40,
    p => p.native_receipt.exec_tid = 2 ** 32, p => p.native_receipt.worker_tid = -1);
  mutations.forEach((mutate, index) => {
    const directory = temporary(t), value = payload(); mutate(value); const saved = prepare(directory, value);
    assert.throws(() => invoke(directory, saved), undefined, 'negative ' + index); assert.ok(!fs.existsSync(path.join(directory, 'capture')));
  });
  assert.throws(() => strictJson('{"a":1,"a":2}'), /Duplicate/);
  assert.throws(() => strictJson('{"a":1e999}'), /Nonfinite/);
  assert.throws(() => validateSavedSnapshot(Buffer.from([0xff])), /encoded data|encoding/i);
});

test('MCP single text wrapper accepted; image or error wrapper refused', t => {
  const raw = Buffer.from(JSON.stringify({content: [{type: 'text', text: JSON.stringify(payload())}]}));
  assert.equal(validateSavedSnapshot(raw).values.length, 24);
  for (const value of [{isError: true, content: [{type: 'text', text: JSON.stringify(payload())}]},
    {content: [{type: 'image', data: 'png', mimeType: 'image/png'}]}]) assert.throws(() => validateSavedSnapshot(Buffer.from(JSON.stringify(value))));
});
