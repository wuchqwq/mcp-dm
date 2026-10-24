#!/usr/bin/env node
// Historical prepared-v1 qualification harness retained with its evidence.
// Current Fourier v2 / READ acceptance uses accept_handoff_mcp.py instead.
// NativeBridge uses the actual Windows
// pipe; no callback substitutes an operation. This is not a model-client test.
import assert from 'node:assert/strict';
import {readFileSync, openSync, writeSync, fsyncSync, closeSync, writeFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {NativeBridge} from '../../../lib/native_bridge.mjs';

const [truthFile, newLedger, newReport] = process.argv.slice(2);
if (!truthFile || !newLedger || !newReport) throw new Error('Usage: truth.json NEW-ledger.jsonl NEW-report.json');
const truth = JSON.parse(readFileSync(truthFile, 'utf8'));
assert.equal(truth.kind, 'synthetic-only');
assert.equal(truth.status, 'RECORDED');
assert.equal(truth.session, process.env.DM_NATIVE_SESSION);
assert.ok(Number.isSafeInteger(truth.host_pid) && truth.host_pid > 0);
const byLabel = Object.fromEntries(truth.images.map(image => [image.label, image]));
const report = {schema: 1, status: 'FAIL', kind: 'synthetic-only', session: truth.session,
  host_pid: truth.host_pid, checks: [], outputs: [], numerical_qualification: 'NOT_TESTED',
  model_client: 'NOT_TESTED'};
// Reserve both paths before the first operation. Never replace old evidence.
const ledger = openSync(newLedger, 'wx');
const reportFd = openSync(newReport, 'wx');
closeSync(reportFd);
let bridge = new NativeBridge({session: truth.session, timeoutMs: 20000});
let hostThread, workerThread;
function saveRequest(op, args) {
  const id = 'qualify-' + randomUUID().replaceAll('-', '');
  const record = {protocol: 'NB2', session: truth.session, id, op, args,
    host_pid: truth.host_pid, wire: `NB2 ${truth.session} ${id} ${op}${args.length ? ' ' + args.join(' ') : ''}\n`};
  writeSync(ledger, JSON.stringify(record) + '\n'); fsyncSync(ledger);
  return id;
}
async function call(op, args = [], label = op, expectedFailure = false) {
  const id = saveRequest(op, args);
  const receipt = await bridge.execute(op, args, {requestId: id});
  report.checks.push({label, op, args, id, receipt, expected_failure: expectedFailure});
  assert.equal(receipt.protocol, 'NB2'); assert.equal(receipt.session, truth.session);
  assert.equal(receipt.host_pid, truth.host_pid); assert.equal(receipt.id, id);
  assert.equal(receipt.original_operation, op); assert.deepEqual(receipt.normalized_args, args);
  assert.equal(receipt.result_version, 1);
  if (hostThread === undefined) { hostThread = receipt.exec_tid; workerThread = receipt.worker_tid; }
  assert.equal(receipt.worker_tid, workerThread);
  assert.equal(receipt.exec_tid, hostThread);
  assert.equal(receipt.state, expectedFailure ? 'failed' : 'completed', JSON.stringify(receipt));
  if (expectedFailure) return null;
  assert.equal(receipt.result.backend, 'digitalmicrograph-native');
  return receipt.result;
}
try {
  const status = await call('STATUS');
  assert.equal(status.ready, true); assert.equal(status.binary_gate, true);
  assert.equal(status.candidate_execution_enabled, true);
  await call('DATASETS');
  await call('UNARY', [byLabel.A.id, 99], 'bad-unary-enum', true);
  await call('UNARY', [byLabel.UINT16.id, 1], 'unsupported-unary-dtype', true);
  await call('UNARY', [byLabel.NONFINITE.id, 1], 'nonfinite-unary', true);
  await call('UNARY', [0xffffffff, 1], 'invalid-source-id', true);
  await call('BINARY', [byLabel.A.id, byLabel.IMPULSE.id, 1], 'no-broadcast', true);
  await call('FFT', [byLabel.NONFINITE.id], 'nonfinite-fft', true);
  await call('FFT', [byLabel.UINT16.id], 'unsupported-fft-dtype', true);
  await call('FILTER', [byLabel.UINT16.id, 1], 'unsupported-filter-dtype', true);

  for (let code = 1; code <= 3; ++code) {
    const result = await call('UNARY', [byLabel.A.id, code], 'unary-' + code);
    report.outputs.push({kind: 'UNARY', opcode: code, source_labels: ['A'], image_id: result.image_id});
  }
  for (let code = 1; code <= 3; ++code) {
    const result = await call('BINARY', [byLabel.A.id, byLabel.B.id, code], 'binary-' + code);
    report.outputs.push({kind: 'BINARY', opcode: code, source_labels: ['A', 'B'], image_id: result.image_id});
  }
  const frequencies = [];
  for (const label of ['CONSTANT', 'IMPULSE', 'SINGLE_FREQUENCY', 'A']) {
    const spectrum = await call('FFT', [byLabel[label].id], 'fft-' + label);
    report.outputs.push({kind: 'FFT', source_labels: [label], image_id: spectrum.image_id});
    frequencies.push({label, image_id: spectrum.image_id});
    for (const op of ['REAL', 'IMAG']) {
      const result = await call(op, [spectrum.image_id], op + '-' + label);
      report.outputs.push({kind: op, source_labels: [label], parent_image_id: spectrum.image_id, image_id: result.image_id});
    }
    const inverse = await call('IFFT', [spectrum.image_id], 'ifft-' + label);
    report.outputs.push({kind: 'IFFT', source_labels: [label], parent_image_id: spectrum.image_id, image_id: inverse.image_id});
    const real = await call('REAL', [inverse.image_id], 'ifft-real-' + label);
    report.outputs.push({kind: 'IFFT_REAL', source_labels: [label], parent_image_id: inverse.image_id, image_id: real.image_id});
  }
  for (const op of ['VENDOR_ARG', 'VENDOR_NORM']) {
    const spectrum = frequencies.find(image => image.label === 'A');
    const result = await call(op, [spectrum.image_id], op);
    report.outputs.push({kind: op, source_labels: ['A'], parent_image_id: spectrum.image_id, image_id: result.image_id});
  }
  for (let code = 1; code <= 4; ++code) {
    const result = await call('FILTER', [byLabel.FILTER_A.id, code], 'filter-' + code);
    report.outputs.push({kind: 'FILTER', opcode: code, source_labels: ['FILTER_A'], image_id: result.image_id});
  }
  // A fresh client knows no local operation registry. NB2 must preserve original
  // operation, parameters, result schema and the very same retained result ID.
  bridge.close(); bridge = new NativeBridge({session: truth.session, timeoutMs: 20000});
  report.recovered = [];
  for (const check of report.checks.filter(check => check.receipt.state === 'completed')) {
    const recovered = await bridge.query(check.id);
    assert.equal(recovered.original_operation, check.op);
    assert.deepEqual(recovered.normalized_args, check.args);
    assert.deepEqual(recovered.result, check.receipt.result);
    report.recovered.push(recovered);
  }
  // RECORDED is deliberately not PASS: only the separate in-host pixel oracle
  // can qualify numerical conventions, calibration and source invariance.
  report.status = 'RECORDED';
} catch (error) {
  report.error = String(error); process.exitCode = 1;
} finally {
  bridge.close(); closeSync(ledger);
  writeFileSync(newReport, JSON.stringify(report, null, 2) + '\n');
}
console.log(report.status + '; independent numerical/source/lifecycle oracle still required');
