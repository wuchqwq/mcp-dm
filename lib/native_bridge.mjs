// Experimental NB2 transport only. Never imports or falls back to the Python bridge.
import net from "node:net";
import { randomUUID } from "node:crypto";
import { TextDecoder } from "node:util";

const UINT32_MAX = 0xffffffff;
// Every possible uint32 sum remains an exact binary64 integer at this bound.
const UINT32_REDUCTION_PIXELS = Math.floor(Number.MAX_SAFE_INTEGER / UINT32_MAX);
const RESPONSE_LIMIT = 128 * 1024;
const STATES = new Set(["queued", "running", "completed", "failed", "unknown"]);
const OPERATIONS = new Map([["STATUS", 0], ["DATASETS", 0], ["INFO", 1], ["MEAN", 1], ["SUMMARY", 1], ["CROP", 5], ["SHOW", 1], ["UNARY", 2], ["BINARY", 3], ["QUERY", 0]]);
for (const [name, count] of [["FILTER", 2], ["PREVIEW", 3], ["READ", 5], ["FFT", 1], ["IFFT", 1], ["REAL", 1], ["IMAG", 1], ["VENDOR_ARG", 1], ["VENDOR_NORM", 1]]) OPERATIONS.set(name, count);
OPERATIONS.set('RELEASE', 2); OPERATIONS.set('RESULT_INFO', 2);
OPERATIONS.set('ROIS', 1);
OPERATIONS.set('PROFILE', 9);
OPERATIONS.set('HISTOGRAM', 4);
// Central closed result-schema registry. STOP is queryable but is submitted
// only by the explicit lifecycle helper, not through the MCP tool catalog.
const RESULT_TYPES = new Map([
  ["STATUS", "status"], ["DATASETS", "datasets"], ["INFO", "image_info"],
  ["MEAN", "native_mean"], ["SUMMARY", "native_summary"], ["CROP", "image_crop"],
  ["SHOW", "image_delivery"], ["STOP", "ipc_stop"],
  ["UNARY", "native_image_operation"], ["BINARY", "native_image_operation"],
  ["FILTER", "native_image_operation"], ["FFT", "native_fourier_operation"], ["IFFT", "native_fourier_operation"],
  ["REAL", "native_fourier_operation"], ["IMAG", "native_fourier_operation"],
  ["VENDOR_ARG", "native_fourier_operation"], ["VENDOR_NORM", "native_fourier_operation"],
  ["PREVIEW", "native_preview"],
  ["READ", "native_data_snapshot"],
  ['RELEASE', 'native_result_release'], ['RESULT_INFO', 'native_result_availability'],
  ['ROIS', 'native_gui_rois'],
  ['PROFILE', 'native_line_profile'],
  ['HISTOGRAM', 'native_histogram'],
]);
const IDENTITY_FIELDS = ["original_operation", "normalized_args", "result_type", "result_version"];
const SUMMARY_OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum", "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"];
const own = (object, key) => Object.hasOwn(object, key);
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const uint32 = value => Number.isInteger(value) && value >= 0 && value <= UINT32_MAX;
const finite = value => typeof value === "number" && Number.isFinite(value);

export function validateNativeRetention(result, expectedRequestId) {
  const value = result.retention;
  if (value === undefined) return; // Historical NB2 creation records remain queryable.
  if (!object(value) || Object.keys(value).length !== 4 || !uint32(value.token) || value.token === 0 ||
      !validRequestId(value.creation_request_id) || value.creation_request_id !== expectedRequestId ||
      value.state_at_creation !== 'plugin_retained' ||
      value.identity_scope !== 'bridge token in this native session, not a host image ID')
    throw new Error('Invalid native retained creation identity');
}

export function validateNativeResultAvailability(result, operation, args) {
  if (!object(result) || !['RELEASE', 'RESULT_INFO'].includes(operation) || !Array.isArray(args) || args.length !== 2 ||
      !args.every(value => uint32(value) && value > 0) || result.backend !== 'digitalmicrograph-native' ||
      result.image_id !== args[0] || result.retention_token !== args[1] || !validRequestId(result.creation_request_id) ||
      !['plugin_retained','available_for_native_processing','released','released_now'].every(key => typeof result[key] === 'boolean') ||
      result.plugin_retained !== result.available_for_native_processing || result.released === result.plugin_retained ||
      (operation === 'RELEASE' && result.plugin_retained) || (operation === 'RESULT_INFO' && result.released_now) ||
      (result.released_now && !result.released) || !Number.isSafeInteger(result.result_bytes) || result.result_bytes <= 0 || result.result_bytes > 8*1024*1024 ||
      !uint32(result.retained_result_count) || result.retained_result_count > 32 ||
      !Number.isSafeInteger(result.retained_result_bytes) || result.retained_result_bytes < 0 || result.retained_result_bytes > 16*1024*1024 ||
      ((result.retained_result_count === 0) !== (result.retained_result_bytes === 0)) ||
      (result.plugin_retained && (result.retained_result_count === 0 || result.retained_result_bytes < result.result_bytes)) ||
      result.document_closed !== false || result.source_write_requested !== false || result.native_object_existence !== 'not_probed' ||
      result.scope !== 'plugin reference only; shown document may still hold the image; old creation receipt is unchanged')
    throw new Error('Invalid native result availability/release contract');
}

// A GUI snapshot is never an implicit request to analyze the newest/selected
// object. Preserve every reported ROI, including ones that cannot safely be
// handed to the existing integer half-open pixel operations.
// HISTOGRAM keeps DM's own bin counts. The bridge must not present a bridge-side
// binning as native, so every published number is checked against the native
// receipt: exact integral counts, complete totals over the admitted range and an
// explicit axis mode.
function floatFromBits(bits) {
  const buffer = new ArrayBuffer(4);
  new Uint32Array(buffer)[0] = bits;
  return new Float32Array(buffer)[0];
}

const HISTOGRAM_AXIS_TOLERANCE = 'binary32_local_ulp_v1';
const HISTOGRAM_AXIS_FIELDS = ['axis_zero_requested','axis_zero_observed','axis_scale_observed',
  'axis_roundtrip_error','axis_roundtrip_bound','axis_max_coordinate_error','axis_tolerance','axis_unavailable_reason'];
function float32Ulp(value) {
  const bytes=Buffer.alloc(4);bytes.writeFloatLE(Math.abs(value));const bits=bytes.readUInt32LE();
  if (bits===0) return 2**-149;
  bytes.writeUInt32LE(bits-1);const below=bytes.readFloatLE();
  const lower=Math.abs(value)-below;
  if (bits===0x7f7fffff) return Infinity;
  bytes.writeUInt32LE(bits+1);return Math.max(lower,bytes.readFloatLE()-Math.abs(value));
}
function histogramAxisPlan(minimum,binWidth,bins) {
  const width=Math.fround(binWidth),normal=value=>finite(value) && (value===0 || Math.abs(value)>=2**-126);
  if (!finite(width) || width<2**-126) return null;
  const quotient=Math.fround(minimum/width),zero=Math.fround(quotient*width);
  if (!normal(quotient) || !normal(zero) || minimum!==0 && (quotient===0 || zero===0)) return null;
  const bound=float32Ulp(quotient)*Math.abs(width)+float32Ulp(zero);
  const maxError=bound+Math.abs(width-binWidth)*(bins-1);
  if (!finite(bound) || !finite(maxError) || Math.abs(zero-minimum)>bound || !(maxError<binWidth/4)) return null;
  return {width,quotient,zero,bound,maxError};
}

