"""Saved protocol fixtures and mock files only, never a real DM qualification."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from crystallography.capture import CaptureError, MAX_NPY_BYTES, load_capture


ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CrystalCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="crystal-capture-fixtures-")
        cls.fixtures = Path(cls.temporary.name)
        fixture = (ROOT / "tests/fixtures/native-operations.mjs").as_uri()
        snapshot = (ROOT / "tools/native_snapshot_handoff.mjs").as_uri()
        region = (ROOT / "tools/native_region_handoff.mjs").as_uri()
        script = r"""import fs from 'node:fs';import path from 'node:path';
import {imageMetadata,readFixture,fourierFixture} from FIXTURE;
import {handoff} from SNAPSHOT;import {handoffRegion} from REGION;
const dir=process.argv[1],session='a'.repeat(32),pid=1234;
function receipt(id,args){return {protocol:'NB2',session,id,request_id:id,state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,
timings_us:{queue:3,execute:4},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};}
function save(name,read,args){const p=path.join(dir,name+'.json');fs.writeFileSync(p,JSON.stringify({...read,native_receipt:receipt(name,args)}));
handoff({workspace:dir,output:name,requestId:'encode-'+name,snapshot:p});}
const rawArgs=[77,1,1,4,3];save('raw',readFixture(rawArgs),rawArgs);
save('unsigned',readFixture(rawArgs,{source:imageMetadata(77,{unsigned:true})}),rawArgs);
for(const op of ['REAL','VENDOR_NORM']){
 const producer=fourierFixture(op,77),source=structuredClone(producer.image);source.id=101;source.shape=[3,6];source.dm_dimensions=[6,3];source.pixels=18;
 source.calibration.forEach((axis)=>{axis.size=source.dm_dimensions[axis.dm_dimension];axis.origin-=1;axis.calibrated_value_at_pixel_zero+=axis.scale;});
 const args=[101,2,1,5,3],read=readFixture(args,{source,provenance:{operation:'CROP',request_id:'crop-one',source_image_ids:[99],semantics:'synthetic contract only'}});
 read.scientific_context={schema_version:1,status:'tracked_fourier',original_operation:op,request_id:'component-one',normalized_args:[77],result_version:2,
 result:producer,source_offset_xy:[1,1],postprocessing:[]};
 if(op==='VENDOR_NORM'){const b=Buffer.alloc(read.raw_bytes);for(let i=0;i<read.sample_count;i++)b.writeFloatLE(i+.25,i*4);read.values_base64=b.toString('base64');}
 save(op==='REAL'?'fft-real':'fft-power',read,args);
 if(op==='REAL'){
   const outsideArgs=[101,5,1,6,3],outside=readFixture(outsideArgs,{source,provenance:read.source_provenance});
   outside.scientific_context=structuredClone(read.scientific_context);save('fft-outside',outside,outsideArgs);
 }
}
const source=imageMetadata(77,{shape:[7,9]}),saved=new Map();
const bridge={async execute(op,args,{requestId}){const reply={protocol:'NB2',session,id:requestId,state:'completed',host_pid:pid,exec_tid:10,worker_tid:20,
timings_us:{queue:0,execute:1},original_operation:op,normalized_args:args,result_type:op==='STATUS'?'status':'native_data_snapshot',result_version:1,
result:op==='STATUS'?{backend:'digitalmicrograph-native',host_pid:pid,ready:true,binary_gate:true,compatibility:{state:'SUPPORTED'}}:readFixture(args,{source})};saved.set(requestId,reply);return reply;},
async query(id){return saved.get(id);},close(){}};
await handoffRegion({workspace:dir,output:'chunked',requestId:'synthetic-region',imageId:77,rect:[1,1,8,6],session,hostPid:pid,blockSamples:8},()=>bridge);
""".replace("FIXTURE", json.dumps(fixture)).replace("SNAPSHOT", json.dumps(snapshot)).replace("REGION", json.dumps(region))
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(cls.fixtures)],
                                cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr)
        from bridge.dm_bridge import MockBackend
        MockBackend().capture2d(1000, [1, 2, 6, 5], str(cls.fixtures / "mock"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="crystal-capture-case-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def capture(self, name="raw"):
        target = self.directory / name
        shutil.copytree(self.fixtures / name, target)
        return target

    def edit(self, path, mutate, rehash=True):
        info = json.loads((path / "input.json").read_bytes())
        manifest = json.loads((path / "capture.json").read_bytes())
        mutate(info, manifest)
        encoded = canonical(info)
        if rehash:
            manifest["input_metadata_sha256"] = sha(encoded)
            if "input_metadata_file_sha256" in manifest:
                manifest["input_metadata_file_sha256"] = sha(encoded)
        (path / "input.json").write_bytes(encoded)
        (path / "capture.json").write_bytes(canonical(manifest))

    def test_saved_read_reopens_exact_signed_values_and_explicit_source_center_mapping(self):
        path = self.capture()
        before = {name: (path / name).read_bytes() for name in ("input.npy", "input.json", "capture.json")}
        capture = load_capture(path, "diffraction", expected_session="a"*32, expected_host_pid=1234)
        expected = np.array([[-0., -2.5, .125], [8., -0., -2.5]], dtype="<f4")
        self.assertEqual(capture.array.tobytes(), expected.tobytes())
        self.assertFalse(capture.array.flags.writeable)
        with self.assertRaises(ValueError):
            capture.array[0, 0] = 2
        self.assertEqual(capture.source_roi, [1, 1, 4, 3])
        self.assertEqual(capture.source_to_local_xy([[1, 1], [3, 2], [2.25, 1.5]]), [[0, 0], [2, 1], [1.25, .5]])
        self.assertEqual([axis["scale"] for axis in capture.coordinate_axes], [-.25, .5])
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] for axis in capture.coordinate_axes], [.25, 1.])
        self.assertIsNone(capture.provenance["actual_dm"])
        self.assertFalse(capture.provenance["live_source_reobserved"])
        capture.assert_unchanged()
        self.assertEqual(before, {name: (path / name).read_bytes() for name in before})

    def test_uint32_preserves_values_larger_than_binary32_precision(self):
        capture = load_capture(self.capture("unsigned"), "diffraction")
        self.assertEqual(capture.array.dtype, np.dtype("<u4"))
        self.assertEqual(capture.array.tolist(), [[0, 16777215, 16777217], [2147483648, 4294967295, 1]])

    def test_fft_crop_plus_read_offsets_and_outside_dc_use_math_grid_not_halfbin(self):
        capture = load_capture(self.capture("fft-real"), "fft")
        self.assertEqual(capture.source_roi, [2, 1, 5, 3])
        axes = capture.frequency_axes_cycles_per_nm()
        # Original 8x4 grid: x step=-0.5, y step=+0.5; crop [1,1]
        # plus READ [2,1] gives original offsets [3,2], hence DC local [1,0].
        self.assertEqual([axis["source_index_offset"] for axis in axes], [3, 2])
        self.assertEqual([axis["dc_index_in_roi"] for axis in axes], [1, 0])
        self.assertEqual([axis["scale"] for axis in axes], [-.5, .5])
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] for axis in axes], [.5, 0])
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] for axis in capture.metadata["working_calibration_xy"]], [.75, -.25])
        local = capture.source_to_local_xy([[3, 1]])[0]
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] + local[dim]*axis["scale"] for dim, axis in enumerate(axes)], [0, 0])
        capture.assert_unchanged()

    def test_native_power_representation_is_retained_without_intensity_calibration(self):
        capture = load_capture(self.capture("fft-power"), "fft")
        self.assertEqual(capture.array.tolist(), [[.25, 1.25, 2.25], [3.25, 4.25, 5.25]])
        self.assertEqual(capture.provenance["scientific_semantics"]["representation"], "squared_magnitude")
        self.assertFalse(capture.provenance["source_intensity_calibration_applied"])

    def test_fft_dc_outside_capture_is_not_clamped_to_a_pixel(self):
        capture = load_capture(self.capture("fft-outside"), "fft")
        axes = capture.frequency_axes_cycles_per_nm()
        self.assertEqual(capture.source_roi, [5, 1, 6, 3])
        self.assertEqual([axis["source_index_offset"] for axis in axes], [6, 2])
        self.assertEqual([axis["dc_index_in_roi"] for axis in axes], [-2, 0])
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] for axis in axes], [-1, 0])

    def test_fft_explicit_reciprocal_angstrom_conversion_is_ten_per_nm(self):
        path = self.capture("fft-power")
        def mutation(info, manifest):
            def units(value):
                if isinstance(value, dict):
                    for key, entry in value.items():
                        if key == "unit" and entry == "1/nm": value[key] = "1/Å"
                        else: units(entry)
                elif isinstance(value, list):
                    for entry in value: units(entry)
            units(info)
            manifest["calibration_before"] = manifest["calibration_after"] = info["source_calibration_dm"]
        self.edit(path, mutation)
        capture = load_capture(path, "fft")
        axes = capture.frequency_axes_cycles_per_nm()
        self.assertEqual([axis["scale"] for axis in axes], [-5, 5])
        self.assertEqual([axis["calibrated_value_at_pixel_zero"] for axis in axes], [5, 0])
        self.assertEqual([axis["source_unit"] for axis in axes], ["1/Å", "1/Å"])

    def test_complete_chunked_read_reuses_original_block_verifier_and_all_hashes(self):
        path = self.capture("chunked")
        capture = load_capture(path, "diffraction", expected_session="a"*32, expected_host_pid=1234)
        self.assertEqual(capture.array.shape, (5, 7))
        self.assertEqual(len(capture.provenance["native_read_request_ids"]), 5)
        self.assertEqual(len(capture.provenance["capture_files_sha256"]), 8)
        self.assertEqual(capture.source_to_local_xy([[1, 1], [7, 5]]), [[0, 0], [6, 4]])
        with (path / "read-4.json").open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(CaptureError, "changed"):
            capture.assert_unchanged()

    def test_existing_generic_mock_schema_is_explicitly_synthetic(self):
        path = self.capture("mock")
        capture = load_capture(path, "synthetic_diffraction")
        self.assertEqual(capture.array.shape, (3, 5))
        self.assertEqual(capture.source_roi, [1, 2, 6, 5])
        self.assertTrue(capture.provenance["synthetic"])
        self.assertFalse(capture.provenance["actual_dm"])
        self.assertIsNone(capture.provenance["native_session"])
        for mode in ("diffraction", "fft"):
            with self.subTest(mode=mode), self.assertRaises(CaptureError):
                load_capture(path, mode)
        with self.assertRaises(CaptureError):
            load_capture(path, "synthetic_diffraction", expected_session="a"*32)

    def test_native_receipts_cannot_be_relabelled_synthetic_or_wrong_source_mode(self):
        with self.assertRaises(CaptureError):
            load_capture(self.capture(), "synthetic_diffraction")
        with self.assertRaises(CaptureError):
            load_capture(self.capture("fft-power"), "diffraction")
        with self.assertRaises(CaptureError):
            load_capture(self.fixtures / "raw", "fft")

    def test_independent_expected_identity_refuses_other_self_consistent_host(self):
        path = self.capture()
        info = json.loads((path / "input.json").read_bytes())
        for options in ({"expected_capture_id": "b"*32}, {"expected_session": "b"*32}, {"expected_host_pid": 4321}):
            with self.subTest(options=options), self.assertRaisesRegex(CaptureError, "Expected"):
                load_capture(path, "diffraction", **options)
        self.assertEqual(load_capture(path, "diffraction", expected_capture_id=info["capture_id"]).source_roi, [1, 1, 4, 3])

    def test_points_refuse_outside_fractional_edge_nonfinite_bool_and_budget(self):
        capture = load_capture(self.capture(), "diffraction")
        for points in ([], [[.99, 1]], [[3.1, 1]], [[1, 2.01]], [[float("nan"), 1]], [[True, 1]], [[1, 1]]*129):
            with self.subTest(points=str(points)[:80]), self.assertRaises(CaptureError):
                capture.source_to_local_xy(points)

    def test_metadata_pixel_and_receipt_hash_tampering_refuse(self):
        path = self.capture()
        before = {name: (path / name).read_bytes() for name in ("input.npy", "input.json", "capture.json")}
        try:
            altered = bytearray(before["input.npy"]); altered[-1] ^= 1
            (path / "input.npy").write_bytes(altered)
            with self.assertRaises(CaptureError):
                load_capture(path, "diffraction")
            (path / "input.npy").write_bytes(before["input.npy"])
            self.edit(path, lambda info, manifest: info["working_calibration_xy"][0].update(scale=99), rehash=False)
            with self.assertRaises(CaptureError):
                load_capture(path, "diffraction")
        finally:
            for name, raw in before.items():
                (path / name).write_bytes(raw)
        self.edit(path, lambda info, manifest: info["native_receipt"].update(host_pid=999))
        with self.assertRaises(CaptureError):
            load_capture(path, "diffraction")

    def test_rehashed_axis_dtype_receipt_and_source_contract_conflicts_refuse(self):
        mutations = {
            "axis-swap": lambda info, m: info.update(axes=["x", "y"]),
            "scale": lambda info, m: info["working_calibration_xy"][0].update(scale=.25),
            "origin": lambda info, m: info["working_calibration_xy"][0].update(origin=99),
            "zero": lambda info, m: info["working_calibration_xy"][0].update(calibrated_value_at_pixel_zero=99),
            "source-id": lambda info, m: info["source_metadata"].update(id=88),
            "source-dtype": lambda info, m: info["source_metadata"].update(data_type_code=11),
            "packing": lambda info, m: info["source_metadata"].update(packing_style=0),
            "roi": lambda info, m: info.update(source_rect_xyxy=[0, 0, 3, 2]),
            "receipt": lambda info, m: info["native_receipt"].update(normalized_args=[77, 0, 0, 3, 2]),
            "pixelhash": lambda info, m: info.update(pixel_sha256="b"*64),
            "metadata-file-hash": lambda info, m: m.update(input_metadata_file_sha256="b"*64),
            "incomplete": lambda info, m: m.update(state="capturing"),
            "missing-calibration": lambda info, m: info.pop("working_calibration_xy"),
        }
        for name, mutation in mutations.items():
            path = self.directory / name; shutil.copytree(self.fixtures / "raw", path)
            self.edit(path, mutation, rehash=name != "metadata-file-hash")
            with self.subTest(name=name), self.assertRaises(CaptureError):
                load_capture(path, "diffraction")

    def test_rehashed_forged_fourier_bin_axis_processed_and_spatial_lineage_refuse(self):
        mutations = {
            "halfbin": lambda info, m: info["scientific_semantics"]["coordinate_axes"][0].update(calibrated_value_at_pixel_zero=.75),
            "offset": lambda info, m: info["scientific_context"].update(source_offset_xy=[0, 0]),
            "postprocessed": lambda info, m: info["scientific_context"].update(postprocessing=["GMSImageProcessing::Square"]),
            "unresolved": lambda info, m: info.update(scientific_context={"schema_version": 1, "status": "unresolved_lineage"}),
            "missing": lambda info, m: info.update(scientific_context=None),
            "grid": lambda info, m: info["scientific_context"]["result"]["frequency_grid"]["axes"][0].update(dc_index=3),
            "phase": lambda info, m: info["scientific_semantics"].update(representation="phase_radians"),
            "spatial": lambda info, m: info["scientific_semantics"].update(domain="spatial"),
            "producer-id": lambda info, m: info["scientific_context"]["result"].update(source_image_id=123),
            "crop-operation": lambda info, m: info["native_source_provenance"].update(operation="UNARY"),
        }
        for name, mutation in mutations.items():
            path = self.directory / name; shutil.copytree(self.fixtures / "fft-real", path)
            self.edit(path, mutation)
            with self.subTest(name=name), self.assertRaises(CaptureError):
                load_capture(path, "fft")

    def test_chunked_snapshot_digest_and_original_request_id_fail(self):
        for index, field in enumerate(("file", "request")):
            path = self.directory / str(index); shutil.copytree(self.fixtures / "chunked", path)
            if field == "file":
                with (path / "read-0.json").open("ab") as stream: stream.write(b" ")
            else:
                self.edit(path, lambda info, m: m["blocks"][0]["request"].update(id="different-original-id"))
            with self.subTest(field=field), self.assertRaises(CaptureError):
                load_capture(path, "diffraction")

    def test_hash_consistent_png_object_array_wrong_dtype_and_trailing_bytes_fail(self):
        payloads = {"png": b"\x89PNG\r\n\x1a\n", "trailing": None}
        for dtype in ("float64", "object"):
            stream = io.BytesIO(); np.save(stream, np.zeros((2, 3), dtype=dtype), allow_pickle=dtype == "object")
            payloads[dtype] = stream.getvalue()
        for name, payload in payloads.items():
            path = self.directory / name; shutil.copytree(self.fixtures / "raw", path)
            raw = (path / "input.npy").read_bytes() + b"x" if payload is None else payload
            (path / "input.npy").write_bytes(raw)
            def mutation(info, manifest):
                info["input_sha256"] = manifest["input_sha256"] = sha(raw)
                info["input_file_bytes"] = len(raw)
            self.edit(path, mutation)
            with self.subTest(name=name), self.assertRaises(CaptureError):
                load_capture(path, "diffraction")

    def test_hash_consistent_nonfinite_and_negative_native_power_pixels_refuse(self):
        for name, replacement, mode in (("raw", float("nan"), "diffraction"), ("fft-power", -.25, "fft")):
            path = self.capture(name)
            values = np.load(path / "input.npy", allow_pickle=False)
            values[0, 0] = replacement
            stream = io.BytesIO(); np.save(stream, values, allow_pickle=False)
            raw = stream.getvalue(); (path / "input.npy").write_bytes(raw)
            def mutation(info, manifest):
                info["input_sha256"] = manifest["input_sha256"] = sha(raw)
                info["pixel_sha256"] = manifest["pixel_sha256"] = sha(values.tobytes())
                info["input_file_bytes"] = len(raw)
            self.edit(path, mutation)
            with self.subTest(name=name), self.assertRaises(CaptureError):
                load_capture(path, mode)

    def test_preallocation_file_budget_duplicate_json_and_nonfinite_json_refuse(self):
        path = self.capture()
        with (path / "input.npy").open("r+b") as stream:
            stream.truncate(MAX_NPY_BYTES+1)
        with self.assertRaisesRegex(CaptureError, "budget"):
            load_capture(path, "diffraction")
        for name, content in (("duplicate", b'{"schema_version":1,"schema_version":1}'), ("nonfinite", b'{"value":NaN}')):
            target = self.directory / name; shutil.copytree(self.fixtures / "raw", target)
            (target / "input.json").write_bytes(content)
            with self.subTest(name=name), self.assertRaises(CaptureError):
                load_capture(target, "diffraction")


if __name__ == "__main__":
    unittest.main()
