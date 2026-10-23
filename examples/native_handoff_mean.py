# -*- coding: utf-8 -*-
"""Explicit external NumPy example over an immutable saved native READ capture.

Run by the user in a separate existing workspace. Never imported by the MCP
server or plugin. No DigitalMicrograph import, socket, script dispatch or return
to DM occurs. This one raw float64 mean is optional user-owned postprocessing.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_file(path, limit=1024*1024):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, "Bounded ordinary capture file required")
    raw = path.read_bytes()
    require(len(raw) <= limit, "Capture file exceeded budget")
    return raw


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate metadata key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError("Nonfinite JSON")))


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def output_target(workspace, relative):
    require(not Path(relative).is_absolute() and ":" not in relative and not any(ord(c) < 32 for c in relative),
            "Output must be a new workspace-relative directory")
    parts = re.split(r"[\\/]", relative)
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
    require(all(part and part not in (".", "..") and not part.endswith((".", " ")) and not reserved.match(part) for part in parts),
            "Unsafe relative output directory")
    target = workspace.joinpath(*parts)
    parent = target.parent.resolve(strict=True)
    require(parent == workspace or workspace in parent.parents, "Output parent escapes workspace")
    return parent / target.name


def run(workspace_arg, capture_arg, output_relative):
    import io
    import numpy as np

    workspace = Path(workspace_arg).resolve(strict=True)
    require(workspace.is_dir(), "Independent workspace must already exist")
    capture = Path(capture_arg).resolve(strict=True)
    require(capture.is_dir(), "Explicit captured input directory required")
    output = output_target(workspace, output_relative)
    require(output != capture and capture not in output.parents, "External output must not be inside its source capture")
    raw = {name: read_file(capture / name) for name in ("input.npy", "input.json", "capture.json")}
    manifest, info = parse_json(raw["capture.json"]), parse_json(raw["input.json"])
    require(manifest.get("schema_version") == info.get("schema_version") == 1 and manifest.get("state") == "captured" and
            manifest.get("capture_id") == info.get("capture_id") and info.get("input_file") == "input.npy" and
            sha(raw["input.npy"]) == info.get("input_sha256") == manifest.get("input_sha256") and
            sha(canonical(info)) == manifest.get("input_metadata_sha256"), "Capture identity/file/metadata hash mismatch")
    require(info.get("dtype") == "float32" and info.get("byte_order") == "little" and info.get("array_order") == "C" and
            info.get("axes") == ["y", "x"] and info.get("intensity_calibration_applied") is False and
            info.get("intensity_calibration") == {"origin": None, "scale": None, "unit": None, "status": "NOT_READ"},
            "Explicit raw native handoff calibration/type required")
    receipt = info.get("native_receipt", {})
    uint32 = lambda value: type(value) is int and 0 <= value <= 0xffffffff
    rect = info.get("source_rect_xyxy")
    require(uint32(info.get("source_image_id")) and type(rect) is list and len(rect) == 4 and
            all(uint32(value) for value in rect) and rect[2] > rect[0] and rect[3] > rect[1],
            "Capture source ID/ROI identity is invalid")
    timings = receipt.get("timings_us", {})
    require(receipt.get("protocol") == "NB2" and receipt.get("state") == "completed" and
            receipt.get("original_operation") == "READ" and receipt.get("result_type") == "native_data_snapshot" and
            type(receipt.get("result_version")) is int and receipt["result_version"] == 1 and
            type(receipt.get("session")) is str and re.fullmatch(r"[a-f0-9]{32}", receipt["session"]) is not None and
            type(receipt.get("id")) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", receipt["id"]) is not None and
            receipt["id"] == receipt.get("request_id") and
            all(uint32(receipt.get(key)) and receipt[key] > 0 for key in ("host_pid", "exec_tid", "worker_tid")) and
            receipt["exec_tid"] != receipt["worker_tid"] and type(timings) is dict and set(timings) == {"queue", "execute"} and
            all(type(timings[key]) is int and 0 <= timings[key] <= 2**53-1 for key in timings) and
            type(receipt.get("normalized_args")) is list and all(uint32(value) for value in receipt["normalized_args"]) and
            receipt["normalized_args"] == [info["source_image_id"]] + rect and
            not any(key in receipt for key in ("error", "code", "result")) and
            sha(canonical(receipt)) == info.get("native_receipt_sha256"),
            "Original native READ receipt/hash missing")
    require(manifest.get("source_image_id") == info["source_image_id"] and manifest.get("source_rect_xyxy") == rect and
            manifest.get("source_shape_yx") == info.get("source_shape_yx") and manifest.get("source_dtype") == "float32" and
            manifest.get("source_data_type_code") == 2 and manifest.get("native_session") == receipt["session"] and
            manifest.get("native_request_id") == receipt["id"] and
            manifest.get("native_receipt_sha256") == info["native_receipt_sha256"] and
            type(info.get("saved_snapshot_sha256")) is str and re.fullmatch(r"[a-f0-9]{64}", info["saved_snapshot_sha256"]) and
            manifest.get("saved_snapshot_sha256") == info["saved_snapshot_sha256"],
            "Capture manifest/input/native session-request identity mismatch")
    values = np.load(io.BytesIO(raw["input.npy"]), allow_pickle=False)
    require(type(values) is np.ndarray and values.dtype == np.dtype("<f4") and values.ndim == 2 and
            list(values.shape) == info.get("shape_yx") and 0 < values.size <= 16384 and values.flags.c_contiguous and
            list(values.shape) == [rect[3] - rect[1], rect[2] - rect[0]] and
            type(info.get("source_shape_yx")) is list and len(info["source_shape_yx"]) == 2 and
            all(type(value) is int and value > 0 for value in info["source_shape_yx"]) and
            rect[2] <= info["source_shape_yx"][1] and rect[3] <= info["source_shape_yx"][0] and
            values.nbytes == info.get("raw_bytes") and sha(values.tobytes(order="C")) == info.get("pixel_sha256") and
            np.isfinite(values).all(), "Bounded finite raw NPY shape/bytes/pixel hash mismatch")
    parameters = {"schema_version": 1, "operation": "raw mean", "execution": "explicit external NumPy example",
                  "capture_id": info["capture_id"], "capture_files_sha256": {name: sha(data) for name, data in raw.items()},
                  "dtype": "float32", "accumulator_dtype": "float64", "shape_yx": info["shape_yx"],
                  "source_image_id": info["source_image_id"], "source_rect_xyxy": info["source_rect_xyxy"],
                  "native_session": receipt["session"], "native_request_id": receipt["id"],
                  "native_receipt_sha256": info["native_receipt_sha256"], "intensity_calibration_applied": False,
                  "source_calibration_dm": info["source_calibration_dm"], "working_calibration_xy": info["working_calibration_xy"],
                  "python_version": sys.version, "numpy_version": np.__version__, "platform": platform.platform(),
                  "dm_called": False, "result_returned_to_dm": False}
    script = Path(__file__).read_bytes(); parameters["script_sha256"] = sha(script)
    output.mkdir()  # Exclusive, after validation; never overwrite an existing directory.
    run_file = output / "run.json"
    with run_file.open("x", encoding="utf-8") as status_file:
        status = {"schema_version": 1, "state": "running", "scope": "explicit external raw mean only"}
        def save_status():
            status_file.seek(0); status_file.truncate()
            json.dump(status, status_file, ensure_ascii=True, allow_nan=False, indent=2)
            status_file.write("\n"); status_file.flush(); os.fsync(status_file.fileno())
        try:
            save_status()
            write_new(output / "native_handoff_mean.py", script)
            write_new(output / "parameters.json", canonical(parameters) + b"\n")
            mean = float(np.mean(values, dtype=np.float64))
            require(math.isfinite(mean), "External raw mean is nonfinite")
            require(all(sha(read_file(capture / name)) == parameters["capture_files_sha256"][name] for name in raw),
                    "Source capture changed during external processing")
            results = {"schema_version": 1, "state": "complete", "scope": "explicit external NumPy raw mean only",
                       "capture_id": info["capture_id"], "mean": mean, "sample_count": int(values.size),
                       "accumulator_dtype": "float64", "intensity_calibration_applied": False,
                       "intensity_unit": None, "intensity_calibration_status": "NOT_READ", "dm_called": False,
                       "result_returned_to_dm": False, "parameters_sha256": sha(canonical(parameters)),
                       "script_sha256": parameters["script_sha256"], "input_sha256": info["input_sha256"]}
            write_new(output / "results.json", canonical(results) + b"\n")
            status.update(state="complete", results_sha256=sha(read_file(output / "results.json")))
            save_status()
            return results
        except BaseException as error:
            status.update(state="failed", error_type=type(error).__name__, error=str(error)); save_status(); raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.workspace, args.capture, args.output)
        print(json.dumps(result, allow_nan=False)); return 0
    except BaseException as error:
        print(json.dumps({"state": "failed", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=True)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
