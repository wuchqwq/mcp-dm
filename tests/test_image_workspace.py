"""Independent synthetic external pixel-workspace tests; never require DM."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import tifffile

from tools import image_workspace as engine


class ImageWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.source = self.base / "series.tiff"
        first = np.arange(35, dtype=np.uint16).reshape(5, 7)
        self.values = np.stack([first, first + 10, first + 20])
        tifffile.imwrite(self.source, self.values, photometric="minisblack", metadata={"axes": "IYX"})
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def request(self, action, **kwargs):
        self.counter += 1
        return {"workspace": str(self.workspace), "action": action,
                "request_id": "test-{}".format(self.counter), **kwargs}

    def run_action(self, action, **kwargs):
        response = engine.execute(self.request(action, **kwargs))
        self.assertTrue(response["ok"], response)
        return response["result"]

    def opened(self):
        return self.run_action("open", source_path=str(self.source))

    def frame(self, index=0, opened=None):
        return self.run_action("frame", object_id=(opened or self.opened())["object_id"], frame_index=index)

    def test_open_does_not_decode_any_page_and_frame_reads_one_page(self):
        with patch.object(tifffile.TiffPage, "asarray", side_effect=AssertionError("open must not decode")):
            source = self.opened()
        self.assertEqual(source["page_count"], 3)
        self.assertFalse(source["pixel_data_loaded"])
        original = tifffile.TiffPage.asarray
        calls = []
        def tracked(page, *args, **kwargs):
            calls.append(page.index)
            return original(page, *args, **kwargs)
        with patch.object(tifffile.TiffPage, "asarray", tracked):
            frame = self.frame(2, source)
        self.assertEqual(calls, [2])
        np.testing.assert_array_equal(np.load(frame["array_path"]), self.values[2])
        self.assertEqual(frame["dtype"], "uint16")
        self.assertEqual(frame["calibration"], {"status": "unknown", "unit": None})

    def test_uint16_boundaries_and_raw_preview_range(self):
        path = self.base / "boundaries.tiff"
        values = np.array([[0, 32767, 32768, 65535]], dtype=np.uint16)
        tifffile.imwrite(path, values)
        opened = self.run_action("open", source_path=str(path))
        frame = self.frame(0, opened)
        view = self.run_action("view", object_id=frame["object_id"], display_range=[0, 65535])
        np.testing.assert_array_equal(np.asarray(Image.open(view["image_path"])), [[0, 127, 128, 255]])
        np.testing.assert_array_equal(np.load(frame["array_path"]), values)
        self.assertTrue(view["display"]["display_only"])

    def test_immutable_ids_reuse_conflict_and_incomplete_records(self):
        request = self.request("open", source_path=str(self.source))
        first = engine.execute(request)
        self.assertEqual(engine.execute(copy.deepcopy(request)), first)
        changed = dict(request, source_path=str(self.base / "other.tiff"))
        self.assertEqual(engine.execute(changed)["error"]["code"], "REQUEST_CONFLICT")
        journal = self.workspace / "requests" / "unfinished.json"
        journal.write_text(json.dumps({"state": "prepared"}), encoding="utf-8")
        result = engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": "unfinished"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["automatic_retry"])

    def test_missing_id_invalid_arguments_and_readonly_no_mutation(self):
        result = engine.execute({"workspace": str(self.workspace), "action": "open", "source_path": str(self.source)})
        self.assertFalse(result["ok"])
        self.assertFalse(self.workspace.exists())
        source = self.opened()
        before = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in self.workspace.rglob("*") if p.is_file()}
        fetched = engine.execute({"workspace": str(self.workspace), "action": "get", "object_id": source["object_id"]})
        self.assertTrue(fetched["ok"])
        queried = engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": source["request_id"]})
        self.assertTrue(queried["ok"])
        after = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in self.workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_source_mutation_is_refused_before_pixel_read(self):
        source = self.opened()
        raw = bytearray(self.source.read_bytes())
        raw[-1] ^= 1
        self.source.write_bytes(raw)
        with patch.object(tifffile.TiffPage, "asarray", side_effect=AssertionError("must refuse before decode")):
            response = engine.execute(self.request("frame", object_id=source["object_id"], frame_index=0))
        self.assertEqual(response["error"]["code"], "SOURCE_CHANGED")

    def test_rgb_float_tiff_and_budgets_are_not_silent_conversions(self):
        for name, values, photo in [("rgb", np.zeros((5, 7, 3), np.uint16), "rgb"),
                                     ("float", np.ones((5, 7), np.float32), "minisblack")]:
            path = self.base / (name + ".tiff")
            tifffile.imwrite(path, values, photometric=photo)
            self.assertFalse(engine.execute(self.request("open", source_path=str(path)))["ok"])
        with patch.object(engine, "MAX_PIXELS", 10), patch.object(tifffile.TiffPage, "asarray", side_effect=AssertionError("budget before decode")):
            response = engine.execute(self.request("open", source_path=str(self.source)))
            self.assertFalse(response["ok"])
        with patch.object(engine, "MAX_PAGES", 2):
            response = engine.execute(self.request("open", source_path=str(self.source)))
            self.assertEqual(response["error"]["code"], "BUDGET_EXCEEDED")

    def test_half_open_view_and_bad_rect_gamma_range(self):
        frame = self.frame()
        view = self.run_action("view", object_id=frame["object_id"], rect=[1, 1, 5, 4], gamma=2, max_size=2)
        np.testing.assert_array_equal(np.load(view["array_path"]), self.values[0, 1:4, 1:5])
        self.assertEqual(view["source_rect_xyxy"], [1, 1, 5, 4])
        with Image.open(view["image_path"]) as png:
            self.assertLessEqual(max(png.size), 2)
        for params in ({"rect": [0, 0, 8, 5]}, {"rect": [0.5, 0, 2, 2]}, {"rect": [1, 1, 1, 2]},
                       {"gamma": 0}, {"gamma": True}, {"max_size": 1025}, {"display_range": [2, 1]},
                       {"display_range": [0, float("inf")]}, {"script": "not allowed"}):
            self.assertFalse(engine.execute(self.request("view", object_id=frame["object_id"], **params))["ok"], params)

    def test_shared_compare_raw_differences_and_composite_annotation_mapping(self):
        source = self.opened()
        frames = [self.frame(i, source) for i in (0, 1)]
        comparison = self.run_action("compare", object_ids=[f["object_id"] for f in frames])
        self.assertEqual(comparison["display"]["display_range"], [0, 44])
        self.assertEqual(comparison["raw_differences"][0]["mean"], 10)
        self.assertEqual(comparison["raw_differences"][0]["stddev"], 0)
        with Image.open(comparison["image_path"]) as png:
            self.assertEqual(png.size, (14, 5))
        annotated = self.run_action("annotate", object_id=comparison["object_id"], annotations=[
            {"kind": "point", "coordinates": [9, 1], "status": "hypothesized", "note": "candidate"},
            {"kind": "rectangle", "coordinates": [6, 0, 8, 3], "status": "user_confirmed"}])
        mapped = annotated["annotations"][0]["source_mappings"][0]
        self.assertEqual(mapped["source_object_id"], frames[1]["object_id"])
        self.assertEqual(mapped["coordinates"], [2, 1])
        self.assertEqual(annotated["annotations"][1]["mapping_status"], "not_a_single_source_region")
        reverted = self.run_action("annotate", object_id=annotated["object_id"], annotations=[])
        np.testing.assert_array_equal(np.asarray(Image.open(reverted["image_path"])),
                                      np.asarray(Image.open(comparison["image_path"]).convert("RGB")))
        self.assertFalse(reverted["scientific_data_changed"])

    def test_fft_independent_known_bins_and_hann_mean_preprocessing(self):
        path = self.base / "known-bins.tiff"
        values = np.tile([0, 1, 0, 1], (4, 1)).astype(np.uint16)
        tifffile.imwrite(path, values)
        frame = self.frame(0, self.run_action("open", source_path=str(path)))
        before = hashlib.sha256(Path(frame["array_path"]).read_bytes()).hexdigest()
        spectrum = self.run_action("fft", object_id=frame["object_id"], window="none", subtract_mean=False)
        expected = np.zeros((4, 4), np.complex128)
        expected[2, 2] = 8
        expected[2, 0] = -8
        np.testing.assert_array_equal(np.load(spectrum["array_path"]), expected)
        self.assertEqual(spectrum["dtype"], "complex128")
        self.assertEqual(spectrum["frequency_unit"], "cycles/pixel")
        self.assertEqual(spectrum["frequency_axes"][1]["dc_index"], 2)
        self.assertIsNone(spectrum["physical_frequency_unit"])
        constant = self.base / "constant.tiff"
        tifffile.imwrite(constant, np.ones((4, 4), np.uint16))
        constant_frame = self.frame(0, self.run_action("open", source_path=str(constant)))
        hann = self.run_action("fft", object_id=constant_frame["object_id"], window="hann", subtract_mean=False)
        self.assertEqual(np.load(hann["array_path"])[2, 2], 2.25)
        zero = self.run_action("fft", object_id=constant_frame["object_id"], window="hann", subtract_mean=True)
        self.assertTrue(np.all(np.load(zero["array_path"]) == 0))
        self.assertEqual(before, hashlib.sha256(Path(frame["array_path"]).read_bytes()).hexdigest())

    def test_context_revisions_propagate_without_fabricating_physical_measurements(self):
        frame = self.frame()
        context = self.run_action("context", object_id=frame["object_id"], metadata={
            "data_meaning": "user says phase", "value_unit": "rad", "frame_meaning": "trial shift",
            "frame_scale": {"origin": 0, "step": 2, "unit": "nm", "source": "user supplied"},
            "xy_scale": {"x": 0.1, "y": 0.2, "unit": "nm", "source_text": "user estimate"}})
        revised = self.run_action("context", object_id=context["object_id"], metadata={"value_unit": None})
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(context["user_context"]["value_unit"], "rad")
        self.assertIsNone(revised["user_context"]["value_unit"])
        view = self.run_action("view", object_id=revised["object_id"])
        self.assertEqual(view["user_context"], revised["user_context"])
        measure = self.run_action("measure", object_id=context["object_id"], points=[[0, 0], [3, 4]])
        self.assertEqual(measure["distance_pixels"], 5)
        self.assertAlmostEqual(measure["image_coordinate_angle_degrees"], 53.13010235415598)
        self.assertFalse(measure["physical_angle"])
        self.assertIsNone(measure["physical_distance"])

    def test_mcp_xy_scale_source_field_and_missing_provenance_refusal(self):
        frame = self.frame()
        context = self.run_action("context", object_id=frame["object_id"], metadata={
            "xy_scale": {"x": 0.25, "y": -0.5, "unit": "nm", "source": "user-provided instrument note"}})
        self.assertEqual(context["user_context"]["xy_scale"]["source"], "user-provided instrument note")
        self.assertFalse(context["calibration_applied"])
        for value in ({"x": 1, "y": 1, "unit": "nm"},
                      {"x": 1, "y": 1, "unit": "nm", "source": " "},
                      {"x": 1, "y": 1, "unit": "nm", "source": 123}):
            self.assertFalse(engine.execute(self.request("context", object_id=frame["object_id"], metadata={"xy_scale": value}))["ok"])

    def test_fft_annotations_are_frequency_bins_never_input_spatial_roi(self):
        frame = self.frame()
        spectrum = self.run_action("fft", object_id=frame["object_id"], rect=[1, 1, 6, 5])
        self.assertEqual(spectrum["source_rect_xyxy"], [1, 1, 6, 5])
        self.assertEqual(spectrum["panels"][0]["domain"], "frequency")
        self.assertEqual(spectrum["panels"][0]["source_object_id"], spectrum["object_id"])
        self.assertNotIn("source_rect_xyxy", spectrum["panels"][0])
        annotated = self.run_action("annotate", object_id=spectrum["object_id"], annotations=[
            {"kind": "point", "coordinates": [2, 2], "status": "hypothesized"},
            {"kind": "point", "coordinates": [0, 2], "status": "hypothesized"}])
        dc = annotated["annotations"][0]["source_mappings"][0]
        self.assertEqual(dc["source_object_id"], spectrum["object_id"])
        self.assertNotEqual(dc["source_object_id"], frame["object_id"])
        self.assertEqual(dc["fft_bin_coordinates"], [2, 2])
        self.assertEqual(dc["frequency_cycles_per_pixel"], [0, 0])
        self.assertFalse(dc["spatial_roi_mapping_performed"])
        self.assertNotIn("coordinates", dc)
        self.assertEqual(annotated["annotations"][1]["source_mappings"][0]["frequency_cycles_per_pixel"], [-0.4, 0])

    def test_downsampled_fft_annotations_keep_fractional_bins_and_cycles(self):
        path = self.base / "nonsquare.tiff"
        tifffile.imwrite(path, np.arange(32, dtype=np.uint16).reshape(8, 4))
        frame = self.frame(0, self.run_action("open", source_path=str(path)))
        spectrum = self.run_action("fft", object_id=frame["object_id"], max_size=4)
        annotated = self.run_action("annotate", object_id=spectrum["object_id"], annotations=[
            {"kind": "point", "coordinates": [1, 2]}, {"kind": "rectangle", "coordinates": [0, 0, 2, 4]}])
        point = annotated["annotations"][0]["source_mappings"][0]
        self.assertEqual(point["fft_bin_coordinates"], [2.5, 4.5])
        self.assertEqual(point["frequency_cycles_per_pixel"], [0.125, 0.0625])
        edges = annotated["annotations"][1]["source_mappings"][0]
        self.assertEqual(edges["fft_bin_coordinates"], [-0.5, -0.5, 3.5, 7.5])
        self.assertEqual(edges["frequency_cycles_per_pixel"], [-0.625, -0.5625, 0.375, 0.4375])

    def test_imported_frequency_panel_annotations_only_map_array_indices(self):
        current = engine.panel("a" * 32, [2, 3, 8, 7], [0, 0, 3, 2], array_domain="frequency")
        point = engine.annotation({"kind": "point", "coordinates": [1, 1]}, [3, 2], [current])["source_mappings"][0]
        self.assertEqual(current["domain"], "source_array_indices")
        self.assertEqual(point["array_index_coordinates"], [4.5, 5.5])
        self.assertFalse(point["spatial_roi_mapping_performed"])
        self.assertFalse(point["frequency_mapping_performed"])
        self.assertNotIn("coordinates", point)
        self.assertNotIn("frequency_cycles_per_pixel", point)

    def test_new_objects_record_software_versions_and_exact_worker_hash(self):
        opened = self.opened()
        provenance = opened["software_provenance"]
        self.assertEqual(provenance["worker_sha256"], hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest())
        self.assertEqual(provenance["numpy"], np.__version__)
        self.assertEqual(provenance["tifffile"], tifffile.__version__)
        self.assertTrue(provenance["python"])
        self.assertTrue(provenance["Pillow"])
        self.assertNotIn("path", provenance)

    def test_large_source_stat_identities_roundtrip_through_node_exactly(self):
        value = SimpleNamespace(st_size=123, st_mtime_ns=2 ** 60 + 123, st_ctime_ns=2 ** 60 + 456,
                                st_ino=2 ** 63 + 1, st_dev=2 ** 63 + 3)
        with patch.object(Path, "stat", return_value=value):
            identity = engine.stat_identity(self.source)
        self.assertEqual(identity, {"size": 123, "mtime_ns": str(2 ** 60 + 123), "ctime_ns": str(2 ** 60 + 456),
                                    "inode": str(2 ** 63 + 1), "device": str(2 ** 63 + 3)})
        script = "let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))));"
        process = subprocess.run(["node", "-e", script], input=json.dumps(identity), text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), identity)
        unsafe_numeric = {key: int(val) for key, val in identity.items()}
        previous = subprocess.run(["node", "-e", script], input=json.dumps(unsafe_numeric), text=True, capture_output=True)
        self.assertEqual(previous.returncode, 0, previous.stderr)
        self.assertNotEqual(json.loads(previous.stdout), unsafe_numeric, "Negative control must reproduce the original lossy JSON path")

    def test_context_and_display_survive_annotation_and_standalone_export(self):
        frame = self.frame()
        context = self.run_action("context", object_id=frame["object_id"], metadata={"value_unit": "user-defined raw unit"})
        viewed = self.run_action("view", object_id=context["object_id"], display_range=[0, 100])
        annotated = self.run_action("annotate", object_id=viewed["object_id"], annotations=[])
        self.assertEqual(annotated["user_context"], context["user_context"])
        exported = self.run_action("export", object_id=annotated["object_id"], output_dir=str(self.base / "context-export"))
        manifest = json.loads((Path(exported["output_dir"]) / "manifest.json").read_text())
        self.assertEqual(manifest["user_context"], context["user_context"])
        self.assertEqual(manifest["display_mapping"], viewed["display"])

    def test_export_exact_scientific_data_png_and_no_overwrite(self):
        frame = self.frame()
        output = self.base / "new-export"
        exported = self.run_action("export", object_id=frame["object_id"], output_dir=str(output))
        self.assertTrue((output / "preview.png").is_file())
        np.testing.assert_array_equal(np.load(output / "data.npy"), self.values[0])
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertTrue(manifest["scientific_NPY_is_not_display_PNG"])
        self.assertFalse(exported["dm_save_as_called"])
        failure = engine.execute(self.request("export", object_id=frame["object_id"], output_dir=str(output)))
        self.assertEqual(failure["error"]["code"], "OUTPUT_EXISTS")
        self.assertTrue((output / "manifest.json").is_file())

    def test_changed_array_or_manifest_cannot_satisfy_get_or_replay(self):
        frame = self.frame()
        path = Path(frame["manifest_path"])
        metadata = json.loads(path.read_text())
        metadata["dtype"] = "float64"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        response = engine.execute({"workspace": str(self.workspace), "action": "get", "object_id": frame["object_id"]})
        self.assertEqual(response["error"]["code"], "CORRUPT_OBJECT")

    def test_default_saved_capture_import_preserves_fractional_pixels_and_metadata(self):
        capture = self.base / "capture"
        capture.mkdir()
        values = np.array([[-1.5, 0.125, 3.75], [4, -2.25, 7.5]], dtype=np.float32)
        np.save(capture / "input.npy", values, allow_pickle=False)
        digest = hashlib.sha256((capture / "input.npy").read_bytes()).hexdigest()
        info = {"schema_version": 1, "capture_id": "a" * 32, "input_file": "input.npy", "input_sha256": digest,
                "dtype": "float32", "shape_yx": [2, 3], "axes": ["y", "x"], "array_order": "C", "byte_order": "little",
                "calibration": {"status": "unknown", "unit": None}}
        manifest = {"schema_version": 1, "capture_id": info["capture_id"], "state": "captured", "input_sha256": digest,
                    "capture_backend": "digitalmicrograph", "input_metadata_sha256": hashlib.sha256(engine.canonical(info)).hexdigest()}
        (capture / "input.json").write_bytes(engine.canonical(info))
        (capture / "capture.json").write_bytes(engine.canonical(manifest))
        imported = self.run_action("import_capture", source_path=str(capture))
        np.testing.assert_array_equal(np.load(imported["array_path"]), values)
        self.assertEqual(imported["upstream_backend"], "digitalmicrograph")
        self.assertEqual(imported["calibration"], info["calibration"])
        self.assertFalse(imported["dm_called"])
        self.assertEqual(json.loads((Path(imported["manifest_path"]).parent / "upstream-metadata.json").read_text())["input"], info)
        info["dtype"] = "uint16"
        manifest["input_metadata_sha256"] = hashlib.sha256(engine.canonical(info)).hexdigest()
        (capture / "input.json").write_bytes(engine.canonical(info))
        (capture / "capture.json").write_bytes(engine.canonical(manifest))
        response = engine.execute(self.request("import_capture", source_path=str(capture)))
        self.assertFalse(response["ok"])

    def test_native_saved_frame_capture_import_uses_generic_image_semantics(self):
        root = Path(engine.__file__).resolve().parents[1]
        fixture_uri = (root / "tests/fixtures/native-operations.mjs").as_uri()
        frame_uri = (root / "tests/fixtures/native-frame-handoff.mjs").as_uri()
        encoder_uri = (root / "tools/native_snapshot_handoff.mjs").as_uri()
        script = """import fs from 'node:fs';import path from 'node:path';
