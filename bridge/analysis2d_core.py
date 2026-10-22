# -*- coding: utf-8 -*-
"""Pure 2D analysis kernels shared by the DM bridge and offline worker.

Python 3.7 / NumPy 1.18 compatible. Inputs are copied or selected by callers;
these functions never mutate them.
"""
import math

import numpy as np


def statistics(sub):
    """Population statistics over finite values; NaN and +/-Inf are counted."""
    flat = np.asarray(sub, dtype="float64").ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        raise RuntimeError("所选区域没有有效数值（全为 NaN/Inf）")
    pct = np.percentile(finite, [0, 1, 50, 99, 100])
    return {
        "count": int(finite.size),
        "total_count": int(flat.size),
        "finite_count": int(finite.size),
        "nan_count": int(np.count_nonzero(np.isnan(flat))),
        "inf_count": int(np.count_nonzero(np.isinf(flat))),
        "invalid_count": int(flat.size - finite.size),
        "min": float(pct[0]), "max": float(pct[4]),
        "mean": float(finite.mean()), "stddev": float(finite.std()),
        "percentiles": {"0": float(pct[0]), "1": float(pct[1]),
                        "50": float(pct[2]), "99": float(pct[3]),
                        "100": float(pct[4])},
    }


def profile(array, calibration, x0, y0, x1, y1, width):
    """Bilinear centerline profile with a symmetric, finite-sample strip mean."""
    a = np.asarray(array)
    if a.ndim != 2 or a.dtype.kind not in "biuf":
        raise ValueError("profile requires a real 2D numeric array")
    h, w = a.shape
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise ValueError("剖面端点必须是有限数值")
    if not (0 <= x0 <= w - 1 and 0 <= x1 <= w - 1 and
            0 <= y0 <= h - 1 and 0 <= y1 <= h - 1):
        raise ValueError("剖面端点超出图像；坐标必须落在像素中心 [0,width-1] × [0,height-1]")
    length = float(np.hypot(x1 - x0, y1 - y0))
    if length == 0:
        raise ValueError("剖面的两个端点不能重合")
    n = max(2, min(int(math.ceil(length)) + 1, 4096))
    ts = np.linspace(0.0, 1.0, n)
    xs = x0 + (x1 - x0) * ts
    ys = y0 + (y1 - y0) * ts
    width = int(width or 1)
    if not 1 <= width <= 1024:
        raise ValueError("width 必须介于 1 和 1024（像素）")
    offsets = np.arange(width, dtype="float64") - (width - 1) / 2.0
    normal_x, normal_y = -(y1 - y0) / length, (x1 - x0) / length
    vals = []
    sample_counts = []
    for k in range(n):
        px, py = xs[k] + normal_x * offsets, ys[k] + normal_y * offsets
        inside = (px >= 0) & (px <= w - 1) & (py >= 0) & (py <= h - 1)
        px, py = px[inside], py[inside]
        ix, iy = np.floor(px).astype(int), np.floor(py).astype(int)
        jx, jy = np.minimum(ix + 1, w - 1), np.minimum(iy + 1, h - 1)
        ax, ay = px - ix, py - iy
        samples = np.zeros(px.shape, dtype="float64")
        for rows, cols, weights in ((iy, ix, (1 - ax) * (1 - ay)),
                                    (iy, jx, ax * (1 - ay)),
                                    (jy, ix, (1 - ax) * ay),
                                    (jy, jx, ax * ay)):
            use = weights > 0
            samples[use] += a[rows[use], cols[use]] * weights[use]
        samples = samples[np.isfinite(samples)]
        sample_counts.append(int(samples.size))
        vals.append(float(samples.mean()) if samples.size else None)
    sx, sy = calibration[0].get("scale"), calibration[1].get("scale")
    ux, uy = calibration[0].get("unit"), calibration[1].get("unit")
    calibrated = (sx is not None and sy is not None and sx != 0 and sy != 0 and
                  math.isfinite(sx) and math.isfinite(sy) and ux == uy and bool(ux))
    distance_length = math.hypot((x1 - x0) * sx, (y1 - y0) * sy) if calibrated else length
    unit = ux if calibrated else "pixel"
    return {
        "n": int(n), "width": width,
        "distance": [float(v) for v in ts * distance_length],
        "unit": unit, "values": vals,
        "calibrated_distance": bool(calibrated),
        "calibration": calibration,
        "sampled_coordinates": [[float(x), float(y)] for x, y in zip(xs, ys)],
        "width_offsets": offsets.tolist(),
        "finite_samples_per_point": sample_counts,
        "sampling": "bilinear at evenly spaced pixel-coordinate centers; mean across pixel-plane perpendicular strip",
        "boundary_policy": "reject out-of-image endpoints; omit out-of-image strip samples and nonfinite interpolated samples",
        "note": "width is exact sample count; even widths use half-pixel symmetric offsets; mixed/missing axis units return pixel distance",
    }


def fft(array, calibration, top_n=12):
    """Unwindowed, mean-subtracted absolute 2D DFT and its peak summary."""
    sub = np.asarray(array, dtype="float64")
    if sub.ndim != 2 or not np.all(np.isfinite(sub)):
        raise ValueError("FFT requires a finite real 2D region; NaN/Inf are not imputed")
    f = np.fft.fftshift(np.abs(np.fft.fft2(sub - float(np.mean(sub)))))
    cy, cx = f.shape[0] // 2, f.shape[1] // 2
    top_n = max(1, min(int(top_n or 12), 200))
    peaks = []
    take = min(int(f.size), top_n + 1)
    flat = f.ravel()
    candidates = np.argpartition(flat, flat.size - take)[-take:]
    candidates = candidates[np.argsort(flat[candidates])[::-1]]
    sx, sy = calibration[0].get("scale"), calibration[1].get("scale")
    ux, uy = calibration[0].get("unit"), calibration[1].get("unit")
    use_x = sx is not None and sx != 0 and math.isfinite(sx) and bool(ux)
    use_y = sy is not None and sy != 0 and math.isfinite(sy) and bool(uy)
    for k in candidates:
        y, x = divmod(int(k), f.shape[1])
        if y == cy and x == cx:
            continue
        dx, dy = int(x - cx), int(y - cy)
        fxp, fyp = dx / float(f.shape[1]), dy / float(f.shape[0])
        fx, fy = (fxp / sx if use_x else None), (fyp / sy if use_y else None)
        same_unit = use_x and use_y and ux == uy
        frequency = math.hypot(fx, fy) if same_unit else None
        peaks.append({
            "dy": dy, "dx": dx, "magnitude": float(f[y, x]),
            "d_pix": float(np.hypot(dy, dx)),
            "fx_cycles_per_pixel": fxp, "fy_cycles_per_pixel": fyp,
            "frequency_cycles_per_pixel": math.hypot(fxp, fyp),
            "fx": fx, "fy": fy,
            "fx_unit": "1/(%s)" % ux if use_x else None,
            "fy_unit": "1/(%s)" % uy if use_y else None,
            "frequency": frequency,
            "spacing": 1.0 / frequency if frequency else None,
            "spacing_unit": ux if same_unit else None,
        })
        if len(peaks) >= top_n:
            break
    return {
        "dc": float(f[cy, cx]), "peaks": peaks,
        "calibration": calibration, "mean_removed": True,
        "window": "rectangular (no apodization)",
        "normalization": "unnormalized absolute DFT; no intensity normalization",
        "note": "dx/dy are signed FFT-bin indices; legacy d_pix is bin-index radius, NOT cycles/pixel; fx/fy include axis calibration; spacing requires matching nonempty axis units",
    }, f
