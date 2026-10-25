#!/usr/bin/env node
// Explicit saved-response encoder. This imports only a pure schema validator;
// it never constructs NativeBridge, opens a socket, imports DM or runs scripts.
import fs from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {validateNativeDataSnapshot, validateNativeLineProfile, validateNativeHistogram, nativeScientificSemantics, validRequestId} from '../lib/native_bridge.mjs';

const requireThat = (condition, message) => { if (!condition) throw new Error(message); };
const sha = value => createHash('sha256').update(value).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const equal = (a, b) => canonical(a) === canonical(b);
const utc = () => new Date().toISOString();
const reserved = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i;

// JSON.parse alone silently accepts duplicate keys. Evidence may not do so.
export function strictJson(text) {
  let i = 0;
  const space = () => { while (/\s/.test(text[i] || '') && i < text.length) ++i; };
  function value() {
    space(); const first = text[i];
    if (first === '"') {
      const start = i++;
      while (i < text.length) { if (text[i] === '\\') { i += 2; continue; } if (text[i++] === '"') return JSON.parse(text.slice(start, i)); }
      throw new Error('Unterminated JSON string');
    }
    if (first === '[' || first === '{') {
      const array = first === '['; ++i; const out = array ? [] : {}; space();
      if (text[i] === (array ? ']' : '}')) { ++i; return out; }
      for (;;) {
        if (array) out.push(value());
        else {
          space(); requireThat(text[i] === '"', 'JSON object key required'); const key = value();
          requireThat(!Object.hasOwn(out, key) && key !== '__proto__', 'Duplicate or unsafe JSON key'); space();
          requireThat(text[i++] === ':', 'JSON colon required'); out[key] = value();
        }
        space(); const end = text[i++]; if (end === (array ? ']' : '}')) return out;
        requireThat(end === ',', 'JSON separator required');
      }
    }
    for (const [token, result] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(token, i)) { i += token.length; return result; }
    }
    const number = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(i));
    requireThat(number, 'Invalid JSON value'); i += number[0].length;
    const result = Number(number[0]); requireThat(Number.isFinite(result), 'Nonfinite JSON number'); return result;
  }
  const result = value(); space(); requireThat(i === text.length, 'Trailing JSON data'); return result;
}

function wellFormed(value) {
  if (typeof value === 'string') {
    for (let i = 0; i < value.length; ++i) {
      const unit = value.charCodeAt(i);
      if (unit >= 0xd800 && unit <= 0xdbff) { const low = value.charCodeAt(++i); requireThat(low >= 0xdc00 && low <= 0xdfff, 'Unpaired Unicode surrogate'); }
      else requireThat(unit < 0xdc00 || unit > 0xdfff, 'Unpaired Unicode surrogate');
    }
  } else if (Array.isArray(value)) value.forEach(wellFormed);
  else if (object(value)) for (const [key, entry] of Object.entries(value)) {
    requireThat(/^[\x20-\x7e]+$/.test(key), 'Evidence keys must be ASCII'); wellFormed(entry);
  }
}

// Match the existing schema-1 Python canonical JSON metadata digest. Integers
// written by JSON.stringify are read as Python ints; floats use Python's
// exponent threshold and two-digit exponent spelling. Input values are bounded
// native metadata, not arbitrary JSON numeric lexemes.
export function canonical(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') {
    requireThat(Number.isFinite(value), 'Nonfinite metadata'); const token = JSON.stringify(value);
    if (!/[.e]/i.test(token)) return token;
    if (Math.abs(value) >= 1e-4 && Math.abs(value) < 1e16) return token;
    const [mantissa, exponent] = value.toExponential().split('e');
    const n = Number(exponent); return mantissa + 'e' + (n >= 0 ? '+' : '-') + String(Math.abs(n)).padStart(2, '0');
  }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  requireThat(object(value), 'Unsupported metadata type');
  return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
}

