# -*- coding: utf-8 -*-
"""Offline display/sample/PNG oracle. Never a scientific export or DM fallback."""
import argparse
import hashlib
import io
import json
import math
import re
import struct
import zlib

from verify_operations import bind_metadata, integer, read_json_hashed, strict_json

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAPPING = "x=floor(px*source_width/width);y=floor(py*source_height/height)"
ORIENTATION = "row-major [y,x], x increases right, y increases down"
SAMPLING = "nearest source integer index, no averaging"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def source_array(entry):
    import numpy as np
    with open(entry["source_npy"], "rb") as source:
        raw = source.read(8193)
    require(len(raw) <= 8192 and hashlib.sha256(raw).hexdigest() == entry.get("source_file_sha256"),
            "Preview source original NPY hash/size mismatch")
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    require(version in ((1, 0), (2, 0)), "Unsupported bounded source NPY version")
    shape, fortran, dtype = (np.lib.format.read_array_header_1_0(stream) if version == (1, 0)
                             else np.lib.format.read_array_header_2_0(stream))
    require(list(shape) == entry.get("shape") and len(shape) == 2 and all(integer(value, 1, 128) for value in shape) and
            not fortran and dtype == np.float32 and entry.get("dtype") == "float32",
            "Preview source NPY header dtype/shape mismatch")
    values = np.load(io.BytesIO(raw), allow_pickle=False)
    require(str(values.dtype) == entry["dtype"] and list(values.shape) == entry["shape"] and
            hashlib.sha256(values.tobytes(order="C")).hexdigest() == entry.get("pixel_sha256") and
            bool(np.isfinite(values).all()), "Preview source pixel/dtype/shape mismatch")
    return values


def reference_preview(values, max_width, max_height):
    require(integer(max_width, 1, 128) and integer(max_height, 1, 128), "Preview requested bounds invalid")
    height, width = min(values.shape[0], max_height), min(values.shape[1], max_width)
    samples, coordinates = [], []
    for py in range(height):
        for px in range(width):
            x, y = px*values.shape[1]//width, py*values.shape[0]//height
            coordinates.append([x, y])
            samples.append(float(values[y, x]))
    minimum, maximum = min(samples), max(samples)
    require(all(math.isfinite(value) for value in samples), "Nonfinite reference sample")
    span = maximum-minimum
    gray = []
    for value in samples:
        # Explicit binary64 operations, half-up rounding, and constant black.
        scaled = (value-minimum)/span*255.0 if span > 0 else 0.0
        gray.append(int(min(255.0, max(0.0, scaled))+0.5))
    return width, height, minimum, maximum, bytes(gray), coordinates, samples


def decode_gray8_png(raw):
    require(type(raw) is bytes and len(raw) <= 2*1024*1024 and raw[:8] == SIGNATURE, "PNG signature/size mismatch")
    offset, width, height, data, ended, data_closed = 8, None, None, bytearray(), False, False
    while offset < len(raw):
        require(offset+12 <= len(raw), "Truncated PNG chunk")
        length = struct.unpack(">I", raw[offset:offset+4])[0]
        name = raw[offset+4:offset+8]
        require(length <= 2*1024*1024 and offset+12+length <= len(raw), "PNG chunk length mismatch")
        payload = raw[offset+8:offset+8+length]
        crc = struct.unpack(">I", raw[offset+8+length:offset+12+length])[0]
        require((zlib.crc32(name+payload) & 0xffffffff) == crc, "PNG chunk CRC mismatch")
        require(not ended, "PNG bytes after IEND")
        if name == b"IHDR":
            require(width is None and offset == 8 and length == 13, "PNG IHDR order/length mismatch")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            require(integer(width, 1, 128) and integer(height, 1, 128) and
                    (depth, color, compression, filtering, interlace) == (8, 0, 0, 0, 0),
                    "PNG must be bounded ordinary grayscale8")
        elif name == b"IDAT":
            require(width is not None and not data_closed, "PNG IDAT order mismatch")
            data.extend(payload)
        elif name == b"IEND":
            require(width is not None and length == 0 and data, "PNG IEND/order mismatch")
            ended, data_closed = True, True
        else:
            raise RuntimeError("Unexpected PNG chunk")
        offset += 12+length
        if ended:
            require(offset == len(raw), "PNG bytes after IEND")
    require(ended and width is not None, "PNG is missing IHDR/IDAT/IEND")
    expected = (width+1)*height
    inflater = zlib.decompressobj()
    try:
        scanlines = inflater.decompress(bytes(data), expected+1)
    except zlib.error as error:
        raise RuntimeError("PNG deflate stream invalid") from error
    require(inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail and len(scanlines) == expected,
            "PNG deflate stream/decoded size mismatch")
    output, previous = bytearray(), bytearray(width)
    for y in range(height):
        start = y*(width+1)
        filter_type, row = scanlines[start], bytearray(scanlines[start+1:start+1+width])
        require(filter_type <= 4, "PNG row filter invalid")
        for x in range(width):
            left, up, upper_left = row[x-1] if x else 0, previous[x], previous[x-1] if x else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left+up)//2
            elif filter_type == 4:
                p = left+up-upper_left
                a, b, c = abs(p-left), abs(p-up), abs(p-upper_left)
                predictor = left if a <= b and a <= c else up if b <= c else upper_left
            else:
                predictor = 0
            row[x] = (row[x]+predictor) & 255
        output.extend(row)
        previous = row
    return width, height, bytes(output)


