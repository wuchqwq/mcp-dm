// Generic context references/CAS only. Fictional proofs test dependency logic;
// no science kernel, DM, worker or user data is exercised by these unit tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync, readFileSync, writeFileSync, readdirSync, mkdirSync, rmSync, copyFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawn, execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {AnalysisContext, ANALYSIS_ROLES, contextFingerprints, requiredContextDependencies} from '../lib/runtime/analysis_context.mjs';
import {FileContextStore} from '../lib/runtime/file_context_store.mjs';

const sha = text => createHash('sha256').update(text).digest('hex');
const ref = (objectId, provider = 'fictional-image', workspace = 'fixture-workspace', session = 'fixture-journal-v1') => ({provider, workspace, session, objectId});
const proof = objectId => ({manifestHash: sha(objectId), kind: 'fictional-reference', roles: [...ANALYSIS_ROLES], scientific: {grid: 'fixture-grid'}});
const selection = (objectId, dependsOn = {}) => ({ref: ref(objectId), dependsOn});
function fixture(t, options = {}) {
  const directory = mkdtempSync(path.join(tmpdir(), 'microscopy-analysis-context-'));
  const store = new FileContextStore({directory});
  const core = new AnalysisContext({store, resolveReference: async scoped => proof(scoped.objectId), validateBindings: async () => {}, ...options});
  t.after(() => {assert.ok(path.resolve(directory).startsWith(path.resolve(tmpdir()) + path.sep)); assert.ok(path.basename(directory).startsWith('microscopy-analysis-context-')); rmSync(directory, {recursive: true, force: true});});
  return {directory, store, core};
}
async function add(core, context, changes, reason = 'Synthetic context update') {
  const result = await core.commit({analysisId: context.analysisId, expectedRevision: context.revision, changes, reason});
  assert.equal(result.state, 'advanced'); return result.context;
}
async function populated(core) {
  let {context} = await core.create({analysisId: 'synthetic-analysis', initialRefs: {experiment: selection('source-frame')}});
  context = await add(core, context, {fft: selection('complex-fft', {experiment: context.fingerprints.experiment})});
  context = await add(core, context, {calibration: selection('calibration-v1', {fft: context.fingerprints.fft})});
  context = await add(core, context, {center: selection('center-v1', {fft: context.fingerprints.fft})});
  context = await add(core, context, {points: [selection('raw-point-1', {fft: context.fingerprints.fft}), selection('raw-point-2', {fft: context.fingerprints.fft})]});
  const geometry = {fft: context.fingerprints.fft, calibration: context.fingerprints.calibration, center: context.fingerprints.center, points: context.fingerprints.points};
  context = await add(core, context, {measurements: [selection('measurement-v1', geometry)]});
  context = await add(core, context, {reference: selection('reference-cif')});
  context = await add(core, context, {orientation: selection('orientation-001', {reference: context.fingerprints.reference})});
  context = await add(core, context, {simulation: selection('unrastered-simulation', {reference: context.fingerprints.reference, orientation: context.fingerprints.orientation})});
  context = await add(core, context, {registration: selection('registration-v1', {measurements: context.fingerprints.measurements, simulation: context.fingerprints.simulation})});
  context = await add(core, context, {comparison: selection('comparison-v1', {measurements: context.fingerprints.measurements, simulation: context.fingerprints.simulation, registration: context.fingerprints.registration})});
  context = await add(core, context, {display: selection('display-v1', {fft: context.fingerprints.fft})});
  return context;
}

test('explicit current context survives a new store/core and keeps immutable historical revisions', async t => {
  const f = fixture(t); const created = await f.core.create({analysisId: 'explicit-analysis', initialRefs: {experiment: selection('frame-v1')}});
  assert.equal(created.context.revision, 1); assert.equal(created.context.slots.experiment.ref.objectId, 'frame-v1');
  const updated = await add(f.core, created.context, {experiment: selection('frame-v2')});
  const second = new AnalysisContext({store: new FileContextStore({directory: f.directory}), resolveReference: async scoped => proof(scoped.objectId), validateBindings: async () => {}});
  assert.deepEqual(await second.read('explicit-analysis'), updated);
  assert.equal((await second.read('explicit-analysis', 1)).slots.experiment.ref.objectId, 'frame-v1');
  assert.equal((await second.read('explicit-analysis')).revision, 2);
  assert.equal(updated.parentHash, created.context.revisionHash);
});

