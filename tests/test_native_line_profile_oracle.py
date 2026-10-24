"""Independent synthetic payload/file counterexamples; no real DM imports."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

MVP = Path(__file__).resolve().parents[1] / "experiments" / "native-bridge" / "mvp"
sys.path.insert(0, str(MVP))
try:
    spec = importlib.util.spec_from_file_location("line_profile_oracle_for_tests", str(MVP / "verify_line_profile.py"))
    oracle = importlib.util.module_from_spec(spec); spec.loader.exec_module(oracle)
    from create_line_profile_fixture import fixed_arrays
finally: sys.path.pop(0)


def request(op, args, identifier="profile-original"):
    session = "a" * 32
    return dict(protocol="NB2", session=session, host_pid=1234, id=identifier, op=op, args=args,
                wire="NB2 " + session + " " + identifier + " " + op + "".join(" " + str(v) for v in args) + "\n")


def receipt(saved):
    result = dict(protocol="NB2", session=saved["session"], host_pid=saved["host_pid"], id=saved["id"], request_id=saved["id"],
                state="completed", original_operation=saved["op"], normalized_args=saved["args"], result_type=oracle.TYPES[saved["op"]],
                result_version=2 if saved["op"] == "ROIS" else 1, exec_tid=0 if saved["op"] == "STOP" else 10, worker_tid=11, timings_us=dict(queue=1, execute=2))
    if saved["op"] == "STOP": result["result"] = {"ipc_stopped": True}
    return result


def make_source(label="float_plane", identifier=77, endpoints=(2, 4, 17, 4)):
    values = fixed_arrays()[label]
    sx = -.25 if label == "float_negative_scale" else .25
    sy = .5 if label == "float_anisotropic" else sx
    source = dict(id=identifier, name="SYNTHETIC_" + label, dtype=str(values.dtype), shape=list(values.shape), pixel_sha256=oracle.sha(values.tobytes()),
                  calibration=[dict(dm_axis=0, origin=1.25, raw_origin=-1.25 / sx, scale=sx, unit="nm"),
                               dict(dm_axis=1, origin=-2.5, raw_origin=2.5 / sy, scale=sy, unit="nm")],
                  intensity_calibration=dict(origin=7.5, scale=-2, unit="arb"),
                  displays=[dict(document_id=31, display_id=9, rois=[dict(roi_id=4, oracle_kind="line", rotation_degrees=0, raw_line_xyxy=list(endpoints))])])
    return source, values


def source_meta(source):
    return dict(id=source["id"], name=source["name"], ndim=2, dtype=source["dtype"], shape=source["shape"], dm_dimensions=source["shape"][::-1],
                data_type_code=2 if source["dtype"] == "float32" else 11, packing_style=1,
                calibration=[dict(dm_dimension=d, numpy_axis=1-d, size=source["shape"][1-d], origin=a["raw_origin"], calibrated_value_at_pixel_zero=a["origin"],
                                  scale=a["scale"], unit=a["unit"], usable=True, issue=None) for d, a in enumerate(source["calibration"])])


def sample(label="float_plane", endpoints=(2, 4, 17, 4)):
    source, data = make_source(label, endpoints=endpoints); args = [77, 31, 9, 4] + list(endpoints) + [1]
    saved = request("PROFILE", args); expected, step, cal = oracle.expected_profile(source, data, args); count = len(expected)
    meta = dict(id=101, ndim=1, dtype="float64", data_type_code=12, shape=[count], dm_dimensions=[count], packing_style=1,
                shape_order="one-dimensional native profile samples", calibration=[dict(dm_dimension=0, numpy_axis=0, size=count, usable=True, issue=None, **cal)])
    result = dict(backend="digitalmicrograph-native", operation="PROFILE", source_image_id=77, image_id=101, source=source_meta(source), image=meta,
                  source_gui_line=dict(document_id=31, display_id=9, roi_id=4, raw_line=dict(zip(("x0","y0","x1","y1"), endpoints)), effective_line=list(endpoints),
                                       rotation_degrees=0, source_layout="direct_image_canonical_xy", slice_ids=[0], coordinate_mapping=oracle.normalized_mapping(source["shape"])),
                  width=1, shape=[count], dtype="float64", axes=oracle.AXES, byte_order="little", array_order="C", data_encoding="base64",
                  sample_count=count, raw_bytes=count*8, output_bytes=count*8, values_base64=base64.b64encode(expected.tobytes()).decode("ascii"),
                  source_sample_start_xy=list(endpoints[:2]), source_sample_end_xy=list(endpoints[2:]), source_sample_step_xy=step,
                  distance_step=abs(cal["scale"]), distance_zero=0, distance_unit="nm", calibration_complete=True,
                  source_intensity_calibration=source["intensity_calibration"], intensity_calibration=source["intensity_calibration"],
                  operator="LiveProfile_ExtractLineProfile", computation="DM native", snapshot_atomic=False, source_write_requested=False,
                  intensity_calibration_applied=False, intensity_semantics="raw pixel intensity", native_receipt=receipt(saved),
                  retention=dict(token=9001, creation_request_id=saved["id"]))
    return source, data, saved, result


def npy_bytes(values):
    stream = io.BytesIO(); np.save(stream, values, allow_pickle=False); return stream.getvalue()


class LineProfileOracleTests(unittest.TestCase):
    def checked(self, source, data, saved, result):
        return oracle.verify_profile_payload(result, saved, source, data, "a"*32, 1234, (10, 11))

    def test_independent_endpoint_values_nonlinearity_unsigned_high_bits_and_signed_native_axis(self):
        for label, ends in (("float_plane",(2,4,17,4)), ("float_nonlinear",(8,2,8,13)), ("uint32_high",(19,9,3,9)), ("float_negative_scale",(2,4,17,4))):
            with self.subTest(label=label):
                source, data, saved, result = sample(label, ends); checked = self.checked(source, data, saved, result)
                self.assertEqual(checked["values"].ndim, 1); self.assertEqual(checked["values"].dtype, np.float64)
                self.assertEqual(checked["values"][0], float(data[ends[1], ends[0]])); self.assertEqual(checked["values"][-1], float(data[ends[3], ends[2]]))
                self.assertEqual(checked["native_calibration"]["scale"], source["calibration"][0]["scale"])
                oracle.verify_npy(npy_bytes(checked["values"]), checked["values"])

    def test_wrong_host_original_request_source_line_rank_calibration_or_encoding_never_pass(self):
        mutations = {
            "wrong_pid": lambda r: r["native_receipt"].update(host_pid=4321),
            "wrong_request_id": lambda r: r["native_receipt"].update(id="other"),
            "wrong_session": lambda r: r["native_receipt"].update(session="b"*32),
            "wrong_original_op": lambda r: r["native_receipt"].update(original_operation="CROP"),
            "wrong_schema": lambda r: r["native_receipt"].update(result_type="native_image_operation"),
            "wrong_thread": lambda r: r["native_receipt"].update(worker_tid=10),
            "wrong_source": lambda r: r.update(source_image_id=78),
            "wrong_retention_request": lambda r: r["retention"].update(creation_request_id="other-original"),
            "invalid_retention_token": lambda r: r["retention"].update(token=0),
            "wrong_source_origin": lambda r: r["source"]["calibration"][0].update(origin=5),
            "wrong_source_zero": lambda r: r["source"]["calibration"][0].update(calibrated_value_at_pixel_zero=0),
            "wrong_doc": lambda r: r["source_gui_line"].update(document_id=32),
            "wrong_display": lambda r: r["source_gui_line"].update(display_id=10),
            "wrong_line": lambda r: r["source_gui_line"].update(roi_id=5),
            "reversed_endpoints": lambda r: r["source_gui_line"].update(effective_line=[17,4,2,4]),
            "wrong_raw_endpoints": lambda r: r["source_gui_line"]["raw_line"].update(x0=3),
            "wrong_endpoint_sampling": lambda r: r.update(source_sample_end_xy=[16,4]),
            "wrong_sample_step": lambda r: r.update(source_sample_step_xy=[-1,0]),
            "wide_line": lambda r: r.update(width=2),
            "wrong_dtype": lambda r: r.update(dtype="float32"),
            "row_image": lambda r: r["image"].update(ndim=2, shape=[1,16], dm_dimensions=[16,1]),
            "wrong_native_axis": lambda r: r["image"]["calibration"][0].update(scale=-.25),
            "wrong_native_zero": lambda r: r["image"]["calibration"][0].update(calibrated_value_at_pixel_zero=1.25),
            "wrong_native_origin": lambda r: r["image"]["calibration"][0].update(origin=1),
            "wrong_unit": lambda r: r["image"]["calibration"][0].update(unit="px"),
            "applied_intensity": lambda r: r.update(intensity_calibration_applied=True),
            "wrong_intensity_copy": lambda r: r.update(intensity_calibration=dict(origin=0,scale=1,unit=None)),
            "wrong_mapping": lambda r: r["source_gui_line"]["coordinate_mapping"].update(scale=[1,1]),
            "wrong_layout": lambda r: r["source_gui_line"].update(source_layout="unsupported"),
            "invalid_encoding": lambda r: r.update(values_base64="%%"),
            "wrong_values": lambda r: r.update(values_base64=base64.b64encode(np.zeros(16,dtype="<f8").tobytes()).decode("ascii")),
            "not_f64_bytes": lambda r: r.update(values_base64=base64.b64encode(np.zeros(16,dtype="<f4").tobytes()).decode("ascii")),
        }
        source, data, saved, result = sample()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(result); mutate(value)
                with self.assertRaises((ValueError, KeyError)): self.checked(source, data, saved, value)

    def test_reversed_value_order_and_negative_scale_are_not_relabelled(self):
        source, data, saved, result = sample("float_nonlinear", (19,9,3,9))
        expected = self.checked(source, data, saved, result)["values"]
        result["values_base64"] = base64.b64encode(expected[::-1].tobytes()).decode("ascii")
        with self.assertRaises(ValueError): self.checked(source, data, saved, result)
        source, data, saved, result = sample("float_negative_scale")
        result["image"]["calibration"][0]["scale"] = .25
        with self.assertRaises(ValueError): self.checked(source, data, saved, result)

    def test_invalid_line_arguments_and_saved_wire(self):
        source, values, saved, result = sample()
        for ends in ((2,2,12,10),(6,6,6,6),(2,4,99,4),(2.5,4,17.5,4)):
            with self.subTest(ends=ends):
                with self.assertRaises(ValueError): oracle.expected_profile(source, values, [77,31,9,4]+list(ends)+[1])
        anisotropic, values = make_source("float_anisotropic")
        with self.assertRaises(ValueError): oracle.expected_profile(anisotropic, values, saved["args"])
        corrupted = copy.deepcopy(saved); corrupted["wire"] = corrupted["wire"].replace(" 17 ", " 16 ")
        with self.assertRaises(ValueError): oracle.request_identity(corrupted, "a"*32, 1234)

    def test_npy_dtype_rank_payload_or_trailing_bytes_never_pass(self):
        source, data, saved, result = sample(); expected = self.checked(source,data,saved,result)["values"]
        wrong = [npy_bytes(expected.astype(np.float32)), npy_bytes(expected[None,:]), npy_bytes(expected[::-1]),
                 npy_bytes(expected)+b"trailer", npy_bytes(expected)[:-1], b"bad"]
        for raw in wrong:
            with self.subTest(bytes=len(raw)):
                with self.assertRaises((ValueError, EOFError)): oracle.verify_npy(raw, expected)

    def make_package(self, directory, result, checked):
        root=Path(directory)/"capture";root.mkdir()
        raw=npy_bytes(checked["values"]);(root/"input.npy").write_bytes(raw)
        native=copy.deepcopy(result);receipt=native.pop("native_receipt")
        info=dict(schema_version=1,capture_id="c"*32,capture_mode="native_profile",shape=result["shape"],dtype="float64",byte_order="little",array_order="C",axes=oracle.AXES,
                  axis_roles=[dict(numpy_axis=0,dm_dimension=0,role="native_profile_axis")],source_image_id=result["source_image_id"],source_shape_yx=result["source"]["shape"],
                  source_line_xyxy=result["source_gui_line"]["effective_line"],source_gui_line=result["source_gui_line"],source_calibration_dm=result["source"]["calibration"],
                  profile_calibration=result["image"]["calibration"],source_metadata=result["source"],profile_metadata=result["image"],native_profile_result=native,
                  source_intensity_calibration=result["source_intensity_calibration"],intensity_calibration=result["intensity_calibration"],source_sample_start_xy=result["source_sample_start_xy"],
                  source_sample_end_xy=result["source_sample_end_xy"],source_sample_step_xy=result["source_sample_step_xy"],distance_zero=0,distance_step=result["distance_step"],distance_unit="nm",
                  native_receipt=receipt,native_receipt_sha256=oracle.sha(oracle.canonical(receipt)),input_sha256=oracle.sha(raw),input_file_bytes=len(raw),raw_bytes=len(checked["raw"]),
                  sample_count=len(checked["values"]),pixel_sha256=oracle.sha(checked["raw"]),intensity_calibration_applied=False,intensity_semantics="raw pixel intensity",width=1,input_file="input.npy",
                  computation="DM native",operator=result["operator"],calibration_complete=True,source_path_included=False,
                  pixel_capture_atomic=False,dm_file_save=False,external_saved_response_encoding=True,saved_snapshot_sha256="d"*64)
        capture=dict(schema_version=1,state="captured",capture_id=info["capture_id"],capture_mode="native_profile",shape=result["shape"],axes=oracle.AXES,
                     source_image_id=result["source_image_id"],source_line_xyxy=info["source_line_xyxy"],source_dtype=result["source"]["dtype"],output_dtype="float64",
                     operation="bounded 1D native profile capture",capture_backend="saved digitalmicrograph-native PROFILE numeric snapshot",external_saved_response_encoding=True,
                     calibration_before=info["source_calibration_dm"],calibration_after=info["source_calibration_dm"],input_sha256=info["input_sha256"],pixel_sha256=info["pixel_sha256"],
                     native_session=receipt["session"],native_request_id=receipt["id"],native_receipt_sha256=info["native_receipt_sha256"],saved_snapshot_sha256=info["saved_snapshot_sha256"],
                     pixel_capture_atomic=False,dm_file_save=False,live_source_reobserved=False)
        self.write_package(root,info,capture)
        return root,info,capture

    def write_package(self,root,info,capture):
        (root/"input.json").write_text(json.dumps(info,allow_nan=False),encoding="utf-8")
        capture["input_metadata_sha256"]=oracle.sha(oracle.canonical(info));capture["input_metadata_file_sha256"]=oracle.sha((root/"input.json").read_bytes())
        (root/"capture.json").write_text(json.dumps(capture,allow_nan=False),encoding="utf-8")

    def test_independent_schema1_profile_reopen_and_rehashed_metadata_counterexamples(self):
        source,data,saved,result=sample("float_negative_scale");checked=self.checked(source,data,saved,result)
        with tempfile.TemporaryDirectory() as directory:
            root,info,capture=self.make_package(directory,result,checked)
            oracle.verify_package(oracle.Evidence(directory),"capture",result,checked)
            mutations={
                "wrong_rank":lambda i,c:i.update(shape=[1,len(checked["values"])]),
                "fake_shape_yx":lambda i,c:i.update(shape_yx=[1,len(checked["values"])]),
                "wrong_axes":lambda i,c:i.update(axes=["distance"]),
                "wrong_dtype":lambda i,c:i.update(dtype="float32"),
                "wrong_native_scale":lambda i,c:i["profile_calibration"][0].update(scale=.25),
                "wrong_source_zero":lambda i,c:i["source_calibration_dm"][0].update(calibrated_value_at_pixel_zero=0),
                "wrong_source_line":lambda i,c:i.update(source_line_xyxy=[3,4,17,4]),
                "wrong_profile_metadata":lambda i,c:i["profile_metadata"].update(ndim=2),
                "wrong_original_receipt":lambda i,c:i["native_receipt"].update(id="invented"),
                "wrong_payload":lambda i,c:i["native_profile_result"].update(values_base64="AA=="),
                "partial":lambda i,c:c.update(state="capturing"),
                "native_save_claim":lambda i,c:i.update(dm_file_save=True),
                "applied_intensity":lambda i,c:i.update(intensity_calibration_applied=True),
                "wrong_capture_identity":lambda i,c:c.update(capture_id="b"*32),
                "wrong_output_dtype":lambda i,c:c.update(output_dtype="uint32"),
            }
            for label,mutate in mutations.items():
                with self.subTest(label=label):
                    i,c=copy.deepcopy(info),copy.deepcopy(capture);mutate(i,c);self.write_package(root,i,c)
                    with self.assertRaises(ValueError):oracle.verify_package(oracle.Evidence(directory),"capture",result,checked)
            self.write_package(root,info,capture)
            wrong=npy_bytes(np.zeros(checked["values"].shape,dtype="<f8"));(root/"input.npy").write_bytes(wrong)
            i,c=copy.deepcopy(info),copy.deepcopy(capture);i["input_sha256"]=c["input_sha256"]=oracle.sha(wrong);i["pixel_sha256"]=c["pixel_sha256"]=oracle.sha(bytes(checked["values"].nbytes))
            self.write_package(root,i,c)
            with self.assertRaises(ValueError):oracle.verify_package(oracle.Evidence(directory),"capture",result,checked)

    def test_actual_host_binding_precedes_DM_import_and_stop_identity_is_original(self):
        with mock.patch.dict(os.environ, {"DM_NATIVE_SESSION":"a"*32}):
            oracle.validate_actual_host(os.getpid(), "a"*32)
            for pid, session in ((os.getpid()+1000,"a"*32),(os.getpid(),"b"*32),(True,"a"*32)):
                with self.assertRaises(ValueError): oracle.validate_actual_host(pid,session)
        stop = request("STOP",[],"saved-before-stop"); completed = receipt(stop)
        oracle.receipt_identity(completed,stop,"a"*32,1234,(10,11))
        completed["id"] = completed["request_id"] = "invented-later-stop"
        with self.assertRaises(ValueError): oracle.receipt_identity(completed,stop,"a"*32,1234,(10,11))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"manifest.json";path.write_text(json.dumps(dict(host_pid=os.getpid()+1000,session="a"*32)))
            with self.assertRaises(ValueError): oracle.verify_host(str(path))

    def test_stop_uses_original_worker_and_zero_exec_with_full_thread_anchor(self):
        saved=request("STOP",[],"original-pre-saved-stop");completed=receipt(saved)
        # Actual raw STOP records have no facade-only request_id field.
        del completed["request_id"]
        self.assertEqual(oracle.receipt_identity(completed,saved,"a"*32,1234,(10,11)),(0,11))
        wrapped=dict(status="RECORDED_COMPLETED_NATIVE_CALL",request=saved,output=completed)
        self.assertEqual(oracle.receipt_identity(oracle.unpack_result(wrapped,saved),saved,"a"*32,1234,(10,11)),(0,11))
        mutations={
            "wrong_worker":lambda r:r.update(worker_tid=12),
            "zero_worker":lambda r:r.update(worker_tid=0),
            "host_exec_is_not_zero":lambda r:r.update(exec_tid=10),
            "other_nonzero_exec":lambda r:r.update(exec_tid=99),
            "boolean_exec":lambda r:r.update(exec_tid=False),
            "wrong_host_pid":lambda r:r.update(host_pid=4321),
            "invented_original_id":lambda r:r.update(id="posthoc-other-stop"),
            "wrong_original_operation":lambda r:r.update(original_operation="STATUS"),
            "wrong_original_arguments":lambda r:r.update(normalized_args=[101]),
            "false_ipc_ack":lambda r:r.update(result={"ipc_stopped":False}),
            "missing_ipc_ack":lambda r:r.pop("result"),
        }
        for label,mutate in mutations.items():
            with self.subTest(label=label):
                value=copy.deepcopy(completed);mutate(value)
                with self.assertRaises(ValueError):oracle.receipt_identity(value,saved,"a"*32,1234,(10,11))
        with self.assertRaises(ValueError):oracle.receipt_identity(completed,saved,"a"*32,1234)
        # STOP's rule must not loosen STATUS or actual PROFILE host execution.
        for operation,args in (("STATUS",[]),("PROFILE",[77,31,9,4,2,4,17,4,1])):
            original=request(operation,args,"original-"+operation);value=receipt(original)
            oracle.receipt_identity(value,original,"a"*32,1234,(10,11))
            for exec_tid,worker_tid in ((0,11),(12,11),(10,12)):
                with self.subTest(operation=operation,exec_tid=exec_tid,worker_tid=worker_tid):
                    bad=copy.deepcopy(value);bad.update(exec_tid=exec_tid,worker_tid=worker_tid)
                    with self.assertRaises(ValueError):oracle.receipt_identity(bad,original,"a"*32,1234,(10,11))

    def test_full_saved_manifest_wrapper_sources_and_packages_are_file_only(self):
        source,data,saved,result=sample();checked=self.checked(source,data,saved,result)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_package(directory,result,checked)
            fixture=dict(status="RECORDED_SYNTHETIC_LINE_PROFILE_FIXTURE",host_pid=1234,session="a"*32,python_is_listener=False,images={},documents=[])
            for index,label in enumerate(fixed_arrays()):
                observed,values=make_source(label,77+index);name=label+".npy";raw=npy_bytes(values);(root/name).write_bytes(raw)
                observed.update(source_file=name,source_file_sha256=oracle.sha(raw));fixture["images"][label]=observed
            status_request=request("STATUS",[],"original-status")
            status=dict(backend="digitalmicrograph-native",ready=True,binary_gate=True,compatibility=dict(state="SUPPORTED"),host_pid=1234,host_thread=10,native_receipt=receipt(status_request))
            manifest=dict(schema=1,host_pid=1234,session="a"*32,fixture_file="fixture.json",status_request_file="status-request.json",status_result_file="status-result.json",
                          cases=[dict(label="horizontal-plane",source_label="float_plane",request_file="profile-request.json",result_file="profile-result.json",capture_directory="capture")])
            for name,value in (("fixture.json",fixture),("status-request.json",status_request),("status-result.json",dict(status="RECORDED_COMPLETED_NATIVE_CALL",request=status_request,output=status)),
                               ("profile-request.json",saved),("profile-result.json",dict(status="RECORDED_COMPLETED_NATIVE_CALL",request=saved,output=result)),("manifest.json",manifest)):
                (root/name).write_text(json.dumps(value,allow_nan=False),encoding="utf-8")
            report=oracle.verify_files(str(root/"manifest.json"))
            self.assertEqual(report["status"],"PASS_LINE_PROFILE_SAVED_FILES")
            self.assertIn("NOT_FRESH_HOST",report["scope"])
            original=(root/"float_nonlinear.npy").read_bytes();(root/"float_nonlinear.npy").write_bytes(original[:-1]+bytes([original[-1]^1]))
            with self.assertRaises(ValueError):oracle.verify_files(str(root/"manifest.json"))

    def test_post_return_fixture_baseline_is_strict_about_actual_host_and_line_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);session="a"*32
            fixture=dict(status="RECORDED_SYNTHETIC_LINE_PROFILE_FIXTURE",host_pid=os.getpid(),session=session,python_is_listener=False,images={},documents=[])
            observations={};images={}
            for index,(label,values) in enumerate(fixed_arrays().items()):
                source,values=make_source(label,77+index);name=label+".npy";raw=npy_bytes(values);(root/name).write_bytes(raw)
                observations[source["id"]]=copy.deepcopy(source)
                source.update(source_file=name,source_file_sha256=oracle.sha(raw));fixture["images"][label]=source
                image=mock.Mock();image.GetNumArray.return_value=values;images[source["id"]]=image
            path=root/"fixture.json";path.write_text(json.dumps(fixture),encoding="utf-8")
            fake_DM=mock.Mock();fake_DM.FindImageByID.side_effect=lambda identifier:images[identifier]
            reverse={id(image):identifier for identifier,image in images.items()}
            observe=lambda dm,image:copy.deepcopy(observations[reverse[id(image)]])
            with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":session}),mock.patch.dict(sys.modules,{"DigitalMicrograph":fake_DM}), \
                 mock.patch.object(oracle,"all_documents",return_value=[]),mock.patch.object(oracle,"image_observation",side_effect=observe):
                report=oracle.verify_fixture_baseline(str(path));self.assertEqual(report["status"],"PASS_LINE_PROFILE_FIXTURE_BASELINE")
                self.assertEqual(report["native_operations_submitted"],0)
                observations[77]["displays"][0]["rois"][0]["raw_line_xyxy"]=[3,4,18,4]
                with self.assertRaisesRegex(ValueError,"GUI geometry differs before MCP"):oracle.verify_fixture_baseline(str(path))
                fixture["host_pid"]+=1000;path.write_text(json.dumps(fixture),encoding="utf-8")
                fake_DM.FindImageByID.reset_mock()
                with self.assertRaisesRegex(ValueError,"actual prepared host PID/session"):oracle.verify_fixture_baseline(str(path))
                fake_DM.FindImageByID.assert_not_called()


if __name__ == "__main__": unittest.main()
