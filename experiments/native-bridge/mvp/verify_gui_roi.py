# -*- coding: utf-8 -*-
"""One-shot same-process native GUI ROI oracle; no receiver or runtime fallback.

Inputs: gui-roi-fixture.json and pre-submission map.json in a private evidence
directory. Every output path must be new. Run once after serialized native
MCP reads; optionally allow explicitly performed GUI ROI additions with
DM_NATIVE_GUI_ROI_ALLOW_ADDITIONS=1. Never edit source pixels or ROI geometry.
"""
import hashlib
import io
import json
import math
import os
import re
import struct

from create_summary_fixture import require, spatial, intensity


RULE = "half-open pixel rectangle [x0,y0,x1,y1]; no rounding or clipping"


def load(path):
    require(os.path.getsize(path) <= 4 * 1024 * 1024, "ROI evidence JSON exceeds budget")
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "Duplicate evidence key")
            result[key] = value
        return result
    with open(path, encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def integer(value, maximum=0x7fffffff):
    return type(value) is int and 0 <= value <= maximum


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def local_path(directory, name):
    require(type(name) is str and os.path.basename(name) == name and name not in ("", ".", ".."), "One local evidence basename required")
    target = os.path.join(directory, name)
    require(not os.path.islink(target), "Linked evidence is not accepted")
    return target


def load_fixed_source(path, fixed, expected_sha256):
    """Validate a bounded immutable NPY header before NumPy may allocate data.

    Our tiny fixture's np.save writes canonical version-1 C-order arrays. Keep
    the old NumPy 1.18 header-reader signature; never trust a claimed shape or
    reopen a mutable filename between header validation and array loading.
    """
    import numpy as np
    limit = int(fixed.nbytes) + 4096
    require(os.path.isfile(path) and not os.path.islink(path), "Original source must be a regular non-symlink file")
    size = os.path.getsize(path)
    require(0 < size <= limit, "Original source NPY exceeds fixed byte budget")
    with open(path, "rb") as source:
        raw = source.read(limit + 1)
    require(len(raw) == size and len(raw) <= limit, "Original source changed or exceeds fixed byte budget")
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, "Original source file changed")
    snapshot = io.BytesIO(raw)
    require(np.lib.format.read_magic(snapshot) == (1, 0), "Fixed source requires canonical NPY version 1.0")
    shape, fortran, dtype = np.lib.format.read_array_header_1_0(snapshot)
    require(tuple(shape) == fixed.shape and dtype == fixed.dtype and fortran is False,
            "Original source NPY header differs from fixed shape/dtype/C-order")
    require(snapshot.tell() + int(fixed.nbytes) == len(raw), "Original source NPY payload size differs from fixed array")
    snapshot.seek(0)
    saved = np.load(snapshot, allow_pickle=False)
    require(saved.dtype == fixed.dtype and saved.shape == fixed.shape and saved.tobytes(order="C") == fixed.tobytes(order="C"),
            "Saved source not the fixed synthetic input")
    return saved