test('display revision leaves saved FFT, points, physical measurements, registration and comparison active', async t => {
  const f = fixture(t), before = await populated(f.core);
  const after = await add(f.core, before, {display: selection('display-gamma2', {fft: before.fingerprints.fft})});
  for (const role of ['fft', 'points', 'measurements', 'registration', 'comparison']) {
    assert.equal(after.fingerprints[role], before.fingerprints[role]);
    for (const entry of Array.isArray(after.slots[role]) ? after.slots[role] : [after.slots[role]]) assert.equal(entry.status, 'active');
  }
  assert.notEqual(after.fingerprints.display, before.fingerprints.display);
});

for (const changed of ['calibration', 'center']) test(changed + ' revision preserves FFT/point identity but marks physical dependents stale', async t => {
  const f = fixture(t), before = await populated(f.core);
  const after = await add(f.core, before, {[changed]: selection(changed + '-v2', {fft: before.fingerprints.fft})});
  for (const role of ['fft', 'points']) {assert.equal(after.fingerprints[role], before.fingerprints[role]); for (const entry of Array.isArray(after.slots[role]) ? after.slots[role] : [after.slots[role]]) assert.equal(entry.status, 'active');}
  for (const role of ['display', 'measurements', 'registration', 'comparison']) for (const entry of Array.isArray(after.slots[role]) ? after.slots[role] : [after.slots[role]]) assert.equal(entry.status, 'stale');
  assert.equal((await f.core.read(before.analysisId, before.revision)).slots.comparison.status, 'active', 'old evidence remains explicitly historical');
});

test('point revision requires remeasurement and new registration/comparison, without recomputing or invalidating FFT', async t => {
  const f = fixture(t), before = await populated(f.core);
  let current = await add(f.core, before, {points: [selection('corrected-point', {fft: before.fingerprints.fft})]});
  assert.equal(current.slots.fft.status, 'active'); assert.equal(current.fingerprints.fft, before.fingerprints.fft);
  assert.equal(current.slots.measurements[0].status, 'stale'); assert.equal(current.slots.registration.status, 'stale');
  await assert.rejects(add(f.core, current, {comparison: selection('invalid-new-comparison', {measurements: current.fingerprints.measurements, simulation: current.fingerprints.simulation, registration: current.fingerprints.registration})}), error => error.code === 'STALE_DEPENDENCY');
  const geometry = {fft: current.fingerprints.fft, points: current.fingerprints.points, calibration: current.fingerprints.calibration, center: current.fingerprints.center};
  current = await add(f.core, current, {measurements: [selection('updated-measurement', geometry)]});
  current = await add(f.core, current, {registration: selection('updated-registration', {measurements: current.fingerprints.measurements, simulation: current.fingerprints.simulation})});
  current = await add(f.core, current, {comparison: selection('updated-comparison', {measurements: current.fingerprints.measurements, simulation: current.fingerprints.simulation, registration: current.fingerprints.registration})});
  assert.equal(current.slots.comparison.status, 'active'); assert.equal(current.fingerprints.fft, before.fingerprints.fft);
});

test('new science frame/FFT producer makes old geometry stale rather than transferring old anchors', async t => {
  const f = fixture(t), before = await populated(f.core);
  const after = await add(f.core, before, {experiment: selection('different-source-frame')});
  for (const role of ['fft', 'points', 'measurements', 'registration', 'comparison']) for (const entry of Array.isArray(after.slots[role]) ? after.slots[role] : [after.slots[role]]) assert.equal(entry.status, 'stale');
  assert.equal(after.slots.fft.ref.objectId, before.slots.fft.ref.objectId, 'retained old evidence is not a new computation');
});

