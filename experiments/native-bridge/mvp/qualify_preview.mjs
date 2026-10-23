// Explicit prepared-host native preview observation; no DM startup/cleanup.
import {readFileSync, writeFileSync, openSync, writeSync, fsyncSync, closeSync} from 'node:fs';
import {createHash, randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
import path from 'node:path';
import {NativeBridge} from '../../../lib/native_bridge.mjs';
import {encodeNativePreview} from '../../../lib/native_preview.mjs';
const [directory] = process.argv.slice(2);
if (!directory) throw new Error('Usage: PRIVATE-existing-synthetic-evidence-directory');
const truth = JSON.parse(readFileSync(path.join(directory, 'operations-truth.json'), 'utf8'));
assert.equal(truth.kind, 'synthetic-only'); assert.equal(truth.status, 'RECORDED');
assert.equal(truth.session, process.env.DM_NATIVE_SESSION);
const images = Object.fromEntries(truth.images.map(image => [image.label, image]));
const ledger = openSync(path.join(directory, 'preview-requests.jsonl'), 'wx');
const reportPath = path.join(directory, 'preview-observations.json');
closeSync(openSync(reportPath, 'wx'));
const report = {schema: 1, status: 'FAIL', host_pid: truth.host_pid, session: truth.session,
  checks: [], numerical_source_mapping: 'NOT_TESTED', model_client: 'NOT_TESTED'};
const bridge = new NativeBridge({session: truth.session, timeoutMs: 20000});
try {
  for (const [label, maxWidth, maxHeight] of [['A', 128, 128], ['FILTER_A', 3, 5]]) {
    const id = 'preview-' + randomUUID().replaceAll('-', '');
    const args = [images[label].id, maxWidth, maxHeight];
    const request = {protocol: 'NB2', session: truth.session, host_pid: truth.host_pid, id, op: 'PREVIEW', args,
      wire: `NB2 ${truth.session} ${id} PREVIEW ${args.join(' ')}\n`};
    writeSync(ledger, JSON.stringify(request) + '\n'); fsyncSync(ledger);
    const receipt = await bridge.execute('PREVIEW', args, {requestId: id});
    report.checks.push({label, request, receipt});
    assert.equal(receipt.state, 'completed'); assert.equal(receipt.host_pid, truth.host_pid);
    assert.equal(receipt.original_operation, 'PREVIEW'); assert.deepEqual(receipt.normalized_args, args);
    assert.equal(receipt.result.image_id, images[label].id);
    const png = encodeNativePreview(receipt.result);
    const filename = path.join(directory, 'preview_' + label.toLowerCase() + '.png');
    writeFileSync(filename, png, {flag: 'wx'});
    Object.assign(report.checks.at(-1), {png: filename, png_sha256: createHash('sha256').update(png).digest('hex')});
    const fresh = new NativeBridge({session: truth.session, timeoutMs: 20000});
    try { assert.deepEqual(await fresh.query(id), receipt); } finally { fresh.close(); }
  }
  report.status = 'RECORDED';
} catch (error) { report.error = String(error); process.exitCode = 1; }
finally { bridge.close(); closeSync(ledger); writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n'); }
console.log(report.status + '; independent source/mapping/PNG verification still required');