import {readFixture} from FIXTURE;
import {frameHandoffFixture} from FRAME;
import {handoff} from ENCODER;
const dir=process.argv[1],frame=frameHandoffFixture({unknownUnits:true}),args=[77,1,1,4,3];
const result=readFixture(args,{source:frame.result.image,provenance:frame.provenance});
result.frame_ancestry=frame.ancestry;
const bytes=Buffer.alloc(result.raw_bytes);for(let i=0;i<result.sample_count;i++)bytes.writeFloatLE([0,32767,32768,65535][i%4],i*4);
result.values_base64=bytes.toString('base64');
const receipt={protocol:'NB2',session:'a'.repeat(32),id:'saved-native-read',request_id:'saved-native-read',state:'completed',
host_pid:1234,exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
const source=path.join(dir,'native-read.json');fs.writeFileSync(source,JSON.stringify({...result,native_receipt:receipt}));
handoff({workspace:dir,output:'native-capture',requestId:'native-encode',snapshot:source});
""".replace("FIXTURE", json.dumps(fixture_uri)).replace("FRAME", json.dumps(frame_uri)).replace("ENCODER", json.dumps(encoder_uri))
        process = subprocess.run(["node", "--input-type=module", "-e", script, str(self.base)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        capture = self.base / "native-capture"
        imported = self.run_action("import_capture", source_path=str(capture))
        self.assertEqual(imported["capture_verification_mode"], "image")
        np.testing.assert_array_equal(np.load(imported["array_path"]), np.load(capture / "input.npy"))
        self.assertFalse(imported["dm_called"])
        original = json.loads((capture / "input.json").read_text())
        preserved = json.loads((Path(imported["manifest_path"]).parent / "upstream-metadata.json").read_text())["input"]
        self.assertEqual(preserved["frame_ancestry"], original["frame_ancestry"])

    def test_compare_rejects_different_view_regions_and_source_shapes(self):
        frame = self.frame()
        left = self.run_action("view", object_id=frame["object_id"], rect=[0, 0, 3, 3])
        right = self.run_action("view", object_id=frame["object_id"], rect=[1, 0, 4, 3])
        response = engine.execute(self.request("compare", object_ids=[left["object_id"], right["object_id"]]))
        self.assertFalse(response["ok"])
        self.assertIn("same source shape and ROI", response["error"]["message"])

    def test_annotation_states_coordinates_and_export_scientific_parent(self):
        frame = self.frame()
        view = self.run_action("view", object_id=frame["object_id"], rect=[1, 1, 6, 5])
        retracted = self.run_action("annotate", object_id=view["object_id"], annotations=[
            {"kind": "rectangle", "coordinates": [0, 0, 5, 4], "status": "retracted", "note": "withdrawn"}])
        self.assertEqual(retracted["annotations"][0]["source_mappings"][0]["coordinates"], [1, 1, 6, 5])
        output = self.base / "annotated-export"
        self.run_action("export", object_id=retracted["object_id"], output_dir=str(output))
        np.testing.assert_array_equal(np.load(output / "data.npy"), self.values[0, 1:5, 1:6])
        for annotation in ({"kind": "point", "coordinates": [-1, 2]}, {"kind": "point", "coordinates": [5, 1]},
                           {"kind": "rectangle", "coordinates": [1, 1, 0, 0]},
                           {"kind": "text", "coordinates": [1, 1], "text": "label", "status": "proven"}):
            self.assertFalse(engine.execute(self.request("annotate", object_id=view["object_id"], annotations=[annotation]))["ok"])

    def test_pending_conflict_and_export_tampering_cannot_create_pass(self):
        frame = self.frame()
        output = self.base / "guarded-export"
        original = self.request("export", object_id=frame["object_id"], output_dir=str(output))
        exported = engine.execute(original)
        self.assertTrue(exported["ok"])
        with (output / "data.npy").open("ab") as changed:
            changed.write(b"bad")
        replay = engine.execute(original)
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["error"]["code"], "CORRUPT_OBJECT")
        response = engine.execute({"workspace": str(self.workspace), "action": "get", "object_id": exported["result"]["object_id"]})
        self.assertFalse(response["ok"])

    def test_truncated_journal_is_unknown_and_foreign_original_cannot_pass(self):
        source = self.opened()
        request = self.request("frame", object_id=source["object_id"], frame_index=1)
        journal = self.workspace / "requests" / (request["request_id"] + ".json")
        journal.write_text('{"state":"pre', encoding="utf-8")
        before = list((self.workspace / "objects").iterdir())
        response = engine.execute(request)
        self.assertEqual(response["state"], "unknown")
        self.assertFalse(response["automatic_retry"])
        self.assertEqual(list((self.workspace / "objects").iterdir()), before)
        query = engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": request["request_id"]})
        self.assertEqual(query["state"], "unknown")
        other = self.workspace / "requests" / "foreign-original.json"
        other.write_bytes((self.workspace / "requests" / (source["request_id"] + ".json")).read_bytes())
        foreign = engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": "foreign-original"})
        self.assertFalse(foreign["ok"])
        self.assertEqual(foreign["error"]["code"], "CORRUPT_OBJECT")

    def test_cli_one_json_request_and_structured_error(self):
        script = Path(engine.__file__)
        request = self.request("open", source_path=str(self.source))
        process = subprocess.run([sys.executable, "-B", str(script)], input=json.dumps(request), capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        response = json.loads(process.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["backend"], "external-image-workspace")
        self.assertNotIn("DigitalMicrograph", process.stdout)
        invalid = subprocess.run([sys.executable, "-B", str(script)], input='{"action":"get","action":"open"}', capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(json.loads(invalid.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
