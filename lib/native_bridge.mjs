// Experimental NB1 transport only. Never imports or falls back to the Python bridge.
import net from "node:net";
import { randomUUID } from "node:crypto";
import { TextDecoder } from "node:util";

const UINT32_MAX = 0xffffffff;
const RESPONSE_LIMIT = 128 * 1024;
const STATES = new Set(["queued", "running", "completed", "failed", "unknown"]);
const OPERATIONS = new Map([["STATUS", 0], ["DATASETS", 0], ["INFO", 1], ["MEAN", 1], ["SUMMARY", 1], ["CROP", 5], ["SHOW", 1], ["QUERY", 0]]);
const SUMMARY_OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum", "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"];
const own = (object, key) => Object.hasOwn(object, key);
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const uint32 = value => Number.isInteger(value) && value >= 0 && value <= UINT32_MAX;
const finite = value => typeof value === "number" && Number.isFinite(value);

function validateSummary(result, expectedImageId) {
  if (result.backend !== "digitalmicrograph-native" || !uint32(result.image_id) ||
      (expectedImageId !== undefined && result.image_id !== expectedImageId)) {
    throw new Error("SUMMARY image/backend identity mismatch");
  }
  if (![result.minimum, result.maximum, result.sum, result.mean].every(finite)) {
    throw new Error("SUMMARY requires four finite reduction values");
  }
  const image = result.image;
  if (!object(image) || image.id !== result.image_id || image.ndim !== 2 || image.data_type_code !== 2 || image.dtype !== "float32" ||
      typeof image.name !== "string" || !Array.isArray(image.shape) || image.shape.length !== 2 || !image.shape.every(value => uint32(value) && value > 0) ||
      !Array.isArray(image.dm_dimensions) || image.dm_dimensions.length !== 2 || !image.dm_dimensions.every((value, index) => value === image.shape[1 - index]) ||
      image.pixels !== image.shape[0] * image.shape[1] || image.pixels > 4194304 ||
      image.shape_order !== "numpy (last axis is X)" || image.native_mean_supported !== true || image.native_summary_supported !== true ||
      image.coordinate_rule !== "physical(i)=calibrated_value_at_pixel_zero+i*scale") {
    throw new Error("SUMMARY requires matching bounded 2D float32 image metadata");
  }
  if (!Array.isArray(image.calibration) || image.calibration.length !== 2 ||
      !image.calibration.every((axis, index) => {
        if (!object(axis) || axis.dm_dimension !== index || axis.numpy_axis !== 1 - index || axis.size !== image.dm_dimensions[index] ||
            ![axis.origin, axis.calibrated_value_at_pixel_zero, axis.scale].every(value => value === null || finite(value)) ||
            !(axis.unit === null || (typeof axis.unit === "string" && axis.unit.length > 0)) || typeof axis.usable !== "boolean") return false;
        const numbersUsable = [axis.origin, axis.calibrated_value_at_pixel_zero, axis.scale].every(finite) && axis.scale !== 0;
        if (axis.usable) return numbersUsable && axis.unit !== null && axis.issue === null;
        // Raw intensity reductions may report recognized unusable spatial
        // calibration. A raw-scale mismatch is not separately serialized.
        if (axis.issue === "unknown_units") return numbersUsable && axis.unit === null;
        if (axis.issue === "invalid_calibration") return axis.unit !== null;
        return axis.issue === "invalid_calibration_and_unknown_units" && axis.unit === null;
      }) || image.calibration_complete !== image.calibration.every(axis => axis.usable)) {
    throw new Error("SUMMARY requires explicit spatial calibration metadata and issues");
  }
  if (!Array.isArray(result.operators) || result.operators.length !== SUMMARY_OPERATORS.length ||
      !result.operators.every((value, index) => value === SUMMARY_OPERATORS[index]) || result.computation !== "DM native" ||
      result.intensity_calibration_applied !== false || result.intensity_semantics !== "raw pixel intensity" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false) {
    throw new Error("SUMMARY requires native operators and raw intensity semantics");
  }
}

export function validRequestId(value) {
  return typeof value === "string" && value.length >= 1 && value.length <= 64 && !/[^A-Za-z0-9_-]/.test(value);
}

export class NativeBridgeError extends Error {
  constructor(message, {session, requestId, code = "NATIVE_TRANSPORT", sent = false} = {}) {
    super(`${message}; session=${session}; request_id=${requestId}; 已发送操作可能仍在执行，请用 dm_native_result 查询，不要自动重发`);
    this.name = "NativeBridgeError";
    this.details = {protocol: "NB1", session, request_id: requestId, state: "unknown", code, sent, error: this.message};
  }
}