function bytesAt(filename, limit = 1024 * 1024) {
  const stat = fs.lstatSync(filename); requireThat(stat.isFile() && !stat.isSymbolicLink() && stat.size <= limit, 'Bounded ordinary file required');
  const data = fs.readFileSync(filename); requireThat(data.length <= limit, 'File grew beyond budget'); return data;
}
function decodeUtf8(bytes) { return new TextDecoder('utf-8', {fatal: true}).decode(bytes); }
function jsonAt(filename) { return strictJson(decodeUtf8(bytesAt(filename))); }
function writeAll(fd, bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    const written = fs.writeSync(fd, bytes, offset, bytes.length - offset, offset);
    requireThat(Number.isSafeInteger(written) && written > 0 && written <= bytes.length - offset, 'File write made no progress or reported invalid length');
    offset += written;
  }
}
function writeFd(fd, value) { const bytes = Buffer.from(JSON.stringify(value, null, 2) + '\n'); fs.ftruncateSync(fd, 0); writeAll(fd, bytes); fs.fsyncSync(fd); }
function writeNew(filename, bytes) { const fd = fs.openSync(filename, 'wx'); try { writeAll(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); } }
function within(root, candidate) { const relative = path.relative(root, candidate); return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative)); }
export function newTarget(workspace, relative) {
  requireThat(typeof relative === 'string' && relative && !path.isAbsolute(relative) && !/[:\x00-\x1f]/.test(relative), 'Output must be a new relative subdirectory');
  const parts = relative.split(/[\\/]/); requireThat(parts.every(part => part && part !== '.' && part !== '..' && !/[. ]$/.test(part) && !reserved.test(part)), 'Unsafe output subdirectory');
  const target = path.join(workspace, ...parts), parent = fs.realpathSync(path.dirname(target));
  requireThat(within(workspace, parent) && fs.statSync(parent).isDirectory(), 'Output parent must already exist inside workspace');
  return {target: path.join(parent, parts.at(-1)), relative: path.relative(workspace, path.join(parent, parts.at(-1)))};
}

export function validateSavedSnapshot(raw) {
  let payload = strictJson(decodeUtf8(raw));
  if (object(payload) && Object.hasOwn(payload, 'content')) {
    requireThat(payload.isError !== true && Array.isArray(payload.content) && payload.content.length === 1 &&
      payload.content[0]?.type === 'text' && typeof payload.content[0].text === 'string', 'A single successful MCP text result is required; previews are not numeric input');
    payload = strictJson(payload.content[0].text);
  }
  requireThat(object(payload), 'Saved MCP text JSON object required'); wellFormed(payload);
  const receipt = payload.native_receipt;
  requireThat(object(receipt) && receipt.protocol === 'NB2' && typeof receipt.session === 'string' && /^[a-f0-9]{32}$/.test(receipt.session) &&
    validRequestId(receipt.id) && receipt.request_id === receipt.id && receipt.state === 'completed' &&
    ((receipt.original_operation === 'READ' && receipt.result_type === 'native_data_snapshot') ||
      (receipt.original_operation === 'PROFILE' && receipt.result_type === 'native_line_profile') ||
      (receipt.original_operation === 'HISTOGRAM' && receipt.result_type === 'native_histogram')) && receipt.result_version === 1 &&
    ['host_pid', 'exec_tid', 'worker_tid'].every(key => Number.isInteger(receipt[key]) && receipt[key] > 0 && receipt[key] <= 0xffffffff) &&
    object(receipt.timings_us) && Object.keys(receipt.timings_us).length === 2 &&
    ['queue', 'execute'].every(key => Number.isSafeInteger(receipt.timings_us[key]) && receipt.timings_us[key] >= 0) &&
    receipt.exec_tid !== receipt.worker_tid && !['result', 'error', 'code'].some(key => Object.hasOwn(receipt, key)), 'Original completed NB2 READ/PROFILE/HISTOGRAM receipt required');
  const {native_receipt: ignored, ...result} = payload; void ignored;
  if (receipt.original_operation === 'PROFILE') validateNativeLineProfile(result, receipt.normalized_args, receipt.id);
  else if (receipt.original_operation === 'HISTOGRAM') {
    validateNativeHistogram(result, receipt.normalized_args, receipt.id);
    requireThat(result.axis_mode === 'bin_index', 'Only the qualified native histogram bin-index axis may be handed off');
  }
  else {
    validateNativeDataSnapshot(result, receipt.normalized_args);
    nativeScientificSemantics(result, {requireFourierContext: true});
  }
  const values = Buffer.from(result.values_base64, 'base64');
  requireThat(values.length <= 65536, 'Native snapshot byte budget exceeded');
  const nativeValues = receipt.original_operation === 'HISTOGRAM' ? histogramCountBytes(result.shape, values) : values;
  return {result, receipt, values, ...(receipt.original_operation === 'HISTOGRAM' ? {nativeValues, wireHash:sha(values)} : {}),
    receiptHash: sha(canonical(receipt)), snapshotHash: sha(raw), pixelHash: sha(nativeValues)};
}

