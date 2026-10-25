"""Independent faults for the one-shot ROI oracle; no DM, DLL or GUI access."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np


MVP = Path(__file__).resolve().parents[1] / "experiments" / "native-bridge" / "mvp"
with mock.patch.object(sys, "path", [str(MVP)] + sys.path):
    ORACLE = runpy.run_path(str(MVP / "verify_gui_roi.py"))
    FIXTURE = runpy.run_path(str(MVP / "create_gui_roi_fixture.py"))
SESSION = "0123456789abcdef0123456789abcdef"
CALIBRATION = [
    {"dm_axis": 0, "origin": 1.25, "raw_origin": 5., "scale": -.25, "unit": "nm"},
    {"dm_axis": 1, "origin": -2.5, "raw_origin": 5., "scale": .5, "unit": "nm"},
]


def save(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def rectangle(roi_id=7, raw=None, rotation=0.):
    return {"roi_id": roi_id, "selected": True, "rotation_degrees": rotation,
            "type": "rectangle", "raw_rectangle": raw or {"top": 1., "left": 2., "bottom": 4., "right": 6.},
            "oracle_kind": "rectangle"}


def source_record(image_id=17, shape=(8, 12), displays=None):
    return {"id": image_id, "name": "independent_synthetic_" + str(image_id), "dtype": "float32", "shape": list(shape),
            "calibration": copy.deepcopy(CALIBRATION), "intensity_calibration": {"origin": 7.5, "scale": -2., "unit": "arb"},
            "displays": displays if displays is not None else [{"document_id": 31, "display_id": 9, "display_type": "raster",
                "rois": [rectangle()], "window_content_size": [640, 480]}]}


def native_result(source):
    image = {key: copy.deepcopy(source[key]) for key in ("id", "name", "dtype", "shape")}
    image.update(ndim=2, packing_style=1, data_type_code=11 if source["dtype"] == "uint32" else 2,
                 calibration=[{"origin": a["raw_origin"], "calibrated_value_at_pixel_zero": a["origin"],
                               "scale": a["scale"], "unit": a["unit"], "dm_dimension": axis, "numpy_axis": 1-axis,
                               "size": source["shape"][1-axis], "usable": True, "issue": None}
                              for axis, a in enumerate(source["calibration"])])
    displays = []
    for expected in source["displays"]:
        pair = {key: expected[key] for key in ("document_id", "display_id")}
        rois = []
        for original in expected["rois"]:
            row = {key: copy.deepcopy(original[key]) for key in ("roi_id", "selected", "rotation_degrees", "type", "raw_rectangle")}
            raw = row["raw_rectangle"]
            issue = "unsupported_roi_type" if row["type"] != "rectangle" else (
                "rotated_rectangle" if row["rotation_degrees"] != 0 else None)
            scale = [float(np.float32(1.) / np.float32(source["shape"][1-axis])) for axis in (0, 1)]
            row.update(coordinate_mapping=None if raw is None else {"offset": [0, 0], "scale": scale, "identity": scale == [1, 1],
                       "space": "source_pixel_to_normalized_display", "source_pixel_aligned": True},
                       rect=None if issue else [raw[key] for key in ("left", "top", "right", "bottom")],
                       analysis_eligible=issue is None, issue=issue)
            rois.append(row)
        displays.append(dict(pair, display_identity=pair.copy(), display_type="raster", source_layout="direct_image_canonical_xy", slice_ids=[0], roi_count=len(rois), rois=rois, issue=None))
    return {"backend": "digitalmicrograph-native", "image_id": source["id"], "image": image, "displays": displays,
            "coordinate_rule": ORACLE["RULE"], "source_write_requested": False, "snapshot_atomic": False}


def original_request(image_id=17, request_id="roi-before", label="float_primary", **extra):
    return dict(label=label, image_id=image_id, request_id=request_id, response_file=request_id + ".json",
                wire_request="NB2 {} {} ROIS {}\n".format(SESSION, request_id, image_id), **extra)


def native_reply(request, result, pid=None):
    return {"protocol": "NB2", "state": "completed", "session": SESSION, "id": request["request_id"],
            "host_pid": os.getpid() if pid is None else pid, "worker_tid": 203, "exec_tid": 204,
            "original_operation": "ROIS", "normalized_args": [request["image_id"]],
            "result_type": "native_gui_rois", "result_version": 1,
            "timings_us": {"queue": 1, "execute": 2}, "result": result}


class FakeImage:
    def __init__(self, record, values):
        self.record, self.values, self.displays, self.scoped_gets = record, values.copy(), [], []
    def IsValid(self): return True
    def GetID(self): return self.record["id"]
    def GetName(self): return self.record["name"]
    def GetNumArray(self): return self.values
    def CountImageDisplays(self): return len(self.displays)
    def GetImageDisplay(self, index): return self.displays[index]
    def GetImageDisplayInImageDocument(self, document, index):
        self.scoped_gets.append((document.document_id, index))
        scoped = [display for display in self.displays if display.document is document]
        if index >= len(scoped):
            raise RuntimeError("scoped display index does not exist")
        return scoped[index]
    def GetDimensionCalibration(self, axis, mode):
        a = self.record["calibration"][axis]
        return a["raw_origin"] if mode else a["origin"], a["scale"], a["unit"]
    def GetIntensityOrigin(self): return 7.5
    def GetIntensityScale(self): return -2.
    def GetIntensityUnitString(self): return "arb"


class FakeRoi:
    def __init__(self, record): self.record = record
    def GetID(self): return self.record["roi_id"]
    def GetRotationAngle(self): return self.record["rotation_degrees"]
    def IsRectangle(self): return self.record["type"] == "rectangle"
    def IsLine(self): return self.record["oracle_kind"] == "line"
    def GetRectangle(self): return tuple(self.record["raw_rectangle"][key] for key in ("top", "left", "bottom", "right"))


class FakeWindow:
    def IsValid(self): return True
    def GetContentSize(self): return 640, 480


class FakeDocument:
    # Deliberately no GetID(): independent oracle must use exact ByID lookup.
    def __init__(self, document_id, image): self.document_id, self.image = document_id, image
    def IsValid(self): return True
    def GetName(self): return "owned_document_" + str(self.document_id)
    def GetWorkspace(self): return 2
    def CountImages(self): return 1
    def GetImage(self, index):
        assert index == 0
        return self.image
    def GetWindow(self): return FakeWindow()


class FakeDisplay:
    def __init__(self, record, image, document): self.record, self.image, self.document = record, image, document
    def IsValid(self): return True
    def GetID(self): return self.record["display_id"]
    def GetImage(self): return self.image
    def GetImageDocument(self): return self.document
    def GetDisplayType(self): return 1
    def CountROIs(self): return len(self.record["rois"])
    def GetROI(self, index): return FakeRoi(self.record["rois"][index])
    def IsROISelected(self, roi): return roi.record["selected"]


class PreparedEvidence:
    def __init__(self, directory):
        self.directory, self.images, self.documents = Path(directory), {}, []
        self.fixture = {"schema": 1, "status": "RECORDED_SYNTHETIC_GUI_ROI_FIXTURE", "host_pid": os.getpid(),
                        "session": SESSION, "python_is_listener": False, "images": {}}
        for index, (label, values) in enumerate(FIXTURE["fixed_arrays"]().items()):
            displays = []
            if label != "hidden":
                displays.append({"document_id": 31 + index, "display_id": 9 + index, "display_type": "raster",
                    "rois": [rectangle()] if label == "float_primary" else [], "window_content_size": [640, 480]})
            record = source_record(17 + index, values.shape, displays)
            record.update(dtype=str(values.dtype), source_file=label + ".npy", pixel_sha256=hashlib.sha256(values.tobytes(order="C")).hexdigest())
            path = self.directory / record["source_file"]
            np.save(str(path), values, allow_pickle=False)
            record["source_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            image = FakeImage(record, values)
            for display in displays:
                document = FakeDocument(display["document_id"], image)
                image.displays.append(FakeDisplay(display, image, document))
                self.documents.append(document)
            self.fixture["images"][label] = record
            self.images[record["id"]] = image
        self.fixture["documents"] = sorted([{"document_id": doc.document_id, "name": doc.GetName(),
            "workspace_id": 2, "image_ids": [doc.image.GetID()]} for doc in self.documents], key=lambda value: value["document_id"])
        self.dm = types.ModuleType("DigitalMicrograph")
        self.dm.CountImageDocumentsOfAllWorkspaces = lambda: len(self.documents)
        self.dm.GetImageDocumentOfAllWorkspaces = lambda index: self.documents[index]
        self.dm.GetImageDocumentByID = lambda identifier: next((doc for doc in self.documents if doc.document_id == identifier), None)
        self.dm.FindImageByID = lambda identifier: self.images.get(identifier)
        self.plan = {"schema": 1, "host_pid": os.getpid(), "session": SESSION, "requests": []}

    def add_reply(self, request, reply):
        self.plan["requests"].append(request)
        save(self.directory / request["response_file"], reply)

    def persist(self):
        save(self.directory / "gui-roi-fixture.json", self.fixture)
        save(self.directory / "map.json", self.plan)

    def verify(self, additions=False):
        self.persist()
        report = {"status": "FAIL"}
        with mock.patch.dict(sys.modules, {"DigitalMicrograph": self.dm}), mock.patch.object(sys, "path", [str(MVP)] + sys.path):
            ORACLE["verify"](str(self.directory), report, additions)
        return report


class GuiRoiOracleTests(unittest.TestCase):
    def test_fixed_source_npy_headers_are_bounded_before_any_array_load(self):
        with tempfile.TemporaryDirectory() as directory:
            fixed = np.arange(12, dtype=np.float32).reshape(3, 4)
            path = Path(directory) / "fixed.npy"
            np.save(str(path), fixed, allow_pickle=False)
            raw = path.read_bytes()
            loaded = ORACLE["load_fixed_source"](str(path), fixed, hashlib.sha256(raw).hexdigest())
            self.assertEqual(loaded.tobytes(order="C"), fixed.tobytes(order="C"))
            cases = [("oversized", b"0" * (fixed.nbytes + 4097)), ("short_payload", raw[:-1]), ("trailing_payload", raw + b"x")]
            for label, header, version in [
                ("huge_claimed_shape", {"descr": "<f4", "fortran_order": False, "shape": (2 ** 40, 2 ** 40)}, 1),
                ("wrong_dtype", {"descr": "<u4", "fortran_order": False, "shape": fixed.shape}, 1),
                ("fortran", {"descr": "<f4", "fortran_order": True, "shape": fixed.shape}, 1),
                ("npy_version_2", {"descr": "<f4", "fortran_order": False, "shape": fixed.shape}, 2),
            ]:
                stream = io.BytesIO()
                writer = np.lib.format.write_array_header_1_0 if version == 1 else np.lib.format.write_array_header_2_0
                writer(stream, header)
                cases.append((label, stream.getvalue()))
            for label, malformed in cases:
                path.write_bytes(malformed)
                with self.subTest(case=label), mock.patch.object(np, "load", side_effect=AssertionError("must validate header before allocating")) as loader:
                    with self.assertRaises(RuntimeError):
                        ORACLE["load_fixed_source"](str(path), fixed, hashlib.sha256(malformed).hexdigest())
                    loader.assert_not_called()

    def test_full_oracle_refuses_oversized_and_huge_shape_sources_before_np_load(self):
        for kind in ("oversized", "huge_claimed_shape"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                prepared = PreparedEvidence(directory)
                source = prepared.fixture["images"]["float_primary"]
                path = Path(directory) / source["source_file"]
                if kind == "oversized":
                    malformed = b"0" * (prepared.images[source["id"]].values.nbytes + 4097)
                else:
                    stream = io.BytesIO()
                    np.lib.format.write_array_header_1_0(stream, {"descr": "<f4", "fortran_order": False, "shape": (2 ** 40, 2 ** 40)})
                    malformed = stream.getvalue()
                path.write_bytes(malformed)
                source["source_file_sha256"] = hashlib.sha256(malformed).hexdigest()
                with mock.patch.object(np, "load", side_effect=AssertionError("unbounded np.load forbidden")) as loader:
                    with self.assertRaisesRegex(RuntimeError, "fixed byte budget|NPY header differs"):
                        prepared.verify()
                    loader.assert_not_called()

    def test_independent_rectangle_and_rotation_comparison(self):
        source = source_record()
        ORACLE["compare_result"](native_result(source), source)
        source["displays"][0]["rois"][0]["rotation_degrees"] = 30.
        result = native_result(source)
        ORACLE["compare_result"](result, source)
        self.assertIsNone(result["displays"][0]["rois"][0]["rect"])
        result["displays"][0]["rois"][0]["issue"] = None
        with self.assertRaises(RuntimeError): ORACLE["compare_result"](result, source)

    def test_wrong_raw_rotation_mapping_and_roi_identity_cannot_pass(self):
        source = source_record()
        changes = [
            lambda r: r["displays"][0]["rois"][0]["raw_rectangle"].update(left=3.),
            lambda r: r["displays"][0]["rois"][0].update(rotation_degrees=30.),
            lambda r: r["displays"][0]["rois"][0].update(roi_id=99),
            lambda r: r["displays"][0]["rois"][0]["coordinate_mapping"].update(offset=[1, 0], identity=False),
            lambda r: r["displays"][0]["rois"][0]["coordinate_mapping"].update(scale=[2, 1], identity=False),
            lambda r: r["displays"][0]["rois"][0]["coordinate_mapping"].update(identity=True),
            lambda r: r["displays"][0]["rois"][0]["coordinate_mapping"].update(source_pixel_aligned=False),
            lambda r: r["displays"][0].update(slice_ids=[0, 1]),
            lambda r: r["displays"][0].update(source_layout="unsupported"),
            lambda r: r["displays"][0].update(selected_dimensions=[0, 1]),
            lambda r: r["displays"][0]["rois"][0].update(rect=[0, 0, 12, 8]),
        ]
        for change in changes:
            result = native_result(source); change(result)
            with self.subTest(change=change), self.assertRaises(RuntimeError): ORACLE["compare_result"](result, source)

    def test_normalized_mapping_alignment_source_slice_and_rotation_have_separate_meanings(self):
        source = source_record(); mapping = native_result(source)["displays"][0]["rois"][0]["coordinate_mapping"]
        raw = rectangle()["raw_rectangle"]
        self.assertFalse(mapping["identity"])
        self.assertTrue(mapping["source_pixel_aligned"])
        self.assertEqual(mapping["scale"], [float(np.float32(1.) / np.float32(12)), .125])
        self.assertIsNone(ORACLE["rectangle_issue"](raw, source["shape"], mapping, 0., "direct_image_canonical_xy", [0]))
        swapped = dict(mapping, source_pixel_aligned=False)
        for layout, slices in [("unsupported", [0]), ("direct_image_canonical_xy", [1]), ("direct_image_canonical_xy", [0, 1]),
                               ("direct_image_canonical_xy", [])]:
            self.assertEqual(ORACLE["rectangle_issue"](raw, source["shape"], swapped, 0., layout, slices), "unsupported_image_source")
            self.assertEqual(ORACLE["rectangle_issue"](raw, source["shape"], swapped, 30., layout, slices), "rotated_rectangle")
        misleading_identity = dict(mapping, scale=[1, 1], identity=True, source_pixel_aligned=False)
        self.assertEqual(ORACLE["rectangle_issue"](raw, source["shape"], misleading_identity, 0.), "unsupported_coordinate_mapping")
        with self.assertRaisesRegex(RuntimeError, "alignment was invented"):
            ORACLE["rectangle_issue"](raw, source["shape"], dict(misleading_identity, source_pixel_aligned=True), 0.)

    def test_reverse_source_and_display_compound_identity_are_independent(self):
        source = source_record()
        changes = [lambda r: r.update(image_id=18), lambda r: r["image"].update(id=18),
            lambda r: r["displays"][0].update(document_id=99), lambda r: r["displays"][0].update(display_id=99),
            lambda r: r["displays"][0]["display_identity"].update(document_id=99),
            lambda r: r["displays"][0]["display_identity"].update(display_id=99)]
        for change in changes:
            result = native_result(source); change(result)
            with self.subTest(change=change), self.assertRaises(RuntimeError): ORACLE["compare_result"](result, source)

    def test_same_named_documents_with_same_image_bind_by_scoped_display_not_enumeration_index(self):
        source = source_record()
        image = FakeImage(source, np.zeros((8, 12), dtype=np.float32))
        documents = [FakeDocument(31, image), FakeDocument(41, image)]
        for index, document in enumerate(documents):
            document.GetName = lambda: "same_document_title"
            record = copy.deepcopy(source["displays"][0]); record.update(document_id=document.document_id, display_id=9 + index)
            image.displays.append(FakeDisplay(record, image, document))
        dm = types.ModuleType("DigitalMicrograph")
        dm.CountImageDocumentsOfAllWorkspaces = lambda: len(documents)
        dm.GetImageDocumentOfAllWorkspaces = lambda index: documents[index]
        looked_up = []
        def by_id(identifier):
            looked_up.append(identifier)
            return next((doc for doc in documents if doc.document_id == identifier), None)
        dm.GetImageDocumentByID = by_id
        rows = ORACLE["all_documents"](dm)
        self.assertEqual([row["document_id"] for row in rows], [31, 41])
        self.assertEqual([row["image_ids"] for row in rows], [[17], [17]])
        self.assertNotEqual(rows[0]["lookup_signature"], rows[1]["lookup_signature"])
        self.assertEqual(max(looked_up), 41)
        self.assertLessEqual(len(looked_up), 256)
        self.assertEqual(image.CountImageDisplays(), 2)
        self.assertTrue(image.scoped_gets)
        self.assertTrue(all(index == 0 for _, index in image.scoped_gets), "global display count must not drive scoped indices")
        image.displays[1].record["display_id"] = 9
        with self.assertRaisesRegex(RuntimeError, "signatures must be unique"):
            ORACLE["all_documents"](dm)

    def test_empty_is_valid_only_when_independent_source_is_actually_empty(self):
        source = source_record(); empty = native_result(source)
        empty["displays"][0].update(rois=[], roi_count=0)
        with self.assertRaises(RuntimeError): ORACLE["compare_result"](empty, source)
        source["displays"][0]["rois"] = []
        ORACLE["compare_result"](native_result(source), source)
        result = native_result(source)
        result["displays"][0]["issue"] = "native_getter_failed"
        with self.assertRaises(RuntimeError): ORACLE["compare_result"](result, source)

    def test_json_boolean_numeric_aliases_do_not_validate_scientific_geometry(self):
        source = source_record()
        for field, value in [("rotation_degrees", False), ("rotation_degrees", "0"), ("rotation_degrees", float("nan")),
                             ("selected", 1), ("selected", "true"), ("roi_id", 7.)]:
            result = native_result(source); result["displays"][0]["rois"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                ORACLE["compare_result"](result, source)
        result = native_result(source)
        result["displays"][0]["rois"][0]["raw_rectangle"]["top"] = True
        with self.assertRaises(RuntimeError): ORACLE["compare_result"](result, source)

    def test_original_receipt_wire_request_and_host_identity_cannot_drift(self):
        request = original_request(); valid = native_reply(request, native_result(source_record()))
        ORACLE["validate_reply"](valid, request, os.getpid(), SESSION)
        for change in [{"host_pid": os.getpid() + 1}, {"session": "f" * 32}, {"id": "other"},
            {"original_operation": "DATASETS"}, {"normalized_args": [18]}, {"result_type": "datasets"},
            {"result_version": 2}, {"result_version": True}, {"state": "failed", "error": "native_getter_failed", "code": "native_error"},
            {"worker_tid": 204}, {"exec_tid": 0}]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                ORACLE["validate_reply"](dict(valid, **change), request, os.getpid(), SESSION)
        wrong = dict(request, wire_request=request["wire_request"].replace("ROIS 17", "ROIS 18"))
        with self.assertRaises(RuntimeError): ORACLE["validate_reply"](valid, wrong, os.getpid(), SESSION)

    def test_full_fake_oracle_binds_actual_pid_even_when_all_saved_records_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = PreparedEvidence(directory)
            source = prepared.fixture["images"]["float_primary"]
            request = original_request()
            prepared.add_reply(request, native_reply(request, native_result(source)))
            self.assertEqual(prepared.verify()["status"], "PASS_SAME_HOST_SYNTHETIC_GUI_ROIS")
            foreign = os.getpid() + 10000
            prepared.fixture["host_pid"] = prepared.plan["host_pid"] = foreign
            reply = native_reply(request, native_result(source), foreign)
            save(Path(directory) / request["response_file"], reply)
            prepared.persist()
            output = Path(directory) / "foreign-observer.json"
            with mock.patch.dict(sys.modules, {"DigitalMicrograph": prepared.dm}), mock.patch.object(sys, "path", [str(MVP)] + sys.path), \
                 mock.patch.dict(os.environ, {"DM_NATIVE_EVIDENCE_DIR": directory, "DM_NATIVE_GUI_ROI_OBSERVER": str(output)}), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(ORACLE["main"](), 1)
            failed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "FAIL")
            self.assertEqual(failed["host_pid"], os.getpid())
            self.assertIn("original fixture process", failed["error"])

    def test_old_query_remains_historical_and_new_snapshot_must_match_current_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = PreparedEvidence(directory)
            source = prepared.fixture["images"]["float_primary"]
            original = native_result(source)
            original_request_record = original_request(request_id="roi-old")
            saved = native_reply(original_request_record, original)
            save(Path(directory) / "original-roi.json", saved)
            old_query = original_request(request_id="roi-old", compare="original", original_response_file="original-roi.json")
            prepared.add_reply(old_query, saved)
            live = prepared.images[source["id"]].displays[0].record
            # Separate GUI state object; never edit fixture history.
            prepared.images[source["id"]].displays[0].record = live = copy.deepcopy(live)
            live["rois"].append(rectangle(8, {"top": 2., "left": 3., "bottom": 5., "right": 7.}))
            fresh_source = copy.deepcopy(source); fresh_source["displays"][0] = live
            fresh_request = original_request(request_id="roi-fresh")
            fresh_reply = native_reply(fresh_request, native_result(fresh_source))
            prepared.add_reply(fresh_request, fresh_reply)
            result = prepared.verify(additions=True)
            self.assertEqual([row["compare"] for row in result["comparisons"]], ["original", "current"])
            # Reusing the old snapshot as a fresh response loses the new ROI.
            save(Path(directory) / fresh_request["response_file"], native_reply(fresh_request, original))
            with self.assertRaisesRegex(RuntimeError, "count mismatch"):
                prepared.verify(additions=True)
            save(Path(directory) / fresh_request["response_file"], fresh_reply)
            changed_old = copy.deepcopy(saved); changed_old["result"]["displays"][0]["rois"][0]["raw_rectangle"]["left"] = 3.
            save(Path(directory) / old_query["response_file"], changed_old)
            with self.assertRaisesRegex(RuntimeError, "immutable original record"):
                prepared.verify(additions=True)

    def test_oracle_getter_exception_and_wrong_reverse_image_do_not_become_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = PreparedEvidence(directory)
            source = prepared.fixture["images"]["float_primary"]
            request = original_request()
            prepared.add_reply(request, native_reply(request, native_result(source)))
            display = prepared.images[source["id"]].displays[0]
            with mock.patch.object(display, "CountROIs", side_effect=RuntimeError("independent getter failed")):
                with self.assertRaisesRegex(RuntimeError, "independent getter failed"): prepared.verify()
            with mock.patch.object(display, "GetImage", return_value=prepared.images[18]):
                with self.assertRaisesRegex(RuntimeError, "reverse source mismatch|display has another image"): prepared.verify()


if __name__ == "__main__":
    unittest.main()
