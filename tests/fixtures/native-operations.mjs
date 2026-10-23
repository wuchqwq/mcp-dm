// Hand-built protocol fixtures only. No vendor API or scientific computation.
export function imageMetadata(id, {complex = false, shape = [4, 8]} = {}) {
  return {id, name: "synthetic protocol fixture", ndim: 2, data_type_code: complex ? 3 : 2,
    dtype: complex ? "complex64" : "float32", packing_style: 1, shape: [...shape], dm_dimensions: [...shape].reverse(),
    pixels: shape[0] * shape[1], shape_order: "numpy (last axis is X)", calibration_complete: true,
    native_mean_supported: !complex, native_summary_supported: !complex,
    coordinate_rule: "physical(i)=calibrated_value_at_pixel_zero+i*scale",
    calibration: [
      {dm_dimension: 0, numpy_axis: 1, size: shape[1], origin: 2, calibrated_value_at_pixel_zero: 0.5, scale: -0.25, unit: "nm", usable: true, issue: null},
      {dm_dimension: 1, numpy_axis: 0, size: shape[0], origin: -1, calibrated_value_at_pixel_zero: 0.5, scale: 0.5, unit: "nm", usable: true, issue: null},
    ]};
}

function frequencyMetadata(id, complex) {
  const source = imageMetadata(77), image = imageMetadata(id, {complex});
  image.calibration.forEach((axis, index) => {
    axis.scale = Math.fround(1 / Math.fround(axis.size * source.calibration[index].scale));
    axis.origin = (axis.size + 1) / 2;
    axis.calibrated_value_at_pixel_zero = Math.fround(-axis.origin * axis.scale);
    axis.unit = "1/nm";
  });
  return image;
}

export function fourierFixture(operation, sourceId = 77, {spatial = false} = {}) {
  const inverse = operation === "IFFT", forward = operation === "FFT", component = !inverse && !forward;
  const complex = forward || inverse, centered = forward || (component && !spatial);
  const source = forward ? imageMetadata(sourceId) : component && spatial ? imageMetadata(sourceId, {complex: true}) : frequencyMetadata(sourceId, true);
  const image = centered ? frequencyMetadata(99, complex) : imageMetadata(99, {complex});
  if (!centered) {
    image.calibration.forEach((axis, index) => {
      axis.origin = 0; axis.calibrated_value_at_pixel_zero = 0;
      if (inverse) axis.scale = Math.fround(1 / Math.fround(axis.size * source.calibration[index].scale));
    });
    if (component) source.calibration = structuredClone(image.calibration);
  }
  const definitions = {FFT: ["Real_FFT", "full_complex"], IFFT: ["IFFT", "full_complex"], REAL: ["Real", "real_component"],
    IMAG: ["Imag", "imaginary_component"], VENDOR_ARG: ["Arg", "phase_radians"], VENDOR_NORM: ["Norm", "squared_magnitude"]};
  return {backend: "digitalmicrograph-native", operation, source_image_id: sourceId, image_id: 99, source, image,
    operator: "GMSImageProcessing::" + definitions[operation][0], computation: "DM native", representation: definitions[operation][1],
    output_bytes: image.pixels * (complex ? 8 : 4), validation_peak_new_image_bytes: image.pixels * (complex ? 12 : 4),
    ownership: "synthetic protocol fixture; no actual image allocated", semantics: "synthetic contract emulation only",
    visible_dm_document: false, source_write_requested: false, snapshot_atomic: false,
    normalization: forward ? "none" : inverse ? "1/(width*height)" : "inherited_parent_transform",
    centering: centered ? "fftshift_data" : "spatial_origin_zero", phase_units: operation === "VENDOR_ARG" ? "radians" : "not_applicable",
    transform_signs: {forward: "+", inverse: "-"}, input_index_origin: "zero-based pixel indices", source_spatial_origin_used: false,
    intensity_calibration_applied: false, inverse_restores_source_origin: false, intensity_calibration_policy: "synthetic protocol contract, not host evidence",
    frequency_grid: centered ? {native_calibration_has_half_bin_offset: true, axes: image.calibration.map(axis => ({
      dm_dimension: axis.dm_dimension, size: axis.size, dc_index: axis.size / 2, cycles_per_pixel_step: 1 / axis.size,
      physical_frequency_step: axis.scale, unit: axis.unit, frequency_at_index_zero: -axis.size / 2 * axis.scale,
      native_calibrated_value_at_pixel_zero: axis.calibrated_value_at_pixel_zero,
      native_calibration_dc_value: axis.calibrated_value_at_pixel_zero + axis.size / 2 * axis.scale,
      coordinate_rule: "f(i)=(i-dc_index)*physical_frequency_step",
    }))} : null};
}

