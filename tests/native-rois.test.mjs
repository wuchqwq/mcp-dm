import test from 'node:test';
import assert from 'node:assert/strict';
import {validateNativeGuiRois} from '../lib/native_bridge.mjs';
import {guiRoisFixture} from './fixtures/native-rois.mjs';

test('GUI rectangle snapshot binds source/display/ROI and keeps signed physical calibration separate', () => {
  const result = guiRoisFixture();
  validateNativeGuiRois(result, 77);
  assert.equal(result.displays[0].rois[0].coordinate_mapping.identity, false);
  assert.equal(result.displays[0].rois[0].coordinate_mapping.source_pixel_aligned, true);
  result.image.calibration[0].unit = null;
  result.image.calibration[0].usable = false;
  result.image.calibration[0].issue = 'unknown_units';
  result.image.calibration_complete = false;
  validateNativeGuiRois(result, 77);
  assert.deepEqual(result.displays[0].rois[0].rect, [2, 1, 10, 6]);
});

test('no display, zero ROIs and unsupported objects remain explicit rather than whole-image selection', () => {
  const result = guiRoisFixture(), display = result.displays[0];
  display.roi_count = 0; display.rois = [];
  validateNativeGuiRois(result, 77);
  display.display_type = 'unsupported'; display.slice_ids = null; display.source_layout = null; display.roi_count = null; display.issue = 'unsupported_display_type';
  validateNativeGuiRois(result, 77);
  result.displays = []; validateNativeGuiRois(result, 77);
  const other = guiRoisFixture(), roi = other.displays[0].rois[0];
  Object.assign(roi, {type: 'unsupported', raw_rectangle: null, coordinate_mapping: null, rect: null, analysis_eligible: false, issue: 'unsupported_roi_type'});
  validateNativeGuiRois(other, 77);
});

test('nonstandard native ROI mappings never pass their raw rectangle to source-pixel operations', () => {
  for (const mapping of [{offset: [1, 0], scale: [1, 1], identity: false},
    {offset: [0, -2.5], scale: [1, 1], identity: false},
    {offset: [0, 0], scale: [2, 2], identity: false},
    {offset: [0, 0], scale: [-1, 1], identity: false}]) {
    const result = guiRoisFixture(), roi = result.displays[0].rois[0];
    Object.assign(mapping, {space: 'source_pixel_to_normalized_display', source_pixel_aligned: false});
    Object.assign(roi, {coordinate_mapping: mapping, rect: null, analysis_eligible: false, issue: 'unsupported_coordinate_mapping'});
    validateNativeGuiRois(result, 77);
    roi.raw_rectangle.left = 2.5;
    validateNativeGuiRois(result, 77); // mapping diagnosis precedes fractional coordinates
    roi.issue = 'fractional_rectangle';
    assert.throws(() => validateNativeGuiRois(result, 77));
    Object.assign(roi, {rect: [2, 1, 10, 6], analysis_eligible: true, issue: null});
    assert.throws(() => validateNativeGuiRois(result, 77));
  }
});

test('source layout and single image slice establish alignment without claiming mathematical identity or spatial axes', () => {
  const result = guiRoisFixture(), display = result.displays[0], roi = display.rois[0];
  assert.equal(roi.coordinate_mapping.identity, false);
  assert.equal(roi.coordinate_mapping.source_pixel_aligned, true);
  assert.deepEqual(roi.coordinate_mapping.scale, [Math.fround(1 / 12), Math.fround(1 / 8)]);
  validateNativeGuiRois(result, 77);
  for (const [layout, slices] of [['unsupported', [0]], ['direct_image_canonical_xy', [1]], ['direct_image_canonical_xy', []],
    ['direct_image_canonical_xy', [0, 1]], ['direct_image_canonical_xy', [0, 0]], ['direct_image_canonical_xy', [0, 1, 2]]]) {
    display.source_layout = layout; display.slice_ids = slices;
    Object.assign(roi.coordinate_mapping, {source_pixel_aligned: false});
    Object.assign(roi, {rect: null, analysis_eligible: false, issue: 'unsupported_image_source'});
    validateNativeGuiRois(result, 77);
    roi.coordinate_mapping.source_pixel_aligned = true;
    assert.throws(() => validateNativeGuiRois(result, 77));
  }
});