def collect(report, truth_path, operations_path, observation_path, preview_path, requests_path):
    truth, truth_hash = read_json_hashed(truth_path)
    operations, operations_hash = read_json_hashed(operations_path)
    observation, observation_hash = read_json_hashed(observation_path)
    previews, previews_hash = read_json_hashed(preview_path)
    with open(requests_path, "rb") as source:
        requests_raw = source.read()
    requests = [strict_json(line) for line in requests_raw.splitlines() if line.strip()]
    report.update(truth_sha256=truth_hash, operations_report_sha256=operations_hash,
                  operations_observation_sha256=observation_hash, preview_observations_sha256=previews_hash,
                  preview_requests_sha256=hashlib.sha256(requests_raw).hexdigest())
    session, host_pid = truth.get("session"), truth.get("host_pid")
    require(all(integer(value.get("schema"), 1, 1) for value in (truth, operations, observation, previews)) and
            type(session) is str and re.fullmatch(r"[a-f0-9]{32}", session) and integer(host_pid, 1) and
            truth.get("kind") == operations.get("kind") == "synthetic-only" and truth.get("python_is_listener") is False and
            truth.get("status") == operations.get("status") == previews.get("status") == "RECORDED" and
            previews.get("session") == operations.get("session") == observation.get("session") == session and
            all(integer(value.get("host_pid"), host_pid, host_pid) for value in (operations, observation, previews)),
            "Preview recorded host/session mismatch")
    require(observation.get("status") == "RECORDED_PARTIAL_QUALIFICATION" and observation.get("truth_sha256") == truth_hash and
            observation.get("operations_report_sha256") == operations_hash and observation.get("source_protection") == "PASS" and
            observation.get("independent_memory") == "PASS" and observation.get("raw_views_and_wrappers_released") is True and
            integer(observation.get("output_count"), 32, 32), "Formal source/memory observation missing or bound to different evidence")
    statuses = [entry.get("receipt", {}) for entry in operations.get("checks", []) if entry.get("label") == "STATUS"]
    require(len(statuses) == 1, "Preview host STATUS anchor missing/ambiguous")
    anchor, status = statuses[0], statuses[0].get("result", {})
    require(anchor.get("protocol") == "NB2" and anchor.get("session") == session and anchor.get("state") == "completed" and
            anchor.get("original_operation") == "STATUS" and anchor.get("normalized_args") == [] and
            anchor.get("result_type") == "status" and integer(anchor.get("result_version"), 1, 1) and
            integer(anchor.get("host_pid"), host_pid, host_pid) and integer(anchor.get("exec_tid"), 1) and
            integer(anchor.get("worker_tid"), 1) and anchor["exec_tid"] != anchor["worker_tid"] and
            status.get("backend") == "digitalmicrograph-native" and status.get("ready") is True and
            status.get("binary_gate") is True and status.get("candidate_execution_enabled") is True and
            status.get("supported_build") == "3.53.4137.0-x64" and
            integer(status.get("host_pid"), host_pid, host_pid) and
            integer(status.get("host_thread"), anchor["exec_tid"], anchor["exec_tid"]),
            "Preview host STATUS anchor mismatch")
    sources = {entry["label"]: entry for entry in truth.get("images", [])}
    require("A" in sources and "FILTER_A" in sources and sources["A"]["shape"] == [4, 4] and
            sources["FILTER_A"]["shape"] == [8, 8], "Dedicated preview source labels/shapes missing")
    checks = previews.get("checks")
    require(type(checks) is list and len(checks) == 2 and {entry.get("label") for entry in checks} == {"A", "FILTER_A"} and
            len(requests) == 2, "Complete two-case preview matrix required")
    ledger, seen = {}, set()
    previous_ids = {entry.get("id") for entry in operations.get("checks", [])}
    for request in requests:
        request_id = request.get("id")
        require(type(request) is dict and set(request) == {"protocol", "session", "host_pid", "id", "op", "args", "wire"} and
                type(request_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) and
                request_id not in ledger and request_id not in previous_ids, "Invalid/duplicate original PREVIEW request")
        ledger[request_id] = request
    for entry in checks:
        label = entry["label"]
        source = sources[label]
        values = source_array(source)
        bounds = [128, 128] if label == "A" else [3, 5]
        args = [source["id"]]+bounds
        request, receipt = entry.get("request", {}), entry.get("receipt", {})
        request_id = request.get("id")
        require(request_id in ledger and request_id not in seen and request == ledger[request_id] and
                request.get("protocol") == "NB2" and request.get("session") == session and
                integer(request.get("host_pid"), host_pid, host_pid) and request.get("op") == "PREVIEW" and
                type(request.get("args")) is list and all(integer(value) for value in request["args"]) and request["args"] == args and
                request.get("wire") == "NB2 %s %s PREVIEW %s\n" % (session, request_id, " ".join(map(str,args))),
                "Original PREVIEW wire/identity/arguments mismatch")
        seen.add(request_id)
        require(receipt.get("protocol") == "NB2" and receipt.get("session") == session and receipt.get("id") == request_id and
                receipt.get("state") == "completed" and integer(receipt.get("host_pid"), host_pid, host_pid) and
                integer(receipt.get("exec_tid"), anchor["exec_tid"], anchor["exec_tid"]) and
                integer(receipt.get("worker_tid"), anchor["worker_tid"], anchor["worker_tid"]) and
                receipt.get("original_operation") == "PREVIEW" and type(receipt.get("normalized_args")) is list and
                all(integer(value) for value in receipt["normalized_args"]) and receipt["normalized_args"] == args and
                receipt.get("result_type") == "native_preview" and integer(receipt.get("result_version"), 1, 1) and
                "error" not in receipt and "code" not in receipt, "PREVIEW native receipt identity/state mismatch")
        timings = receipt.get("timings_us")
        require(type(timings) is dict and all(integer(timings.get(key), 0, (1 << 53)-1) for key in ("queue", "execute")),
                "PREVIEW native timing mismatch")
        result = receipt.get("result", {})
        require(type(result) is dict and result.get("backend") == "digitalmicrograph-native" and
                result.get("operation") == "PREVIEW" and integer(result.get("image_id"), source["id"], source["id"]) and
                result.get("operator") == "GMS::Image::GetRealValue" and
                result.get("computation") == "DM native value reads; display adaptation only" and
                result.get("quantitative") is False and result.get("source_write_requested") is False and result.get("snapshot_atomic") is False,
                "PREVIEW display/native semantics mismatch")
        bind_metadata(result.get("source"), source["id"], {"values": values, "name": source["name"],
                      "calibration": source["calibration"], "intensity_calibration": source["intensity_calibration"]})
        width, height, minimum, maximum, gray, coordinates, samples = reference_preview(values,*bounds)
        require(integer(result.get("width"), width, width) and integer(result.get("height"), height, height) and
                integer(result.get("sample_count"), width*height, width*height), "PREVIEW size/sample count/no-upscale mismatch")
        require(type(result.get("sampled_minimum")) in (int,float) and type(result.get("sampled_maximum")) in (int,float) and
                result["sampled_minimum"] == minimum and result["sampled_maximum"] == maximum,
                "PREVIEW sampled raw range mismatch; intensity calibration must not be applied")
        require(result.get("range_source") == "sampled native point values" and integer(result.get("constant_range_gray8"), 0, 0) and
                result.get("mapping") == MAPPING and result.get("orientation") == ORIENTATION and result.get("sampling") == SAMPLING,
                "PREVIEW coordinate/orientation/sampling policy mismatch")
        require(type(result.get("gray8_hex")) is str and result["gray8_hex"] == gray.hex(),
                "PREVIEW grayscale differs from floor sampling/binary64 half-up reference")
        with open(entry["png"], "rb") as source_file:
            png = source_file.read(2*1024*1024+1)
        png_hash = hashlib.sha256(png).hexdigest()
        require(png_hash == entry.get("png_sha256"), "Preview PNG original byte hash mismatch")
        png_width, png_height, png_gray = decode_gray8_png(png)
        require((png_width, png_height) == (width, height) and png_gray == gray,
                "PNG dimensions/decoded gray pixels differ from raw source mapping")
        report["checks"].append({"label": label, "request_id": request_id, "image_id": source["id"], "status": "PASS",
            "source_file_sha256": source["source_file_sha256"], "source_pixel_sha256": source["pixel_sha256"],
            "width": width, "height": height, "sample_coordinates_xy": coordinates, "raw_sample_values": samples,
            "sampled_minimum": minimum, "sampled_maximum": maximum, "png_sha256": png_hash,
            "gray8_pixel_sha256": hashlib.sha256(gray).hexdigest(), "intensity_calibration_applied": False,
            "source_intensity_calibration": source["intensity_calibration"], "constant_input": minimum == maximum})
    require(seen == set(ledger), "PREVIEW requests/receipts not one-to-one")
    report.update(status="PASS_DISPLAY_SAMPLE_MAPPING", host_pid=host_pid, session=session,
                  source_protection="PASS_RECORDED_PRIOR_SAME_HOST_ORACLE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("truth", "operations-report", "operations-observation", "preview-observations", "preview-requests", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args(argv)
    with open(args.output, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "scope": "offline_display_sample_mapping_only", "checks": [],
                  "scientific_export": False, "quantitative_analysis": False, "model_visual_verification": "NOT_TESTED",
                  "post_preview_source_invariance": "NOT_TESTED_BY_THIS_OFFLINE_ORACLE", "runtime_fallback": False}
        try:
            collect(report,args.truth,args.operations_report,args.operations_observation,args.preview_observations,args.preview_requests)
        except BaseException as error:
            report.update(error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False)
        output.write("\n")
    print(report["status"]+": display/sample mapping only")
    return 0 if report["status"] == "PASS_DISPLAY_SAMPLE_MAPPING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