// The same closed axis contract is used by creation, historical QUERY, SHOW's
// frozen creation context and the saved-response encoder. A unit label or a
// caller-supplied tolerance never qualifies a physical axis on its own.
function validateHistogramAxis(context,image) {
  const bins=context.bins,range=context.requested_range,source=context.source_intensity_calibration,axis=image.calibration[0];
  if (!uint32(bins) || bins<2 || bins>4096 || image.shape[0]!==bins ||
      !Array.isArray(range) || range.length!==2 || !range.every(finite) || !(range[0]<range[1]) ||
      range.some(value=>Math.fround(value)!==value) || context.bin_left_edge!==range[0] ||
      context.bin_width!==(range[1]-range[0])/bins || !object(source) || Object.keys(source).length!==3 ||
      !finite(source.origin) || !finite(source.scale) || !(source.unit===null || typeof source.unit==='string' && source.unit.length>0))
    throw new Error('HISTOGRAM axis source/range/geometry context mismatch');
  if (context.axis_mode==='bin_index') {
    if (context.axis_calibration_is_bin_left_edge!==false || image.calibration_complete!==false ||
        axis.origin!==0 || axis.calibrated_value_at_pixel_zero!==0 || axis.scale!==1 || axis.unit!==null || axis.usable!==false)
      throw new Error('HISTOGRAM bin-index axis must not claim a calibrated intensity axis');
    const supplied=HISTOGRAM_AXIS_FIELDS.filter(key=>own(context,key));
    // The original axis-display audit emitted these unused zero placeholders
    // even for bin_index. Recognize that exact historical shape without using
    // its superseded tolerance as permission for a physical intensity axis.
    const legacy=['axis_zero_requested','axis_zero_observed','axis_scale_observed','axis_roundtrip_error','axis_tolerance'];
    if (supplied.length===legacy.length && legacy.every(key=>own(context,key)) &&
        legacy.slice(0,4).every(key=>context[key]===0) &&
        context.axis_tolerance==='binary32 divide/multiply round trip: 8 ulp of max(|origin|,|scale|,1)') return;
    if (supplied.length && (supplied.length!==HISTOGRAM_AXIS_FIELDS.length ||
        HISTOGRAM_AXIS_FIELDS.slice(0,6).some(key=>context[key]!==null) || context.axis_tolerance!==HISTOGRAM_AXIS_TOLERANCE ||
        !['source_intensity_calibration_not_identity','source_intensity_units_unavailable',
          'axis_entrypoint_unavailable','binary32_axis_not_resolved'].includes(context.axis_unavailable_reason)))
      throw new Error('HISTOGRAM bin-index axis cannot carry a forged calibration observation');
    if (supplied.length) {
      const identity=source.origin===0 && source.scale===1,unit=typeof source.unit==='string';
      const reason=context.axis_unavailable_reason;
      if ((reason==='source_intensity_calibration_not_identity' && identity) ||
          (reason==='source_intensity_units_unavailable' && (!identity || unit)) ||
          (['axis_entrypoint_unavailable','binary32_axis_not_resolved'].includes(reason) && (!identity || !unit)) ||
          (reason==='binary32_axis_not_resolved' && histogramAxisPlan(range[0],context.bin_width,bins)!==null))
        throw new Error('HISTOGRAM bin-index fallback reason contradicts its source/axis plan');
    }
    return;
  }
  const plan=histogramAxisPlan(range[0],context.bin_width,bins);
  if (context.axis_mode!=='source_intensity_units' || source.origin!==0 || source.scale!==1 ||
      typeof source.unit!=='string' || !source.unit || !plan ||
      context.axis_calibration_is_bin_left_edge!==true || image.calibration_complete!==true ||
      axis.unit!==source.unit || axis.usable!==true || axis.issue!==null ||
      axis.origin!==-plan.quotient || axis.calibrated_value_at_pixel_zero!==plan.zero || axis.scale!==plan.width ||
      context.axis_zero_requested!==range[0] || context.axis_zero_observed!==axis.calibrated_value_at_pixel_zero ||
      context.axis_scale_observed!==axis.scale || context.axis_roundtrip_error!==Math.abs(plan.zero-range[0]) ||
      context.axis_roundtrip_bound!==plan.bound || context.axis_max_coordinate_error!==plan.maxError ||
      context.axis_tolerance!==HISTOGRAM_AXIS_TOLERANCE || context.axis_unavailable_reason!==null)
    throw new Error('HISTOGRAM intensity axis requires the exact identity-intensity native roundtrip contract');
}
export function validateNativeHistogram(result, args, requestId) {
  if (!object(result) || !Array.isArray(args) || args.length !== 4 || !args.every(uint32) || args[1] < 2 || args[1] > 4096)
    throw new Error('HISTOGRAM requires id, 2..4096 bins and a native float32 range');
  const [sourceId, bins, minBits, maxBits] = args;
  const minimum = floatFromBits(minBits), maximum = floatFromBits(maxBits);
  // Split into narrow checks so a failure names the field that disagrees.
  if (result.backend !== 'digitalmicrograph-native' || result.operation !== 'HISTOGRAM' ||
      result.source_image_id !== sourceId || !uint32(result.image_id) || result.image_id === 0 || result.image_id === sourceId ||
      result.candidate_probe === true || result.qualification === 'NOT_QUALIFIED' ||
      result.bins !== bins || result.range_covers_source !== true || result.counts_complete !== true ||
      result.operator !== 'GMSImageProcessing::CalcHistogram' || result.computation !== 'DM native' ||
      result.intensity_calibration_applied !== false || result.source_write_requested !== false ||
      result.snapshot_atomic !== false || result.dtype !== 'uint32' ||
      !Array.isArray(result.axes) || result.axes.length !== 1 || result.axes[0] !== 'intensity_bin' ||
      result.binning !== 'uniform linear bins over the caller range; the range must cover the complete native source minimum/maximum' ||
      result.bin_edge_rule !== 'left edge at range_min, width = (max-min)/bins' ||
      result.counts_encoding !== 'exact uint32 counts little-endian binary64 payload' ||
      result.intensity_semantics !== 'raw pixel intensity counts per bin' ||
      result.ownership !== 'plugin retained strong reference until normal native STOP/cleanup; shown document may retain image' ||
      !['bin_index','source_intensity_units'].includes(result.axis_mode)) {
    throw new Error('HISTOGRAM identity/operator/native binning contract mismatch');
  }
  validateImageMetadata(result.source, sourceId, false, {requireReductions:false});
  if (result.source.dtype !== 'float32' || result.source.packing_style !== 1 || result.source.pixels !== result.source_pixels)
    throw new Error('HISTOGRAM source descriptor/pixel count mismatch');
  // The caller range must be the exact binary32 value the bridge received; no
  // silent widening into a different admitted interval.
  if (!Array.isArray(result.requested_range) || result.requested_range.length !== 2 ||
      result.requested_range[0] !== minimum || result.requested_range[1] !== maximum ||
      !(minimum < maximum) || !Number.isFinite(minimum) || !Number.isFinite(maximum) ||
      result.bin_left_edge !== minimum || result.bin_width !== (maximum - minimum) / bins) {
    throw new Error('HISTOGRAM requested range/bin width mismatch');
  }
  if (!Number.isSafeInteger(result.source_pixels) || result.source_pixels < 1 || result.source_pixels > 4194304 ||
      !Number.isSafeInteger(result.counts_sum) || result.counts_sum !== result.source_pixels ||
      !Array.isArray(result.shape) || result.shape.length !== 1 || result.shape[0] !== bins ||
      result.raw_bytes !== bins * 8 || result.output_bytes !== bins * 4 ||
      !finite(result.source_min) || !finite(result.source_max) || result.source_min > result.source_max ||
      minimum > result.source_min || maximum < result.source_max) {
    throw new Error('HISTOGRAM counts/shape/budget or source-range coverage mismatch');
  }
  if (typeof result.values_base64 !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(result.values_base64) ||
      result.values_base64.length % 4 !== 0) throw new Error('HISTOGRAM counts encoding is not canonical base64');
  const bytes = Buffer.from(result.values_base64, 'base64');
  if (bytes.length !== bins * 8 || bytes.toString('base64') !== result.values_base64) throw new Error('HISTOGRAM counts payload length/canonical encoding mismatch');
  let total = 0;
  for (let i = 0; i < bins; ++i) {
    const count = bytes.readDoubleLE(i * 8);
    if (!Number.isFinite(count) || count < 0 || Math.trunc(count) !== count || count > result.source_pixels) {
      throw new Error('HISTOGRAM counts must be exact non-negative native doubles');
    }
    total += count;
  }
  if (total !== result.counts_sum) throw new Error('HISTOGRAM counts payload total mismatch');
  validateOneDimensionalDisplay(result.image, result.image_id, 'HISTOGRAM');
  validateHistogramAxis(result,result.image);
  if (!object(result.retention)) throw new Error('HISTOGRAM retained creation identity required');
  validateNativeRetention(result, requestId ?? result.retention.creation_request_id);
  return result;
}