test('reference/orientation revisions invalidate the exact simulation/comparison dependents', async t => {
  const f = fixture(t), before = await populated(f.core);
  const after = await add(f.core, before, {orientation: selection('orientation-110', {reference: before.fingerprints.reference})});
  for (const role of ['simulation', 'registration', 'comparison']) assert.equal(after.slots[role].status, 'stale');
  assert.equal(after.slots.fft.status, 'active'); assert.equal(after.slots.measurements[0].status, 'active');
});

test('half-finished immutable measurement/simulation may start analysis without forcing a complete workflow', async t => {
  const f = fixture(t);
  const created = await f.core.create({initialRefs: {measurements: [selection('existing-measurement')], simulation: selection('existing-simulation')}});
  assert.equal(created.context.slots.measurements[0].status, 'active'); assert.equal(created.context.slots.simulation.status, 'active');
  assert.equal(created.context.fingerprints.experiment, null);
});

test('exported dependency helpers match core bindings without exposing mutable rule state', async t => {
  const f = fixture(t), context = await populated(f.core);
  assert.deepEqual(contextFingerprints(context.slots), context.fingerprints);
  const dependencies = requiredContextDependencies('measurements', context.slots);
  assert.deepEqual(dependencies, {required: ['points', 'calibration', 'center'], parents: ['fft', 'experiment']});
  dependencies.required.length = 0;
  assert.deepEqual(requiredContextDependencies('measurements', context.slots).required, ['points', 'calibration', 'center']);
});

test('same object ID in another provider/workspace/session is a distinct scoped identity', async t => {
  const f = fixture(t), {context} = await f.core.create({initialRefs: {reference: selection('same-id')}});
  for (const changedScope of [{provider: 'another-provider'}, {workspace: 'another-workspace'}, {session: 'another-session'}]) {
    const changed = {...ref('same-id'), ...changedScope};
    const next = await add(f.core, await f.core.read(context.analysisId), {reference: {ref: changed}});
    assert.notEqual(next.fingerprints.reference, context.fingerprints.reference);
  }
});

test('simultaneously supplied active references cannot form a dependency cycle', async t => {
  const f = fixture(t), candidates = {
    reference: {ref: ref('reference'), proof: proof('reference')},
    orientation: {ref: ref('orientation'), proof: proof('orientation')},
  };
  const hashes = contextFingerprints(candidates);
  await assert.rejects(f.core.create({initialRefs: {
    reference: selection('reference', {orientation: hashes.orientation}),
    orientation: selection('orientation', {reference: hashes.reference}),
  }}), error => error.code === 'CYCLIC_DEPENDENCY');
});

test('wrong scope, unsupported roles, stale and omitted selected dependencies refuse promotion', async t => {
  const f = fixture(t); const {context} = await f.core.create({initialRefs: {experiment: selection('frame')}});
  for (const invalid of [{ref: {objectId: 'naked'}}, {ref: {...ref('frame'), extra: 'field'}}, {ref: {...ref('frame'), session: ''}}])
    await assert.rejects(add(f.core, context, {display: invalid}), error => error.code === 'INVALID_REFERENCE');
  await assert.rejects(add(f.core, context, {fft: selection('fft')}), error => error.code === 'MISSING_DEPENDENCY');
  await assert.rejects(add(f.core, context, {fft: selection('fft', {experiment: sha('wrong')})}), error => error.code === 'STALE_DEPENDENCY');
  const restricted = new AnalysisContext({store: f.store, resolveReference: async () => ({...proof('restricted'), roles: ['reference']}), validateBindings: async () => {}});
  await assert.rejects(add(restricted, context, {display: selection('not-a-display')}), error => error.code === 'INVALID_REFERENCE_PROOF');
  assert.equal((await f.core.read(context.analysisId)).revision, context.revision);
});

