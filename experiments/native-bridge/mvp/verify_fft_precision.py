# -*- coding: utf-8 -*-
"""Independent offline error attribution; does not import/call DigitalMicrograph.

No tolerance is learned from observed data. A direct-DM equivalence PASS does
not convert a numerical FAIL into PASS. The original 0.5 absolute round-trip
threshold and every original result remain unchanged.
"""
import argparse
import base64
import hashlib
import io
import json
import os

from fft_precision_fixture import arrays, POLICY


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    require(os.path.getsize(path) <= 4 * 1024 * 1024, "JSON budget exceeded")
    with open(path, "r", encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def read_array(directory, descriptor, dtype, shape):
    import numpy as np
    name = descriptor.get("file")
    require(type(name) is str and os.path.basename(name) == name and name.endswith(".npy"), "Snapshot must be one local basename")
    path = os.path.join(directory, name)
    require(not os.path.islink(path) and os.path.getsize(path) <= 1024 * 1024, "Snapshot file budget/link invalid")
    with open(path, "rb") as source: raw = source.read()
    require(hashlib.sha256(raw).hexdigest() == descriptor.get("sha256"), "Snapshot hash mismatch")
    stream = io.BytesIO(raw)
    require(shape in ([8, 8], [128, 128]) and dtype in ("uint32", "float32", "complex64"), "Fixed snapshot descriptor required")
    require(np.lib.format.read_magic(stream) == (1, 0), "Fixed snapshot requires NPY version 1.0")
    header_shape, fortran, header_dtype = np.lib.format.read_array_header_1_0(stream)
    require(tuple(header_shape) == tuple(shape) and header_dtype == np.dtype(dtype) and fortran is False,
            "Snapshot header differs from fixed shape/dtype/order")
    require(stream.tell() + shape[0] * shape[1] * header_dtype.itemsize == len(raw), "Snapshot payload size mismatch")
    stream.seek(0); values = np.load(stream, allow_pickle=False)
    require(stream.tell() == len(raw) and type(values) is np.ndarray and str(values.dtype) == dtype and list(values.shape) == shape and
            descriptor.get("dtype") == dtype and descriptor.get("shape") == shape and values.flags.c_contiguous and np.isfinite(values).all(),
            "Snapshot dtype/shape/finiteness/bytes mismatch")
    return values


def error_terms(source, spectrum, inverse, real):
    import numpy as np
    require(source.dtype in (np.uint32, np.float32) and source.ndim == 2 and source.shape in ((8, 8), (128, 128)), "Fixed source dtype/shape required")
    require(spectrum.dtype == inverse.dtype == np.complex64 and real.dtype == np.float32 and source.shape == spectrum.shape == inverse.shape == real.shape,
            "Full complex64 transform / float32 component required")
    require(all(np.isfinite(value).all() for value in (source, spectrum, inverse, real)), "Nonfinite precision input")
    require(real.tobytes(order="C") == inverse.real.copy(order="C").tobytes(order="C"), "REAL changed stored inverse component")
    original = source.astype(np.float64); converted = source.astype(np.float32).astype(np.float64)
    reference_spectrum = np.fft.fftshift(np.fft.ifft2(converted)) * source.size
    forward_error = float(np.abs(spectrum.astype(np.complex128) - reference_spectrum).max())
    forward_bound = POLICY["fft_absolute_error_factor_of_sum_abs"] * float(np.abs(converted).sum())
    # Apply the already-declared inverse convention to the SAME saved spectrum.
    # This separates error present in stored forward components from extra
    # error introduced by the vendor inverse; it is not a runtime replacement.
    ideal_inverse_of_stored = np.fft.fft2(np.fft.ifftshift(spectrum.astype(np.complex128))) / source.size
    return {
        "uint32_to_float32_max_absolute_error": float(np.abs(converted - original).max()),
        "forward_stored_complex64_max_absolute_error": forward_error,
        "forward_predeclared_absolute_bound": forward_bound,
        "forward_tolerance": "PASS" if forward_error <= forward_bound else "FAIL",
        "stored_spectrum_ideal_inverse_vs_converted_max_complex_error": float(np.abs(ideal_inverse_of_stored - converted).max()),
        "native_inverse_vs_ideal_inverse_of_stored_max_complex_error": float(np.abs(inverse.astype(np.complex128) - ideal_inverse_of_stored).max()),
        "roundtrip_vs_converted_max_absolute_error": float(np.abs(real.astype(np.float64) - converted).max()),
        "roundtrip_vs_original_max_absolute_error": float(np.abs(real.astype(np.float64) - original).max()),
        "inverse_max_imaginary_residual": float(np.abs(inverse.imag).max()),
        "inverse_predeclared_max_absolute_error": POLICY["inverse_max_absolute_error"],
        "roundtrip_tolerance": "PASS" if float(np.abs(real.astype(np.float64) - original).max()) <= POLICY["inverse_max_absolute_error"] else "FAIL",
        "interpretation": "maxima are separate diagnostics, not an additive error identity",
    }


def verify(directory, expected_pid=None, expected_session=None):
    fixture = load_json(os.path.join(directory, "fixture.json")); observation = load_json(os.path.join(directory, "observation.json"))
    pid = fixture.get("host_pid"); session = fixture.get("session")
    require(type(pid) is int and pid > 0 and type(session) is str and len(session) == 32 and all(c in "0123456789abcdef" for c in session), "Original host identity missing")
    require((expected_pid is None or expected_pid == pid) and (expected_session is None or expected_session == session), "Expected host/session mismatch")
    require(fixture.get("status") == "RECORDED_SYNTHETIC_FIXTURE" and observation.get("status") == "RECORDED_SAME_HOST_PRECISION_COMPARISON" and
            fixture.get("policy") == observation.get("policy") == POLICY and observation.get("host_pid") == pid and observation.get("session") == session and
            observation.get("source_pixels_unchanged") is True and observation.get("python_is_listener") is False and fixture.get("python_is_listener") is False,
            "Same-host source/observer/fixed policy validation failed")
    require(set(fixture.get("images", {})) == set(observation.get("cases", {})) == set(arrays()), "Incomplete precision matrix")
    report = {"schema": 1, "status": "FAIL", "host_pid": pid, "session": session, "cases": {}, "policy": POLICY,
              "scope": "offline verification of supplied same-host evidence; not fresh host execution"}
    direct_ids = set(); source_ids = {entry.get("id") for entry in fixture["images"].values()}; bridge_ids = set(); threads = None
    require(len(source_ids) == 6 and all(type(v) is int and v > 0 for v in source_ids), "Source ID matrix invalid")
    for label, fixed in arrays().items():
        entry = fixture["images"][label]; row = observation["cases"][label]; shape = list(fixed.shape)
        require(row.get("source_id") == entry["id"], "Source identity mismatch")
        source = read_array(directory, entry, str(fixed.dtype), shape)
        require(source.tobytes() == fixed.tobytes(), "Source differs from predeclared synthetic fixture")
        snaps = row["snapshots"]; ids = {}; data = {}
        for kind, op in (("fft", "FFT"), ("ifft", "IFFT"), ("real", "REAL"), ("read", "READ")):
            result = row["native"][kind]; receipt = result["native_receipt"]
            args = [entry["id"]] if kind == "fft" else [ids["fft"]] if kind == "ifft" else [ids["ifft"]] if kind == "real" else [ids["real"], 0, 0, shape[1], shape[0]]
            require(receipt.get("state") == "completed" and receipt.get("host_pid") == pid and receipt.get("session") == session and
                    receipt.get("original_operation") == op and receipt.get("normalized_args") == args and receipt.get("request_id") == receipt.get("id") and
                    type(receipt.get("id")) is str and len(receipt["id"]) > 0, "Original MCP operation/PID/session/ID/arguments mismatch")
            require(receipt.get("result_type") == ("native_data_snapshot" if kind == "read" else "native_fourier_operation") and receipt.get("result_version") == (1 if kind == "read" else 2), "Receipt schema mismatch")
            current = (receipt.get("exec_tid"), receipt.get("worker_tid"))
            require(all(type(v) is int and v > 0 for v in current) and current[0] != current[1] and (threads is None or current == threads), "MCP execution threads mismatch")
            threads = current
            if kind == "read":
                require(result.get("source_image_id") == ids["real"] and result.get("requested_rect") == result.get("effective_rect") == args[1:] and
                        result.get("dtype") == "float32" and result.get("shape") == shape and result.get("byte_order") == "little" and result.get("array_order") == "C",
                        "READ shape/identity/coordinates/order differ")
                require(base64.b64decode(result["values_base64"], validate=True) == data["real"].tobytes(), "READ pixel difference")
                continue
            image_id = result.get("image_id"); parent = args[0]
            require(type(image_id) is int and image_id > 0 and image_id not in bridge_ids and image_id not in source_ids and result.get("source_image_id") == parent,
                    "Native result identity aliases source/another result")
            bridge_ids.add(image_id); ids[kind] = image_id
            dtype = "float32" if kind == "real" else "complex64"
            require(result.get("computation") == "DM native" and result.get("image", {}).get("id") == image_id and
                    result["image"].get("dtype") == dtype and result["image"].get("shape") == shape, "DM transform metadata mismatch")
            data[kind] = read_array(directory, snaps["bridge_" + kind], dtype, shape)
        for kind in ("fft", "ifft"):
            direct_id = row.get("direct_ids", {}).get(kind)
            require(type(direct_id) is int and direct_id > 0 and direct_id not in direct_ids and direct_id not in source_ids and direct_id not in bridge_ids,
                    "Direct DM output identity aliases another image")
            direct_ids.add(direct_id)
            direct = read_array(directory, snaps["direct_" + kind], "complex64", shape)
            require(direct.tobytes() == data[kind].tobytes(), "Direct DM and MCP differ: " + label + " " + kind)
        terms = error_terms(source, data["fft"], data["ifft"], data["real"])
        terms.update(direct_DM_vs_MCP="PASS_BITWISE", READ_vs_same_host_raw_pixels="PASS_BITWISE")
        report["cases"][label] = terms
    # Identical converted input must be compared across BOTH original dtypes.
    for label in ("low", "high", "medium"):
        for kind in ("fft", "ifft"):
            left = observation["cases"][label + "_uint32"]["snapshots"]["bridge_" + kind]
            right = observation["cases"][label + "_float32"]["snapshots"]["bridge_" + kind]
            a = read_array(directory, left, "complex64", left["shape"]); b = read_array(directory, right, "complex64", right["shape"])
            require(a.tobytes() == b.tobytes(), "uint32 and its exact binary32 control transform differently")
    report["direct_equivalence"] = "PASS_BITWISE_ALL_CASES"
    require(direct_ids.isdisjoint(bridge_ids | source_ids), "Direct outputs alias another case's native/source image")
    require(set(observation.get("owned_direct_image_ids", [])) == direct_ids and len(observation["owned_direct_image_ids"]) == 12 and
            observation.get("document_count") == fixture.get("document_count_after", -99) + 12 and fixture.get("document_count_after") == fixture.get("document_count_before", -99) + 7,
            "Direct document count/owned image identity mismatch")
    report["numeric_tolerance"] = "FAIL" if any(row["forward_tolerance"] == "FAIL" or row["roundtrip_tolerance"] == "FAIL" for row in report["cases"].values()) else "PASS"
    report["status"] = "FAIL_NUMERICAL_TOLERANCE" if report["numeric_tolerance"] == "FAIL" else "PASS_FIXED_SYNTHETIC_PRECISION"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True); parser.add_argument("--host-pid", type=int); parser.add_argument("--session")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); report = {"schema": 1, "status": "FAIL"}
    try: report = verify(args.directory, args.host_pid, args.session)
    except BaseException as error: report.update(error_type=type(error).__name__, error=str(error))
    with open(args.output, "x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, allow_nan=False); output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"] == "PASS_FIXED_SYNTHETIC_PRECISION" else 1


if __name__ == "__main__": raise SystemExit(main())