export function validateNativeGuiRois(result, expectedImageId, version = 2) {
  const objectId = value => uint32(value) && value <= 0x7fffffff;
  if (![1, 2].includes(version) || !uint32(expectedImageId) || !object(result) || result.backend !== 'digitalmicrograph-native' || result.image_id !== expectedImageId ||
      result.candidate_probe === true || result.qualification === 'NOT_QUALIFIED' ||
      result.coordinate_rule !== 'half-open pixel rectangle [x0,y0,x1,y1]; no rounding or clipping' ||
      result.source_write_requested !== false || result.snapshot_atomic !== false ||
      !Array.isArray(result.displays) || result.displays.length > 16)
    throw new Error('Invalid native GUI ROI source/snapshot contract');
  validateImageMetadata(result.image, expectedImageId, false, {requireReductions: false, allowUint32: true});
  if (result.image.packing_style !== 1) throw new Error('Native GUI ROI source requires ordinary packing');
  const displays = new Set();
  let total = 0;
  for (const display of result.displays) {
    if (!object(display) || !objectId(display.document_id) || !objectId(display.display_id) ||
        !object(display.display_identity) || Object.keys(display.display_identity).length !== 2 ||
        display.display_identity.document_id !== display.document_id || display.display_identity.display_id !== display.display_id ||
        Object.hasOwn(display, 'selected_dimensions') || !Array.isArray(display.rois))
      throw new Error('Invalid native GUI display composite identity');
    const key = `${display.document_id}:${display.display_id}`;
    if (displays.has(key)) throw new Error('Duplicate native GUI display identity');
    displays.add(key);
    if (display.display_type === 'unsupported') {
      if (display.issue !== 'unsupported_display_type' || display.slice_ids !== null || display.source_layout !== null || display.roi_count !== null || display.rois.length)
        throw new Error('Unsupported display must not impersonate a successful empty raster');
      continue;
    }
    if (display.display_type !== 'raster' || display.issue !== null || !Array.isArray(display.slice_ids) ||
        display.slice_ids.length > 5 || !display.slice_ids.every(uint32) ||
        !['direct_image_canonical_xy', 'unsupported'].includes(display.source_layout) || !uint32(display.roi_count) ||
        display.roi_count !== display.rois.length || display.roi_count > 64 || (total += display.roi_count) > 128)
      throw new Error('Invalid native GUI raster ROI count/budget');
    const rois = new Set();
    for (const roi of display.rois) {
      if (!object(roi) || !objectId(roi.roi_id) || rois.has(roi.roi_id) || typeof roi.selected !== 'boolean' ||
          !finite(roi.rotation_degrees) || typeof roi.analysis_eligible !== 'boolean') throw new Error('Invalid native GUI ROI identity/rotation/selection');
      rois.add(roi.roi_id);
      if (version === 2 && (!own(roi, 'raw_line') || !own(roi, 'line'))) throw new Error('ROIS v2 requires explicit line fields');
      if (version === 1 && (own(roi, 'raw_line') || own(roi, 'line'))) throw new Error('Historical ROIS v1 has no line fields');
      if (roi.type !== 'line' && version === 2 && (roi.raw_line !== null || roi.line !== null)) throw new Error('Non-line ROI must not claim line geometry');
      if (roi.type === 'line') {
        if (version !== 2 || roi.raw_rectangle !== null || roi.rect !== null || !object(roi.raw_line) || Object.keys(roi.raw_line).length !== 4 ||
            !['x0','y0','x1','y1'].every(key => finite(roi.raw_line[key]))) throw new Error('Invalid native GUI line geometry');
        const line = ['x0','y0','x1','y1'].map(key => roi.raw_line[key]);
        const {direct, normalized} = validateGuiMapping(roi.coordinate_mapping, result.image.shape, display.source_layout, display.slice_ids);
        const [x0,y0,x1,y1] = line;
        const issue = roi.rotation_degrees !== 0 ? 'rotated_line' : !direct ? 'unsupported_image_source' : !normalized ? 'unsupported_coordinate_mapping' :
          x0 === x1 && y0 === y1 ? 'empty_line' : line.some(value => !Number.isInteger(value)) ? 'fractional_line' :
          x0 !== x1 && y0 !== y1 ? 'unsupported_line_orientation' :
          x0 < 0 || y0 < 0 || x1 < 0 || y1 < 0 || x0 >= result.image.shape[1] || x1 >= result.image.shape[1] || y0 >= result.image.shape[0] || y1 >= result.image.shape[0] ? 'out_of_bounds_line' :
          Math.floor(Math.hypot(x1-x0,y1-y0))+1 > 4096 ? 'line_sample_budget' : null;
        if (roi.issue !== issue || roi.analysis_eligible !== (issue === null) ||
            (issue !== null ? roi.line !== null : !Array.isArray(roi.line) || roi.line.length !== 4 || !roi.line.every((value,index) => value === line[index])))
          throw new Error('Native GUI line eligibility/coordinates mismatch');
        continue;
      }
      if (roi.type === 'unsupported') {
        if (roi.raw_rectangle !== null || roi.coordinate_mapping !== null || roi.rect !== null || roi.analysis_eligible !== false || roi.issue !== 'unsupported_roi_type')
          throw new Error('Unsupported ROI must never become an analysis rectangle');
        continue;
      }
      if (roi.type !== 'rectangle' || !object(roi.raw_rectangle) || Object.keys(roi.raw_rectangle).length !== 4 ||
          !['top', 'left', 'bottom', 'right'].every(name => finite(roi.raw_rectangle[name])))
        throw new Error('Native GUI rectangle requires four original finite coordinates');
      const mapping = roi.coordinate_mapping;
      if (!object(mapping) || Object.keys(mapping).length !== 5 ||
          !Array.isArray(mapping.offset) || mapping.offset.length !== 2 || !mapping.offset.every(finite) ||
          !Array.isArray(mapping.scale) || mapping.scale.length !== 2 || !mapping.scale.every(value => finite(value) && value !== 0))
        throw new Error('Native GUI rectangle requires a finite nonzero native coordinate mapping');
      const identity = mapping.offset.every(value => value === 0) && mapping.scale.every(value => value === 1);
      if (mapping.identity !== identity) throw new Error('Native GUI rectangle coordinate mapping identity mismatch');
      const direct = display.source_layout === 'direct_image_canonical_xy' && display.slice_ids.length === 1 && display.slice_ids[0] === 0;
      const normalized = mapping.offset.every(value => value === 0) &&
        mapping.scale.every((value, index) => value === Math.fround(1 / Math.fround(result.image.shape[1 - index])));
      if (mapping.space !== 'source_pixel_to_normalized_display' || mapping.source_pixel_aligned !== (direct && normalized))
        throw new Error('Native GUI rectangle coordinate space/source alignment mismatch');
      const raw = roi.raw_rectangle, rect = [raw.left, raw.top, raw.right, raw.bottom];
      const issue = roi.rotation_degrees !== 0 ? 'rotated_rectangle' : !direct ? 'unsupported_image_source' :
        !normalized ? 'unsupported_coordinate_mapping' : raw.right <= raw.left || raw.bottom <= raw.top ? 'empty_or_reversed_rectangle' :
        rect.some(value => !Number.isInteger(value)) ? 'fractional_rectangle' :
        raw.left < 0 || raw.top < 0 || raw.right > result.image.shape[1] || raw.bottom > result.image.shape[0] ? 'out_of_bounds_rectangle' : null;
      if (roi.issue !== issue || roi.analysis_eligible !== (issue === null) ||
          (issue !== null ? roi.rect !== null : !Array.isArray(roi.rect) || roi.rect.length !== 4 || !roi.rect.every((value, index) => value === rect[index])))
        throw new Error('Native GUI rectangle eligibility/coordinates mismatch; no rounding or clipping');
    }
  }
}

function validateGuiMapping(mapping, shape, layout, slices) {
  if (!object(mapping) || Object.keys(mapping).length !== 5 ||
      !Array.isArray(mapping.offset) || mapping.offset.length !== 2 || !mapping.offset.every(finite) ||
      !Array.isArray(mapping.scale) || mapping.scale.length !== 2 || !mapping.scale.every(value => finite(value) && value !== 0))
    throw new Error('Native GUI ROI requires finite nonzero mapping');
  const identity = mapping.offset.every(value => value === 0) && mapping.scale.every(value => value === 1);
  const direct = layout === 'direct_image_canonical_xy' && Array.isArray(slices) && slices.length === 1 && slices[0] === 0;
  const normalized = mapping.offset.every(value => value === 0) && mapping.scale.every((value,index) => value === Math.fround(1/Math.fround(shape[1-index])));
  if (mapping.identity !== identity || mapping.space !== 'source_pixel_to_normalized_display' || mapping.source_pixel_aligned !== (direct && normalized))
    throw new Error('Native GUI ROI coordinate space/source alignment mismatch');
  return {direct, normalized};
}

// Only PROFILE admits true one-dimensional f64. Existing 2D tools stay 2D.
export function validateNativeLineProfile(result, args, requestId) {
  const fail = message => { throw new Error('Invalid native line profile: ' + message); };
  const matches = (a,b) => Array.isArray(a) && a.length === b.length && a.every((v,i) => v === b[i]);
  if (!Array.isArray(args) || args.length !== 9 || !args.every(uint32) || args.slice(1,4).some(v => v > 0x7fffffff) || args[8] !== 1) fail('arguments');
  const [sourceId,docId,displayId,roiId,x0,y0,x1,y1] = args, line = [x0,y0,x1,y1];
  const n = Math.floor(Math.hypot(x1-x0,y1-y0))+1;
  if ((x0 === x1 && y0 === y1) || (x0 !== x1 && y0 !== y1) || n > 4096) fail('line geometry/budget');
  if (!object(result) || result.backend !== 'digitalmicrograph-native' || result.operation !== 'PROFILE' || result.source_image_id !== sourceId ||
      !uint32(result.image_id) || result.image_id === 0 || result.image_id === sourceId || result.candidate_probe === true || result.qualification === 'NOT_QUALIFIED') fail('identity/qualification');
  validateImageMetadata(result.source, sourceId, false, {requireReductions:false,allowUint32:true});
  const source = result.source;
  if (source.packing_style !== 1 || source.calibration_complete !== true || x0 >= source.shape[1] || x1 >= source.shape[1] || y0 >= source.shape[0] || y1 >= source.shape[0] ||
      source.calibration[0].scale !== source.calibration[1].scale || source.calibration[0].unit !== source.calibration[1].unit) fail('source calibration/bounds');
  const binding = result.source_gui_line;
  if (!object(binding) || binding.document_id !== docId || binding.display_id !== displayId || binding.roi_id !== roiId || binding.rotation_degrees !== 0 ||
      !object(binding.raw_line) || Object.keys(binding.raw_line).length !== 4 || !matches(['x0','y0','x1','y1'].map(k => binding.raw_line[k]),line) || !matches(binding.effective_line,line)) fail('GUI line binding');
  const mapped = validateGuiMapping(binding.coordinate_mapping, source.shape, binding.source_layout, binding.slice_ids);
  if (!mapped.direct || !mapped.normalized) fail('GUI source/mapping');
  const image = result.image, axis = image?.calibration?.[0], sourceAxis = source.calibration[0];
  if (!object(image) || image.id !== result.image_id || typeof image.name !== 'string' || image.ndim !== 1 || image.dtype !== 'float64' || image.data_type_code !== 12 ||
      image.packing_style !== 1 || !matches(image.shape,[n]) || !matches(image.dm_dimensions,[n]) || image.pixels !== n || image.shape_order !== 'one-dimensional native profile samples' ||
      image.native_mean_supported !== false || image.native_summary_supported !== false || image.calibration_complete !== true ||
      image.coordinate_rule !== 'physical(i)=calibrated_value_at_pixel_zero+i*scale' || !Array.isArray(image.calibration) || image.calibration.length !== 1 ||
      !object(axis) || axis.dm_dimension !== 0 || axis.numpy_axis !== 0 || axis.size !== n || axis.origin !== 0 || axis.calibrated_value_at_pixel_zero !== 0 ||
      axis.scale !== sourceAxis.scale || axis.unit !== sourceAxis.unit || axis.usable !== true || axis.issue !== null) fail('true 1D native f64 metadata/calibration');
  if (!matches(result.shape,[n]) || result.dtype !== 'float64' || !matches(result.axes,['native_profile_axis']) || result.byte_order !== 'little' || result.array_order !== 'C' || result.data_encoding !== 'base64' ||
      result.sample_count !== n || result.raw_bytes !== n*8 || result.output_bytes !== n*8 || result.width !== 1 || result.calibration_complete !== true ||
      !matches(result.source_sample_start_xy,[x0,y0]) || !matches(result.source_sample_end_xy,[x1,y1]) || !matches(result.source_sample_step_xy,[(x1-x0)/(n-1),(y1-y0)/(n-1)]) ||
      result.distance_zero !== 0 || result.distance_step !== Math.abs(sourceAxis.scale) || result.distance_unit !== sourceAxis.unit) fail('shape/trajectory/native axis semantics');
  const intensity = result.intensity_calibration, originalIntensity = result.source_intensity_calibration;
  if (![intensity,originalIntensity].every(value => object(value) && Object.keys(value).length === 3 && finite(value.origin) && finite(value.scale) &&
      (value.unit === null || typeof value.unit === 'string' && value.unit.length > 0)) ||
      !['origin','scale','unit'].every(key => intensity[key] === originalIntensity[key])) fail('intensity metadata copy');
  if (result.operator !== 'LiveProfile_ExtractLineProfile' || result.computation !== 'DM native' || result.source_write_requested !== false || result.snapshot_atomic !== false ||
      result.intensity_calibration_applied !== false || result.intensity_semantics !== 'raw pixel intensity' ||
      result.ownership !== 'plugin retained strong reference until normal native STOP/cleanup; shown document may retain image') fail('native execution/ownership/raw semantics');
  if (typeof result.values_base64 !== 'string' || result.values_base64.length !== 4*Math.ceil(n*8/3)) fail('bounded bytes');
  const bytes = Buffer.from(result.values_base64,'base64');
  if (bytes.length !== n*8 || bytes.toString('base64') !== result.values_base64) fail('canonical f64 bytes');
  for (let i=0;i<n;++i) if (!Number.isFinite(bytes.readDoubleLE(i*8))) fail('nonfinite sample');
  if (!object(result.retention)) fail('retained creation identity required');
  validateNativeRetention(result, requestId ?? result.retention.creation_request_id);
}