// This is an exact transport conversion, not a histogram computation. The DM
// result is uint32 storage read through GetRealValue's binary64 return type.
// Never write the wire doubles to an NPY advertised as native count storage.
function histogramCountBytes(shape, values) {
  requireThat(Array.isArray(shape) && shape.length === 1 && Number.isInteger(shape[0]) && shape[0] >= 2 && shape[0] <= 4096 &&
    Buffer.isBuffer(values) && values.length === shape[0]*8, 'Bounded true 1D histogram shape/binary64 bytes required');
  const counts = Buffer.alloc(shape[0]*4);
  for (let i=0;i<shape[0];++i) {
    const value = values.readDoubleLE(i*8);
    requireThat(Number.isFinite(value) && Number.isInteger(value) && value >= 0 && value <= 0xffffffff,
      'Histogram transport values must be exact uint32 counts');
    counts.writeUInt32LE(value,i*4);
  }
  return counts;
}

export function encodeHistogramNpy(shape, values) {
  const counts = histogramCountBytes(shape, values);
  const dict = `{'descr': '<u4', 'fortran_order': False, 'shape': (${shape[0]},), }`;
  const padding = (64 - ((10 + Buffer.byteLength(dict) + 1) % 64)) % 64;
  const header = Buffer.from(dict + ' '.repeat(padding) + '\n', 'ascii');
  const prefix = Buffer.from([0x93,0x4e,0x55,0x4d,0x50,0x59,1,0,0,0]); prefix.writeUInt16LE(header.length,8);
  return Buffer.concat([prefix,header,counts]);
}

export function encodeProfileNpy(shape, values) {
  requireThat(Array.isArray(shape) && shape.length === 1 && Number.isInteger(shape[0]) && shape[0] >= 2 && shape[0] <= 4096 &&
    Buffer.isBuffer(values) && values.length === shape[0]*8, 'Bounded true 1D float64 shape/bytes required');
  for (let i=0;i<shape[0];++i) requireThat(Number.isFinite(values.readDoubleLE(i*8)), 'Nonfinite profile sample');
  const dict = `{'descr': '<f8', 'fortran_order': False, 'shape': (${shape[0]},), }`;
  const padding = (64 - ((10 + Buffer.byteLength(dict) + 1) % 64)) % 64;
  const header = Buffer.from(dict + ' '.repeat(padding) + '\n', 'ascii');
  const prefix = Buffer.from([0x93,0x4e,0x55,0x4d,0x50,0x59,1,0,0,0]); prefix.writeUInt16LE(header.length,8);
  return Buffer.concat([prefix,header,values]);
}

export function encodeNpy(shape, values, dtype = 'float32') {
  const descriptor = dtype === 'float32' ? '<f4' : dtype === 'uint32' ? '<u4' : null;
  requireThat(Array.isArray(shape) && shape.length === 2 && shape.every(n => Number.isSafeInteger(n) && n > 0) &&
    descriptor && shape[0] * shape[1] <= 16384 && values.length === shape[0] * shape[1] * 4, 'Bounded float32/uint32 shape/bytes required');
  return Buffer.concat([encodeNpyHeader(shape, dtype), values]);
}

