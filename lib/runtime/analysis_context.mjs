// Revision-aware references only. Scientific providers remain authoritative for
// arrays, calibration, calculations and original-operation journals.
import {createHash, randomUUID} from 'node:crypto';

export const ANALYSIS_ROLES = Object.freeze(['experiment', 'fft', 'display', 'calibration', 'center', 'points', 'measurements', 'reference', 'orientation', 'simulation', 'registration', 'comparison']);
const ARRAY_ROLES = new Set(['points', 'measurements']);
const ID = /^[A-Za-z0-9_-]{1,64}$/, HASH = /^[a-f0-9]{64}$/;
const plain = value => value && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value));
export class AnalysisContextError extends Error {constructor(code, message) {super(message); this.code = code;}}
const need = (condition, code, message) => {if (!condition) throw new AnalysisContextError(code, message);};
function canonical(value, seen = new Set(), depth = 0) {
  need(depth <= 32, 'CONTEXT_BUDGET', 'Context JSON nesting exceeds budget');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  const array = Array.isArray(value);
  need(array || plain(value), 'INVALID_CONTEXT', 'Context data must be finite plain JSON');
  need(!seen.has(value), 'INVALID_CONTEXT', 'Context data cannot contain cycles');
  const keys = Reflect.ownKeys(value);
  need(keys.length === (array ? value.length + 1 : Object.keys(value).length), 'INVALID_CONTEXT', 'Context data contains sparse or hidden fields');
  for (const key of keys) {
    if (array && key === 'length') continue;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    need(typeof key === 'string' && descriptor.enumerable && Object.hasOwn(descriptor, 'value'), 'INVALID_CONTEXT', 'Context data cannot contain accessors');
  }
  seen.add(value);
  const result = array ? '[' + Array.from({length: value.length}, (_, index) => canonical(value[index], seen, depth + 1)).join(',') + ']'
    : '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key], seen, depth + 1)).join(',') + '}';
  seen.delete(value); return result;
}
const copy = value => JSON.parse(canonical(value));
const digest = value => createHash('sha256').update(canonical(value)).digest('hex');
const entries = value => value === null || value === undefined ? [] : Array.isArray(value) ? value : [value];
const active = value => entries(value).length > 0 && entries(value).every(entry => entry.status === 'active');
export const contextFingerprints = slots => Object.fromEntries(ANALYSIS_ROLES.map(role => [role, entries(slots[role]).length ? digest(entries(slots[role]).map(({ref, proof}) => ({ref, proof}))) : null]));
const fingerprints = contextFingerprints;
const invalidates = {
  experiment: ['fft', 'display', 'calibration', 'center', 'points', 'measurements', 'registration', 'comparison'],
  fft: ['display', 'calibration', 'center', 'points', 'measurements', 'registration', 'comparison'],
  calibration: ['display', 'measurements', 'registration', 'comparison'], center: ['display', 'measurements', 'registration', 'comparison'],
  points: ['measurements', 'registration', 'comparison'], measurements: ['registration', 'comparison'],
  reference: ['orientation', 'simulation', 'registration', 'comparison'], orientation: ['simulation', 'registration', 'comparison'],
  simulation: ['registration', 'comparison'], registration: ['comparison'], display: [], comparison: [],
};
const parented = new Set(['display', 'calibration', 'center', 'points', 'measurements']);
const required = {orientation: ['reference'], simulation: ['reference', 'orientation'], measurements: ['points', 'calibration', 'center'], registration: ['measurements', 'simulation'], comparison: ['measurements', 'simulation', 'registration']};

export function requiredContextDependencies(slot, slots) {
  need(ANALYSIS_ROLES.includes(slot) && plain(slots), 'INVALID_CONTEXT', 'Dependency inspection needs a supported role and selections');
  const selected = (required[slot] ?? []).filter(dependency => entries(slots[dependency]).length);
  if (slot === 'fft' && entries(slots.experiment).length) selected.push('experiment');
  return {required: selected, parents: parented.has(slot) ? ['fft', 'experiment'].filter(dependency => entries(slots[dependency]).length) : []};
}

function reference(value) {
  need(plain(value) && Object.keys(value).sort().join(',') === 'objectId,provider,session,workspace', 'INVALID_REFERENCE', 'Reference needs exact provider/workspace/session/objectId scope');
  for (const key of ['provider', 'session', 'workspace', 'objectId']) need(typeof value[key] === 'string' && value[key].trim().length > 0 && value[key].length <= (key === 'workspace' ? 4096 : 256), 'INVALID_REFERENCE', 'Invalid scoped reference field ' + key);
  return copy(value);
}
function reason(value) {need(typeof value === 'string' && value.trim().length > 0 && value.length <= 4000, 'INVALID_REASON', 'Context revision requires an explicit bounded reason'); return value;}
function analysisId(value) {need(typeof value === 'string' && ID.test(value), 'INVALID_ANALYSIS_ID', 'Invalid analysis identity'); return value;}

