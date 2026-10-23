# -*- coding: utf-8 -*-
"""Offline, independent FILTER oracle over explicit synthetic-host snapshots.

This tool imports no DM or native runtime. It never chooses the best matching
kernel or FFT convention. Fourier checks require --include-fourier explicitly.
They use a fixed positive-exponent centered DFT, its normalized inverse, and
the exact quarter-turn roots available in this small predetermined fixture.
"""
import argparse
import hashlib
import io
import json
import math
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError("Nonfinite JSON")))


def read_json(path):
    with open(path, "rb") as source:
        raw = source.read()
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


def read_array(path):
    import numpy as np
    with open(path, "rb") as source:
        raw = source.read()
    values = np.load(io.BytesIO(raw), allow_pickle=False)
    require(type(values) is np.ndarray, "Snapshot is not one NPY array")
    return values, hashlib.sha256(raw).hexdigest()


def filter_reference(values, opcode):
    """Predetermined 3x3 reference plus a per-pixel float32 rounding bound.

    gamma(19) bounds 9 products + 8 additions + vendor and reference storage;
    power-of-two coefficients are exactly representable. Sobel additionally
    bounds norm sensitivity and two rounded squares/add plus final storage.
    The bound includes absolute float32 subnormal rounding. Edge values must
    match exactly and receive zero tolerance. No vendor computation is called.
    """
    import numpy as np
    require(type(opcode) is int and opcode in (1, 2, 3, 4), "Unknown fixed FILTER opcode")
    require(type(values) is np.ndarray and values.dtype == np.float32 and values.ndim == 2 and
            min(values.shape) >= 5 and max(values.shape) <= 256 and np.isfinite(values).all(),
            "FILTER reference requires finite float32 2D synthetic input, each dimension 5..256")
    kernels = {
        1: ((1 / 16.0, 2 / 16.0, 1 / 16.0), (2 / 16.0, 4 / 16.0, 2 / 16.0), (1 / 16.0, 2 / 16.0, 1 / 16.0)),
        3: ((-1, -1, -1), (-1, 8, -1), (-1, -1, -1)),
        4: ((-1, -1, -1), (-1, 9, -1), (-1, -1, -1)),
    }
    gx = ((1, 0, -1), (2, 0, -2), (1, 0, -1))
    gy = ((1, 2, 1), (0, 0, 0), (-1, -2, -1))
    expected = values.copy() if opcode in (1, 4) else np.zeros_like(values)
    tolerance = np.zeros(values.shape, dtype=np.float64)
    u = 2.0 ** -24
    gamma19 = (19 * u) / (1 - 19 * u)
    gamma2 = (2 * u) / (1 - 2 * u)
    subnormal = 2.0 ** -149

    def dot(y, x, kernel):
        products = [float(values[y + dy - 1, x + dx - 1]) * kernel[dy][dx]
                    for dy in range(3) for dx in range(3)]
        return math.fsum(products), math.fsum(abs(value) for value in products)

    for y in range(1, values.shape[0] - 1):
        for x in range(1, values.shape[1] - 1):
            if opcode == 2:
                a, sa = dot(y, x, gx)
                b, sb = dot(y, x, gy)
                af, bf = np.float32(a), np.float32(b)
                squared = np.float32(np.float32(af * af) + np.float32(bf * bf))
                expected[y, x] = np.float32(math.sqrt(float(squared)))
                component_error = math.hypot(gamma19 * sa + 19 * subnormal,
                                             gamma19 * sb + 19 * subnormal)
                magnitude = math.hypot(a, b)
                # Norm is 1-Lipschitz. gamma2 bounds the squared-norm
                # operations; its square-root relative effect is <= gamma2.
                # Both vendor and reference evaluate their rounded norm.
                tolerance[y, x] = (component_error + 2 * (gamma2 + u) *
                                    (magnitude + component_error) + 8 * subnormal) / (1 - u)
            else:
                total, absolute_sum = dot(y, x, kernels[opcode])
                expected[y, x] = np.float32(total)
                tolerance[y, x] = gamma19 * absolute_sum + 19 * subnormal
    require(np.isfinite(expected).all() and np.isfinite(tolerance).all(), "Reference exceeds finite float32 range")
    return expected, tolerance