export function encodeNpyHeader(shape, dtype = 'float32') {
  const descriptor = dtype === 'float32' ? '<f4' : dtype === 'uint32' ? '<u4' : null;
  requireThat(Array.isArray(shape) && shape.length === 2 && shape.every(n => Number.isSafeInteger(n) && n > 0) &&
    shape[0]*shape[1] <= 4194304 && descriptor, 'Bounded 2D numeric NPY header required');
  const dict = `{'descr': '${descriptor}', 'fortran_order': False, 'shape': (${shape[0]}, ${shape[1]}), }`;
  const padding = (64 - ((10 + Buffer.byteLength(dict) + 1) % 64)) % 64;
  const header = Buffer.from(dict + ' '.repeat(padding) + '\n', 'ascii');
  const prefix = Buffer.from([0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59, 1, 0, 0, 0]); prefix.writeUInt16LE(header.length, 8);
  return Buffer.concat([prefix, header]);
}

export function packageInfo(snapshot, captureId, npy) {
  const {result, receipt, pixelHash, snapshotHash, receiptHash} = snapshot;
  if (receipt?.original_operation === 'HISTOGRAM') return {
    schema_version:1, capture_id:captureId, capture_mode:'native_histogram', shape:result.shape,
    dtype:'uint32', native_storage_dtype:'uint32', byte_order:'little', array_order:'C',
    axes:['bin_index'], axis_roles:[{numpy_axis:0,dm_dimension:0,role:'bin_index'}],
    source_image_id:result.source_image_id, source_shape_yx:result.source.shape,
    source_metadata:result.source, source_calibration_dm:result.source.calibration,
    histogram_metadata:result.image, histogram_calibration:result.image.calibration,
    calibration_complete:result.image.calibration_complete, axis_mode:result.axis_mode,
    axis_calibration_is_bin_left_edge:false,
    native_calibration_semantics:'native bin-index axis; explicit bin geometry is not a calibrated native intensity axis',
    bins:result.bins, bin_left_edge:result.bin_left_edge, bin_width:result.bin_width,
    requested_range:result.requested_range, binning:result.binning, bin_edge_rule:result.bin_edge_rule,
    source_min:result.source_min, source_max:result.source_max, source_pixels:result.source_pixels,
    range_covers_source:result.range_covers_source, counts_sum:result.counts_sum, counts_complete:result.counts_complete,
    source_intensity_calibration:result.source_intensity_calibration,
    intensity_calibration_applied:false, intensity_semantics:result.intensity_semantics,
    computation:'DM native', operator:result.operator,
    input_file:'input.npy', input_sha256:Buffer.isBuffer(npy)?sha(npy):npy.sha256,
    input_file_bytes:Buffer.isBuffer(npy)?npy.length:npy.byteLength,
    raw_bytes:result.output_bytes, native_storage_bytes:result.output_bytes, sample_count:result.bins,
    pixel_sha256:pixelHash, wire_scalar_dtype:'float64', wire_byte_order:'little',
    wire_encoding:result.counts_encoding, wire_raw_bytes:result.raw_bytes, wire_values_sha256:snapshot.wireHash,
    transport_conversion:'exact finite integral binary64 values to uint32; no histogram calculation or rebinning',
    source_path_included:false, native_receipt:receipt, native_receipt_sha256:receiptHash,
    saved_snapshot_sha256:snapshotHash, native_histogram_result:result,
    snapshot_identity_scope:'immutable stored numeric bytes; source image ID and live pixels remain mutable',
    pixel_capture_atomic:false, dm_file_save:false, external_saved_response_encoding:true,
  };
  if (receipt?.original_operation === 'PROFILE') return {
    schema_version:1, capture_id:captureId, capture_mode:'native_profile', shape:result.shape, dtype:'float64', byte_order:'little', array_order:'C',
    axes:['native_profile_axis'], axis_roles:[{numpy_axis:0,dm_dimension:0,role:'native_profile_axis'}],
    source_image_id:result.source_image_id, source_shape_yx:result.source.shape,
    source_line_xyxy:result.source_gui_line.effective_line, source_gui_line:result.source_gui_line,
    source_calibration_dm:result.source.calibration, profile_calibration:result.image.calibration,
    source_sample_start_xy:result.source_sample_start_xy, source_sample_end_xy:result.source_sample_end_xy, source_sample_step_xy:result.source_sample_step_xy,
    distance_zero:result.distance_zero, distance_step:result.distance_step, distance_unit:result.distance_unit,
    native_calibration_semantics:'native signed profile axis; distance_step is separately derived, not substituted for native scale',
    calibration_complete:true, source_metadata:result.source, profile_metadata:result.image,
    source_intensity_calibration:result.source_intensity_calibration, intensity_calibration:result.intensity_calibration,
    intensity_calibration_applied:false, intensity_semantics:'raw pixel intensity', computation:'DM native', operator:result.operator, width:1,
    input_file:'input.npy', input_sha256:Buffer.isBuffer(npy)?sha(npy):npy.sha256,
    input_file_bytes:Buffer.isBuffer(npy)?npy.length:npy.byteLength, raw_bytes:result.raw_bytes, sample_count:result.sample_count,
    pixel_sha256:pixelHash, source_path_included:false, native_receipt:receipt, native_receipt_sha256:receiptHash, saved_snapshot_sha256:snapshotHash,
    native_profile_result:result, snapshot_identity_scope:'immutable stored numeric bytes; source image ID and live pixels remain mutable',
    pixel_capture_atomic:false, dm_file_save:false, external_saved_response_encoding:true,
  };
  const scientific = nativeScientificSemantics(result, {requireFourierContext: true});
  const sourceCal = result.source.calibration.map((axis, index) => ({...axis, axis: index === 0 ? 'x' : 'y'}));
  const workCal = result.roi_calibration.map((axis, index) => ({...axis, axis: index === 0 ? 'x' : 'y'}));
  return {schema_version: 1, capture_id: captureId, shape_yx: result.shape, dtype: result.dtype, byte_order: 'little', array_order: 'C',
    axes: ['y', 'x'], axis_roles: [{numpy_axis: 0, dm_dimension: 1, role: 'y'}, {numpy_axis: 1, dm_dimension: 0, role: 'x'}],
    source_image_id: result.source_image_id, source_shape_yx: result.source.shape, source_rect_xyxy: result.effective_rect,
    source_rect_convention: 'zero-based half-open [x0,y0,x1,y1]', source_calibration_dm: sourceCal, working_calibration_xy: workCal,
    pixel_coordinate_model: scientific.domain === 'frequency' ?
      'pixel centers at integer x,y; use scientific_semantics.coordinate_axes for Fourier bins; working_calibration_xy is unmodified native DM metadata' :
      'pixel centers at integer x,y; physical value = calibrated_value_at_pixel_zero + index*scale',
    scientific_context: result.scientific_context ?? null, scientific_semantics: scientific,
    native_calibration_semantics: 'native DM calibration; not necessarily mathematical Fourier bin coordinates',
    calibration_complete: result.calibration_complete, source_metadata: result.source,
    intensity_calibration: {origin: null, scale: null, unit: null, status: 'NOT_READ'}, intensity_calibration_applied: false,
    input_file: 'input.npy', input_sha256: Buffer.isBuffer(npy) ? sha(npy) : npy.sha256,
    input_file_bytes: Buffer.isBuffer(npy) ? npy.length : npy.byteLength, raw_bytes: result.raw_bytes,
    sample_count: result.sample_count, pixel_sha256: pixelHash, source_path_included: false,
    native_receipt: receipt, native_receipt_sha256: receiptHash, saved_snapshot_sha256: snapshotHash,
    native_source_provenance: result.source_provenance, native_source_provenance_scope: result.source_provenance_scope,
    coordinate_mapping_policy: result.coordinate_mapping_policy,
    snapshot_identity_scope: 'immutable stored numeric bytes; source image ID and live pixels remain mutable',
    pixel_capture_atomic: false, dm_file_save: false, external_saved_response_encoding: true};
}

