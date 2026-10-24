import {imageMetadata} from './native-operations.mjs';

export function normalizedGuiMapping(shape, sourceLayout = 'direct_image_canonical_xy', sliceIds = [0]) {
  const scale = [Math.fround(1 / Math.fround(shape[1])), Math.fround(1 / Math.fround(shape[0]))];
  return {offset: [0, 0], scale, identity: scale.every(value => value === 1),
    space: 'source_pixel_to_normalized_display', source_pixel_aligned: sourceLayout === 'direct_image_canonical_xy' && sliceIds.length === 1 && sliceIds[0] === 0};
}

// Synthetic protocol fixtures only; no vendor calls or GMS qualification.
export function guiRoisFixture(imageId = 77, version = 2) {
  return {
    backend: 'digitalmicrograph-native', image_id: imageId,
    image: imageMetadata(imageId, {shape: [8, 12]}),
    displays: [{document_id: 31, display_id: 9, display_identity: {document_id: 31, display_id: 9},
      display_type: 'raster', source_layout: 'direct_image_canonical_xy', slice_ids: [0], roi_count: 1, rois: [{roi_id: 4, selected: true, rotation_degrees: 0, type: 'rectangle',
        ...(version === 2 ? {raw_line:null,line:null} : {}), raw_rectangle: {top: 1, left: 2, bottom: 6, right: 10}, rect: [2, 1, 10, 6],
        coordinate_mapping: normalizedGuiMapping([8, 12]),
        analysis_eligible: true, issue: null}], issue: null}],
    coordinate_rule: 'half-open pixel rectangle [x0,y0,x1,y1]; no rounding or clipping',
    source_write_requested: false, snapshot_atomic: false,
  };
}