test('display IDs may coincide in different documents but their composite identities must differ', () => {
  const result = guiRoisFixture(), second = structuredClone(result.displays[0]);
  second.document_id = second.display_identity.document_id = 32;
  result.displays.push(second);
  validateNativeGuiRois(result, 77);
});

test('document/display/ROI identifiers match nonnegative native int32 bounds independently of image uint32 IDs', () => {
  for (const value of [0, 0x7fffffff, 0x80000000, 0xffffffff]) {
    for (const kind of ['document', 'display', 'roi']) {
      const result = guiRoisFixture(0xffffffff), display = result.displays[0];
      if (kind === 'document') display.document_id = display.display_identity.document_id = value;
      else if (kind === 'display') display.display_id = display.display_identity.display_id = value;
      else display.rois[0].roi_id = value;
      if (value <= 0x7fffffff) validateNativeGuiRois(result, 0xffffffff);
      else assert.throws(() => validateNativeGuiRois(result, 0xffffffff), `${kind}=${value}`);
    }
  }
});

test('nonzero native rotation is retained and refused before mapping/coordinate eligibility without normalization', () => {
  for (const rotation of [30, -30, 360, 1e-9]) {
    const result = guiRoisFixture(), roi = result.displays[0].rois[0];
    Object.assign(roi, {rotation_degrees: rotation, rect: null, analysis_eligible: false, issue: 'rotated_rectangle'});
    validateNativeGuiRois(result, 77);
    roi.coordinate_mapping = {...roi.coordinate_mapping, offset: [1, 0], scale: [2, 1], identity: false, source_pixel_aligned: false};
    validateNativeGuiRois(result, 77);
    roi.issue = 'unsupported_coordinate_mapping';
    assert.throws(() => validateNativeGuiRois(result, 77));
    Object.assign(roi, {rect: [2, 1, 10, 6], analysis_eligible: true, issue: null});
    assert.throws(() => validateNativeGuiRois(result, 77));
  }
});

test('fractional, outside and degenerate rectangles are retained but never silently rounded/clipped for analysis', () => {
  for (const [raw, issue] of [
    [{top: 1, left: 2.5, bottom: 6, right: 10}, 'fractional_rectangle'],
    [{top: 1, left: -1, bottom: 6, right: 10}, 'out_of_bounds_rectangle'],
    [{top: 1, left: 2, bottom: 9, right: 10}, 'out_of_bounds_rectangle'],
    [{top: 1, left: 2, bottom: 6, right: 13}, 'out_of_bounds_rectangle'],
    [{top: 1, left: 2, bottom: 1, right: 10}, 'empty_or_reversed_rectangle'],
    [{top: 5, left: 2, bottom: 1, right: 10}, 'empty_or_reversed_rectangle'],
  ]) {
    const result = guiRoisFixture(), roi = result.displays[0].rois[0];
    Object.assign(roi, {raw_rectangle: raw, rect: null, analysis_eligible: false, issue});
    validateNativeGuiRois(result, 77);
    roi.analysis_eligible = true;
    assert.throws(() => validateNativeGuiRois(result, 77));
  }
});