function validateSummary(result, expectedImageId) {
  if (result.backend !== "digitalmicrograph-native" || !uint32(result.image_id) ||
      (expectedImageId !== undefined && result.image_id !== expectedImageId)) {
    throw new Error("SUMMARY image/backend identity mismatch");
  }
  if (![result.minimum, result.maximum, result.sum, result.mean].every(finite)) {
    throw new Error("SUMMARY requires four finite reduction values");
  }
  validateImageMetadata(result.image, result.image_id, false, {allowUint32: true});
  if (result.image.dtype === "uint32" && (!uint32(result.minimum) || !uint32(result.maximum) ||
      result.minimum > result.maximum || !Number.isSafeInteger(result.sum) || result.sum < 0 ||
      result.sum < result.minimum * result.image.pixels || result.sum > result.maximum * result.image.pixels ||
      result.sum > result.image.pixels * UINT32_MAX || result.mean < result.minimum || result.mean > result.maximum)) {
    throw new Error("SUMMARY uint32 reductions exceed exact integer/range bounds");
  }
  if (!Array.isArray(result.operators) || result.operators.length !== SUMMARY_OPERATORS.length ||
      !result.operators.every((value, index) => value === SUMMARY_OPERATORS[index]) || result.computation !== "DM native" ||
      result.intensity_calibration_applied !== false || result.intensity_semantics !== "raw pixel intensity" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false) {
    throw new Error("SUMMARY requires native operators and raw intensity semantics");
  }
}

function validateMean(result, expectedImageId) {
  if (!finite(result.mean)) throw new Error("MEAN requires a finite numeric mean");
  // Historical synthetic transports deliberately have no genuine image metadata.
  // A real native receipt must bind the supported source type and raw semantics.
  if (result.backend !== "digitalmicrograph-native") return;
  if (result.image_id !== expectedImageId) throw new Error("MEAN image/backend identity mismatch");
  validateImageMetadata(result.image, expectedImageId, false, {requireReductions: false, allowUint32: true});
  if (result.image.native_mean_supported !== true || (result.image.dtype === "uint32" && result.image.pixels > UINT32_REDUCTION_PIXELS)) {
    throw new Error("MEAN requires eligible bounded native image metadata");
  }
  if (result.operator !== "GMSImageProcessing::GetMean" || result.computation !== "DM native" ||
      result.intensity_calibration_applied !== false || result.intensity_semantics !== "raw pixel intensity" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false ||
      (result.image.dtype === "uint32" && (result.mean < 0 || result.mean > UINT32_MAX))) {
    throw new Error("MEAN native raw semantics/uint32 range mismatch");
  }
}

function validateUint32Crop(result, args) {
  // Keep the old float32 crop receipt reader compatible; uint32 is newly typed.
  if (![result.source, result.image].some(image => image?.dtype === "uint32" || image?.data_type_code === 11)) return;
  validateImageMetadata(result.source, args[0], false, {requireReductions: false, allowUint32: true});
  validateImageMetadata(result.image, result.image_id, false, {requireReductions: false, allowUint32: true});
  const [x0, y0, x1, y1] = args.slice(1), width = x1 - x0, height = y1 - y0;
  if (result.backend !== "digitalmicrograph-native" || result.source.dtype !== "uint32" || result.image.dtype !== "uint32" ||
      result.source.packing_style !== 1 || result.image.packing_style !== 1 ||
      result.source.calibration_complete !== true || result.image.calibration_complete !== true ||
      x1 > result.source.shape[1] || y1 > result.source.shape[0] ||
      result.image.shape[0] !== height || result.image.shape[1] !== width ||
      result.output_bytes !== width * height * 4 || result.output_bytes > 4 * 1024 * 1024 ||
      !result.source.calibration.every((axis, index) => axis.scale === result.image.calibration[index].scale && axis.unit === result.image.calibration[index].unit) ||
      result.operator !== "GMS::Image::GetSubSliceAsImage" || result.computation !== "DM native independent pixel copy" ||
      result.visible_dm_document !== false || result.source_write_requested !== false || result.snapshot_atomic !== false) {
    throw new Error("CROP uint32 dtype/shape/calibration/native copy mismatch");
  }
}