export class AnalysisContext {
  constructor({store, resolveReference, validateBindings} = {}) {
    need(store && ['read', 'compareAndSet', 'saveProposal', 'readProposal', 'findRequest'].every(method => typeof store[method] === 'function'), 'INVALID_CONTEXT_STORE', 'Context needs an explicit immutable CAS storage port');
    need(typeof resolveReference === 'function' && typeof validateBindings === 'function', 'INVALID_REFERENCE_PORT', 'Context needs explicit reference-resolution and binding-validation ports');
    this.store = store; this.resolveReference = resolveReference; this.validateBindings = validateBindings;
  }

  #context(record) {
    const value = copy(record.value);
    need(value.contextVersion === 1 && plain(value.slots) && typeof value.reason === 'string' && value.reason.trim().length > 0 && value.reason.length <= 4000 &&
      Array.isArray(value.changedSlots) && value.changedSlots.every(role => ANALYSIS_ROLES.includes(role)), 'CORRUPT_CONTEXT', 'Stored context schema is invalid');
    const mutationFields = Object.hasOwn(value, 'requestId') || Object.hasOwn(value, 'mutationSha256');
    need(!mutationFields || (typeof value.requestId === 'string' && ID.test(value.requestId) && HASH.test(value.mutationSha256 ?? '')), 'CORRUPT_CONTEXT', 'Stored context mutation identity/hash is invalid');
    need(Object.keys(value.slots).every(slot => ANALYSIS_ROLES.includes(slot)), 'CORRUPT_CONTEXT', 'Stored context contains unknown roles');
    for (const [slot, selection] of Object.entries(value.slots)) {
      need(selection === null || (ARRAY_ROLES.has(slot) ? Array.isArray(selection) && selection.length > 0 && selection.length <= 64 : plain(selection)), 'CORRUPT_CONTEXT', 'Stored role selection shape is invalid');
      for (const entry of entries(selection)) {
      need(plain(entry) && Object.keys(entry).sort().join(',') === 'dependsOn,proof,ref,staleBecause,status' && plain(entry.dependsOn) && Array.isArray(entry.staleBecause) && entry.staleBecause.every(role => ANALYSIS_ROLES.includes(role)) &&
        Object.entries(entry.dependsOn).every(([role, hash]) => ANALYSIS_ROLES.includes(role) && role !== slot && HASH.test(hash)), 'CORRUPT_CONTEXT', 'Stored context dependency/status record is invalid');
      reference(entry.ref);
      need(['active', 'stale'].includes(entry.status) && plain(entry.proof) && HASH.test(entry.proof.manifestHash ?? '') && typeof entry.proof.kind === 'string' && entry.proof.kind.length > 0 &&
        Array.isArray(entry.proof.roles) && entry.proof.roles.every(role => ANALYSIS_ROLES.includes(role)) && entry.proof.roles.includes(slot), 'CORRUPT_CONTEXT', 'Stored context reference proof/status is invalid');
      }
    }
    return {...value, analysisId: record.analysisId, revision: record.revision, revisionHash: record.hash, parentHash: record.parentHash, fingerprints: fingerprints(value.slots)};
  }

  async read(id, revision) {return this.#context(await this.store.read(analysisId(id), revision));}
  async readProposal(id, proposalId) {return copy(await this.store.readProposal(analysisId(id), proposalId));}

  async #mutationResult(found) {
    if (found.kind === 'revision') return {state: 'advanced', context: this.#context(found.record)};
    const proposal = found.record, savedRevision = proposal.value?.observedCurrentRevision;
    need(Number.isSafeInteger(savedRevision) && savedRevision >= 1, 'CORRUPT_CONTEXT', 'Historical mutation is missing its original observed context revision');
    const observed = await this.store.read(proposal.analysisId, savedRevision);
    need(observed.hash === proposal.value.observedCurrentHash, 'CORRUPT_CONTEXT', 'Historical mutation observed context hash mismatch');
    return {state: 'historical', context: this.#context(observed), proposal: copy(proposal)};
  }

  async #existingMutation(id, requestId, mutationSha256) {
    if (requestId === undefined) return null;
    need(typeof requestId === 'string' && ID.test(requestId), 'INVALID_CONTEXT_REQUEST', 'Context mutation requires a pre-saved safe request identity');
    const found = await this.store.findRequest(id, requestId);
    if (!found) return null;
    need(HASH.test(found.record.value?.mutationSha256 ?? ''), 'CORRUPT_CONTEXT', 'Stored context mutation hash is invalid');
    need(found.record.value.mutationSha256 === mutationSha256, 'REQUEST_CONFLICT', 'Same context request_id has different mutation parameters');
    return this.#mutationResult(found);
  }

  async readRequest(id, requestId) {
    analysisId(id); need(typeof requestId === 'string' && ID.test(requestId), 'INVALID_CONTEXT_REQUEST', 'Context query requires the original request identity');
    const found = await this.store.findRequest(id, requestId);
    need(found, 'CONTEXT_REQUEST_NOT_FOUND', 'Original context mutation was not found; do not guess or repeat scientific work');
    return this.#mutationResult(found);
  }

  async #entry(slot, value) {
    need(plain(value) && Object.keys(value).every(key => ['ref', 'dependsOn'].includes(key)) && Object.hasOwn(value, 'ref'), 'INVALID_CONTEXT_CHANGE', 'A selection contains only ref and optional dependsOn');
    const ref = reference(value.ref), dependsOn = copy(value.dependsOn ?? {});
    need(plain(dependsOn) && Object.entries(dependsOn).every(([key, hash]) => ANALYSIS_ROLES.includes(key) && key !== slot && HASH.test(hash)), 'INVALID_DEPENDENCY', 'Dependency binding requires another selected role and exact fingerprint');
    const proof = copy(await this.resolveReference(copy(ref)));
    need(plain(proof) && Object.keys(proof).every(key => ['manifestHash', 'kind', 'roles', 'scientific'].includes(key)) && HASH.test(proof.manifestHash ?? '') && typeof proof.kind === 'string' && proof.kind.length > 0 && proof.kind.length <= 128 &&
      Array.isArray(proof.roles) && proof.roles.every(role => ANALYSIS_ROLES.includes(role)) && proof.roles.includes(slot) && (proof.scientific === undefined || plain(proof.scientific)), 'INVALID_REFERENCE_PROOF', 'Provider did not return a valid immutable proof for selected role');
    need(Buffer.byteLength(canonical(proof)) <= 16 * 1024, 'CONTEXT_BUDGET', 'Reference proof exceeds 16 KiB; arrays/results do not belong in a context');
    return {ref, proof, dependsOn, status: 'active', staleBecause: []};
  }

  async #apply(baseSlots, changes) {
    need(plain(changes) && Object.keys(changes).length > 0 && Object.keys(changes).every(role => ANALYSIS_ROLES.includes(role)), 'INVALID_CONTEXT_CHANGE', 'Changes need explicit supported context roles');
    const slots = copy(baseSlots), replaced = new Set(Object.keys(changes));
    for (const [slot, selection] of Object.entries(changes)) {
      if (selection === null) {slots[slot] = null; continue;}
      if (ARRAY_ROLES.has(slot)) {
        need(Array.isArray(selection) && selection.length > 0 && selection.length <= 64, 'INVALID_CONTEXT_CHANGE', slot + ' must contain 1..64 scoped selections');
        slots[slot] = await Promise.all(selection.map(item => this.#entry(slot, item)));
      } else {need(!Array.isArray(selection), 'INVALID_CONTEXT_CHANGE', slot + ' must be one scoped selection'); slots[slot] = await this.#entry(slot, selection);}
    }
    const before = fingerprints(baseSlots), after = fingerprints(slots), changedSlots = new Set(ANALYSIS_ROLES.filter(role => before[role] !== after[role]));
    const pending = [...changedSlots], visited = new Set();
    while (pending.length) {
      const source = pending.shift(); if (visited.has(source)) continue; visited.add(source);
      for (const target of invalidates[source] ?? []) {
        if (replaced.has(target)) continue;
        for (const entry of entries(slots[target])) {entry.status = 'stale'; if (!entry.staleBecause.includes(source)) entry.staleBecause.push(source);}
        if (entries(slots[target]).length) pending.push(target);
      }
    }
    const visiting = new Set(), checked = new Set();
    const checkAcyclic = slot => {
      need(!visiting.has(slot), 'CYCLIC_DEPENDENCY', 'Current context dependencies cannot contain a cycle');
      if (checked.has(slot) || !active(slots[slot])) return;
      visiting.add(slot);
      for (const entry of entries(slots[slot])) for (const dependency of Object.keys(entry.dependsOn)) checkAcyclic(dependency);
      visiting.delete(slot); checked.add(slot);
    };
    for (const slot of Object.keys(slots)) checkAcyclic(slot);
    // Old dependencies can never silently become fresh again. Explicit new
    // selections must bind all selected current inputs and pass provider checks.
    for (const [slot, selection] of Object.entries(slots)) for (const entry of entries(selection)) {
      const dependencyIssues = Object.keys(entry.dependsOn).filter(dependency => after[dependency] !== entry.dependsOn[dependency] || !active(slots[dependency]));
      if (!replaced.has(slot)) {
        if (dependencyIssues.length) {entry.status = 'stale'; entry.staleBecause = [...new Set([...entry.staleBecause, ...dependencyIssues])];}
        continue;
      }
      need(dependencyIssues.length === 0, 'STALE_DEPENDENCY', 'New ' + slot + ' refers to a changed, missing or stale dependency: ' + dependencyIssues.join(','));
      const {required: mustBind, parents} = requiredContextDependencies(slot, slots);
      need(mustBind.every(dependency => Object.hasOwn(entry.dependsOn, dependency)), 'MISSING_DEPENDENCY', 'New ' + slot + ' must bind selected current inputs: ' + mustBind.join(','));
      if (parents.length) {
        need(parents.length === 0 || parents.some(dependency => Object.hasOwn(entry.dependsOn, dependency)), 'MISSING_DEPENDENCY', 'New ' + slot + ' must bind its selected scientific parent');
      }
      await this.validateBindings({slot, entry: copy(entry), slots: copy(slots), changedSlots: [...changedSlots], fingerprints: copy(after)});
    }
    need(Buffer.byteLength(canonical(slots)) <= 96 * 1024, 'CONTEXT_BUDGET', 'Context references exceed budget');
    return {slots, changedSlots: [...changedSlots]};
  }

  async create({analysisId: requestedId = randomUUID().replaceAll('-', ''), initialRefs = {}, reason: explanation = 'Create explicit current-analysis references', requestId} = {}) {
    const id = analysisId(requestedId); reason(explanation);
    const accepted = copy(initialRefs), mutationSha256 = digest({operation: 'create', analysisId: id, initialRefs: accepted, reason: explanation});
    const recovered = await this.#existingMutation(id, requestId, mutationSha256); if (recovered) return recovered;
    const applied = Object.keys(accepted).length ? await this.#apply({}, accepted) : {slots: {}, changedSlots: []};
    const value = {contextVersion: 1, reason: explanation, slots: applied.slots, changedSlots: applied.changedSlots, ...(requestId === undefined ? {} : {requestId, mutationSha256})};
    const result = await this.store.compareAndSet({analysisId: id, expectedRevision: 0, parentHash: null, value});
    if (!result.committed) {const original = await this.#existingMutation(id, requestId, mutationSha256); if (original) return original;}
    need(result.committed, 'ANALYSIS_EXISTS', 'Analysis identity already exists; read it rather than replacing it');
    return {state: 'advanced', context: this.#context(result.record)};
  }

  async commit({analysisId: requestedId, expectedRevision, changes, reason: explanation, requestId}) {
    const id = analysisId(requestedId); reason(explanation);
    need(Number.isSafeInteger(expectedRevision) && expectedRevision >= 1, 'INVALID_REVISION', 'Context commit requires the revision read before work began');
    const accepted = copy(changes), mutationSha256 = digest({operation: 'commit', analysisId: id, expectedRevision, changes: accepted, reason: explanation});
    const recovered = await this.#existingMutation(id, requestId, mutationSha256); if (recovered) return recovered;
    const base = await this.store.read(id, expectedRevision), baseContext = this.#context(base);
    const applied = await this.#apply(baseContext.slots, accepted);
    const value = {contextVersion: 1, reason: explanation, slots: applied.slots, changedSlots: applied.changedSlots, ...(requestId === undefined ? {} : {requestId, mutationSha256})};
    const afterResolution = await this.#existingMutation(id, requestId, mutationSha256); if (afterResolution) return afterResolution;
    const result = await this.store.compareAndSet({analysisId: id, expectedRevision, parentHash: base.hash, value});
    if (result.committed) return {state: 'advanced', context: this.#context(result.record)};
    const afterConflict = await this.#existingMutation(id, requestId, mutationSha256); if (afterConflict) return afterConflict;
    // Provider outcomes were already persisted independently. A lost CAS only
    // prevents promotion; it does not undo or replay any scientific operation.
    const proposal = await this.store.saveProposal(id, {expectedRevision, baseHash: base.hash, reason: explanation, candidate: value, changes: accepted,
      observedCurrentRevision: result.record.revision, observedCurrentHash: result.record.hash, ...(requestId === undefined ? {} : {requestId, mutationSha256})});
    return this.#mutationResult({kind: 'proposal', record: proposal});
  }
}