test('cross-image/display identity, count truncation and invented eligibility never validate', () => {
  const changes = [
    r => {r.image_id = 78;}, r => {r.image.id = 78;},
    r => {r.image.packing_style = 2;},
    r => {r.source_write_requested = true;}, r => {r.snapshot_atomic = true;},
    r => {r.candidate_probe = true;}, r => {r.qualification = 'NOT_QUALIFIED';},
    r => {r.displays[0].display_identity.display_id = 10;},
    r => {r.displays[0].display_identity.document_id = 99;},
    r => {r.displays[0].display_identity.image_id = 77;},
    r => {r.displays[0].roi_count = 0;}, r => {r.displays[0].roi_count = null;},
    r => {r.displays[0].slice_ids = null;},
    r => {r.displays[0].slice_ids = [false];},
    r => {r.displays[0].slice_ids = [0, 1, 2, 3, 4, 5];},
    r => {r.displays[0].source_layout = 'transposed';},
    r => {r.displays[0].selected_dimensions = [0, 1];},
    r => {r.displays.push(structuredClone(r.displays[0]));},
    r => {r.displays[0].rois.push(structuredClone(r.displays[0].rois[0])); r.displays[0].roi_count = 2;},
    r => {r.displays[0].rois[0].rect = [1, 2, 10, 6];},
    r => {r.displays[0].rois[0].selected = null;},
    r => {delete r.displays[0].rois[0].rotation_degrees;},
    r => {r.displays[0].rois[0].rotation_degrees = true;},
    r => {r.displays[0].rois[0].rotation_degrees = NaN;},
    r => {r.displays[0].rois[0].rotation_degrees = Infinity;},
    r => {r.displays[0].rois[0].rotation_degrees = 360;},
    r => {r.displays[0].rois[0].raw_rectangle.left = NaN;},
    r => {r.displays[0].rois[0].raw_rectangle.top = Infinity;},
    r => {r.displays[0].rois[0].raw_rectangle.extra = 1;},
    r => {r.displays[0].rois[0].coordinate_mapping = null;},
    r => {r.displays[0].rois[0].coordinate_mapping.offset = [0];},
    r => {r.displays[0].rois[0].coordinate_mapping.offset[0] = NaN;},
    r => {r.displays[0].rois[0].coordinate_mapping.scale[1] = Infinity;},
    r => {r.displays[0].rois[0].coordinate_mapping.scale[1] = 0;},
    r => {r.displays[0].rois[0].coordinate_mapping.identity = true;},
    r => {r.displays[0].rois[0].coordinate_mapping.space = 'source_pixel';},
    r => {r.displays[0].rois[0].coordinate_mapping.source_pixel_aligned = false;},
    r => {r.displays[0].rois[0].coordinate_mapping.offset[0] = 1;},
    r => {r.displays[0].rois[0].issue = 'fractional_rectangle';},
    r => {r.displays[0].rois[0].type = 'line';},
    r => {r.displays[0].issue = 'native_getter_failed'; r.displays[0].rois = []; r.displays[0].roi_count = 0;},
    r => {r.displays[0].display_type = 'unsupported'; r.displays[0].issue = 'unsupported_display_type'; r.displays[0].roi_count = null;},
  ];
  for (const change of changes) {
    const result = guiRoisFixture(); change(result);
    assert.throws(() => validateNativeGuiRois(result, 77), change.toString());
  }
});

test('display and ROI budgets reject rather than truncate', () => {
  const result = guiRoisFixture(), seed = result.displays[0];
  result.displays = Array.from({length: 17}, (_, id) => ({...structuredClone(seed), display_id: id,
    display_identity: {document_id: 31, display_id: id}}));
  assert.throws(() => validateNativeGuiRois(result, 77));
  result.displays = [seed]; seed.rois = Array.from({length: 65}, (_, id) => ({...seed.rois[0], roi_id: id})); seed.roi_count = 65;
  assert.throws(() => validateNativeGuiRois(result, 77));
  seed.rois.length = 64; seed.roi_count = 64;
  result.displays = Array.from({length: 3}, (_, id) => ({...structuredClone(seed), display_id: id,
    display_identity: {document_id: 31, display_id: id}}));
  assert.throws(() => validateNativeGuiRois(result, 77));
});