export function operationFixture(operation, args) {
  if (["FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"].includes(operation)) return fourierFixture(operation, args[0]);
  if (operation === "READ") return readFixture(args);
  if (operation === "PREVIEW") {
    const source = imageMetadata(args[0]), width = Math.min(source.shape[1], args[1]), height = Math.min(source.shape[0], args[2]);
    return {backend: "digitalmicrograph-native", operation, image_id: args[0], source, width, height, sample_count: width * height,
      gray8_hex: Array.from({length: width * height}, (_, index) => ["00", "11", "80", "ff"][index % 4]).join(""),
      sampled_minimum: -2.5, sampled_maximum: 8, constant_range_gray8: 0, range_source: "sampled native point values",
      mapping: "x=floor(px*source_width/width);y=floor(py*source_height/height)", orientation: "row-major [y,x], x increases right, y increases down",
      sampling: "nearest source integer index, no averaging", quantitative: false, source_write_requested: false, snapshot_atomic: false,
      operator: "GMS::Image::GetRealValue", computation: "DM native value reads; display adaptation only"};
  }
  if (operation === "FILTER") {
    const source = imageMetadata(args[0], {shape: [5, 7]}), image = imageMetadata(99, {shape: [5, 7]});
    return {backend: "digitalmicrograph-native", operation, filter_kind: args[1], source_image_id: args[0], image_id: 99, source, image,
      operator: "GMSImageProcessing::" + {1: "SmoothFilter", 2: "SobelFilter", 3: "LaplaceFilter", 4: "SharpenFilter"}[args[1]],
      computation: "DM native", kernel: "vendor_defined", edge_behavior: "vendor_defined", semantics: "synthetic contract emulation only",
      output_bytes: image.pixels * 4, validation_peak_new_image_bytes: image.pixels * (args[1] === 2 ? 8 : 4),
      ownership: "synthetic protocol fixture; no actual image allocated", visible_dm_document: false, source_write_requested: false, snapshot_atomic: false};
  }
  const ids = args.slice(0, -1), opcode = args.at(-1);
  const [name, operator] = (operation === "UNARY" ? {1: ["negate", "Negate"], 2: ["abs", "Abs"], 3: ["square", "Square"]}
    : {1: ["add", "operator+"], 2: ["subtract", "operator-"], 3: ["multiply", "operator*"]})[opcode];
  return {backend: "digitalmicrograph-native", operation: name, opcode, source_image_ids: ids, sources: ids.map(id => imageMetadata(id)),
    image_id: 99, image: imageMetadata(99), operator: "GMSImageProcessing::" + operator, computation: "DM native",
    intensity_calibration_applied: false, intensity_semantics: "raw pixel intensity", source_write_requested: false, snapshot_atomic: false,
    ownership: "synthetic protocol fixture; no actual image allocated"};
}

export function readFixture(args = [77, 1, 1, 4, 3], {source = imageMetadata(args[0]), provenance = null} = {}) {
  const rect = args.slice(1), [x0, y0, x1, y1] = rect, width = x1 - x0, height = y1 - y0;
  const bytes = Buffer.alloc(width * height * 4);
  for (let index = 0; index < width * height; index++) bytes.writeFloatLE([-0, -2.5, 0.125, 8][index % 4], index * 4);
  const offsets = [x0, y0], sizes = [width, height];
  const roi = source.calibration.map((axis, index) => {
    const origin = axis.origin === null ? NaN : axis.origin - offsets[index];
    const zero = axis.calibrated_value_at_pixel_zero === null || axis.scale === null ? NaN : axis.calibrated_value_at_pixel_zero + offsets[index] * axis.scale;
    const numbersUsable = !["invalid_calibration", "invalid_calibration_and_unknown_units"].includes(axis.issue) &&
      [axis.origin, axis.calibrated_value_at_pixel_zero, axis.scale, origin, zero].every(value => typeof value === "number" && Number.isFinite(value)) && axis.scale !== 0;
    const unitKnown = axis.unit !== null, usable = numbersUsable && unitKnown;
    return {dm_dimension: index, numpy_axis: 1 - index, size: sizes[index], source_offset: offsets[index],
      source_origin: axis.origin, source_calibrated_value_at_pixel_zero: axis.calibrated_value_at_pixel_zero,
      origin: numbersUsable ? origin : null, calibrated_value_at_pixel_zero: numbersUsable ? zero : null,
      scale: axis.scale, unit: axis.unit, usable, issue: usable ? null : numbersUsable ? "unknown_units" : unitKnown ? "invalid_calibration" : "invalid_calibration_and_unknown_units"};
  });
  return {backend: "digitalmicrograph-native", operation: "READ", source_image_id: args[0], source,
    requested_rect: rect, effective_rect: [...rect], shape: [height, width], dtype: "float32", byte_order: "little", axes: ["y", "x"], array_order: "C",
    data_encoding: "base64", values_base64: bytes.toString("base64"), sample_count: width * height, raw_bytes: bytes.length,
    operator: "GMS::Image::GetRealValue", computation: "DM native point reads; data handoff only",
    intensity_calibration_applied: false, intensity_semantics: "raw pixel intensity", source_write_requested: false, snapshot_atomic: false,
    ownership: "response-owned numeric snapshot; no native result image", roi_calibration: roi, calibration_complete: roi.every(axis => axis.usable),
    coordinate_mapping_policy: "logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged",
    source_provenance_scope: "immutable creation record only; source image remains mutable", source_provenance: provenance};
}