test('provider binding validator checks actual immutable scientific provenance before a fresh attachment', async t => {
  const checked = [];
  const f = fixture(t, {validateBindings: async call => {checked.push(call); if (call.entry.ref.objectId === 'old-result-relabelled') throw Object.assign(new Error('actual saved grid/scale differs'), {code: 'SCIENTIFIC_BINDING_MISMATCH'});}});
  const {context} = await f.core.create({initialRefs: {experiment: selection('current-frame')}});
  await assert.rejects(add(f.core, context, {display: selection('old-result-relabelled', {experiment: context.fingerprints.experiment})}), error => error.code === 'SCIENTIFIC_BINDING_MISMATCH');
  assert.equal(checked.at(-1).slot, 'display'); assert.deepEqual(checked.at(-1).changedSlots, ['display']);
  assert.equal((await f.core.read(context.analysisId)).revision, 1);
});

test('late old result persists as immutable historical proposal and cannot overwrite newer current selection after restart', async t => {
  const f = fixture(t), {context: old} = await f.core.create({analysisId: 'late-analysis', initialRefs: {experiment: selection('old-frame')}});
  const current = await add(f.core, old, {experiment: selection('new-frame')});
  const late = await f.core.commit({analysisId: old.analysisId, expectedRevision: old.revision, changes: {display: selection('late-display', {experiment: old.fingerprints.experiment})}, reason: 'Old operation arrived after researcher changed selection'});
  assert.equal(late.state, 'historical'); assert.equal(late.context.revisionHash, current.revisionHash);
  assert.equal(late.context.slots.experiment.ref.objectId, 'new-frame');
  assert.equal(late.proposal.value.candidate.slots.display.ref.objectId, 'late-display');
  const restarted = new AnalysisContext({store: new FileContextStore({directory: f.directory}), resolveReference: async scoped => proof(scoped.objectId), validateBindings: async () => {}});
  assert.deepEqual(await restarted.readProposal(old.analysisId, late.proposal.proposalId), late.proposal);
  assert.equal((await restarted.read(old.analysisId)).revisionHash, current.revisionHash);
});

test('reusing context ID refuses overwrite; query/history never resolves references or runs science', async t => {
  let resolutions = 0; const f = fixture(t, {resolveReference: async scoped => {resolutions++; return proof(scoped.objectId);}});
  const {context} = await f.core.create({analysisId: 'no-overwrite', initialRefs: {experiment: selection('frame')}});
  await assert.rejects(f.core.create({analysisId: 'no-overwrite'}), error => error.code === 'ANALYSIS_EXISTS');
  const calls = resolutions;
  await f.core.read('no-overwrite'); await f.core.read('no-overwrite', context.revision);
  assert.equal(resolutions, calls);
});

test('context creation and committed mutation recover their original request after newer revisions and restart', async t => {
  let resolutions = 0;
  const f = fixture(t, {resolveReference: async scoped => {resolutions++; return proof(scoped.objectId);}});
  const createArgs = {analysisId: 'request-recovery', requestId: 'create-original', initialRefs: {experiment: selection('frame-v1')}, reason: 'Create sourced references'};
  const created = await f.core.create(createArgs);
  const updateArgs = {analysisId: createArgs.analysisId, requestId: 'update-original', expectedRevision: 1,
    changes: {display: selection('display-v1', {experiment: created.context.fingerprints.experiment})}, reason: 'Select first display'};
  const updated = await f.core.commit(updateArgs);
  await add(f.core, updated.context, {display: selection('display-v2', {experiment: updated.context.fingerprints.experiment})});
  const count = resolutions;
  assert.deepEqual(await f.core.create(createArgs), created);
  assert.deepEqual(await f.core.commit(updateArgs), updated);
  assert.equal(resolutions, count, 'same-ID recovery does not re-resolve provider objects');
  await assert.rejects(f.core.commit({...updateArgs, reason: 'Changed parameters reuse original ID'}), error => error.code === 'REQUEST_CONFLICT');
  await assert.rejects(f.core.create({...createArgs, initialRefs: {experiment: selection('another-frame')}}), error => error.code === 'REQUEST_CONFLICT');
  const restarted = new AnalysisContext({store: new FileContextStore({directory: f.directory}), resolveReference: async () => {throw Error('readRequest must not resolve science');}, validateBindings: async () => {}});
  assert.deepEqual(await restarted.readRequest(createArgs.analysisId, 'create-original'), created);
  assert.deepEqual(await restarted.readRequest(createArgs.analysisId, 'update-original'), updated);
  await assert.rejects(restarted.readRequest(createArgs.analysisId, 'unknown-request'), error => error.code === 'CONTEXT_REQUEST_NOT_FOUND');
  assert.equal((await restarted.read(createArgs.analysisId)).revision, 3);
});