function validateImageMetadata(image, expectedId, complex = false, {requireReductions = true, allowUint32 = false} = {}) {
  const unsigned = !complex && allowUint32 && image?.dtype === "uint32";
  if (!object(image) || image.id !== expectedId || image.ndim !== 2 || image.data_type_code !== (complex ? 3 : unsigned ? 11 : 2) || image.dtype !== (complex ? "complex64" : unsigned ? "uint32" : "float32") ||
      (unsigned && (image.is_integer !== true || image.is_unsigned !== true || image.packing_style !== 1)) ||
      typeof image.name !== "string" || !Array.isArray(image.shape) || image.shape.length !== 2 || !image.shape.every(value => uint32(value) && value > 0) ||
      !Array.isArray(image.dm_dimensions) || image.dm_dimensions.length !== 2 || !image.dm_dimensions.every((value, index) => value === image.shape[1 - index]) ||
      image.pixels !== image.shape[0] * image.shape[1] || image.pixels > (unsigned && requireReductions ? UINT32_REDUCTION_PIXELS : 4194304) ||
      image.shape_order !== "numpy (last axis is X)" || typeof image.native_mean_supported !== "boolean" || typeof image.native_summary_supported !== "boolean" ||
      (requireReductions && (image.native_mean_supported !== !complex || image.native_summary_supported !== !complex)) ||
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
}

function validateDerivedOperation(result, operation, args, version = 1) {
  const fourier = operation !== "FILTER", complexSource = fourier && operation !== "FFT";
  const complexOutput = operation === "FFT" || operation === "IFFT";
  const definitions = {
    FFT: ["Real_FFT", "full_complex"], IFFT: ["IFFT", "full_complex"], REAL: ["Real", "real_component"],
    IMAG: ["Imag", "imaginary_component"], VENDOR_ARG: ["Arg", "vendor_arg"], VENDOR_NORM: ["Norm", "vendor_norm"],
  };
  if (version === 2) {
    definitions.VENDOR_ARG[1] = "phase_radians";
    definitions.VENDOR_NORM[1] = "squared_magnitude";
  }
  const filters = {1: "SmoothFilter", 2: "SobelFilter", 3: "LaplaceFilter", 4: "SharpenFilter"};
  const name = fourier ? definitions[operation][0] : filters[args[1]];
  if (!name || result.backend !== "digitalmicrograph-native" || result.operation !== operation || result.source_image_id !== args[0] ||
      !uint32(result.image_id) || result.image_id === 0 || result.image_id === args[0] || result.operator !== "GMSImageProcessing::" + name ||
      result.computation !== "DM native" || typeof result.ownership !== "string" || !result.ownership ||
      typeof result.semantics !== "string" || !result.semantics || result.visible_dm_document !== false ||
      result.source_write_requested !== false || result.snapshot_atomic !== false) throw new Error("Native derived operation identity/ownership mismatch");
  const unsignedSource = result.source?.dtype === "uint32" || result.source?.data_type_code === 11;
  const unsignedOutput = operation === "FILTER" && unsignedSource && [1, 4].includes(args[1]);
  const outputDtype = complexOutput ? "complex64" : unsignedOutput ? "uint32" : "float32";
  validateImageMetadata(result.source, args[0], complexSource, {allowUint32: operation === "FILTER" || (operation === "FFT" && version === 2)});
  if (unsignedSource && result.image?.dtype !== outputDtype) throw new Error("Native operation output dtype differs from per-operation matrix");
  validateImageMetadata(result.image, result.image_id, complexOutput, {allowUint32: unsignedOutput});
  if (unsignedSource || own(result, "dtype_semantics")) {
    validateNativeDtypeSemantics(result, [result.source], outputDtype);
  }
  if (unsignedSource && (result.source.calibration_complete !== true || result.image.calibration_complete !== true)) {
    throw new Error("Native uint32 derived calibration mismatch");
  }
  if ([result.source, result.image].some(image => image.packing_style !== 1) ||
      !result.source.shape.every((value, index) => value === result.image.shape[index])) throw new Error("Native derived operation packing/shape mismatch");
  const pixels = result.image.pixels;
  if (fourier) {
    // Version 1 remains the historical bounded vendor-defined record. Newer
    // dimensions do not retroactively qualify those old semantics.
    const maximumDimension = version === 2 ? 1024 : 256;
    const maximumPixels = version === 2 ? 1048576 : 65536;
    if (pixels > maximumPixels || result.image.shape.some(value => value > maximumDimension) || result.representation !== definitions[operation][1] ||
        (version === 1 && (result.normalization !== "vendor_defined" || result.centering !== "vendor_defined" || result.phase_units !== "vendor_defined")) ||
        result.output_bytes !== pixels * (complexOutput ? 8 : 4) || result.validation_peak_new_image_bytes !== pixels * (complexOutput ? 12 : 4)) {
      throw new Error("Native Fourier representation/budget/vendor semantics mismatch");
    }
    if (version === 2) validateFourierV2(result, operation);
  } else {
    if (result.filter_kind !== args[1] || result.kernel !== "vendor_defined" || result.edge_behavior !== "vendor_defined" ||
        pixels > 65536 || result.image.shape.some(value => value < 5 || value > 256) ||
        result.output_bytes !== pixels * 4 || result.output_bytes > 4 * 1024 * 1024 ||
        result.validation_peak_new_image_bytes !== pixels * (args[1] === 2 ? 8 : 4) ||
        !result.source.calibration.every((axis, index) => ["origin", "calibrated_value_at_pixel_zero", "scale", "unit"].every(key => axis[key] === result.image.calibration[index][key]))) {
      throw new Error("Native filter kind/budget/calibration/vendor semantics mismatch");
    }
  }
}

function validateFourierV2(result, operation) {
  const source = result.source, image = result.image;
  const component = !["FFT", "IFFT"].includes(operation);
  const centered = result.centering === "fftshift_data";
  const reciprocalStep = (size, scale) => Math.fround(1 / Math.fround(size * scale));
  if (image.shape.some(value => value < 4 || value > 1024 || (value & (value - 1)) !== 0) ||
      source.calibration_complete !== true || image.calibration_complete !== true ||
      result.normalization !== (operation === "FFT" ? "none" : operation === "IFFT" ? "1/(width*height)" : "inherited_parent_transform") ||
      !["fftshift_data", "spatial_origin_zero"].includes(result.centering) ||
      (operation === "FFT" && !centered) || (operation === "IFFT" && centered) ||
      result.phase_units !== (operation === "VENDOR_ARG" ? "radians" : "not_applicable") ||
      !object(result.transform_signs) || Object.keys(result.transform_signs).length !== 2 || result.transform_signs.forward !== "+" || result.transform_signs.inverse !== "-" ||
      result.input_index_origin !== "zero-based pixel indices" || result.source_spatial_origin_used !== false ||
      result.intensity_calibration_applied !== false || result.inverse_restores_source_origin !== false ||
      typeof result.intensity_calibration_policy !== "string" || !result.intensity_calibration_policy) {
    throw new Error("Native Fourier v2 convention/calibration contract mismatch");
  }
  if (component && !source.calibration.every((axis, index) => ["origin", "calibrated_value_at_pixel_zero", "scale", "unit"].every(key => axis[key] === image.calibration[index][key]))) {
    throw new Error("Native Fourier v2 component calibration changed");
  }
  if (!centered) {
    if (result.frequency_grid !== null || image.calibration.some(axis => axis.origin !== 0 || axis.calibrated_value_at_pixel_zero !== 0) ||
        (operation === "IFFT" && !image.calibration.every((axis, index) => axis.scale === reciprocalStep(axis.size, source.calibration[index].scale)))) {
      throw new Error("Native Fourier v2 spatial origin/frequency grid mismatch");
    }
    return;
  }
  const grid = result.frequency_grid;
  if (!object(grid) || grid.native_calibration_has_half_bin_offset !== true || !Array.isArray(grid.axes) || grid.axes.length !== 2 ||
      !grid.axes.every((axis, index) => {
        const native = image.calibration[index], size = native.size;
        return object(axis) && axis.dm_dimension === index && axis.size === size && axis.dc_index === size / 2 &&
          axis.cycles_per_pixel_step === 1 / size && axis.physical_frequency_step === native.scale && axis.unit === native.unit &&
          axis.frequency_at_index_zero === -size / 2 * native.scale &&
          axis.native_calibrated_value_at_pixel_zero === native.calibrated_value_at_pixel_zero &&
          axis.native_calibration_dc_value === native.calibrated_value_at_pixel_zero + size / 2 * native.scale &&
          native.origin === (size + 1) / 2 &&
          (operation !== "FFT" || native.scale === reciprocalStep(size, source.calibration[index].scale)) &&
          axis.coordinate_rule === "f(i)=(i-dc_index)*physical_frequency_step";
      })) throw new Error("Native Fourier v2 mathematical frequency grid/native half-bin mismatch");
}

function validateImageOperation(result, operation, args) {
  const unary = operation === "UNARY", opcode = args.at(-1), ids = args.slice(0, -1);
  const names = unary ? {1: ["negate", "GMSImageProcessing::Negate"], 2: ["abs", "GMSImageProcessing::Abs"], 3: ["square", "GMSImageProcessing::Square"]}
    : {1: ["add", "GMSImageProcessing::operator+"], 2: ["subtract", "GMSImageProcessing::operator-"], 3: ["multiply", "GMSImageProcessing::operator*"]};
  if (!own(names, opcode) || result.backend !== "digitalmicrograph-native" || !uint32(result.image_id) || ids.includes(result.image_id) ||
      result.operation !== names[opcode][0] || result.opcode !== opcode || result.operator !== names[opcode][1] ||
      !Array.isArray(result.source_image_ids) || result.source_image_ids.length !== ids.length || !result.source_image_ids.every((id, index) => id === ids[index]) ||
      !Array.isArray(result.sources) || result.sources.length !== ids.length || typeof result.ownership !== "string" || !result.ownership ||
      result.computation !== "DM native" || result.intensity_calibration_applied !== false || result.intensity_semantics !== "raw pixel intensity" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false) throw new Error("Native image operation identity/raw semantics mismatch");
  const unsignedInputs = result.sources.some(source => source?.dtype === "uint32" || source?.data_type_code === 11);
  if (unsignedInputs) {
    // Native unary/binary output storage is binary32 for uint32 inputs.
    // Mixed scalar input types remain outside this explicit contract.
    if (result.sources.some(source => source?.dtype !== "uint32")) {
      throw new Error("Native uint32 operation input/output dtype is not admitted");
    }
    validateNativeDtypeSemantics(result, result.sources, "float32");
    if (result.image.calibration_complete !== true || result.sources.some(source => source.calibration_complete !== true) ||
        result.image.pixels > 1048576 || result.output_bytes !== result.image.pixels * 4 || result.visible_dm_document !== false) {
      throw new Error("Native uint32 operation calibration/output budget mismatch");
    }
  } else if (own(result, "dtype_semantics")) {
    validateNativeDtypeSemantics(result, result.sources, "float32");
  }
  validateImageMetadata(result.image, result.image_id);
  if (result.image.packing_style !== 1) throw new Error("Native image operation packing mismatch");
  result.sources.forEach((source, index) => {
    validateImageMetadata(source, ids[index], false, {allowUint32: unsignedInputs});
    if (source.packing_style !== 1 || !source.shape.every((value, axis) => value === result.image.shape[axis]) ||
        !source.calibration.every((axis, dimension) => ["origin", "calibrated_value_at_pixel_zero", "scale", "unit"].every(key => axis[key] === result.image.calibration[dimension][key]))) {
      throw new Error("Native image operation source/output shape/packing/calibration mismatch");
    }
  });
}

function validateNativeDtypeSemantics(result, sources, outputDtype) {
  const semantics = result.dtype_semantics;
  const precision = outputDtype === "float32" ? "binary32 result; not lossless for arbitrary uint32 inputs" :
    outputDtype === "uint32" ? "uint32 native result storage" : "complex binary32 result; not lossless for arbitrary uint32 inputs";
  if (!object(result.image) || !object(semantics) || Object.keys(semantics).length !== 4 || !Array.isArray(semantics.input_dtypes) ||
      semantics.input_dtypes.length !== sources.length || !semantics.input_dtypes.every((dtype, index) => dtype === sources[index].dtype) ||
      result.image.dtype !== outputDtype || semantics.output_dtype !== outputDtype ||
      semantics.selection !== "DM native operator output; no bridge pixel cast" || semantics.precision !== precision) {
    throw new Error("Native uint32 dtype_semantics/input/output precision mismatch");
  }
}

// A rank-one result is delivered through its own admission group. It keeps a
// true [N] shape and one native axis; it is never presented as a fabricated
// [1,N] raster and never reuses the 2D image descriptor schema. PROFILE carries
// native float64 samples, HISTOGRAM native uint32 bin counts.
function validateOneDimensionalDisplay(display, imageId, operation) {
  const code = operation === 'HISTOGRAM' ? 11 : 12;
  const dtype = operation === 'HISTOGRAM' ? 'uint32' : 'float64';
  if (!object(display) || display.id !== imageId || display.ndim !== 1 || display.data_type_code !== code ||
      display.dtype !== dtype || display.packing_style !== 1 ||
      !Array.isArray(display.shape) || display.shape.length !== 1 ||
      !uint32(display.shape[0]) || display.shape[0] < 2 || display.shape[0] > 4096 ||
      display.pixels !== display.shape[0] || !Array.isArray(display.dm_dimensions) ||
      display.dm_dimensions.length !== 1 || display.dm_dimensions[0] !== display.shape[0] ||
      !Array.isArray(display.calibration) || display.calibration.length !== 1 ||
      typeof display.name !== 'string' || display.native_mean_supported !== false || display.native_summary_supported !== false ||
      (operation === 'HISTOGRAM' && (display.is_integer !== true || display.is_unsigned !== true)) ||
      display.coordinate_rule !== 'physical(i)=calibrated_value_at_pixel_zero+i*scale' ||
      display.shape_order !== (operation === 'HISTOGRAM' ? 'one-dimensional native histogram bins'
        : 'one-dimensional native profile samples')) {
    throw new Error('SHOW 1D display descriptor mismatch');
  }
  if (operation === 'HISTOGRAM' && !(display.calibration_complete === true || display.calibration_complete === false)) {
    throw new Error('SHOW 1D histogram display requires an explicit axis completeness flag');
  }
  if (operation === 'PROFILE' && display.calibration_complete !== true) {
    throw new Error('SHOW 1D profile display requires a complete native axis');
  }
  const axis = display.calibration[0];
  const numeric = [axis?.origin, axis?.calibrated_value_at_pixel_zero, axis?.scale].every(finite);
  if (!object(axis) || !numeric || axis.scale === 0 || axis.dm_dimension !== 0 || axis.numpy_axis !== 0 || axis.size !== display.shape[0] ||
      !(axis.unit === null || (typeof axis.unit === 'string' && axis.unit.length > 0))) {
    throw new Error('SHOW 1D display requires one explicit native axis');
  }
  if (display.calibration_complete) {
    if (!numeric || axis.scale === 0 || typeof axis.unit !== 'string' || axis.unit.length === 0 || axis.usable !== true) {
      throw new Error('SHOW 1D display complete axis is inconsistent');
    }
  } else if (operation === 'HISTOGRAM') {
    // An uncalibrated histogram axis is an honest bin index, never a claim.
    if (axis.usable !== false || typeof axis.issue !== 'string' || !axis.issue || axis.unit !== null) {
      throw new Error('SHOW 1D histogram display must report its axis issue');
    }
  } else {
    throw new Error('SHOW 1D display complete axis is inconsistent');
  }
}

function validateShow(result, imageId) {
  if (!object(result) || !uint32(imageId) || imageId === 0 || result.image_id !== imageId || result.delivery !== "visible_dm_document" || result.document_visible !== true) {
    throw new Error("SHOW result identity/delivery mismatch");
  }
  const is1d = own(result, 'one_dimensional_display');
  const styleKeys=['display_style','display_style_scope','display_style_reason'];
  const hasStyle=styleKeys.some(key=>own(result,key));
  if ((own(result,'histogram_axis_context') || hasStyle) && (!is1d || result.retained_operation!=='HISTOGRAM'))
    throw new Error('SHOW histogram axis/style context requires a true histogram result');
  if (!is1d && ['rank','display_family','display_class','retained_operation'].some(key => own(result,key)))
    throw new Error('SHOW rank-one identity requires its true one-dimensional descriptor');
  // Older NB2 v1 SHOW records have no descriptor. When the newer descriptor is
  // present, validate its actual type; a UI receipt never means a file was saved
  // or that an MCP model visually inspected it.
  if (!is1d && !own(result, "image")) return;
  if (is1d) {
    const operation = result.retained_operation;
    if (result.rank !== 1 || !['PROFILE', 'HISTOGRAM'].includes(operation) ||
        result.display_family !== 'native_1d_image_document' || result.display_class !== 'host_selected' ||
        own(result, 'image')) {
      throw new Error("SHOW 1D delivery must not claim a 2D descriptor");
    }
    validateOneDimensionalDisplay(result.one_dimensional_display, imageId, operation);
    if (operation==='HISTOGRAM') {
      if (own(result,'histogram_axis_context')) {
        if (!object(result.histogram_axis_context)) throw new Error('SHOW histogram requires a frozen axis context');
        validateHistogramAxis(result.histogram_axis_context,result.one_dimensional_display);
      } else {
        // Historical bin-index SHOWs remain recognizable; an arbitrary complete
        // axis never gains admission merely through a descriptor/unit label.
        const image=result.one_dimensional_display,axis=image.calibration[0];
        if (image.calibration_complete!==false || axis.origin!==0 || axis.calibrated_value_at_pixel_zero!==0 ||
            axis.scale!==1 || axis.unit!==null || axis.usable!==false)
          throw new Error('SHOW calibrated histogram requires its exact creation axis context');
      }
      if (hasStyle) {
        const reasons=new Set(['style_not_qualified','style_entrypoints_unavailable','display_resolution_unavailable','document_has_no_display',
          'display_count_over_budget','display_holder_missing','display_is_not_a_line_plot','style_flag_did_not_read_back',
          'display_for_image_not_found']);
        if (!['histogram','default'].includes(result.display_style) ||
            result.display_style_scope!=='host line-plot presentation only; no scientific claim; reversible in the DM UI' ||
            (result.display_style==='histogram' ? own(result,'display_style_reason') : !reasons.has(result.display_style_reason)))
          throw new Error('SHOW histogram style must be an observed optional host presentation result');
      }
    }
  } else {
    validateImageMetadata(result.image, imageId, result.image?.dtype === "complex64", {requireReductions: false, allowUint32: true});
  }
  if (result.backend !== "digitalmicrograph-native" ||
      result.operator !== "ImageGetOrCreateImageDocument + ImageDocumentShow" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false || result.file_saved !== false ||
      result.model_visual_verification !== false || typeof result.ownership !== "string" || !result.ownership) {
    throw new Error("SHOW descriptor/native ownership/no-save contract mismatch");
  }
}

function validatePreview(result, args) {
  if (result.backend !== "digitalmicrograph-native" || result.operation !== "PREVIEW" || result.image_id !== args[0] ||
      args[1] < 1 || args[1] > 128 || args[2] < 1 || args[2] > 128 ||
      result.operator !== "GMS::Image::GetRealValue" || result.computation !== "DM native value reads; display adaptation only" ||
      result.quantitative !== false || result.source_write_requested !== false || result.snapshot_atomic !== false ||
      result.range_source !== "sampled native point values" ||
      result.mapping !== "x=floor(px*source_width/width);y=floor(py*source_height/height)" ||
      result.orientation !== "row-major [y,x], x increases right, y increases down" || result.sampling !== "nearest source integer index, no averaging") {
    throw new Error("Native PREVIEW identity/display adaptation contract mismatch");
  }
  validateImageMetadata(result.source, args[0], false, {requireReductions: false, allowUint32: true});
  const width = Math.min(result.source.shape[1], args[1]), height = Math.min(result.source.shape[0], args[2]);
  if (result.source.packing_style !== 1 || result.width !== width || result.height !== height || result.sample_count !== width * height ||
      !finite(result.sampled_minimum) || !finite(result.sampled_maximum) || result.sampled_minimum > result.sampled_maximum ||
      result.constant_range_gray8 !== 0 || typeof result.gray8_hex !== "string" || result.gray8_hex.length !== 2 * width * height ||
      !/^[0-9a-f]+$/.test(result.gray8_hex) || (result.sampled_minimum === result.sampled_maximum && !/^0+$/.test(result.gray8_hex))) {
    throw new Error("Native PREVIEW shape/packing/sampled range/gray8 mismatch");
  }
  if (result.source.dtype === "uint32" && (!uint32(result.sampled_minimum) || !uint32(result.sampled_maximum))) {
    throw new Error("Native PREVIEW uint32 sampled values must be exact unsigned integers");
  }
}

// Pure validation shared with the explicit external snapshot encoder. No I/O.
// Explicit wrapper so the delivery contract is testable without a live host.
// Rank-one PROFILE delivery is admitted by its own group and keeps a true [N]
// descriptor; 2D results keep their existing metadata validation unchanged.
export function validateNativeShow(result, imageId) {
  return validateShow(result, imageId);
}

export function validateNativeDataSnapshot(result, args) {
  if (!object(result) || !Array.isArray(args) || args.length !== 5 || !args.every(uint32)) throw new Error("Native READ requires five explicit uint32 arguments");
  const rect = args.slice(1), [x0, y0, x1, y1] = rect, width = x1 - x0, height = y1 - y0;
  const sameRect = value => Array.isArray(value) && value.length === 4 && value.every((item, index) => item === rect[index]);
  if (result.backend !== "digitalmicrograph-native" || result.operation !== "READ" || result.source_image_id !== args[0] ||
      !sameRect(result.requested_rect) || !sameRect(result.effective_rect) || width <= 0 || height <= 0 || width * height > 16384 ||
      !Array.isArray(result.shape) || result.shape.length !== 2 || result.shape[0] !== height || result.shape[1] !== width ||
      !["float32", "uint32"].includes(result.dtype) || result.byte_order !== "little" || result.array_order !== "C" || result.data_encoding !== "base64" ||
      !Array.isArray(result.axes) || result.axes.length !== 2 || result.axes[0] !== "y" || result.axes[1] !== "x" ||
      result.sample_count !== width * height || result.raw_bytes !== width * height * 4 ||
      result.operator !== "GMS::Image::GetRealValue" || result.computation !== "DM native point reads; data handoff only" ||
      result.intensity_calibration_applied !== false || result.intensity_semantics !== "raw pixel intensity" ||
      result.source_write_requested !== false || result.snapshot_atomic !== false ||
      result.ownership !== "response-owned numeric snapshot; no native result image" ||
      result.coordinate_mapping_policy !== "logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged" ||
      result.source_provenance_scope !== "immutable creation record only; source image remains mutable" ||
      ["image_id", "image", "png", "path", "preview_path", "output_path"].some(key => own(result, key))) {
    throw new Error("Native READ identity/ROI/array/raw snapshot contract mismatch");
  }
  validateImageMetadata(result.source, args[0], false, {requireReductions: false, allowUint32: true});
  if (result.dtype !== result.source.dtype || result.source.packing_style !== 1 || x1 > result.source.shape[1] || y1 > result.source.shape[0]) {
    throw new Error("Native READ source packing/bounds mismatch");
  }
  const encoded = result.values_base64;
  if (typeof encoded !== "string" || encoded.length !== 4 * Math.ceil(result.raw_bytes / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded)) {
    throw new Error("Native READ base64 encoding/byte length mismatch");
  }
  const bytes = Buffer.from(encoded, "base64");
  if (bytes.length !== result.raw_bytes || bytes.toString("base64") !== encoded) throw new Error("Native READ requires canonical base64 bytes");
  for (let offset = 0; offset < bytes.length; offset += 4) {
    if (result.dtype === "float32" && !Number.isFinite(bytes.readFloatLE(offset))) throw new Error("Native READ requires finite little-endian float32 values");
  }
  const offsets = [x0, y0], sizes = [width, height];
  if (!Array.isArray(result.roi_calibration) || result.roi_calibration.length !== 2 || !result.roi_calibration.every((axis, index) => {
    const source = result.source.calibration[index], offset = offsets[index];
    const origin = source.origin === null ? NaN : source.origin - offset;
    const zero = source.calibrated_value_at_pixel_zero === null || source.scale === null ? NaN : source.calibrated_value_at_pixel_zero + offset * source.scale;
    const numbersUsable = !["invalid_calibration", "invalid_calibration_and_unknown_units"].includes(source.issue) &&
      [source.origin, source.calibrated_value_at_pixel_zero, source.scale, origin, zero].every(finite) && source.scale !== 0;
    const unitKnown = source.unit !== null, usable = numbersUsable && unitKnown;
    const issue = usable ? null : numbersUsable ? "unknown_units" : unitKnown ? "invalid_calibration" : "invalid_calibration_and_unknown_units";
    return object(axis) && axis.dm_dimension === index && axis.numpy_axis === 1 - index && axis.size === sizes[index] && axis.source_offset === offset &&
      axis.source_origin === source.origin && axis.source_calibrated_value_at_pixel_zero === source.calibrated_value_at_pixel_zero &&
      axis.origin === (numbersUsable ? origin : null) && axis.calibrated_value_at_pixel_zero === (numbersUsable ? zero : null) &&
      axis.scale === source.scale && axis.unit === source.unit && axis.usable === usable && axis.issue === issue;
  }) || result.calibration_complete !== result.roi_calibration.every(axis => axis.usable)) {
    throw new Error("Native READ translated ROI calibration/issues mismatch");
  }
  const provenance = result.source_provenance;
  if (provenance !== null) {
    const operations = new Set(["CROP", "UNARY", "BINARY", "FILTER", "FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"]);
    if (!object(provenance) || Object.keys(provenance).length !== 4 || !operations.has(provenance.operation) || !validRequestId(provenance.request_id) ||
        !Array.isArray(provenance.source_image_ids) || provenance.source_image_ids.length !== (provenance.operation === "BINARY" ? 2 : 1) ||
        !provenance.source_image_ids.every(id => uint32(id) && id !== args[0]) || typeof provenance.semantics !== "string" || !provenance.semantics) {
      throw new Error("Native READ retained source provenance mismatch");
    }
  }
  nativeScientificSemantics(result);
}

// Preserve a frozen Fourier creation contract separately from the live DM
// calibration. This is metadata validation/coordinate translation, not an FFT.
// Missing legacy context stays unknown; reciprocal-looking units prove nothing.
export function nativeScientificSemantics(result, {requireFourierContext = false} = {}) {
  const unknown = status => ({schema_version: 1, status, domain: 'unknown',
    representation: 'unknown', coordinate_axes: null, phase_units: null,
    native_calibration_preserved: true, scope: 'creation lineage only; live pixels remain mutable'});
  const context = result.scientific_context;
  const fourierOps = new Set(['FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM']);
  if (context === undefined || context === null) {
    if (requireFourierContext && fourierOps.has(result.source_provenance?.operation))
      throw new Error('SCIENTIFIC_CONTEXT_REQUIRED: legacy Fourier READ lacks its bin/representation contract; do not infer it from DM calibration');
    return unknown('not_recorded');
  }
  if (!object(context) || context.schema_version !== 1) throw new Error('Invalid scientific context schema');
  if (context.status === 'unresolved_lineage') {
    if (Object.keys(context).length !== 2) throw new Error('Invalid unresolved scientific context');
    return unknown('unresolved_lineage');
  }
  if (context.status !== 'tracked_fourier' || Object.keys(context).length !== 9 ||
      !fourierOps.has(context.original_operation) || !validRequestId(context.request_id) ||
      context.result_version !== 2 || !Array.isArray(context.normalized_args) ||
      context.normalized_args.length !== 1 || !context.normalized_args.every(uint32) ||
      !Array.isArray(context.source_offset_xy) || context.source_offset_xy.length !== 2 || !context.source_offset_xy.every(uint32) ||
      !Array.isArray(context.postprocessing) || context.postprocessing.length > 32 ||
      !context.postprocessing.every(value => ['GMSImageProcessing::Negate', 'GMSImageProcessing::Abs', 'GMSImageProcessing::Square',
        'GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter', 'GMSImageProcessing::LaplaceFilter',
        'GMSImageProcessing::SharpenFilter'].includes(value)) || !object(context.result) || !object(result.source_provenance)) {
    throw new Error('Invalid tracked scientific context identity/history');
  }
  const producer = context.result;
  validateDerivedOperation(producer, context.original_operation, context.normalized_args, 2);
  if (producer.image.dtype !== 'float32' || result.source?.dtype !== 'float32')
    throw new Error('Scientific scalar READ must retain a real Fourier component, not packed/complex bytes');
  const direct = result.source_image_id === producer.image_id;
  if (direct && (context.source_offset_xy.some(value => value !== 0) || context.postprocessing.length ||
      result.source_provenance.request_id !== context.request_id || result.source_provenance.operation !== context.original_operation ||
      !Array.isArray(result.source_provenance.source_image_ids) || result.source_provenance.source_image_ids.length !== 1 ||
      result.source_provenance.source_image_ids[0] !== context.normalized_args[0]))
    throw new Error('Scientific direct-result identity mismatch');
  if (!direct) {
    // A later Fourier operator creates its own authoritative context; it cannot
    // inherit a different REAL/IMAG/phase/power result merely because axes match.
    // Crops may preserve all coordinates (including a full-size zero-offset
    // copy). Scalar operations must carry the matching recorded processing step.
    const provenance = result.source_provenance;
    const finalStep = context.postprocessing.at(-1);
    const scalarSteps = {
      UNARY: ['GMSImageProcessing::Negate', 'GMSImageProcessing::Abs', 'GMSImageProcessing::Square'],
      FILTER: ['GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter',
        'GMSImageProcessing::LaplaceFilter', 'GMSImageProcessing::SharpenFilter'],
    };
    if (provenance.request_id === context.request_id ||
        !(provenance.operation === 'CROP' || scalarSteps[provenance.operation]?.includes(finalStep)))
      throw new Error('Scientific derived-result lineage mismatch');
  }
  const near = (actual, expected, scale) => finite(actual) && finite(expected) &&
    Math.abs(actual - expected) <= 8 * 2 ** -23 * Math.max(Math.abs(actual), Math.abs(expected), Math.abs(scale), 2 ** -126);
  for (let axis = 0; axis < 2; ++axis) {
    const base = producer.image.calibration[axis], current = result.source.calibration[axis];
    const offset = context.source_offset_xy[axis], size = result.source.dm_dimensions[axis];
    if (offset + size > producer.image.dm_dimensions[axis] || current.scale !== base.scale || current.unit !== base.unit ||
        !near(current.origin, base.origin - offset, 1) ||
        !near(current.calibrated_value_at_pixel_zero, base.calibrated_value_at_pixel_zero + offset * base.scale, base.scale))
      throw new Error('Scientific lineage/native calibration mismatch');
  }
  const frequency = producer.frequency_grid !== null;
  const axes = result.roi_calibration.map((native, axis) => {
    const offset = context.source_offset_xy[axis] + result.effective_rect[axis];
    const grid = frequency ? producer.frequency_grid.axes[axis] : null;
    const step = frequency ? grid.physical_frequency_step : producer.image.calibration[axis].scale;
    const zero = frequency ? grid.frequency_at_index_zero : producer.image.calibration[axis].calibrated_value_at_pixel_zero;
    const nativeZero = native.calibrated_value_at_pixel_zero;
    const mathZero = zero + offset * step;
    return {dm_dimension: axis, numpy_axis: 1 - axis, size: result.shape[1 - axis],
      transform_size: producer.image.dm_dimensions[axis], source_index_offset: offset,
      dc_index_in_roi: frequency ? grid.dc_index - offset : null,
      calibrated_value_at_pixel_zero: mathZero, scale: step, unit: native.unit,
      native_calibrated_value_at_pixel_zero: nativeZero,
      native_minus_mathematical_zero: nativeZero - mathZero,
      coordinate_rule: 'coordinate(i)=calibrated_value_at_pixel_zero+i*scale'};
  });
  const changedValues = context.postprocessing.length > 0;
  return {schema_version: 1, status: 'tracked_fourier', domain: frequency ? 'frequency' : 'spatial',
    representation: changedValues ? 'processed_scalar' : producer.representation,
    original_representation: producer.representation, phase_units: !changedValues && producer.phase_units === 'radians' ? 'radians' : null,
    transform_signs: {...producer.transform_signs}, normalization: producer.normalization,
    centering: producer.centering, source_spatial_origin_used: producer.source_spatial_origin_used,
    inverse_restores_source_origin: producer.inverse_restores_source_origin,
    intensity_calibration_policy: producer.intensity_calibration_policy,
    source_operation: context.original_operation, source_request_id: context.request_id,
    postprocessing: [...context.postprocessing], coordinate_axes: axes,
    native_calibration_preserved: true, scope: 'creation lineage only; live pixels remain mutable'};
}

export function validRequestId(value) {
  return typeof value === "string" && value.length >= 1 && value.length <= 64 && !/[^A-Za-z0-9_-]/.test(value);
}

export class NativeBridgeError extends Error {
  constructor(message, {session, requestId, code = "NATIVE_TRANSPORT", sent = false} = {}) {
    super(`${message}; session=${session}; request_id=${requestId}; 已发送操作可能仍在执行，请用 dm_native_result 查询，不要自动重发`);
    this.name = "NativeBridgeError";
    this.details = {protocol: "NB2", session, request_id: requestId, state: "unknown", original_operation: null,
      normalized_args: null, result_type: null, result_version: null, code, sent, error: this.message};
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
    this._validateSubmittedIdentity(operation, args, reply);
    // Submission is never repeated. QUERY uses the original operation ID.
    const submitted = reply.state === "queued" || reply.state === "running";
    try {
      while (reply.state === "queued" || reply.state === "running") {
        await this._pause(requestId, deadline, signal);
        reply = await this._exchange("QUERY", [], requestId, deadline, signal);
        this._validateSubmittedIdentity(operation, args, reply);
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
    try {
      this._validateSubmittedIdentity(operation, args, reply);
      if (reply.state !== "completed") return reply;
      const original = reply.original_operation, originalArgs = reply.normalized_args, result = reply.result;
      if (['CROP','UNARY','BINARY','FILTER','FFT','IFFT','REAL','IMAG','VENDOR_ARG','VENDOR_NORM','PROFILE','HISTOGRAM'].includes(original)) validateNativeRetention(result, reply.id);
      if (["UNARY", "BINARY", "FILTER", "FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM", "SHOW"].includes(original) &&
          (result.candidate_probe === true || result.qualification === "NOT_QUALIFIED")) {
        throw new Error("Unqualified candidate result cannot satisfy the native scientific contract");
      }
      if (original === 'RELEASE' || original === 'RESULT_INFO') validateNativeResultAvailability(result, original, originalArgs);
      else if (original === 'PROFILE') validateNativeLineProfile(result, originalArgs, reply.id);
      else if (original === 'HISTOGRAM') validateNativeHistogram(result, originalArgs, reply.id);
      else if (original === 'ROIS') validateNativeGuiRois(result, originalArgs[0], reply.result_version);
      else if (original === "SUMMARY") validateSummary(result, originalArgs[0]);
      else if (original === "PREVIEW") validatePreview(result, originalArgs);
      else if (original === "READ") validateNativeDataSnapshot(result, originalArgs);
      else if (original === "UNARY" || original === "BINARY") validateImageOperation(result, original, originalArgs);
      else if (original === "FILTER" || RESULT_TYPES.get(original) === "native_fourier_operation") validateDerivedOperation(result, original, originalArgs, reply.result_version);
      else if (original === "MEAN") validateMean(result, originalArgs[0]);
      else if (original === "CROP") {
        const rect = originalArgs.slice(1), matches = value => Array.isArray(value) && value.length === 4 && value.every((item, index) => item === rect[index]);
        if (!uint32(result.image_id) || result.image_id === originalArgs[0] || result.source_image_id !== originalArgs[0] ||
            !(own(result, "effective_rect") || own(result, "rect")) || (own(result, "effective_rect") && !matches(result.effective_rect)) ||
            (own(result, "rect") && !matches(result.rect)) || (own(result, "requested_rect") && !matches(result.requested_rect))) {
          throw new Error("CROP result identity/rectangle mismatch");
        }
        validateUint32Crop(result, originalArgs);
      } else if (original === "SHOW") {
        validateShow(result, originalArgs[0]);
      } else if (original === "STOP" && (Object.keys(result).length !== 1 || result.ipc_stopped !== true)) {
        throw new Error("STOP result mismatch");
      }
    } catch (error) { throw this._error(`Invalid native response: ${error.message}`, reply.id, "NATIVE_PROTOCOL", true); }
    return reply;
  }

  _validateSubmittedIdentity(operation, args, reply) {
    if (operation === "QUERY" || reply.original_operation === null || reply.code === "id_conflict") return;
    if (reply.original_operation !== operation || !reply.normalized_args.every((value, index) => value === args[index]) || reply.normalized_args.length !== args.length) {
      throw this._error("NB2 original operation/arguments differ from submitted request", reply.id, "NATIVE_PROTOCOL", true);
    }
    if (RESULT_TYPES.get(operation) === "native_fourier_operation" && reply.result_version !== 2) {
      throw this._error("New Fourier submissions require native_fourier_operation result_version 2; version 1 is historical QUERY only", reply.id, "NATIVE_PROTOCOL", true);
    }
    if (operation === 'ROIS' && reply.result_version !== 2) {
      throw this._error('New ROIS submissions require native_gui_rois result_version 2; version 1 is historical QUERY only', reply.id, 'NATIVE_PROTOCOL', true);
    }
  }

  _deadline(timeoutMs) {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 600000) throw new Error("Invalid native timeout");
    return Date.now() + timeoutMs;
  }

  _validateRequest(operation, args, requestId) {
    if (!OPERATIONS.has(operation) || !Array.isArray(args) || args.length !== OPERATIONS.get(operation) || !args.every(uint32)) {
      throw new TypeError("Unsupported NB2 operation or invalid unsigned 32-bit arguments");
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
    if (!object(reply) || reply.protocol !== "NB2" || reply.session !== this.session || reply.id !== requestId) {
      throw new Error("NB2 response protocol/session/request identity mismatch");
    }
    if (!STATES.has(reply.state) || !uint32(reply.host_pid) || reply.host_pid === 0 ||
        !uint32(reply.worker_tid) || reply.worker_tid === 0 || !uint32(reply.exec_tid) ||
        !object(reply.timings_us) || ![reply.timings_us.queue, reply.timings_us.execute].every(v => Number.isSafeInteger(v) && v >= 0)) {
      throw new Error("Invalid NB2 state, host/thread identity or timings");
    }
    if (this.hostPid !== null && reply.host_pid !== this.hostPid) throw new Error("NB2 host PID changed within the configured session");
    if ((reply.state === "queued" && reply.exec_tid !== 0) || (reply.state === "running" && reply.exec_tid === 0) ||
        (reply.original_operation === "STOP" && reply.exec_tid !== 0)) throw new Error("Invalid NB2 execution thread for state/STOP");
    if (reply.original_operation === null) {
      if (!IDENTITY_FIELDS.every(key => own(reply, key) && reply[key] === null) ||
          !["unknown", "failed"].includes(reply.state) || reply.exec_tid !== 0 || reply.code === "id_conflict") {
        throw new Error("NB2 missing-record identity must be explicitly null");
      }
    } else {
      const original = reply.original_operation;
      const count = original === "STOP" ? 0 : OPERATIONS.get(original);
      if (!RESULT_TYPES.has(original) || !Array.isArray(reply.normalized_args) || reply.normalized_args.length !== count ||
          !reply.normalized_args.every(uint32) || reply.result_type !== RESULT_TYPES.get(original) ||
          !(["native_fourier_operation", "native_gui_rois"].includes(reply.result_type) ? [1, 2].includes(reply.result_version) : reply.result_version === 1) || reply.state === "unknown") {
        throw new Error("NB2 original operation/result schema identity mismatch");
      }
    }
    if (reply.state === "completed") {
      if (!own(reply, "result") || !object(reply.result) || (reply.exec_tid === 0 && reply.original_operation !== "STOP") || own(reply, "error") || own(reply, "code")) {
        throw new Error("Invalid NB2 completed result");
      }
    } else if (own(reply, "result")) {
      throw new Error("NB2 non-completed response must not contain a result");
    }
    if (reply.state === "failed") {
      if (typeof reply.error !== "string" || !reply.error || typeof reply.code !== "string" || !reply.code) throw new Error("NB2 failure requires error and code");
    } else if (own(reply, "error") || own(reply, "code")) {
      throw new Error("NB2 error/code may only appear in failed responses");
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
      const payload = `NB2 ${this.session} ${requestId} ${operation}${args.length ? " " + args.join(" ") : ""}\n`;
      if (Buffer.byteLength(payload, "ascii") > 512) return finish(this._error("NB2 request exceeds 512 bytes", requestId, "NATIVE_PROTOCOL"));
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
        if (bytes > RESPONSE_LIMIT) return finish(this._error("NB2 response exceeds 128 KiB", requestId, "NATIVE_PROTOCOL", sent));
        chunks.push(chunk);
        if (!chunk.includes(10)) return;
        try {
          const raw = Buffer.concat(chunks, bytes);
          if (raw.length < 2 || raw[raw.length - 1] !== 10 || raw.indexOf(10) !== raw.length - 1) throw new Error("NB2 requires exactly one newline-terminated JSON response");
          const line = new TextDecoder("utf-8", {fatal: true}).decode(raw.subarray(0, -1));
          const parsed = JSON.parse(line, (_key, value) => {
            if (typeof value === "number" && !Number.isFinite(value)) throw new Error("NB2 JSON contains a nonfinite number");
            return value;
          });
          const reply = this._validateOperationResult(operation, args, this._validateReply(parsed, requestId));
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