export class NativeBridge {
  constructor({session, timeoutMs = 30000, pollMs = 25} = {}) {
    if (typeof session !== "string" || session.length !== 32 || !/^[a-f0-9]{32}$/.test(session)) {
      throw new Error("DM_NATIVE_SESSION must be exactly 32 lowercase hexadecimal characters from the explicitly started experimental native build");
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 600000) throw new Error("Invalid native timeout");
    if (!Number.isFinite(pollMs) || pollMs < 1 || pollMs > 1000) throw new Error("Invalid native poll interval");
    this.session = session;
    this.pipePath = `\\\\.\\pipe\\dm_mcp_native_${session}`;
    this.timeoutMs = timeoutMs;
    this.pollMs = pollMs;
    this.sockets = new Set();
    this.hostPid = null;
    this.closed = false;
  }

  async execute(operation, args = [], {requestId = randomUUID(), signal, timeoutMs = this.timeoutMs} = {}) {
    this._validateRequest(operation, args, requestId);
    const deadline = this._deadline(timeoutMs);
    let reply = await this._exchange(operation, args, requestId, deadline, signal);
    // Submission is never repeated. QUERY uses the original operation ID.
    const submitted = reply.state === "queued" || reply.state === "running";
    try {
      while (reply.state === "queued" || reply.state === "running") {
        await this._pause(requestId, deadline, signal);
        reply = await this._exchange("QUERY", [], requestId, deadline, signal);
      }
    } catch (error) {
      // `sent` describes the original operation, even when a later QUERY never
      // connected or its deadline expired before creating a new socket.
      if (submitted && error instanceof NativeBridgeError) error.details.sent = true;
      throw error;
    }
    return this._validateOperationResult(operation, args, reply);
  }

  async query(requestId, {signal, timeoutMs = this.timeoutMs} = {}) {
    this._validateRequest("QUERY", [], requestId);
    const reply = await this._exchange("QUERY", [], requestId, this._deadline(timeoutMs), signal);
    return this._validateOperationResult("QUERY", [], reply);
  }

  _validateOperationResult(operation, args, reply) {
    // QUERY deliberately carries no original operation. Recognizable SUMMARY
    // results can still be checked after a client restart in the same session.
    const summary = reply.state === "completed" && (operation === "SUMMARY" ||
      (operation === "QUERY" && ["minimum", "maximum", "sum", "operators"].some(key => own(reply.result, key))));
    if (summary) {
      try { validateSummary(reply.result, operation === "SUMMARY" ? args[0] : undefined); }
      catch (error) { throw this._error(`Invalid native response: ${error.message}`, reply.id, "NATIVE_PROTOCOL", true); }
    }
    return reply;
  }