test('late mutation request is deduplicated in immutable proposal history and recovery keeps its original observed revision', async t => {
  const f = fixture(t), {context: base} = await f.core.create({analysisId: 'late-request', initialRefs: {experiment: selection('frame')}});
  let current = await add(f.core, base, {display: selection('newer-display', {experiment: base.fingerprints.experiment})});
  const lateArgs = {analysisId: base.analysisId, expectedRevision: base.revision, requestId: 'late-original',
    changes: {display: selection('late-old-display', {experiment: base.fingerprints.experiment})}, reason: 'Late provider result'};
  const late = await f.core.commit(lateArgs);
  assert.equal(late.state, 'historical'); assert.equal(late.context.revisionHash, current.revisionHash);
  current = await add(f.core, current, {display: selection('newest-display', {experiment: current.fingerprints.experiment})});
  assert.deepEqual(await f.core.commit(lateArgs), late);
  assert.deepEqual(await f.core.readRequest(base.analysisId, 'late-original'), late);
  assert.equal(readdirSync(path.join(f.directory, base.analysisId, 'proposals')).filter(name => name.endsWith('.json')).length, 1);
  await assert.rejects(f.core.commit({...lateArgs, reason: 'Different original late mutation'}), error => error.code === 'REQUEST_CONFLICT');
  assert.equal((await f.core.read(base.analysisId)).revisionHash, current.revisionHash);
});

test('concurrent same-ID context mutation creates one revision and both callers recover that original', async t => {
  const f = fixture(t), {context} = await f.core.create({analysisId: 'duplicate-context-request', initialRefs: {experiment: selection('frame')}});
  const second = new AnalysisContext({store: new FileContextStore({directory: f.directory}), resolveReference: async scoped => proof(scoped.objectId), validateBindings: async () => {}});
  const args = {analysisId: context.analysisId, expectedRevision: 1, requestId: 'same-mutation', changes: {display: selection('display', {experiment: context.fingerprints.experiment})}, reason: 'Concurrent same mutation'};
  const outcomes = await Promise.all([f.core.commit(args), second.commit(args)]);
  assert.deepEqual(outcomes[0], outcomes[1]); assert.equal(outcomes[0].state, 'advanced');
  assert.equal((await f.core.read(context.analysisId)).revision, 2);
  assert.equal(existsSync(path.join(f.directory, context.analysisId, 'proposals')), false);
});

test('same-ID conflicting concurrent mutations refuse the loser instead of creating a second context result', async t => {
  const f = fixture(t), {context} = await f.core.create({analysisId: 'conflicting-context-request', initialRefs: {experiment: selection('frame')}});
  const args = {analysisId: context.analysisId, expectedRevision: 1, requestId: 'conflicting-mutation', reason: 'Explicit mutation'};
  const outcomes = await Promise.allSettled([
    f.core.commit({...args, changes: {display: selection('display-a', {experiment: context.fingerprints.experiment})}}),
    f.core.commit({...args, changes: {display: selection('display-b', {experiment: context.fingerprints.experiment})}}),
  ]);
  assert.equal(outcomes.filter(outcome => outcome.status === 'fulfilled').length, 1);
  assert.equal(outcomes.filter(outcome => outcome.status === 'rejected' && outcome.reason.code === 'REQUEST_CONFLICT').length, 1);
  assert.equal((await f.core.read(context.analysisId)).revision, 2);
});

