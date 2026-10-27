// Portable, single-process execution mechanics. Providers own scientific
// validation, durable request identity and recovery; this is not a journal.
import {createHash, randomUUID} from 'node:crypto';
import {performance} from 'node:perf_hooks';

function canonical(value, seen = new Set(), depth = 0) {
  if (depth > 64) throw new TypeError('Execution parameters exceed nesting budget');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (!value || typeof value !== 'object' || seen.has(value)) throw new TypeError('Execution parameters must be finite plain JSON');
  const array = Array.isArray(value);
  if (!array && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) throw new TypeError('Execution parameters must be plain JSON');
  if (Reflect.ownKeys(value).length !== (array ? value.length + 1 : Object.keys(value).length)) throw new TypeError('Execution parameters contain hidden or sparse fields');
  for (const key of Reflect.ownKeys(value)) {
    if (array && key === 'length') continue;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== 'string' || !descriptor.enumerable || !Object.hasOwn(descriptor, 'value') ||
        (array && (!/^(0|[1-9][0-9]*)$/.test(key) || Number(key) >= value.length))) throw new TypeError('Execution parameters contain hidden fields or accessors');
  }
  seen.add(value);
  const encoded = array ? '[' + Array.from(value, item => canonical(item, seen, depth + 1)).join(',') + ']'
    : '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key], seen, depth + 1)).join(',') + '}';
  seen.delete(value);
  return encoded;
}
const text = value => typeof value === 'string' && value.length > 0;
function freeze(value) {if (value && typeof value === 'object') {Object.values(value).forEach(freeze); Object.freeze(value);} return value;}
const defaults = {
  queued: 'Cancelled while queued; operation was not started',
  cancelled: 'Stopped waiting; operation may still finish. Query the original request; do not automatically resubmit.',
  timeout: 'Execution deadline; state may be incomplete. Query the original request; do not automatically resubmit.',
};
function waitError(message, category) {
  const error = new Error(message); error.executionCategory = category; return error;
}

export class ExecutionCoordinator {
  #pending = []; #active = new Set(); #held = new Set(); #idle = new Set(); #sequence = 0; #pumping = false; #pumpAgain = false;
  #capacity; #clock; #origin; #session = randomUUID(); #observations = new Map(); #maxObservations;

  constructor({capacity = {work: 2, query: 1}, clock = () => performance.now(), maxObservations = 256} = {}) {
    if (!capacity || !['work', 'query'].every(key => Number.isSafeInteger(capacity[key]) && capacity[key] >= 1 && capacity[key] <= 32)) throw new TypeError('Execution capacity needs bounded work and query worker slots');
    if (typeof clock !== 'function' || !Number.isSafeInteger(maxObservations) || maxObservations < 1 || maxObservations > 4096) throw new TypeError('Invalid execution observation configuration');
    this.#capacity = {...capacity}; this.#clock = clock; this.#origin = clock(); this.#maxObservations = maxObservations;
  }

  #now() {return Math.max(0, this.#clock() - this.#origin);}