  _deadline(timeoutMs) {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 600000) throw new Error("Invalid native timeout");
    return Date.now() + timeoutMs;
  }

  _validateRequest(operation, args, requestId) {
    if (!OPERATIONS.has(operation) || !Array.isArray(args) || args.length !== OPERATIONS.get(operation) || !args.every(uint32)) {
      throw new TypeError("Unsupported NB1 operation or invalid unsigned 32-bit arguments");
    }
    if (!validRequestId(requestId)) throw new TypeError("request_id must match [A-Za-z0-9_-]{1,64}");
  }

  _error(message, requestId, code, sent = false) {
    return new NativeBridgeError(message, {session: this.session, requestId, code, sent});
  }

  _pause(requestId, deadline, signal) {
    return new Promise((resolve, reject) => {
      let timer;
      const finish = (error) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        error ? reject(error) : resolve();
      };
      const abort = () => finish(this._error("等待已取消，状态未知", requestId, "NATIVE_CANCELLED", true));
      if (signal?.aborted) return abort();
      if (this.closed) return finish(this._error("Native bridge client closed", requestId, "NATIVE_CLOSED", true));
      if (deadline <= Date.now()) return finish(this._error("Native request timed out，状态未知", requestId, "NATIVE_TIMEOUT", true));
      signal?.addEventListener("abort", abort, {once: true});
      timer = setTimeout(() => finish(), Math.min(this.pollMs, deadline - Date.now()));
    });
  }

  _validateReply(reply, requestId) {
    if (!object(reply) || reply.protocol !== "NB1" || reply.session !== this.session || reply.id !== requestId) {
      throw new Error("NB1 response protocol/session/request identity mismatch");
    }
    if (!STATES.has(reply.state) || !uint32(reply.host_pid) || reply.host_pid === 0 ||
        !uint32(reply.worker_tid) || reply.worker_tid === 0 || !uint32(reply.exec_tid) ||
        !object(reply.timings_us) || ![reply.timings_us.queue, reply.timings_us.execute].every(v => Number.isSafeInteger(v) && v >= 0)) {
      throw new Error("Invalid NB1 state, host/thread identity or timings");
    }
    if (this.hostPid !== null && reply.host_pid !== this.hostPid) throw new Error("NB1 host PID changed within the configured session");
    if (reply.state === "completed") {
      if (!own(reply, "result") || !object(reply.result) || reply.exec_tid === 0 || own(reply, "error") || own(reply, "code")) {
        throw new Error("Invalid NB1 completed result");
      }
    } else if (own(reply, "result")) {
      throw new Error("NB1 non-completed response must not contain a result");
    }
    if (reply.state === "failed") {
      if (typeof reply.error !== "string" || !reply.error || typeof reply.code !== "string" || !reply.code) throw new Error("NB1 failure requires error and code");
    } else if (own(reply, "error") || own(reply, "code")) {
      throw new Error("NB1 error/code may only appear in failed responses");
    }
    this.hostPid = reply.host_pid;
    return reply;
  }

  _exchange(operation, args, requestId, deadline, signal) {
    return new Promise((resolve, reject) => {
      let socket, timer, retryTimer, settled = false, sent = false, bytes = 0;
      const chunks = [];
      const finish = (error, reply) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        clearTimeout(retryTimer);
        signal?.removeEventListener("abort", abort);
        if (socket) { this.sockets.delete(socket); socket.destroy(); }
        error ? reject(error) : resolve(reply);
      };
      const abort = () => finish(this._error("等待已取消，状态未知", requestId, "NATIVE_CANCELLED", sent));
      if (signal?.aborted) return abort();
      if (this.closed) return finish(this._error("Native bridge client closed", requestId, "NATIVE_CLOSED"));
      if (deadline <= Date.now()) return finish(this._error("Native request timed out，状态未知", requestId, "NATIVE_TIMEOUT"));
      const payload = `NB1 ${this.session} ${requestId} ${operation}${args.length ? " " + args.join(" ") : ""}\n`;
      if (Buffer.byteLength(payload, "ascii") > 512) return finish(this._error("NB1 request exceeds 512 bytes", requestId, "NATIVE_PROTOCOL"));
      timer = setTimeout(() => finish(this._error("Native request timed out，状态未知", requestId, "NATIVE_TIMEOUT", sent)), Math.max(1, deadline - Date.now()));
      signal?.addEventListener("abort", abort, {once: true});
      const connect = () => {
      if (settled) return;
      if (this.closed) return finish(this._error("Native bridge client closed", requestId, "NATIVE_CLOSED", sent));
      if (deadline <= Date.now()) return finish(this._error("Native pipe readiness timed out，状态未知", requestId, "NATIVE_TIMEOUT", sent));
      let attempt;
      try { attempt = net.createConnection(this.pipePath); }
      catch (error) { return finish(this._error(`Native pipe connection failed: ${error.message}`, requestId, "NATIVE_CONNECTION")); }
      socket = attempt;
      this.sockets.add(attempt);
      attempt.once("connect", () => {
        if (settled || socket !== attempt) return;
        // A failed write can still have delivered some or all bytes to the host.
        sent = true;
        attempt.write(payload, "ascii", error => {
          if (error) finish(this._error(`Native pipe write failed: ${error.message}`, requestId, "NATIVE_CONNECTION", true));
        });
      });
      attempt.on("data", chunk => {
        if (settled || socket !== attempt) return;
        bytes += chunk.length;
        if (bytes > RESPONSE_LIMIT) return finish(this._error("NB1 response exceeds 128 KiB", requestId, "NATIVE_PROTOCOL", sent));
        chunks.push(chunk);
        if (!chunk.includes(10)) return;
        try {
          const raw = Buffer.concat(chunks, bytes);
          if (raw.length < 2 || raw[raw.length - 1] !== 10 || raw.indexOf(10) !== raw.length - 1) throw new Error("NB1 requires exactly one newline-terminated JSON response");
          const line = new TextDecoder("utf-8", {fatal: true}).decode(raw.subarray(0, -1));
          const parsed = JSON.parse(line, (_key, value) => {
            if (typeof value === "number" && !Number.isFinite(value)) throw new Error("NB1 JSON contains a nonfinite number");
            return value;
          });
          const reply = this._validateReply(parsed, requestId);
          finish(null, reply);
        } catch (error) { finish(this._error(`Invalid native response: ${error.message}`, requestId, "NATIVE_PROTOCOL", sent)); }
      });
      // The host waits briefly for the client to close after receiving its one
      // reply. Parse the complete frame before closing; never wait for host EOF.
      attempt.once("end", () => {
        if (!settled && socket === attempt) finish(this._error("Native pipe ended before a complete JSON frame", requestId, "NATIVE_PROTOCOL", sent));
      });
      attempt.once("error", error => {
        if (settled || socket !== attempt) return;
        if (!sent && (error.code === "ENOENT" || error.code === "EBUSY")) {
          // Waiting for a pipe instance before connect/write is not an
          // operation resend. Never take this path after any write attempt.
          this.sockets.delete(attempt); socket = null; attempt.destroy();
          retryTimer = setTimeout(connect, Math.min(5, Math.max(1, deadline - Date.now())));
          return;
        }
        finish(this._error(`Native pipe error: ${error.message}`, requestId, "NATIVE_CONNECTION", sent));
      });
      attempt.once("close", () => {
        if (!settled && socket === attempt) finish(this._error("Native pipe disconnected before a complete response", requestId, "NATIVE_CONNECTION", sent));
      });
      };
      connect();
    });
  }

  close() {
    this.closed = true;
    for (const socket of this.sockets) socket.destroy(new Error("Native bridge client closed"));
  }
}