test('context requires an explicit provider binding validator rather than defaulting scientific compatibility to true', t => {
  const f = fixture(t);
  assert.throws(() => new AnalysisContext({store: f.store, resolveReference: async scoped => proof(scoped.objectId)}), error => error.code === 'INVALID_REFERENCE_PORT');
});

test('append rejects cumulative history overflow before publishing and leaves previous current readable', t => {
  const f = fixture(t), store = new FileContextStore({directory: f.directory, maxHistoryBytes: 4096});
  const first = store.compareAndSet({analysisId: 'byte-budget', expectedRevision: 0, parentHash: null, value: {fixture: 'a'.repeat(500)}});
  assert.equal(first.committed, true);
  assert.throws(() => store.compareAndSet({analysisId: 'byte-budget', expectedRevision: 1, parentHash: first.record.hash, value: {fixture: 'b'.repeat(3500)}}), error => error.code === 'CONTEXT_BUDGET');
  assert.deepEqual(store.read('byte-budget'), first.record);
  assert.deepEqual(readdirSync(path.join(f.directory, 'byte-budget')), ['00000001.json']);
  assert.throws(() => new FileContextStore({directory: f.directory, maxHistoryBytes: 16 * 1024 * 1024 + 1}), error => error.code === 'INVALID_CONTEXT_BUDGET');
});

test('partial temporary file is ignored but a corrupt/missing committed chain refuses current state', async t => {
  const f = fixture(t), {context} = await f.core.create({analysisId: 'corrupt-analysis', initialRefs: {experiment: selection('frame')}});
  const directory = path.join(f.directory, 'corrupt-analysis');
  writeFileSync(path.join(directory, 'pending-interrupted.tmp'), '{partial');
  assert.equal((await f.core.read('corrupt-analysis')).revisionHash, context.revisionHash);
  await add(f.core, context, {display: selection('view', {experiment: context.fingerprints.experiment})});
  const first = path.join(directory, '00000001.json'), saved = readFileSync(first);
  writeFileSync(first, saved.toString().replace('frame', 'tampered-frame'));
  await assert.rejects(f.core.read('corrupt-analysis'), error => error.code === 'CORRUPT_CONTEXT');
  writeFileSync(first, saved); rmSync(first);
  await assert.rejects(f.core.read('corrupt-analysis'), error => error.code === 'CORRUPT_CONTEXT');
});

test('even a self-consistent stored hash cannot make an invalid context shape readable', async t => {
  const f = fixture(t);
  f.store.compareAndSet({analysisId: 'bad-context-shape', expectedRevision: 0, parentHash: null,
    value: {contextVersion: 1, reason: 'Malformed fixture only', slots: {experiment: {ref: ref('frame'), proof: proof('frame'), status: 'active'}}}});
  await assert.rejects(f.core.read('bad-context-shape'), error => error.code === 'CORRUPT_CONTEXT');
});

test('invalid JSON, over-budget proof, path traversal and unscoped references are refused', async t => {
  const f = fixture(t);
  await assert.rejects(f.core.create({analysisId: '../escape'}), error => error.code === 'INVALID_ANALYSIS_ID');
  await assert.rejects(f.core.create({initialRefs: {experiment: {ref: {...ref('frame'), workspace: ''}}}}), error => error.code === 'INVALID_REFERENCE');
  const bad = new AnalysisContext({store: f.store, resolveReference: async () => ({...proof('frame'), scientific: {huge: 'x'.repeat(17000)}}), validateBindings: async () => {}});
  await assert.rejects(bad.create({initialRefs: {experiment: selection('frame')}}), error => error.code === 'CONTEXT_BUDGET');
  for (const value of [NaN, undefined, new Date(), new Map(), new Set(), {nested: Infinity}]) {
    const core = new AnalysisContext({store: f.store, resolveReference: async () => value, validateBindings: async () => {}});
    await assert.rejects(core.create({initialRefs: {experiment: selection('frame')}}));
  }
  assert.throws(() => new FileContextStore({directory: 'relative'}), error => error.code === 'INVALID_CONTEXT_DIRECTORY');
});