def document_signature(document):
    require(document is not None and document.IsValid(), "Enumerated document invalid")
    name = document.GetName()
    require(type(name) is str and name.isascii(), "Prepared document ASCII title required")
    image_count = document.CountImages()
    require(integer(image_count, 64), "Invalid document image count")
    ids = []
    for image_index in range(image_count):
        image = document.GetImage(image_index)
        require(image is not None and image.IsValid(), "Document image invalid")
        ids.append(image.GetID()); image = None
    require(len(ids) == len(set(ids)) and all(integer(value, 0xffffffff) for value in ids), "Document image identity invalid")
    scoped_displays = []
    for image_index in range(image_count):
        image = document.GetImage(image_index)
        total = image.CountImageDisplays()
        require(integer(total, 16), "Invalid scoped display bound")
        # This deliberately narrow fixture creates exactly one display for
        # each image present in a document. CountImageDisplays() is across
        # documents, not a per-document count. Do not probe a nonexistent
        # scoped index or reinterpret a getter exception as an empty set.
        require(total > 0, "Document image has no display")
        for display_index in (0,):
            display = image.GetImageDisplayInImageDocument(document, display_index)
            require(display is not None and display.IsValid(), "Prepared document scoped display missing")
            require(display.GetImage().GetID() == image.GetID(), "Document-scoped display has another image")
            roi_count = display.CountROIs()
            require(integer(roi_count, 64), "Invalid scoped ROI count")
            rois = []
            for roi_index in range(roi_count):
                roi = display.GetROI(roi_index)
                roi_id, rotation = roi.GetID(), roi.GetRotationAngle()
                require(integer(roi_id) and finite(rotation), "Invalid scoped ROI identity/rotation")
                rectangle, line = roi.IsRectangle(), roi.IsLine()
                require(type(rectangle) is bool and type(line) is bool, "Invalid scoped ROI type")
                geometry = list(roi.GetRectangle()) if rectangle else list(roi.GetLine()) if line else None
                require(geometry is None or len(geometry) == 4 and all(finite(value) for value in geometry), "Invalid scoped ROI geometry")
                rois.append([roi_id, "rectangle" if rectangle else "line" if line else "other", float(rotation), geometry])
                roi = None
            require(display.CountROIs() == roi_count and integer(display.GetID()), "Scoped display changed")
            scoped_displays.append([image.GetID(), display.GetID(), sorted(rois)])
            display = None
        image = None
    scope = json.dumps(sorted(scoped_displays), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return name, int(document.GetWorkspace()), tuple(sorted(ids)), scope


def all_documents(DM):
    count = DM.CountImageDocumentsOfAllWorkspaces()
    require(integer(count, 64), "Invalid/big all-workspace document count")
    signatures = []
    for index in range(count):
        document = DM.GetImageDocumentOfAllWorkspaces(index)
        signatures.append(document_signature(document))
        document = None
    require(len(set(signatures)) == count, "Prepared document signatures must be unique")
    documents = []
    # This old binding lacks ImageDocument.GetID(). A documented by-ID lookup
    # independently proves each numeric identity. The enumeration position is
    # never substituted for an ID. No unbounded search or pointer access.
    wanted = set(signatures)
    for identifier in range(256):
        if not wanted:
            break
        document = DM.GetImageDocumentByID(identifier)
        if document is None or not document.IsValid():
            document = None
            continue
        signature = document_signature(document)
        if signature in wanted:
            documents.append({"document_id": identifier, "name": signature[0], "workspace_id": signature[1],
                              "image_ids": list(signature[2]), "lookup_signature": signature[3]})
            wanted.remove(signature)
        document = None
    require(not wanted and len(documents) == count and DM.CountImageDocumentsOfAllWorkspaces() == count,
            "Document set changed during observation")
    return sorted(documents, key=lambda row: row["document_id"])


def image_observation(DM, image):
    import numpy as np
    require(image is not None and image.IsValid(), "Observed source invalid")
    identifier = image.GetID()
    values = image.GetNumArray()
    require(type(values) is np.ndarray and values.ndim == 2 and 0 < values.size <= 48 * 32 and
            values.dtype in (np.dtype("float32"), np.dtype("uint32")) and np.isfinite(values).all(), "Unexpected source array")
    observation = {"id": identifier, "name": image.GetName(), "dtype": str(values.dtype), "shape": list(values.shape),
                   "pixel_sha256": hashlib.sha256(values.tobytes(order="C")).hexdigest(),
                   "calibration": [spatial(image, axis) for axis in (0, 1)], "intensity_calibration": intensity(image)}
    require(type(observation["name"]) is str and observation["name"].isascii(), "Fixture ASCII name unexpectedly changed")
    values = None
    count = image.CountImageDisplays()
    require(integer(count, 16), "Invalid/big display count")
    displays = []
    for index in range(count):
        display = image.GetImageDisplay(index)
        require(display is not None and display.IsValid(), "Exact-image display invalid")
        reverse = display.GetImage()
        require(reverse is not None and reverse.IsValid() and reverse.GetID() == identifier, "Display reverse source mismatch")
        document = display.GetImageDocument()
        require(document is not None and document.IsValid(), "Display document invalid")
        signature = document_signature(document)
        matches = [row["document_id"] for row in all_documents(DM) if
                   (row["name"], row["workspace_id"], tuple(row["image_ids"]), row["lookup_signature"]) == signature]
        require(len(matches) == 1, "Display document cannot be independently bound by exact ID")
        doc_id, display_id = matches[0], display.GetID()
        require(integer(doc_id) and integer(display_id), "Display composite identity missing")
        display_type = display.GetDisplayType()
        require(type(display_type) is int and display_type == 1, "Fixture display must actually be raster")
        roi_count = display.CountROIs()
        require(integer(roi_count, 64), "Invalid/big ROI count")
        rois = []
        for roi_index in range(roi_count):
            roi = display.GetROI(roi_index)
            require(roi is not None, "ROI getter returned no object")
            roi_id, rotation, selected = roi.GetID(), roi.GetRotationAngle(), display.IsROISelected(roi)
            require(integer(roi_id) and finite(rotation) and type(selected) is bool, "ROI identity/rotation/selection invalid")
            rectangle, line = roi.IsRectangle(), roi.IsLine()
            require(type(rectangle) is bool and type(line) is bool and not (rectangle and line), "ROI type ambiguous")
            raw = None
            if rectangle:
                coords = roi.GetRectangle()
                require(type(coords) in (list, tuple) and len(coords) == 4 and all(finite(value) for value in coords), "Invalid rectangle coordinates")
                raw = dict(zip(("top", "left", "bottom", "right"), (float(value) for value in coords)))
            entry = {"roi_id": roi_id, "selected": selected, "rotation_degrees": float(rotation),
                     "type": "rectangle" if rectangle else "unsupported", "raw_rectangle": raw,
                     "oracle_kind": "rectangle" if rectangle else "line" if line else "other"}
            if line:
                coords = roi.GetLine()
                require(type(coords) in (list, tuple) and len(coords) == 4 and all(finite(value) for value in coords), "Invalid line oracle")
                entry["raw_line_xyxy"] = [float(value) for value in coords]
            rois.append(entry); roi = None
        require(len({row["roi_id"] for row in rois}) == len(rois) and display.CountROIs() == roi_count,
                "ROI set changed during independent observation")
        window = document.GetWindow()
        size = list(window.GetContentSize()) if window is not None and window.IsValid() else None
        displays.append({"document_id": doc_id, "display_id": display_id, "display_type": "raster",
                         "rois": sorted(rois, key=lambda row: row["roi_id"]), "window_content_size": size})
        display = reverse = document = window = None
    require(image.CountImageDisplays() == count, "Image display set changed during observation")
    pairs = {(row["document_id"], row["display_id"]) for row in displays}
    require(len(pairs) == len(displays), "Duplicate display compound identity")
    observation["displays"] = sorted(displays, key=lambda row: (row["document_id"], row["display_id"]))
    return observation


def normalized_mapping(shape, source_layout="direct_image_canonical_xy", slice_ids=(0,)):
    # Native getter divides float32 one by float32 source extents. The bounded
    # fixture dimensions are exact float32 integers. This is the predeclared
    # formula derived from the fixed getter, not values copied from a reply.
    f32 = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
    scale = [f32(1.0 / f32(shape[1])), f32(1.0 / f32(shape[0]))]
    return {"offset": [0, 0], "scale": scale, "identity": scale == [1, 1],
            "space": "source_pixel_to_normalized_display",
            "source_pixel_aligned": source_layout == "direct_image_canonical_xy" and list(slice_ids) == [0]}


def rectangle_issue(raw, shape, mapping, rotation, source_layout="direct_image_canonical_xy", slice_ids=(0,)):
    require(type(raw) is dict and set(raw) == {"top", "left", "bottom", "right"} and all(finite(v) for v in raw.values()), "Invalid raw rectangle")
    require(type(mapping) is dict and set(mapping) == {"offset", "scale", "identity", "space", "source_pixel_aligned"} and
            type(mapping["offset"]) is list and type(mapping["scale"]) is list and len(mapping["offset"]) == len(mapping["scale"]) == 2 and
            all(finite(value) for value in mapping["offset"] + mapping["scale"]) and all(value != 0 for value in mapping["scale"]), "Invalid ROI coordinate mapping")
    identity = mapping["offset"] == [0, 0] and mapping["scale"] == [1, 1]
    require(type(mapping["identity"]) is bool and mapping["identity"] == identity, "Mapping identity was invented")
    require(mapping["space"] == "source_pixel_to_normalized_display" and type(mapping["source_pixel_aligned"]) is bool,
            "Mapping coordinate space/alignment invalid")
    require(source_layout in ("direct_image_canonical_xy", "unsupported") and
            type(slice_ids) in (list, tuple) and len(slice_ids) <= 5 and
            all(integer(value, 0xffffffff) for value in slice_ids), "Image source layout/slice identity types invalid")
    direct_source = source_layout == "direct_image_canonical_xy" and list(slice_ids) == [0]
    expected = normalized_mapping(shape)
    standard_mapping = mapping["offset"] == expected["offset"] and mapping["scale"] == expected["scale"]
    require(mapping["source_pixel_aligned"] == (direct_source and standard_mapping), "Mapping source alignment was invented")
    if rotation != 0:
        return "rotated_rectangle"
    if not direct_source:
        return "unsupported_image_source"
    if not standard_mapping:
        return "unsupported_coordinate_mapping"
    if raw["left"] >= raw["right"] or raw["top"] >= raw["bottom"]:
        return "empty_or_reversed_rectangle"
    if any(math.trunc(value) != value for value in raw.values()):
        return "fractional_rectangle"
    if raw["left"] < 0 or raw["top"] < 0 or raw["right"] > shape[1] or raw["bottom"] > shape[0]:
        return "out_of_bounds_rectangle"
    return None


def compare_result(result, source):
    require(type(result) is dict and result.get("backend") == "digitalmicrograph-native" and result.get("image_id") == source["id"] and
            type(result.get("image_id")) is int and
            result.get("coordinate_rule") == RULE and result.get("source_write_requested") is False and result.get("snapshot_atomic") is False,
            "Native readonly ROI result identity/policy mismatch")
    image = result.get("image", {})
    require(type(image.get("id")) is int and image.get("id") == source["id"] and image.get("name") == source["name"] and image.get("dtype") == source["dtype"] and
            type(image.get("shape")) is list and all(type(value) is int and value > 0 for value in image["shape"]) and
            image.get("shape") == source["shape"] and type(image.get("ndim")) is int and image.get("ndim") == 2 and
            type(image.get("packing_style")) is int and image.get("packing_style") == 1 and type(image.get("data_type_code")) is int and
            image.get("data_type_code") == (2 if source["dtype"] == "float32" else 11), "Native source descriptor mismatch")
    require(type(image.get("calibration")) is list and len(image["calibration"]) == 2, "Native source calibrations missing")
    for axis, (actual, expected) in enumerate(zip(image["calibration"], source["calibration"])):
        require(all(finite(actual.get(key)) for key in ("origin", "calibrated_value_at_pixel_zero", "scale")) and
                type(actual.get("dm_dimension")) is int and actual["dm_dimension"] == axis and
                type(actual.get("numpy_axis")) is int and actual["numpy_axis"] == 1-axis and
                type(actual.get("size")) is int and actual["size"] == source["shape"][1-axis] and
                actual.get("usable") is True and actual.get("issue") is None and
                actual.get("origin") == expected["raw_origin"] and actual.get("calibrated_value_at_pixel_zero") == expected["origin"] and
                actual.get("scale") == expected["scale"] and actual.get("unit") == expected["unit"], "Native spatial zero/origin/signed scale mismatch")
    displays = result.get("displays")
    require(type(displays) is list and len(displays) == len(source["displays"]), "Native display count mismatch")
    current = {(row["document_id"], row["display_id"]): row for row in source["displays"]}
    seen = set()
    for actual in displays:
        pair = (actual.get("document_id"), actual.get("display_id"))
        require(all(integer(value) for value in pair) and pair in current and pair not in seen, "Native display identity missing, duplicated or bound to another image")
        seen.add(pair); expected = current[pair]
        identity = actual.get("display_identity")
        require(type(identity) is dict and set(identity) == {"document_id", "display_id"} and
                all(integer(value) for value in identity.values()), "Native composite display identity type invalid")
        require("selected_dimensions" not in actual and actual.get("display_identity") == {"document_id": pair[0], "display_id": pair[1]} and
                actual.get("display_type") == "raster" and actual.get("issue") is None and
                actual.get("source_layout") == "direct_image_canonical_xy" and
                type(actual.get("slice_ids")) is list and actual["slice_ids"] == [0] and
                all(type(value) is int for value in actual["slice_ids"]) and
                type(actual.get("roi_count")) is int and actual.get("roi_count") == len(expected["rois"]), "Native display binding/type/count mismatch")
        rois = actual.get("rois")
        require(type(rois) is list and len(rois) == len(expected["rois"]), "Native ROI set count mismatch")
        source_rois = {row["roi_id"]: row for row in expected["rois"]}; ids = set()
        for actual_roi in rois:
            roi_id = actual_roi.get("roi_id")
            require(integer(roi_id) and roi_id in source_rois and roi_id not in ids, "Native ROI identity missing/duplicated/wrong display")
            ids.add(roi_id); expected_roi = source_rois[roi_id]
            require(type(actual_roi.get("selected")) is bool and finite(actual_roi.get("rotation_degrees")), "Native selection/rotation type invalid")
            raw_rectangle = actual_roi.get("raw_rectangle")
            require(raw_rectangle is None or type(raw_rectangle) is dict and
                    set(raw_rectangle) == {"top", "left", "bottom", "right"} and all(finite(value) for value in raw_rectangle.values()),
                    "Native rectangle type/nonfinite error")
            for key in ("selected", "rotation_degrees", "type", "raw_rectangle"):
                require(actual_roi.get(key) == expected_roi[key], "Native ROI geometry/type/rotation/selection mismatch: " + key)
            if expected_roi["type"] == "unsupported":
                require(actual_roi.get("coordinate_mapping") is None and actual_roi.get("issue") == "unsupported_roi_type" and
                        actual_roi.get("rect") is None and actual_roi.get("analysis_eligible") is False, "Nonrectangle treated as analysable region")
                continue
            # The old Python binding cannot inspect native ImageSource internals
            # or the ROI mapping getter. This checks the predeclared direct-image
            # contract and normalization formula with independent source shape;
            # it is not a second host proof of those private layout/getter facts.
            mapping = actual_roi.get("coordinate_mapping")
            require(mapping == normalized_mapping(source["shape"]), "Prepared source mapping not the predeclared normalization")
            issue = rectangle_issue(expected_roi["raw_rectangle"], source["shape"], mapping, expected_roi["rotation_degrees"], actual["source_layout"], actual["slice_ids"])
            raw = expected_roi["raw_rectangle"]
            rectangle = [raw[key] for key in ("left", "top", "right", "bottom")] if issue is None else None
            require(actual_roi.get("rect") is None or type(actual_roi["rect"]) is list and
                    len(actual_roi["rect"]) == 4 and all(finite(value) for value in actual_roi["rect"]), "Native integer rectangle type invalid")
            require(actual_roi.get("issue") == issue and actual_roi.get("rect") == rectangle and
                    actual_roi.get("analysis_eligible") is (issue is None), "Native direct-analysis eligibility mismatch")


def validate_reply(reply, request, pid, session):
    require(reply.get("protocol") == "NB2" and reply.get("state") == "completed" and type(reply.get("host_pid")) is int and reply.get("host_pid") == pid and
            reply.get("session") == session and reply.get("id") == request["request_id"] and
            reply.get("original_operation") == "ROIS" and type(reply.get("normalized_args")) is list and
            all(type(value) is int for value in reply["normalized_args"]) and reply.get("normalized_args") == [request["image_id"]] and
            reply.get("result_type") == "native_gui_rois" and type(reply.get("result_version")) is int and reply.get("result_version") == 1 and
            type(reply.get("worker_tid")) is int and reply["worker_tid"] > 0 and type(reply.get("exec_tid")) is int and reply["exec_tid"] > 0 and
            reply["worker_tid"] != reply["exec_tid"] and type(reply.get("result")) is dict and
            not any(key in reply for key in ("error", "code")), "Native original request/host/session/schema identity mismatch")
    timings = reply.get("timings_us")
    require(type(timings) is dict and all(type(timings.get(key)) is int and timings[key] >= 0 for key in ("queue", "execute")), "Native timings missing")
    wire = "NB2 {} {} ROIS {}\n".format(session, request["request_id"], request["image_id"])
    require(request.get("wire_request") == wire, "Original pre-submission request missing or changed")


def verify(directory, report, allow_additions=False):
    import numpy as np
    import DigitalMicrograph as DM
    from create_gui_roi_fixture import fixed_arrays
    fixture = load(os.path.join(directory, "gui-roi-fixture.json"))
    plan = load(os.path.join(directory, "map.json"))
    pid, session = fixture.get("host_pid"), fixture.get("session")
    require(pid == os.getpid() and integer(pid, 0xffffffff) and type(session) is str and re.fullmatch(r"[0-9a-f]{32}", session), "Oracle is not the original fixture process/session")
    require(fixture.get("status") == "RECORDED_SYNTHETIC_GUI_ROI_FIXTURE" and type(plan.get("schema")) is int and plan.get("schema") == 1 and
            type(plan.get("host_pid")) is int and plan.get("host_pid") == pid and plan.get("session") == session and fixture.get("python_is_listener") is False,
            "Fixture/request map host identity incomplete")
    documents = all_documents(DM)
    doc_identity = lambda rows: [{key: value for key, value in row.items() if key != "lookup_signature"} for row in rows]
    require(doc_identity(documents) == doc_identity(fixture.get("documents", [])), "Image documents, workspaces or source membership changed")
    require(set(fixture["images"]) == set(fixed_arrays()), "Fixed source matrix incomplete")
    current = {}
    for label, fixed in fixed_arrays().items():
        original = fixture["images"][label]
        path = local_path(directory, original["source_file"])
        saved = load_fixed_source(path, fixed, original["source_file_sha256"])
        image = DM.FindImageByID(original["id"])
        observed = image_observation(DM, image)
        values = image.GetNumArray()
        require(values.dtype == saved.dtype and values.shape == saved.shape and values.tobytes(order="C") == saved.tobytes(order="C"), "Entire original scientific pixel array changed")
        values = image = None
        for key in ("id", "name", "dtype", "shape", "pixel_sha256", "calibration", "intensity_calibration"):
            require(observed[key] == original[key], "Original source metadata/calibration changed: " + key)
        old_displays = {(r["document_id"], r["display_id"]): r for r in original["displays"]}
        new_displays = {(r["document_id"], r["display_id"]): r for r in observed["displays"]}
        require(set(old_displays) == set(new_displays), "Display membership changed")
        for pair, old in old_displays.items():
            new = new_displays[pair]
            if not allow_additions:
                require(new["rois"] == old["rois"], "Original ROI set/geometry/selection changed")
            else:
                new_rois = {r["roi_id"]: r for r in new["rois"]}
                for old_roi in old["rois"]:
                    require(old_roi["roi_id"] in new_rois, "Original ROI disappeared")
                    actual = new_rois[old_roi["roi_id"]]
                    require({k: v for k, v in actual.items() if k != "selected"} ==
                            {k: v for k, v in old_roi.items() if k != "selected"}, "GUI changed an original ROI geometry")
        current[label] = observed
    requests = plan.get("requests")
    require(type(requests) is list and 0 < len(requests) <= 128, "Bounded original request ledger required")
    identities = {}; comparisons = []
    for request in requests:
        label = request.get("label")
        require(label in current and type(request.get("image_id")) is int and request.get("image_id") == current[label]["id"] and type(request.get("request_id")) is str and
                re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["request_id"]), "Request source/ID missing or changed")
        reply = load(local_path(directory, request["response_file"]))
        validate_reply(reply, request, pid, session)
        mode = request.get("compare", "current")
        require(mode in ("current", "original"), "Unknown comparison mode")
        if mode == "original":
            original_reply = load(local_path(directory, request["original_response_file"]))
            require(original_reply == reply, "Recovered old QUERY changed its immutable original record")
            expected = fixture["images"][label]
        else:
            expected = current[label]
        compare_result(reply["result"], expected)
        old = identities.setdefault(request["request_id"], (request["image_id"], reply))
        require(old == (request["image_id"], reply), "Same request ID has conflicting results")
        comparisons.append({"label": label, "request_id": request["request_id"], "compare": mode, "status": "PASS"})
    require(all_documents(DM) == documents, "Oracle altered document membership")
    report.update(status="PASS_SAME_HOST_SYNTHETIC_GUI_ROIS", host_pid=pid, session=session,
                  python_is_listener=False, source_pixels_names_calibrations_unchanged=True,
                  documents=documents, current_images=current, comparisons=comparisons,
                  allowed_manual_gui_additions=allow_additions,
                  coordinate_mapping_evidence="fixed native direct-image layout/slice contract and normalization formula with independent source shape; old Python binding cannot inspect ImageSource internals or mapping getter",
                  scope="same-process independent getters and full synthetic pixels; not model-client or concurrent-edit qualification")


def main():
    directory = os.path.abspath(os.environ["DM_NATIVE_EVIDENCE_DIR"])
    target = os.environ.get("DM_NATIVE_GUI_ROI_OBSERVER", os.path.join(directory, "gui-roi-observer.json"))
    with open(target, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "host_pid": os.getpid(), "python_is_listener": False}
        try:
            verify(directory, report, os.environ.get("DM_NATIVE_GUI_ROI_ALLOW_ADDITIONS") == "1")
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