  #snapshot(receipt) {
    const value = structuredClone(receipt), time = value.timing, now = this.#now();
    time.queueMs = (time.startingAtMs ?? time.closedAtMs ?? now) - time.queuedAtMs;
    time.startMs = time.startingAtMs === null ? null : (time.startedAtMs ?? time.closedAtMs ?? now) - time.startingAtMs;
    time.runMs = time.startedAtMs === null ? null : (time.closedAtMs ?? now) - time.startedAtMs;
    time.waitMs = (time.waitEndedAtMs ?? now) - time.queuedAtMs;
    time.totalMs = (time.closedAtMs ?? now) - time.queuedAtMs;
    return value;
  }

  #trim() {
    for (const [token, receipt] of this.#observations) {
      if (this.#observations.size <= this.#maxObservations) break;
      if (receipt.closed) this.#observations.delete(token);
    }
  }

  list({requestScope, requestId, limit = 50} = {}) {
    const scope = this.#scope(requestScope);
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new TypeError('Observation limit must be 1..100');
    return [...this.#observations.values()].filter(receipt => receipt.requestRef && this.#sameScope(receipt.requestRef, scope) &&
      (requestId === undefined || receipt.requestRef.requestId === requestId)).slice(-limit).map(receipt => this.#snapshot(receipt));
  }

  inspect(executionToken, {requestScope} = {}) {
    const scope = this.#scope(requestScope), receipt = this.#observations.get(executionToken);
    if (!receipt || !receipt.requestRef || !this.#sameScope(receipt.requestRef, scope)) throw new Error('Execution observation not found in the selected provider/workspace/session');
    return this.#snapshot(receipt);
  }

  #scope(scope) {
    if (!scope || !['provider', 'workspace', 'session'].every(key => text(scope[key]))) throw new TypeError('Execution identity needs explicit provider/workspace/session scope');
    return {provider: scope.provider, workspace: scope.workspace, session: scope.session};
  }

  #sameScope(a, b) {return ['provider', 'workspace', 'session'].every(key => a[key] === b[key]);}

  invoke(spec, port, {signal} = {}) {
    return this.#submit(spec, port, signal, 'invoke');
  }

  recover(spec, port, {signal} = {}) {
    if (!text(spec?.requestId)) throw new TypeError('Recovery requires the original saved requestId');
    if (spec.resourceKeys?.length) throw new TypeError('Recovery must not acquire a write resource');
    // No invoke/start port is reachable from recovery, including on failure.
    return this.#submit({...spec, resourceKeys: [], lane: 'query'}, port, signal, 'recover');
  }

  #submit(spec, port, signal, mode) {
    if (!text(spec?.operation) || !(spec.requestId === null || text(spec.requestId))) throw new TypeError('Execution needs an operation and explicit requestId (or null for an inspection)');
    if (!Array.isArray(spec.resourceKeys) || !spec.resourceKeys.every(text)) throw new TypeError('Execution needs provider-supplied resourceKeys');
    if (!Number.isSafeInteger(spec.timeoutMs) || spec.timeoutMs <= 0 || spec.timeoutMs > 2147483647) throw new TypeError('Execution timeoutMs must be a positive bounded integer');
    const start = mode === 'recover' ? port?.query : port?.start;
    if (typeof start !== 'function') throw new TypeError('Execution requires an explicit ' + (mode === 'recover' ? 'query' : 'start') + ' port');
    if (signal && (typeof signal.addEventListener !== 'function' || typeof signal.removeEventListener !== 'function')) throw new TypeError('Invalid execution abort signal');
    const raw = canonical(spec.parameters), parameters = freeze(JSON.parse(raw));
    const resourceKeys = [...new Set(spec.resourceKeys)].sort();
    const lane = spec.lane ?? 'work';
    if (!['work', 'query'].includes(lane) || (lane === 'query' && resourceKeys.length)) throw new TypeError('Query capacity cannot acquire write resources');
    const requestScope = spec.requestScope === undefined ? null : this.#scope(spec.requestScope);
    const messages = {...defaults, ...port.messages};
    const receipt = {receiptVersion: 1, executionId: ++this.#sequence, mode, operation: spec.operation, requestId: spec.requestId,
      executionToken: this.#session + ':' + this.#sequence, requestRef: requestScope ? {...requestScope, requestId: spec.requestId} : null,
      parametersSha256: createHash('sha256').update(raw).digest('hex'), resourceKeys, lane, state: 'queued', waitState: 'waiting', closed: false,
      timing: {queuedAtMs: this.#now(), startingAtMs: null, startedAtMs: null, waitEndedAtMs: null, deadlineAtMs: null, closedAtMs: null}};
    this.#observations.set(receipt.executionToken, receipt); this.#trim();
    let resolveWait, rejectWait, resolveClosed;
    const waiting = new Promise((resolve, reject) => {resolveWait = resolve; rejectWait = reject;});
    const workerDone = new Promise(resolve => {resolveClosed = resolve;});
    const job = {resourceKeys, lane, receipt, workerDone, start, parameters, timeoutMs: spec.timeoutMs, messages, signal,
      resolveClosed, settled: false, started: false, timer: null, port: null};
    job.finishWait = (state, value, failed = false) => {
      if (job.settled) return;
      job.settled = true; receipt.waitState = state;
      receipt.timing.waitEndedAtMs = this.#now();
      signal?.removeEventListener('abort', job.abort);
      (failed ? rejectWait : resolveWait)(value);
    };
    job.abort = () => {
      if (!job.started) {
        this.#pending = this.#pending.filter(item => item !== job);
        receipt.state = 'not_started'; receipt.closed = true;
        receipt.timing.closedAtMs = this.#now();
        job.finishWait('cancelled', waitError(messages.queued, 'cancelled_before_start'), true);
        resolveClosed(); this.#pump();
      } else job.finishWait('cancelled', waitError(messages.cancelled, 'cancelled_wait'), true);
    };
    Object.defineProperties(waiting, {
      workerDone: {value: workerDone},
      receipt: {value: () => this.#snapshot(receipt)},
    });
    this.#pending.push(job);
    signal?.addEventListener('abort', job.abort, {once: true});
    if (signal?.aborted) job.abort(); else this.#pump();
    return waiting;
  }

  #pump() {
    if (this.#pumping) {this.#pumpAgain = true; return;}
    this.#pumping = true;
    try {
      // FIFO for conflicting keys; a blocked task does not stop independent
      // work or resource-free inspection/recovery queries.
      do {
        this.#pumpAgain = false;
        const blocked = new Set();
        for (const job of [...this.#pending]) {
          // Trusted ports can synchronously enqueue or cancel another task.
          // A removed task in this snapshot must never be started.
          if (!this.#pending.includes(job)) continue;
          if (job.resourceKeys.some(key => this.#held.has(key) || blocked.has(key))) {
            job.receipt.queueReason = 'resource';
            job.resourceKeys.forEach(key => blocked.add(key)); continue;
          }
          if ([...this.#active].filter(active => active.lane === job.lane).length >= this.#capacity[job.lane]) {job.receipt.queueReason = 'capacity'; continue;}
          this.#pending.splice(this.#pending.indexOf(job), 1);
          this.#active.add(job); job.resourceKeys.forEach(key => this.#held.add(key));
          this.#start(job);
        }
      } while (this.#pumpAgain);
    } finally {this.#pumping = false;}
    this.#notifyIdle();
  }

  #start(job) {
    job.started = true; job.receipt.state = 'starting'; job.receipt.queueReason = null;
    job.receipt.timing.startingAtMs = this.#now();
    let operation;
    try {
      operation = job.start(job.parameters);
    } catch (error) {
      job.receipt.state = 'failed'; job.finishWait('failed', error, true); this.#release(job); return;
    }
    if (!operation || typeof operation.result?.then !== 'function' || typeof operation.closed?.then !== 'function' ||
        (operation.requestStop !== undefined && typeof operation.requestStop !== 'function')) {
      // A malformed adapter may already have started work. Fail closed: never
      // infer that work is gone, or release its resources from a bad contract.
      Promise.resolve(operation?.result).catch(() => {});
      Promise.resolve(operation?.closed).catch(() => {});
      job.receipt.state = 'unknown';
      job.finishWait('failed', waitError('Provider returned an invalid execution lifecycle; resource retained', 'lifecycle'), true);
      return;
    }
    job.port = operation;
    job.receipt.state = 'running'; job.receipt.timing.startedAtMs = this.#now();
    job.timer = setTimeout(() => {
      job.receipt.deadlineReached = true;
      job.receipt.timing.deadlineAtMs = this.#now();
      job.finishWait('timed_out', waitError(job.messages.timeout, 'deadline'), true);
      // Cancellation detaches the waiter only. The resource guard remains
      // active until close; a stop request/false/error is never proof of exit.
      job.receipt.stopRequested = !job.receipt.closed && typeof operation.requestStop === 'function';
      try {Promise.resolve(job.receipt.closed ? undefined : operation.requestStop?.()).catch(error => {job.receipt.stopError = String(error?.message ?? error);});}
      catch (error) {job.receipt.stopError = String(error?.message ?? error);}
    }, job.timeoutMs);
    Promise.resolve(operation.result).then(value => {
      job.resultSettled = true; if (job.receipt.closed) clearTimeout(job.timer);
      if (!job.lifecycleFailed) job.receipt.state = 'completed';
      job.finishWait('completed', value);
    }, error => {
      job.resultSettled = true; if (job.receipt.closed) clearTimeout(job.timer);
      if (!job.lifecycleFailed) job.receipt.state = 'failed';
      job.receipt.error = {category: error?.executionCategory ?? 'provider_failure', message: String(error?.message ?? error)};
      job.finishWait('failed', error, true);
    });
    Promise.resolve(operation.closed).then(() => this.#release(job), error => {
      // A rejected close promise is a broken adapter, not proof of closure.
      job.lifecycleFailed = true; job.receipt.state = 'unknown';
      job.finishWait('failed', waitError('Provider closure was not confirmed; resource retained: ' + String(error), 'lifecycle'), true);
    });
  }

  #release(job) {
    job.receipt.closed = true;
    job.receipt.timing.closedAtMs = this.#now(); this.#trim();
    if (job.resultSettled || !job.port) clearTimeout(job.timer);
    this.#active.delete(job); job.resourceKeys.forEach(key => this.#held.delete(key));
    job.resolveClosed(); this.#pump();
  }

  whenIdle(resourceKey) {
    if (resourceKey !== undefined && !text(resourceKey)) throw new TypeError('Invalid idle resource key');
    const busy = () => [...this.#pending, ...this.#active].some(job => resourceKey === undefined || job.resourceKeys.includes(resourceKey));
    if (!busy()) return Promise.resolve();
    return new Promise(resolve => this.#idle.add({busy, resolve}));
  }

  #notifyIdle() {
    for (const waiter of this.#idle) if (!waiter.busy()) {this.#idle.delete(waiter); waiter.resolve();}
  }
}