test('immutable CAS publication has exactly one winner across separate Node processes', async t => {
  const f = fixture(t), id = 'process-cas';
  const created = f.store.compareAndSet({analysisId: id, expectedRevision: 0, parentHash: null, value: {fixture: 'initial'}});
  const script = path.join(f.directory, 'cas-child.mjs');
  writeFileSync(script, `import {FileContextStore} from ${JSON.stringify(pathToFileURL(fileURLToPath(new URL('../lib/runtime/file_context_store.mjs', import.meta.url))).href)};\n` +
    `const store=new FileContextStore({directory:process.argv[2]});const base=store.read('process-cas');console.log('READY');process.stdin.once('data',()=>{console.log(JSON.stringify(store.compareAndSet({analysisId:'process-cas',expectedRevision:base.revision,parentHash:base.hash,value:{winner:process.argv[3]}})));});\n`);
  const children = ['a', 'b'].map(label => {
    const child = spawn(process.execPath, [script, f.directory, label], {windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
    let raw = '', stderr = '', ready;
    const readiness = new Promise(resolve => {ready = resolve;}); child.stdout.on('data', part => {raw += part; if (raw.includes('READY\n')) ready();}); child.stderr.on('data', part => {stderr += part;});
    const ended = new Promise((resolve, reject) => {child.once('error', reject); child.once('exit', (code, signal) => code === 0 ? resolve({raw, stderr}) : reject(Error('CAS child failed ' + code + '/' + signal + ': ' + stderr)));});
    return {child, readiness, ended};
  });
  await Promise.all(children.map(child => child.readiness)); for (const child of children) child.child.stdin.end('commit\n');
  const outcomes = (await Promise.all(children.map(child => child.ended))).map(({raw}) => JSON.parse(raw.trim().split('\n').at(-1)));
  assert.equal(outcomes.filter(result => result.committed).length, 1); assert.equal(outcomes.filter(result => !result.committed).length, 1);
  const current = f.store.read(id); assert.equal(current.revision, 2); assert.equal(current.parentHash, created.record.hash);
  assert.deepEqual(readdirSync(path.join(f.directory, id)).filter(name => /^[0-9]{8}\.json$/.test(name)), ['00000001.json', '00000002.json']);
});

test('generic context and store import in an isolated copied directory without provider/server/DM tree', t => {
  const f = fixture(t), isolated = path.join(f.directory, 'portable'); mkdirSync(isolated);
  for (const name of ['analysis_context.mjs', 'file_context_store.mjs']) copyFileSync(fileURLToPath(new URL('../lib/runtime/' + name, import.meta.url)), path.join(isolated, name));
  const smoke = path.join(isolated, 'smoke.mjs');
  writeFileSync(smoke, `import {AnalysisContext} from './analysis_context.mjs';import {FileContextStore} from './file_context_store.mjs';import {createHash} from 'node:crypto';import path from 'node:path';\n` +
    `const core=new AnalysisContext({store:new FileContextStore({directory:path.resolve('records')}),resolveReference:async ref=>({manifestHash:createHash('sha256').update(ref.objectId).digest('hex'),kind:'fixture',roles:['experiment']}),validateBindings:async()=>{}});const a=await core.create({analysisId:'portable-context',initialRefs:{experiment:{ref:{provider:'test',workspace:'opaque',session:'v1',objectId:'fixed'}}}});console.log(JSON.stringify(await core.read(a.context.analysisId)));\n`);
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('DM_')));
  const result = JSON.parse(execFileSync(process.execPath, [smoke], {cwd: isolated, env, encoding: 'utf8', timeout: 10000, windowsHide: true}));
  assert.equal(result.revision, 1); assert.equal(result.slots.experiment.ref.objectId, 'fixed');
  for (const absent of ['GMS', 'server.mjs', 'lib', 'tools', 'node_modules']) assert.equal(existsSync(path.join(isolated, absent)), false);
});
