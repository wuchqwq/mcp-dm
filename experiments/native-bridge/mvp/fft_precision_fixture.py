# -*- coding: utf-8 -*-
"""Fixed FFT precision fixtures. Acceptance only; never a native runtime fallback."""


def arrays():
    import numpy as np
    y, x = np.indices((8, 8), dtype=np.uint32)
    low = (3 * x + 7 * y + (x * y) % 11).astype(np.uint32)
    high = (np.uint32(2 ** 31) + low * 17 + 1).astype(np.uint32)
    y, x = np.indices((128, 128), dtype=np.uint32)
    # All these integers are exactly binary32-representable. Any round-trip
    # error in this control cannot be blamed on uint32 -> binary32 conversion.
    medium = (4000000 + ((x * 7919 + y * 104729 + x * y * 13) % 700001)).astype(np.uint32)
    result = {}
    for label, value in (("low", low), ("high", high), ("medium", medium)):
        result[label + "_uint32"] = value
        result[label + "_float32"] = value.astype(np.float32)
    return result


POLICY = {
    "schema": 1,
    "forward_sign": "+",
    "forward_centering": "fftshift_data",
    "inverse_sign": "-",
    "inverse_normalization": "1/(width*height)",
    "inverse_max_absolute_error": 0.5,
    "fft_absolute_error_factor_of_sum_abs": 2 ** -17,
    "direct_vs_bridge_required": "bitwise_same_dtype_shape_pixels",
    "read_vs_host_required": "bitwise_same_dtype_shape_pixels",
    "thresholds_chosen_before_observation": True,
    "scope": "fixed synthetic cases only; preserve historical FAIL independently",
}