def verify_filter(values, actual, opcode):
    import numpy as np
    expected, tolerance = filter_reference(values, opcode)
    require(type(actual) is np.ndarray and actual.dtype == np.float32 and actual.shape == values.shape and
            np.isfinite(actual).all(), "FILTER output dtype/shape/finite mismatch")
    errors = np.abs(actual.astype(np.float64) - expected.astype(np.float64))
    require(bool(np.all(errors <= tolerance)), "FILTER differs from predetermined kernel/edge reference")
    return {"maximum_absolute_error": float(errors.max()),
            "maximum_rounding_bound": float(tolerance.max()),
            "border_comparison": "exact", "interior_comparison": "float32_rounding_bound"}


def quarter_turn_dft(values, inverse=False):
    """Acceptance-only exact-root DFT, never imported by native/product code.

    The fixture dimensions/nonzero coordinates use only {1,i,-1,-i}. Reject
    other roots instead of introducing a fitted FFT tolerance or convention.
    Forward output is centered. Inverse input is centered and output is spatial.
    """
    import numpy as np
    require(type(values) is np.ndarray and values.ndim == 2 and
            values.dtype == (np.complex64 if inverse else np.float32) and
            1 <= min(values.shape) <= max(values.shape) <= 8 and np.isfinite(values).all(),
            "Quarter-turn reference requires small fixed finite float32/complex64 input")
    height, width = values.shape
    roots = (complex(1, 0), complex(0, 1), complex(-1, 0), complex(0, -1))
    result = np.empty(values.shape, dtype=np.complex64)
    for out_y in range(height):
        for out_x in range(width):
            real, imag = [], []
            for in_y in range(height):
                for in_x in range(width):
                    value = complex(values[in_y, in_x])
                    if value == 0:
                        continue
                    if inverse:
                        numerator = -4 * ((in_y - height // 2) * out_y * width +
                                          (in_x - width // 2) * out_x * height)
                    else:
                        numerator = 4 * ((out_y - height // 2) * in_y * width +
                                         (out_x - width // 2) * in_x * height)
                    denominator = height * width
                    require(numerator % denominator == 0, "Fixture needs roots outside the predetermined quarter-turn contract")
                    term = value * roots[(numerator // denominator) % 4]
                    real.append(term.real); imag.append(term.imag)
            scale = 1.0 / (height * width) if inverse else 1.0
            total = complex(math.fsum(real) * scale, math.fsum(imag) * scale)
            stored = np.complex64(total)
            require(complex(stored) == total, "Predetermined reference is not exactly representable as complex64")
            result[out_y, out_x] = stored
    return result


def verify_fourier(report, sources, operations, independent):
    import numpy as np
    hand_inputs = {
        "A": np.array([[1.25, -2.5, 3.75, 4], [-5, 6, 7, -8],
                       [9.25, 10, -11, 12], [13, 14.5, 15, -16]], dtype=np.float32),
        "CONSTANT": np.full((4, 4), 3.25, dtype=np.float32),
        "IMPULSE": np.zeros((4, 8), dtype=np.float32),
        "SINGLE_FREQUENCY": np.array([[1, 0, -1, 0], [2, 1, 0, 1],
                                      [1, 0, -1, 0], [0, -1, -2, -1]], dtype=np.float32),
    }
    hand_inputs["IMPULSE"][1, 2] = 1
    required_keys = {(kind, label) for label in hand_inputs for kind in ("FFT", "REAL", "IMAG", "IFFT", "IFFT_REAL")}
    required_keys.update({("VENDOR_ARG", "A"), ("VENDOR_NORM", "A")})
    entries = {}
    for entry in operations["outputs"]:
        if entry.get("kind") in ("UNARY", "BINARY", "FILTER"):
            continue
        require(type(entry.get("source_labels")) is list and len(entry["source_labels"]) == 1,
                "Fourier source identity missing")
        key = entry.get("kind"), entry["source_labels"][0]
        require(key in required_keys and key not in entries, "Unexpected/duplicate Fourier operation")
        entries[key] = entry
    require(set(entries) == required_keys, "Fixed four-fixture Fourier matrix incomplete")
    arrays = {}
    observations = {}
    for key, entry in entries.items():
        matches = [value for value in independent["outputs"] if value.get("image_id") == entry.get("image_id")]
        require(len(matches) == 1, "Fourier independent output missing/ambiguous")
        observation = matches[0]
        require(observation.get("kind") == key[0] and observation.get("source_labels") == [key[1]] and
                observation.get("parent_image_id") == entry.get("parent_image_id") and
                observation.get("status") == "NOT_QUALIFIED", "Fourier independent identity/qualification mismatch")
        actual, file_hash = read_array(observation["snapshot"])
        require(file_hash == observation.get("snapshot_file_sha256") and
                hashlib.sha256(actual.tobytes(order="C")).hexdigest() == observation.get("pixel_sha256") and
                str(actual.dtype) == observation.get("dtype") and list(actual.shape) == observation.get("shape") and
                np.isfinite(actual).all(), "Fourier original snapshot changed")
        op = "REAL" if key[0] == "IFFT_REAL" else key[0]
        calls = [value for value in operations["checks"] if value.get("id") == observation.get("request_id")]
        require(len(calls) == 1, "Fourier original receipt missing")
        call = calls[0]; receipt = call.get("receipt", {}); result = receipt.get("result", {})
        parent_id = sources[key[1]][0]["id"] if op == "FFT" else entry.get("parent_image_id")
        require(call.get("op") == receipt.get("original_operation") == op and
                call.get("args") == receipt.get("normalized_args") == [parent_id] and
                receipt.get("state") == "completed" and receipt.get("protocol") == "NB2" and
                receipt.get("session") == report["session"] and receipt.get("host_pid") == report["host_pid"] and
                receipt.get("result_type") == "native_fourier_operation" and receipt.get("result_version") == 1 and
                result.get("image_id") == entry.get("image_id") and result.get("computation") == "DM native" and
                result.get("source_write_requested") is False, "Fourier original operation receipt mismatch")
        arrays[key], observations[key] = actual, observation
    default_intensity = {"origin": 0.0, "scale": 1.0, "unit": ""}
    for label, hand_input in hand_inputs.items():
        require(label in sources and sources[label][1].dtype == np.float32 and
                np.array_equal(sources[label][1], hand_input), "Predetermined Fourier hand input changed")
        source_truth, source = sources[label]
        forward = quarter_turn_dft(source)
        # The inverse input is this same fixture's already checked forward
        # transform. Discrete Fourier orthogonality fixes the normalized
        # negative-sign inverse exactly to the original spatial array. This
        # also avoids fitting an irrational-root numerical tolerance for 8-wide
        # inverse sums whose exact cancellations are known analytically.
        inverse = source.astype(np.complex64)
        forward_cal, inverse_cal = [], []
        for axis in source_truth["calibration"]:
            dim = axis["dm_axis"]
            require(type(dim) is int and dim in (0, 1) and axis["unit"] == "nm" and
                    type(axis["scale"]) in (int, float) and axis["scale"] != 0, "Unsupported predetermined frequency unit/calibration")
            length = source.shape[-1 - dim]
            frequency_scale = 1.0 / (length * axis["scale"])
            raw_origin = (length + 1) / 2.0
            forward_cal.append({"dm_axis": dim, "origin": -raw_origin * frequency_scale,
                                "raw_origin": raw_origin, "scale": frequency_scale, "unit": "1/nm"})
            inverse_cal.append({"dm_axis": dim, "origin": 0.0, "raw_origin": 0.0,
                                "scale": axis["scale"], "unit": "nm"})
        references = {"FFT": forward, "REAL": forward.real, "IMAG": forward.imag,
                      "IFFT": inverse, "IFFT_REAL": inverse.real}
        if label == "A":
            parent = arrays[("FFT", label)]
            references["VENDOR_ARG"] = np.array([[math.atan2(float(z.imag), float(z.real)) for z in row]
                                                  for row in parent], dtype=np.float32)
            references["VENDOR_NORM"] = np.array([[float(z.real) ** 2 + float(z.imag) ** 2 for z in row]
                                                   for row in parent], dtype=np.float32)
        for kind, expected in references.items():
            key = kind, label
            actual, observation = arrays[key], observations[key]
            require(actual.dtype == expected.dtype and actual.shape == expected.shape and np.array_equal(actual, expected),
                    "Fourier differs from fixed positive-sign centered/normalized-inverse/phase/power reference: " + kind + ":" + label)
            if kind == "VENDOR_ARG":
                require(np.array_equal(np.signbit(actual[expected == 0]), np.signbit(expected[expected == 0])),
                        "Phase signed-zero branch differs from atan2")
            parent_kind = "IFFT" if kind == "IFFT_REAL" else "FFT"
            if kind != "FFT":
                require(entries[key].get("parent_image_id") == entries[(parent_kind, label)]["image_id"],
                        "Fourier parent lineage changed")
            calibration = inverse_cal if kind in ("IFFT", "IFFT_REAL") else forward_cal
            require(observation.get("calibration") == calibration and observation.get("intensity_calibration") == default_intensity,
                    "Fourier signed frequency/raw-origin/physical-zero/intensity calibration differs from fixed convention")
            report["fourier"].append({"operation": kind, "source_label": label, "image_id": entries[key]["image_id"],
                                       "status": "PASS", "comparison": "exact_on_predetermined_quarter_turn_fixture",
                                       "maximum_absolute_error": 0.0, "calibration": "PASS"})
    report["fft"] = "PASS_PREDETERMINED_SYNTHETIC_FIXTURES_ONLY"
    report["fourier_convention"] = {
        "forward": "centered positive-exponent DFT; unnormalized; no mean subtraction",
        "inverse": "negative-exponent inverse of centered input, divided by width*height",
        "arg": "atan2(imaginary,real), radians, signed-zero branch preserved",
        "norm": "real*real+imaginary*imaginary; squared magnitude",
        "frequency_scale": "1/(axis_length*source_signed_scale)",
        "frequency_raw_origin": "(axis_length+1)/2",
        "frequency_physical_zero": "-frequency_raw_origin*frequency_scale",
        "dc_pixel": "axis_length/2; its physical coordinate is -0.5*frequency_scale",
        "inverse_calibration": "original signed scale/unit; raw origin and physical zero reset to 0",
        "intensity_calibration": "origin 0, scale 1, empty unit",
        "qualification_scope": "exact 4x4 and 4x8 fixture matrix; no arbitrary-size/error-bound claim"}


def collect(report, truth_path, operations_path, independent_path, include_fourier=False):
    import numpy as np
    truth, truth_hash = read_json(truth_path)
    operations, operations_hash = read_json(operations_path)
    independent, independent_hash = read_json(independent_path)
    report.update(truth_sha256=truth_hash, operations_report_sha256=operations_hash,
                  independent_report_sha256=independent_hash)
    require(truth.get("schema") == operations.get("schema") == independent.get("schema") == 1,
            "Unsupported evidence schema")
    session, host = truth.get("session"), truth.get("host_pid")
    require(type(session) is str and re.fullmatch(r"[a-f0-9]{32}", session) is not None and
            type(host) is int and host > 0 and truth.get("kind") == operations.get("kind") == "synthetic-only" and
            truth.get("python_is_listener") is False and truth.get("status") == operations.get("status") == "RECORDED" and
            operations.get("session") == independent.get("session") == session and
            type(operations.get("host_pid")) is int and operations["host_pid"] == host and
            type(independent.get("host_pid")) is int and independent["host_pid"] == host,
            "Synthetic evidence/session/host mismatch")
    require(independent.get("status") == "RECORDED_PARTIAL_QUALIFICATION" and
            independent.get("source_protection") == "PASS" and
            independent.get("independent_memory") == "PASS" and
            independent.get("raw_views_and_wrappers_released") is True and
            independent.get("truth_sha256") == truth_hash and
            independent.get("operations_report_sha256") == operations_hash,
            "Independent source-protection report is absent or bound to different evidence")
    require(type(truth.get("initial_document_count")) is int and
            independent.get("document_count") == truth["initial_document_count"], "Document-count evidence mismatch")
    require(type(independent.get("output_count")) is int and
            independent["output_count"] == len(independent.get("outputs", [])) == len(operations.get("outputs", [])),
            "Independent output-count evidence mismatch")
    report.update(session=session, host_pid=host, source_protection="PASS_RECORDED_BY_INDEPENDENT_HOST_ORACLE")
    sources = {}
    image_ids = set()
    require(type(truth.get("images")) is list and truth["images"], "Missing source truth")
    for entry in truth["images"]:
        label, image_id = entry.get("label"), entry.get("id")
        require(type(label) is str and label not in sources and type(image_id) is int and
                0 < image_id < 0xffffffff and image_id not in image_ids, "Duplicate/invalid source identity")
        image_ids.add(image_id)
        values, file_hash = read_array(entry["source_npy"])
        require(file_hash == entry.get("source_file_sha256") and str(values.dtype) == entry.get("dtype") and
                list(values.shape) == entry.get("shape") and
                hashlib.sha256(values.tobytes(order="C")).hexdigest() == entry.get("pixel_sha256"),
                "Original source NPY/pixels/dtype/shape changed")
        sources[label] = (entry, values)
    require("FILTER_A" in sources, "Missing dedicated FILTER_A source")
    source_truth, source = sources["FILTER_A"]
    outputs = [value for value in operations.get("outputs", []) if value.get("kind") == "FILTER"]
    require(len(outputs) == 4 and {value.get("opcode") for value in outputs} == {1, 2, 3, 4},
            "Four fixed FILTER operations were not all recorded exactly once")
    seen_outputs = set()
    for entry in sorted(outputs, key=lambda value: value["opcode"]):
        image_id, opcode = entry.get("image_id"), entry["opcode"]
        require(type(opcode) is int and type(image_id) is int and 0 < image_id < 0xffffffff and
                image_id not in image_ids and image_id not in seen_outputs and
                entry.get("source_labels") == ["FILTER_A"], "FILTER source/output identity mismatch")
        seen_outputs.add(image_id)
        calls = [value for value in operations.get("checks", []) if value.get("op") == "FILTER" and
                 value.get("args") == [source_truth["id"], opcode] and value.get("expected_failure") is not True]
        require(len(calls) == 1, "FILTER receipt is missing or ambiguous")
        receipt = calls[0].get("receipt", {})
        result = receipt.get("result", {})
        require(receipt.get("protocol") == "NB2" and receipt.get("session") == session and receipt.get("host_pid") == host and
                receipt.get("state") == "completed" and receipt.get("original_operation") == "FILTER" and
                receipt.get("normalized_args") == [source_truth["id"], opcode] and
                receipt.get("result_type") == "native_image_operation" and receipt.get("result_version") == 1 and
                result.get("image_id") == image_id and result.get("backend") == "digitalmicrograph-native" and
                result.get("computation") == "DM native" and result.get("source_write_requested") is False,
                "FILTER original native receipt mismatch")
        observations = [value for value in independent.get("outputs", []) if value.get("image_id") == image_id]
        require(len(observations) == 1 and observations[0].get("kind") == "FILTER" and
                observations[0].get("status") == "NOT_QUALIFIED", "FILTER independent snapshot missing or changed qualification")
        observation = observations[0]
        require(observation.get("source_labels") == ["FILTER_A"] and observation.get("opcode") == opcode and
                type(observation.get("opcode")) is int and
                observation.get("request_id") == receipt.get("id") == calls[0].get("id") and
                type(observation.get("request_id")) is str and observation["request_id"],
                "Independent FILTER original identity mismatch")
        require(observation.get("calibration") == source_truth.get("calibration") and
                observation.get("intensity_calibration") == source_truth.get("intensity_calibration"),
                "FILTER output calibration differs from original source")
        actual, snapshot_hash = read_array(observation["snapshot"])
        require(snapshot_hash == observation.get("snapshot_file_sha256") and
                hashlib.sha256(actual.tobytes(order="C")).hexdigest() == observation.get("pixel_sha256") and
                str(actual.dtype) == observation.get("dtype") and list(actual.shape) == observation.get("shape"),
                "FILTER snapshot metadata mismatch")
        comparison = verify_filter(source, actual, opcode)
        report["filters"].append(dict(comparison, opcode=opcode, image_id=image_id, status="PASS",
                                       snapshot_sha256=snapshot_hash, source_image_id=source_truth["id"]))
    report["status"] = "PASS_FILTERS_ONLY"
    if include_fourier:
        report["fourier"] = []
        verify_fourier(report, sources, operations, independent)
        report["status"] = "PASS_PREPARED_OPERATIONS_MATH"
        report["scope"] = "offline_fixed_filter_and_fourier_fixture_math_only"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("truth", "operations-report", "independent", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--include-fourier", action="store_true",
                        help="Apply the fixed, exact quarter-turn Fourier fixture contract as well")
    args = parser.parse_args(argv)
    # Reserve first: errors preserve a fresh diagnostic and never overwrite an old result.
    with open(args.output, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "scope": "offline_fixed_filter_math_only",
                  "filters": [], "fft": "NOT_QUALIFIED", "source_protection": "NOT_TESTED",
                  "runtime_fallback": False, "ui_visibility": "NOT_TESTED", "lifecycle": "NOT_TESTED"}
        try:
            collect(report, args.truth, args.operations_report, args.independent, args.include_fourier)
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print(report["status"] + "; Fourier scope: " + report["fft"])
    return 0 if report["status"] in ("PASS_FILTERS_ONLY", "PASS_PREPARED_OPERATIONS_MATH") else 1


if __name__ == "__main__":
    raise SystemExit(main())