function verifyCaptured(target, journal, snapshot, npy) {
  const receipt = journal.capture_receipt;
  requireThat(object(receipt) && receipt.state === 'captured' && receipt.capture_id === journal.capture_id, 'Incomplete capture receipt');
  const manifest = jsonAt(path.join(target, 'capture.json')), info = jsonAt(path.join(target, 'input.json'));
  const expected = packageInfo(snapshot, journal.capture_id, npy);
  requireThat(equal(info, expected) && manifest.state === 'captured' && manifest.capture_id === journal.capture_id &&
    manifest.input_sha256 === info.input_sha256 && manifest.input_metadata_sha256 === sha(canonical(info)) &&
    manifest.source_image_id === info.source_image_id &&
    (snapshot.receipt.original_operation === 'PROFILE' ? equal(manifest.source_line_xyxy,info.source_line_xyxy) :
      snapshot.receipt.original_operation === 'HISTOGRAM' ? manifest.native_result_image_id === info.histogram_metadata.id &&
        manifest.bins === info.bins && manifest.axis_mode === info.axis_mode && manifest.wire_values_sha256 === info.wire_values_sha256 :
        equal(manifest.source_rect_xyxy, info.source_rect_xyxy)), 'Captured metadata/receipt hash mismatch');
  for (const name of ['input.npy', 'input.json', 'capture.json']) requireThat(sha(bytesAt(path.join(target, name))) === receipt.files_sha256[name], 'Captured file hash mismatch: ' + name);
  requireThat(bytesAt(path.join(target, 'input.npy')).equals(npy), 'Captured NPY bytes changed');
  return receipt;
}

export function handoff({workspace: workspaceArg, output, requestId, snapshot: snapshotFile}) {
  requireThat(validRequestId(requestId) && !reserved.test(requestId), 'Explicit safe caller request-id required');
  const workspace = fs.realpathSync(workspaceArg); requireThat(fs.statSync(workspace).isDirectory(), 'Workspace must already exist');
  const {target, relative} = newTarget(workspace, output);
  const snapshotPath = fs.realpathSync(snapshotFile), snapshot = validateSavedSnapshot(bytesAt(snapshotPath));
  const profile = snapshot.receipt.original_operation === 'PROFILE';
  const histogram = snapshot.receipt.original_operation === 'HISTOGRAM';
  const npy = profile ? encodeProfileNpy(snapshot.result.shape,snapshot.values) :
    histogram ? encodeHistogramNpy(snapshot.result.shape,snapshot.values) : encodeNpy(snapshot.result.shape, snapshot.values, snapshot.result.dtype);
  const parameters = {workspace, output: relative, output_requested: output, snapshot_path: snapshotPath,
    snapshot_requested: path.resolve(snapshotFile), saved_snapshot_sha256: snapshot.snapshotHash,
    native_receipt_sha256: snapshot.receiptHash, native_values_sha256: snapshot.wireHash ?? snapshot.pixelHash,
    session: snapshot.receipt.session, native_request_id: snapshot.receipt.id, operation: snapshot.receipt.original_operation, normalized_args: snapshot.receipt.normalized_args};
  const requestDirectory = path.join(workspace, 'handoff-requests');
  try { fs.mkdirSync(requestDirectory); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  requireThat(fs.lstatSync(requestDirectory).isDirectory() && !fs.lstatSync(requestDirectory).isSymbolicLink() &&
    fs.realpathSync(requestDirectory) === requestDirectory, 'Request directory must be an ordinary workspace directory');
  const journalPath = path.join(requestDirectory, requestId + '.json');
  let fd;
  try { fd = fs.openSync(journalPath, 'wx+'); } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    let old;
    try { old = jsonAt(journalPath); } catch {
      return {state: 'UNKNOWN_INCOMPLETE', request_id: requestId, capture_dir: target, automatic_retry: false,
        reason: 'existing request journal cannot be verified; preserved without repair'};
    }
    requireThat(old.request_id === requestId && old.parameters_sha256 === sha(canonical(parameters)) && equal(old.parameters, parameters), 'HANDOFF_CONFLICT: request-id already has different immutable parameters');
    if (old.state !== 'CAPTURED' || !old.capture_receipt || !old.native_receipt)
      return {state: 'UNKNOWN_INCOMPLETE', request_id: requestId, capture_dir: target, automatic_retry: false};
    requireThat(old.native_receipt_sha256 === snapshot.receiptHash && equal(old.native_receipt, snapshot.receipt), 'Stored native receipt hash mismatch');
    return verifyCaptured(target, old, snapshot, npy);
  }
  const created = utc(), captureId = randomUUID().replaceAll('-', '');
  const journal = {schema_version: 1, kind: 'native_snapshot_handoff_request', request_id: requestId, state: 'PREPARED',
    created_utc: created, capture_id: captureId, parameters, parameters_sha256: sha(canonical(parameters)),
    native_receipt: snapshot.receipt, native_receipt_sha256: snapshot.receiptHash};
  let manifestFd, manifest;
  try {
    writeFd(fd, journal); // Immutable request is durable before output mkdir.
    fs.mkdirSync(target); // Atomic exclusive target: no recursive creation.
    const info = packageInfo(snapshot, captureId, npy);
    manifest = {schema_version: 1, capture_id: captureId, state: 'capturing', operation: profile ? 'bounded 1D native profile capture' : 'bounded 2D capture',
      capture_backend: 'saved digitalmicrograph-native READ numeric snapshot', external_saved_response_encoding: true,
      source_image_id: info.source_image_id, source_shape_yx: info.source_shape_yx, source_rect_xyxy: info.source_rect_xyxy,
      source_rect_convention: info.source_rect_convention, source_dtype: info.dtype, source_data_type_code: snapshot.result.source.data_type_code,
      calibration_before: info.source_calibration_dm, memory_estimate_bytes: npy.length + snapshot.values.length,
      memory_budget_bytes: 256 * 1024, pixel_capture_atomic: false,
      capture_consistency: 'independent saved response bytes; live source was not reobserved by this encoder; native READ is not atomic',
      created_utc: created, native_session: snapshot.receipt.session, native_request_id: snapshot.receipt.id,
      handoff_request_id: requestId, native_receipt_sha256: snapshot.receiptHash, saved_snapshot_sha256: snapshot.snapshotHash,
      dm_file_save: false, live_source_reobserved: false};
    if (profile) {
      delete manifest.source_rect_xyxy; delete manifest.source_rect_convention;
      Object.assign(manifest,{capture_mode:'native_profile',shape:info.shape,axes:info.axes,source_line_xyxy:info.source_line_xyxy,
        capture_backend:'saved digitalmicrograph-native PROFILE numeric snapshot',
        source_dtype:snapshot.result.source.dtype, output_dtype:info.dtype,
        capture_consistency:'immutable saved profile response bytes; live source was not reobserved by this encoder; native PROFILE is not atomic'});
    }
    if (histogram) {
      delete manifest.source_rect_xyxy; delete manifest.source_rect_convention;
      Object.assign(manifest,{capture_mode:'native_histogram',operation:'bounded 1D native histogram capture',
        shape:info.shape,axes:info.axes,axis_mode:info.axis_mode,bins:info.bins,native_result_image_id:info.histogram_metadata.id,
        capture_backend:'saved digitalmicrograph-native HISTOGRAM numeric snapshot',
        source_dtype:snapshot.result.source.dtype,output_dtype:info.dtype,native_storage_dtype:info.native_storage_dtype,
        native_storage_bytes:info.native_storage_bytes,wire_scalar_dtype:info.wire_scalar_dtype,wire_byte_order:info.wire_byte_order,
        wire_encoding:info.wire_encoding,wire_raw_bytes:info.wire_raw_bytes,wire_values_sha256:info.wire_values_sha256,
        capture_consistency:'immutable saved histogram response bytes; live source was not reobserved by this encoder; native HISTOGRAM is not atomic'});
    }
    manifestFd = fs.openSync(path.join(target, 'capture.json'), 'wx+'); writeFd(manifestFd, manifest);
    writeNew(path.join(target, 'input.npy'), npy);
    writeNew(path.join(target, 'input.json'), Buffer.from(JSON.stringify(info, null, 2) + '\n'));
    requireThat(bytesAt(path.join(target, 'input.npy')).equals(npy) && equal(jsonAt(path.join(target, 'input.json')), info), 'Output readback mismatch');
    manifest = {...manifest, state: 'captured', calibration_after: info.source_calibration_dm,
      input_sha256: info.input_sha256, input_metadata_sha256: sha(canonical(info)),
      input_metadata_file_sha256: sha(bytesAt(path.join(target, 'input.json'))), pixel_sha256: snapshot.pixelHash,
      descriptor_unchanged: true, descriptor_evidence: 'native READ metadata-before/after contract; no atomic pixel claim', completed_utc: utc()};
    if (profile) manifest.descriptor_evidence = 'native PROFILE source metadata-before/after contract; no atomic pixel claim';
    if (histogram) Object.assign(manifest,{descriptor_unchanged:null,source_descriptor_reobserved:false,
      descriptor_evidence:'saved HISTOGRAM v1 has no source-unchanged attestation; current adapter guards metadata/intensity before/after, but this encoder does not reobserve the source or attest historical records'});
    writeFd(manifestFd, manifest);
    const files = Object.fromEntries(['input.npy', 'input.json', 'capture.json'].map(name => [name, sha(bytesAt(path.join(target, name)))]));
    journal.capture_receipt = {state: 'captured', capture_id: captureId, capture_dir: target, shape_yx: info.shape_yx, dtype: info.dtype,
      source_rect_xyxy: info.source_rect_xyxy, input_sha256: info.input_sha256, request_id: requestId,
      native_session: snapshot.receipt.session, native_request_id: snapshot.receipt.id, files_sha256: files,
      pixel_capture_atomic: false, dm_file_save: false};
    if (profile) {
      delete journal.capture_receipt.shape_yx; delete journal.capture_receipt.source_rect_xyxy;
      Object.assign(journal.capture_receipt,{capture_mode:'native_profile',shape:info.shape,source_line_xyxy:info.source_line_xyxy});
    }
    if (histogram) {
      delete journal.capture_receipt.shape_yx; delete journal.capture_receipt.source_rect_xyxy;
      Object.assign(journal.capture_receipt,{capture_mode:'native_histogram',shape:info.shape,axes:info.axes,
        native_result_image_id:info.histogram_metadata.id,axis_mode:info.axis_mode,bins:info.bins,
        native_storage_bytes:info.native_storage_bytes,wire_raw_bytes:info.wire_raw_bytes,wire_values_sha256:info.wire_values_sha256});
    }
    verifyCaptured(target, journal, snapshot, npy);
    journal.state = 'CAPTURED'; writeFd(fd, journal); return journal.capture_receipt;
  } catch (error) {
    journal.state = 'FAILED'; delete journal.capture_receipt; journal.error = String(error);
    if (manifestFd !== undefined) { try { writeFd(manifestFd, {...manifest, state: 'failed', error: String(error)}); } catch {} }
    try { writeFd(fd, journal); } catch {} throw error;
  } finally { if (manifestFd !== undefined) fs.closeSync(manifestFd); fs.closeSync(fd); }
}

export function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i += 2) {
    const name = argv[i]; requireThat(['--workspace', '--output', '--request-id', '--snapshot'].includes(name) &&
      !Object.hasOwn(options, name) && typeof argv[i + 1] === 'string' && !argv[i + 1].startsWith('--'), 'Usage: --workspace EXISTING_DIR --output NEW_RELATIVE_DIR --request-id ID --snapshot SAVED_MCP_TEXT_JSON');
    options[name] = argv[i + 1];
  }
  requireThat(Object.keys(options).length === 4, 'All four explicit arguments are required');
  const result = handoff({workspace: options['--workspace'], output: options['--output'], requestId: options['--request-id'], snapshot: options['--snapshot']});
  process.stdout.write(JSON.stringify(result) + '\n'); return result.state === 'captured' ? 0 : 1;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); } catch (error) { process.stdout.write(JSON.stringify({state: 'failed', error: String(error)}) + '\n'); process.exitCode = 1; }
}
