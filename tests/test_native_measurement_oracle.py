"""Independent scientific/lifetime counterexamples, not live DM acceptance."""
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MVP = ROOT / "experiments" / "native-bridge" / "mvp"
sys.path.insert(0, str(MVP))
try:
    spec = importlib.util.spec_from_file_location("measurement_oracle_for_tests", str(MVP / "verify_native_measurements.py"))
    oracle = importlib.util.module_from_spec(spec); spec.loader.exec_module(oracle)
    from create_measurement_fixture import fixed_arrays, source_intensity
finally: sys.path.pop(0)


def request(op, args, identifier="original-histogram"):
    return dict(protocol="NB2", session="a" * 32, host_pid=1234, id=identifier, op=op, args=args,
                wire="NB2 " + "a" * 32 + " " + identifier + " " + op + "".join(" " + str(v) for v in args) + "\n")


def receipt(saved):
    result = dict(protocol="NB2", session=saved["session"], host_pid=saved["host_pid"], id=saved["id"], request_id=saved["id"],
                  state="completed", original_operation=saved["op"], normalized_args=saved["args"], result_type=oracle.TYPES[saved["op"]],
                  result_version=2 if saved["op"] == "ROIS" else 1, exec_tid=0 if saved["op"] == "STOP" else 10, worker_tid=11,
                  timings_us=dict(queue=1, execute=2))
    if saved["op"] == "STOP": result["result"] = dict(ipc_stopped=True)
    return result


def source_record(label="float_edges", identifier=77):
    values = fixed_arrays()[label]
    scale = -.25 if label == "float_edges" else .25
    return dict(id=identifier, name="SYNTHETIC_" + label, dtype=str(values.dtype), shape=list(values.shape),
                pixel_sha256=oracle.sha(values.tobytes()), displays=[],
                calibration=[dict(dm_axis=d, origin=zero, raw_origin=-zero / scale, scale=scale, unit="nm") for d, zero in enumerate((1.25, -2.5))],
                intensity_calibration=source_intensity(label)), values


def source_metadata(source):
    unsigned = source["dtype"] == "uint32"
    return dict(id=source["id"], name=source["name"], dtype=source["dtype"], data_type_code=11 if unsigned else 2,
                is_integer=unsigned, is_unsigned=unsigned, ndim=2, shape=source["shape"], dm_dimensions=source["shape"][::-1],
                pixels=int(np.prod(source["shape"])), shape_order="numpy (last axis is X)", packing_style=1,
                native_mean_supported=True, native_summary_supported=True, calibration_complete=True,
                coordinate_rule="physical(i)=calibrated_value_at_pixel_zero+i*scale",
                calibration=[dict(dm_dimension=d, numpy_axis=1-d, size=source["shape"][1-d], origin=axis["raw_origin"],
                                  calibrated_value_at_pixel_zero=axis["origin"], scale=axis["scale"], unit=axis["unit"], usable=True, issue=None)
                             for d, axis in enumerate(source["calibration"])])


def float_bits(value): return struct.unpack("<I", struct.pack("<f", value))[0]


def sample(bins=8, label="float_edges", bounds=(-2,2)):
    source, values = source_record(label)
    saved = request("HISTOGRAM", [77, bins, float_bits(bounds[0]), float_bits(bounds[1])])
    expected, edges, requested = oracle.expected_histogram(values, saved["args"])
    axis = dict(dm_dimension=0, numpy_axis=0, size=bins, origin=0, calibrated_value_at_pixel_zero=0,
                scale=1, unit=None, usable=False, issue="unknown_units")
    image = dict(id=101, name="SYNTHETIC_NATIVE_HISTOGRAM", ndim=1, dtype="uint32", data_type_code=11, is_integer=True, is_unsigned=True,
                 shape=[bins], dm_dimensions=[bins], pixels=bins, packing_style=1, shape_order="one-dimensional native histogram bins",
                 calibration=[axis], calibration_complete=False, native_mean_supported=False, native_summary_supported=False,
                 coordinate_rule="physical(i)=calibrated_value_at_pixel_zero+i*scale")
    result = dict(backend="digitalmicrograph-native", operation="HISTOGRAM", source_image_id=77, image_id=101, source=source_metadata(source), image=image,
                  source_min=float(values.min()), source_max=float(values.max()), source_pixels=values.size, requested_range=requested, range_covers_source=True, bins=bins,
                  bin_width=(requested[1]-requested[0]) / bins, bin_left_edge=requested[0], binning="uniform linear bins over the caller range; the range must cover the complete native source minimum/maximum",
                  bin_edge_rule="left edge at range_min, width = (max-min)/bins", counts_sum=values.size, counts_complete=True, shape=[bins], dtype="uint32",
                  axes=["intensity_bin"], counts_encoding="exact uint32 counts little-endian binary64 payload",
                  values_base64=base64.b64encode(expected.astype("<f8").tobytes()).decode("ascii"), raw_bytes=bins*8, output_bytes=bins*4,
                  axis_mode="bin_index", axis_calibration_is_bin_left_edge=False, source_intensity_calibration=source["intensity_calibration"],
                  operator="GMSImageProcessing::CalcHistogram", computation="DM native", intensity_calibration_applied=False,
                  intensity_semantics="raw pixel intensity counts per bin", source_write_requested=False, snapshot_atomic=False,
                  ownership="plugin retained strong reference until normal native STOP/cleanup; shown document may retain image",
                  retention=dict(token=9001, creation_request_id=saved["id"], state_at_creation="plugin_retained",
                                 identity_scope="bridge token in this native session, not a host image ID"), native_receipt=receipt(saved))
    return source, values, saved, result


def intensity_axis_sample(bins=8, bounds=(-15.5,6.875)):
    source,values,saved,result=sample(bins,"float_identity",bounds)
    plan=oracle.histogram_axis_plan(result["requested_range"],bins)
    result["image"]["calibration"][0].update(origin=plan["raw_origin"],calibrated_value_at_pixel_zero=plan["zero_observed"],
        scale=plan["scale_observed"],unit="arb",usable=True,issue=None)
    result["image"]["calibration_complete"]=True
    result.update(axis_mode="source_intensity_units",axis_calibration_is_bin_left_edge=True,
        axis_zero_requested=plan["zero_requested"],axis_zero_observed=plan["zero_observed"],axis_scale_observed=plan["scale_observed"],
        axis_roundtrip_error=plan["roundtrip_error"],axis_roundtrip_bound=plan["roundtrip_bound"],axis_max_coordinate_error=plan["max_coordinate_error"],
        axis_tolerance="binary32_local_ulp_v1",axis_unavailable_reason=None)
    return source,values,saved,result


def show_sample(creation):
    saved = request("SHOW", [creation["image_id"]], "original-show")
    result = dict(backend="digitalmicrograph-native", image_id=creation["image_id"], delivery="visible_dm_document", document_visible=True,
                  rank=1, display_family="native_1d_image_document", display_class="host_selected", retained_operation=creation["operation"],
                  one_dimensional_display=copy.deepcopy(creation["image"]), operator="ImageGetOrCreateImageDocument + ImageDocumentShow",
                  source_write_requested=False, snapshot_atomic=False, file_saved=False, model_visual_verification=False, native_receipt=receipt(saved))
    return saved, result


def npy_bytes(values):
    output = io.BytesIO(); np.save(output, values, allow_pickle=False); return output.getvalue()


class NativeMeasurementOracleTests(unittest.TestCase):
    def checked(self, source, data, saved, result):
        return oracle.verify_histogram_payload(result, saved, source, data, "a"*32, 1234, (10,11))

    def test_independent_hand_counts_and_bins_above_source_pixels(self):
        # Hand-counted, including exact min/max and interior half-unit edges.
        self.assertEqual(self.checked(*sample())["values"].tolist(), [3,2,3,2,3,3,3,5])
        for bins in (2, 64, 4096):
            with self.subTest(bins=bins):
                checked = self.checked(*sample(bins))
                self.assertEqual(checked["values"].shape, (bins,))
                self.assertEqual(checked["values"].dtype, np.dtype("<u4"))
                self.assertEqual(int(checked["values"].sum()),24)
                self.assertEqual(len(checked["raw"]), bins*4)
                self.assertEqual(len(checked["wire_raw"]), bins*8)
                self.assertEqual(int(checked["values"][-1]), 3 if bins > 8 else 14)

    def test_identity_axis_known_native_roundtrip_and_positive_negative_caller_edges(self):
        # Predeclared bit-level constants independently agree with the reported
        # pinned-host divide/multiply example; not read out of a result payload.
        plan=oracle.histogram_axis_plan([-15.5,6.875],8)
        self.assertEqual(plan["raw_origin"],5.54189920425415)
        self.assertEqual(plan["zero_observed"],-15.499999046325684)
        self.assertEqual(plan["roundtrip_error"],9.5367431640625e-07)
        self.assertEqual(plan["roundtrip_bound"],2.2873282432556152e-06)
        self.assertEqual(oracle.local_binary32_ulp(0),2.**-149)
        self.assertEqual(oracle.local_binary32_ulp(-1),2.**-23)
        for bins,bounds in ((8,(-15.5,6.875)),(7,(.1,4.5)),(17,(-.3,4.5)),(64,(0,4.5))):
            with self.subTest(bins=bins,bounds=bounds):
                checked=self.checked(*intensity_axis_sample(bins,bounds))
                self.assertEqual(checked["axis_checked"]["mode"],"source_intensity_units")
                self.assertEqual(int(checked["values"].sum()),24)

    def test_forged_physical_axis_nonidentity_units_and_relaxed_tolerances_cannot_pass(self):
        source,data,saved,result=intensity_axis_sample()
        changes=[lambda r:r.update(axis_zero_requested=-15.5001),lambda r:r.update(axis_zero_observed=-15.5),
                 lambda r:r.update(axis_roundtrip_error=0),lambda r:r.update(axis_roundtrip_bound=r["axis_roundtrip_bound"]*8),
                 lambda r:r.update(axis_max_coordinate_error=r["axis_max_coordinate_error"]*2),lambda r:r.update(axis_tolerance="anything binary32 permissive"),
                 lambda r:r.update(axis_tolerance="binary32 divide/multiply round trip: 8 ulp of max(|origin|,|scale|,1)"),
                 lambda r:r.pop("axis_roundtrip_bound"),lambda r:r.update(axis_unavailable_reason="made_up"),
                 lambda r:r["image"]["calibration"][0].update(origin=-15.5),lambda r:r["image"]["calibration"][0].update(unit="nm"),
                 lambda r:r["image"]["calibration"][0].update(calibrated_value_at_pixel_zero=-15.5)]
        for change in changes:
            bad=copy.deepcopy(result);change(bad)
            with self.assertRaises(ValueError):self.checked(source,data,saved,bad)
        # Self-consistent observed metadata still cannot substitute another
        # float32 value merely because it falls inside the published bound.
        bad=copy.deepcopy(result);bad["axis_zero_observed"]=-15.5;bad["axis_roundtrip_error"]=0
        bad["image"]["calibration"][0]["calibrated_value_at_pixel_zero"]=-15.5
        with self.assertRaises(ValueError):self.checked(source,data,saved,bad)
        nonidentity=copy.deepcopy(source);nonidentity["intensity_calibration"]=dict(origin=7.5,scale=-2,unit="arb")
        bad=copy.deepcopy(result);bad["source_intensity_calibration"]=nonidentity["intensity_calibration"]
        with self.assertRaisesRegex(ValueError,"nonidentity"):self.checked(nonidentity,data,saved,bad)

    def test_style_is_presentation_only_and_requires_independent_getter_for_a_success_claim(self):
        creation=sample()[-1];saved,result=show_sample(creation)
        result.update(display_style="histogram",display_style_scope=oracle.STYLE_SCOPE)
        oracle.verify_show_payload(result,saved,creation,"a"*32,1234,(10,11))
        display=mock.Mock();fake_DM=mock.Mock();fake_DM.LinePlotImageDisplayGetHistogramStyle.return_value=True
        observed=oracle.observe_show_style(fake_DM,display,result)
        self.assertEqual(observed["status"],"PASS_INDEPENDENT_STYLE_GETTER")
        fake_DM.LinePlotImageDisplayGetHistogramStyle.return_value=False
        with self.assertRaises(ValueError):oracle.observe_show_style(fake_DM,display,result)
        with self.assertRaisesRegex(ValueError,"UNVERIFIED"):oracle.observe_show_style(object(),display,result)
        for change in (lambda r:r.update(display_style="bars-ish"),lambda r:r.update(display_style_scope="scientific calibrated intensity"),
                       lambda r:r.update(display_style_reason="unnecessary fallback"),lambda r:r.update(display_style="default"),
                       lambda r:r.update(display_style="default",display_style_reason="unknown_reason")):
            bad=copy.deepcopy(result);change(bad)
            with self.assertRaises(ValueError):oracle.verify_show_payload(bad,saved,creation,"a"*32,1234,(10,11))
        result.update(display_style="default",display_style_reason="style_entrypoints_unavailable")
        fake_DM.LinePlotImageDisplayGetHistogramStyle.reset_mock()
        self.assertEqual(oracle.observe_show_style(fake_DM,display,result)["current_flag"],"NOT_INFERRED")
        fake_DM.LinePlotImageDisplayGetHistogramStyle.assert_not_called()

    def test_show_cannot_change_frozen_histogram_axis_context(self):
        source,data,original,creation=intensity_axis_sample();saved,result=show_sample(creation)
        result["histogram_axis_context"]=oracle.histogram_axis_context(creation)
        oracle.verify_show_payload(result,saved,creation,"a"*32,1234,(10,11))
        for change in (lambda r:r.pop("histogram_axis_context"),lambda r:r["histogram_axis_context"].update(axis_tolerance="loose"),
                       lambda r:r["histogram_axis_context"].update(axis_zero_requested=-15.5+1),
                       lambda r:r["histogram_axis_context"]["source_intensity_calibration"].update(scale=-2)):
            bad=copy.deepcopy(result);change(bad)
            with self.assertRaises(ValueError):oracle.verify_show_payload(bad,saved,creation,"a"*32,1234,(10,11))

    def test_historical_index_and_explicit_new_unavailable_axis_remain_distinct(self):
        source,data,saved,result=sample()
        # PR8 has no axis numeric diagnostics. The historical PR9 index reply
        # had four zero placeholders; neither claims physical calibration.
        self.checked(source,data,saved,result)
        legacy=copy.deepcopy(result);legacy.update({key:0 for key in oracle.AXIS_NUMBERS[:4]})
        legacy["axis_tolerance"]=oracle.LEGACY_AXIS_POLICY
        self.checked(source,data,saved,legacy)
        modern=copy.deepcopy(result);modern.update({key:None for key in oracle.AXIS_NUMBERS})
        modern.update(axis_tolerance="binary32_local_ulp_v1",axis_unavailable_reason="source_intensity_calibration_not_identity")
        self.checked(source,data,saved,modern)
        for change in (lambda r:r.update(axis_zero_requested=0),lambda r:r.pop("axis_roundtrip_bound"),
                       lambda r:r.update(axis_tolerance="loose binary32"),lambda r:r.update(axis_unavailable_reason="unknown_reason"),
                       lambda r:r.update(axis_unavailable_reason="axis_entrypoint_unavailable")):
            bad=copy.deepcopy(modern);change(bad)
            with self.assertRaises(ValueError):self.checked(source,data,saved,bad)
        saved_show,shown=show_sample(modern)
        with self.assertRaises(ValueError):oracle.verify_show_payload(shown,saved_show,modern,"a"*32,1234,(10,11))
        shown["histogram_axis_context"]=oracle.histogram_axis_context(modern)
        shown.update(display_style="default",display_style_scope=oracle.STYLE_SCOPE,display_style_reason="style_not_qualified")
        oracle.verify_show_payload(shown,saved_show,modern,"a"*32,1234,(10,11))
        with self.assertRaises(ValueError):oracle.histogram_axis_plan([1e-44,2e-44],4096)

    def test_host_request_dtype_axis_range_count_and_encoding_counterexamples(self):
        mutations = {
            "wrong_pid": lambda r:r["native_receipt"].update(host_pid=4321),
            "wrong_session": lambda r:r["native_receipt"].update(session="b"*32),
            "wrong_id": lambda r:r["native_receipt"].update(id="invented-after"),
            "wrong_original_args": lambda r:r["native_receipt"].update(normalized_args=[77,8,0,1]),
            "wrong_original_op": lambda r:r["native_receipt"].update(original_operation="PROFILE"),
            "wrong_result_type": lambda r:r["native_receipt"].update(result_type="native_line_profile"),
            "wrong_thread": lambda r:r["native_receipt"].update(worker_tid=10),
            "zero_output": lambda r:r.update(image_id=0),
            "source_alias": lambda r:r.update(image_id=77),
            "wrong_source": lambda r:r.update(source_image_id=78),
            "wrong_source_calibration": lambda r:r["source"]["calibration"][0].update(scale=.25),
            "wrong_retention": lambda r:r["retention"].update(creation_request_id="other"),
            "zero_token": lambda r:r["retention"].update(token=0),
            "wire_as_native_dtype": lambda r:r.update(dtype="float64"),
            "float64_native_image": lambda r:r["image"].update(dtype="float64",data_type_code=12),
            "row_raster": lambda r:r["image"].update(ndim=2,shape=[1,8]),
            "invented_axis": lambda r:r.update(axis_mode="raw_intensity"),
            "calibrated_histogram": lambda r:r["image"].update(calibration_complete=True),
            "wrong_axis_origin": lambda r:r["image"]["calibration"][0].update(origin=1),
            "wrong_bin_left": lambda r:r.update(bin_left_edge=-1.5),
            "wrong_width": lambda r:r.update(bin_width=1),
            "wrong_range": lambda r:r.update(requested_range=[-3,3]),
            "source_extrema": lambda r:r.update(source_max=1.75),
            "wrong_total": lambda r:r.update(counts_sum=23),
            "incomplete": lambda r:r.update(counts_complete=False),
            "wire_byte_confusion": lambda r:r.update(raw_bytes=32),
            "storage_byte_confusion": lambda r:r.update(output_bytes=64),
            "noncanonical_base64": lambda r:r.update(values_base64=r["values_base64"]+"="),
            "wrong_intensity": lambda r:r.update(intensity_calibration_applied=True),
            "wrong_source_intensity": lambda r:r["source_intensity_calibration"].update(scale=2),
        }
        source,data,saved,result = sample()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value=copy.deepcopy(result);mutate(value)
                with self.assertRaises((ValueError,TypeError)): self.checked(source,data,saved,value)
        for bad in (-1, .5, float("nan"), float("inf"), 25):
            with self.subTest(count=bad):
                value=copy.deepcopy(result);counts=np.array([3,2,3,2,3,3,3,5],dtype="<f8");counts[0]=bad
                value["values_base64"]=base64.b64encode(counts.tobytes()).decode("ascii")
                with self.assertRaises(ValueError):self.checked(source,data,saved,value)
        # A different distribution with an unchanged total is also a FAIL.
        changed=copy.deepcopy(result);counts=np.array([2,3,3,2,3,3,3,5],dtype="<f8")
        changed["values_base64"]=base64.b64encode(counts.tobytes()).decode("ascii")
        with self.assertRaises(ValueError):self.checked(source,data,saved,changed)

    def test_show_retains_exact_native_image_and_true_rank(self):
        creation=sample()[-1];saved,result=show_sample(creation)
        oracle.verify_show_payload(result,saved,creation,"a"*32,1234,(10,11))
        mutations=[lambda r:r.update(image_id=102),lambda r:r.update(rank=2),lambda r:r.update(display_class="LinePlotImageDisplay"),
                   lambda r:r.update(retained_operation="PROFILE"),lambda r:r.update(image=creation["image"]),lambda r:r.update(file_saved=True),
                   lambda r:r.update(model_visual_verification=True),lambda r:r["one_dimensional_display"].update(dtype="float64"),
                   lambda r:r["one_dimensional_display"]["calibration"][0].update(scale=.5)]
        for change in mutations:
            value=copy.deepcopy(result);change(value)
            with self.assertRaises(ValueError):oracle.verify_show_payload(value,saved,creation,"a"*32,1234,(10,11))

    def test_document_inventory_is_exact_not_newest_window_or_count_only(self):
        original=[dict(document_id=1,image_ids=[77],lookup_signature="fixed-original")]
        shown=dict(document_id=2,image_ids=[101],lookup_signature="fixed-shown")
        self.assertEqual(oracle.verify_document_inventory(original+[shown],original,{101}),{101:shown})
        for docs in (original,original+[dict(shown,image_ids=[102])],original+[shown,dict(shown,document_id=3)],
                     [dict(original[0],lookup_signature="changed"),shown],original+[dict(shown,image_ids=[101,77])]):
            with self.subTest(docs=docs):
                with self.assertRaises(ValueError):oracle.verify_document_inventory(docs,original,{101})

    def test_npy_native_dtype_rank_and_uint32_high_bits_are_not_float_storage(self):
        values=np.array([0,16777217,2147483648,4294967295],dtype="<u4")
        oracle.verify_native_npy(npy_bytes(values),values)
        for bad in (values.astype("<f8"),values.reshape(1,4),values.astype("<f4"),values[::-1]):
            with self.assertRaises(ValueError):oracle.verify_native_npy(npy_bytes(bad),values)
        with self.assertRaises(ValueError):oracle.verify_native_npy(npy_bytes(values)+b"trailing",values)

    def test_histogram_real_encoder_independent_package_and_coherent_wrong_sidecars(self):
        source,data,saved,result=sample(64);checked=self.checked(source,data,saved,result)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);snapshot=root/"snapshot.json";snapshot.write_text(json.dumps(result),encoding="utf-8")
            command=["node",str(ROOT/"tools"/"native_snapshot_handoff.mjs"),"--workspace",directory,"--output","capture","--request-id","histogram-export","--snapshot",str(snapshot)]
            execution=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(execution.returncode,0,execution.stdout+execution.stderr)
            oracle.verify_histogram_package(oracle.Evidence(directory),"capture",result,checked)
            capture=root/"capture";original_info=json.loads((capture/"input.json").read_text());original_manifest=json.loads((capture/"capture.json").read_text())
            changes=[lambda i:i.update(dtype="float64"),lambda i:i.update(wire_scalar_dtype="uint32"),lambda i:i.update(raw_bytes=512),
                     lambda i:i.update(native_storage_bytes=512),lambda i:i.update(wire_raw_bytes=256),lambda i:i.update(axes=["intensity"]),
                     lambda i:i.update(bin_left_edge=0),lambda i:i.update(bin_width=1),lambda i:i.update(requested_range=[0,4]),
                     lambda i:i.update(calibration_complete=True),lambda i:i.update(intensity_calibration_applied=True),
                     lambda i:i["native_receipt"].update(host_pid=4321),lambda i:i["source_calibration_dm"][0].update(scale=.25)]
            for index,change in enumerate(changes):
                with self.subTest(index=index):
                    info=copy.deepcopy(original_info);change(info)
                    (capture/"input.json").write_text(json.dumps(info),encoding="utf-8")
                    manifest=copy.deepcopy(original_manifest);manifest["input_metadata_sha256"]=oracle.sha(oracle.canonical(info));manifest["input_metadata_file_sha256"]=oracle.sha((capture/"input.json").read_bytes())
                    (capture/"capture.json").write_text(json.dumps(manifest),encoding="utf-8")
                    with self.assertRaises(ValueError):oracle.verify_histogram_package(oracle.Evidence(directory),"capture",result,checked)

    def test_identity_axis_real_encoder_preserves_requested_vs_observed_and_exact_bounds(self):
        for bins,bounds in ((8,(-15.5,6.875)),(7,(.1,4.5))):
            with self.subTest(bounds=bounds),tempfile.TemporaryDirectory() as directory:
                source,data,saved,result=intensity_axis_sample(bins,bounds);checked=self.checked(source,data,saved,result)
                root=Path(directory);snapshot=root/"snapshot.json";snapshot.write_text(json.dumps(result),encoding="utf-8")
                process=subprocess.run(["node",str(ROOT/"tools"/"native_snapshot_handoff.mjs"),"--workspace",directory,"--output","capture",
                                        "--request-id","identity-histogram-export","--snapshot",str(snapshot)],capture_output=True,text=True,timeout=30)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)
                oracle.verify_histogram_package(oracle.Evidence(directory),"capture",result,checked)
                target=root/"capture";info=json.loads((target/"input.json").read_text());manifest=json.loads((target/"capture.json").read_text())
                self.assertEqual(info["axes"],["intensity_bin"]);self.assertTrue(info["calibration_complete"])
                for field in oracle.AXIS_NUMBERS+("axis_tolerance","axis_unavailable_reason"):
                    self.assertEqual(info[field],result[field])
                info["axis_roundtrip_bound"]*=8
                (target/"input.json").write_text(json.dumps(info),encoding="utf-8")
                manifest["input_metadata_sha256"]=oracle.sha(oracle.canonical(info));manifest["input_metadata_file_sha256"]=oracle.sha((target/"input.json").read_bytes())
                (target/"capture.json").write_text(json.dumps(manifest),encoding="utf-8")
                with self.assertRaises(ValueError):oracle.verify_histogram_package(oracle.Evidence(directory),"capture",result,checked)

    def test_wrong_actual_host_is_rejected_before_DM_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"manifest.json";path.write_text(json.dumps(dict(host_pid=os.getpid()+1000,session="a"*32)))
            with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":"a"*32}),mock.patch.dict(sys.modules,{"DigitalMicrograph":None}):
                with self.assertRaisesRegex(ValueError,"actual prepared host PID/session"):oracle.verify_measurements(str(path))

    def test_profile_original_wire_requires_canonical_uint32_not_equivalent_float_text(self):
        original=request("PROFILE",[77,3,4,5,0,1,5,1,1],"original-line-profile")
        oracle.request_identity(original,"a"*32,1234,"PROFILE")
        changed=copy.deepcopy(original);changed["args"][4]=0.0
        changed["wire"]=changed["wire"].replace(" 0 "," 0.0 ")
        with self.assertRaisesRegex(ValueError,"Original saved request identity"):oracle.request_identity(changed,"a"*32,1234,"PROFILE")
        changed=copy.deepcopy(original);changed["wire"]=changed["wire"].replace(" 0 "," 0.0 ")
        with self.assertRaisesRegex(ValueError,"saved wire differs"):oracle.request_identity(changed,"a"*32,1234,"PROFILE")

    def test_complete_saved_manifest_binds_fixed_sources_receipts_and_files_without_host_claim(self):
        source,data,saved,result=sample(64)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);snapshot=root/"snapshot.json";snapshot.write_text(json.dumps(result),encoding="utf-8")
            process=subprocess.run(["node",str(ROOT/"tools"/"native_snapshot_handoff.mjs"),"--workspace",directory,"--output","capture",
                                    "--request-id","histogram-export","--snapshot",str(snapshot)],capture_output=True,text=True,timeout=30)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            fixture=dict(schema=1,status="RECORDED_SYNTHETIC_NATIVE_MEASUREMENT_FIXTURE",host_pid=1234,session="a"*32,
                         python_is_listener=False,roi_creation="fixture_API_not_manual_GUI_drawing",images={},documents=[])
            for index,label in enumerate(fixed_arrays()):
                observed,values=source_record(label,77+index);raw=npy_bytes(values);filename=label+".npy";(root/filename).write_bytes(raw)
                observed.update(source_file=filename,source_file_sha256=oracle.sha(raw));fixture["images"][label]=observed
            status_request=request("STATUS",[],"original-status")
            status=dict(backend="digitalmicrograph-native",ready=True,binary_gate=True,compatibility=dict(state="SUPPORTED"),host_pid=1234,host_thread=10,native_receipt=receipt(status_request))
            manifest=dict(schema=1,host_pid=1234,session="a"*32,fixture_file="fixture.json",status_request_file="status-request.json",status_result_file="status-result.json",
                          cases=[dict(label="histogram64",source_label="float_edges",request_file="hist-request.json",result_file="hist-result.json",capture_directory="capture")])
            for filename,value in (("fixture.json",fixture),("status-request.json",status_request),("status-result.json",dict(status="RECORDED_COMPLETED_NATIVE_CALL",request=status_request,output=status)),
                                   ("hist-request.json",saved),("hist-result.json",dict(status="RECORDED_COMPLETED_NATIVE_CALL",request=saved,output=result)),("manifest.json",manifest)):
                (root/filename).write_text(json.dumps(value),encoding="utf-8")
            report=oracle.verify_measurements(str(root/"manifest.json"),"files")
            self.assertEqual(report["status"],"PASS_NATIVE_MEASUREMENT_SAVED_FILES");self.assertIn("NOT_FRESH_HOST",report["scope"])
            bad=copy.deepcopy(saved);bad["id"]="after-the-fact-receipt-id";(root/"hist-request.json").write_text(json.dumps(bad))
            with self.assertRaises(ValueError):oracle.verify_measurements(str(root/"manifest.json"),"files")

    def test_stop_requires_original_saved_id_zero_exec_and_same_worker(self):
        saved=request("STOP",[],"pre-saved-original-stop");completed=receipt(saved)
        oracle.receipt_identity(completed,saved,"a"*32,1234,(10,11))
        for change in (lambda r:r.update(id="invented-later"),lambda r:r.update(exec_tid=10),lambda r:r.update(worker_tid=12),
                       lambda r:r.update(host_pid=4321),lambda r:r.update(result=dict(ipc_stopped=False))):
            value=copy.deepcopy(completed);change(value)
            with self.assertRaises(ValueError):oracle.receipt_identity(value,saved,"a"*32,1234,(10,11))

    def test_manual_baseline_only_accepts_added_ROIs_and_selection_flags(self):
        source,values=source_record()
        old_roi=dict(roi_id=1,selected=True,oracle_kind="line",rotation_degrees=0,raw_line_xyxy=[0,1,5,1])
        source["displays"]=[dict(document_id=3,display_id=4,display_type="raster",rois=[old_roi])]
        current=copy.deepcopy(source);current["displays"][0]["rois"][0]["selected"]=False
        added=dict(roi_id=2,selected=True,oracle_kind="line",rotation_degrees=0,raw_line_xyxy=[5,2,0,2])
        current["displays"][0]["rois"].append(added)
        self.assertEqual(oracle.verify_manual_additions(source,current),[dict(document_id=3,display_id=4,roi=added)])
        # Deliberate user viewport preparation is independent of pixel values
        # and the unchanged source-coordinate geometry of existing ROIs.
        source["displays"][0]["window_content_size"]=[80,80]
        current["displays"][0]["window_content_size"]=[640,480]
        self.assertEqual(oracle.verify_manual_additions(source,current),[dict(document_id=3,display_id=4,roi=added)])
        changes=[lambda r:r.update(pixel_sha256="b"*64),lambda r:r["calibration"][0].update(scale=.25),
                 lambda r:r["intensity_calibration"].update(scale=1),lambda r:r["displays"][0].update(display_id=5),
                 lambda r:r["displays"][0]["rois"][0].update(raw_line_xyxy=[0,0,5,0]),
                 lambda r:r["displays"][0]["rois"].pop(0),lambda r:r["displays"][0]["rois"][-1].update(rotation_degrees=1)]
        for change in changes:
            bad=copy.deepcopy(current);change(bad)
            with self.assertRaises(ValueError):oracle.verify_manual_additions(source,bad)

    def test_independent_idle_observation_distinguishes_document_held_and_final_closed_outputs(self):
        source,data,saved,result=sample();checked=self.checked(source,data,saved,result)
        original_stop=request("STOP",[],"original-pre-submission-stop");original_stop["host_pid"]=os.getpid()
        stop_receipt=receipt(original_stop)
        evidence=mock.Mock();evidence.json.side_effect=lambda name:{"stop-original.json":original_stop,"stop-receipt.json":stop_receipt}[name]
        sources={"float_edges":(source,data)}
        context=dict(manifest=dict(stop_request_file="stop-original.json",stop_result_file="stop-receipt.json"),fixture=dict(documents=[]),sources=sources,
                     evidence=evidence,host_pid=os.getpid(),session="a"*32,threads=(10,11),shown={101},released={101},
                     entries={"histogram":dict(result=result,checked=checked)})
        source_image=mock.Mock();source_image.GetNumArray.return_value=data
        output_image=mock.Mock();output_image.IsValid.return_value=True;output_image.GetID.return_value=101
        output_image.GetNumDimensions.return_value=1;output_image.GetDataType.return_value=11;output_image.GetDimensionSize.return_value=8
        output_image.GetName.return_value=result["image"]["name"];output_image.GetNumArray.return_value=checked["values"].copy()
        output_image.GetDimensionCalibration.return_value=(0.,1.,"")
        output_image.CountImageDisplays.return_value=1
        display=mock.Mock();display.IsValid.return_value=True;display.GetImage.return_value=output_image;display.GetID.return_value=9;display.GetDisplayType.return_value=3
        output_image.GetImageDisplay.return_value=display;output_image.GetImageDisplayInImageDocument.return_value=display
        document=mock.Mock();document.GetWindow.return_value.IsValid.return_value=True
        fake_DM=mock.Mock();fake_DM.FindImageByID.side_effect=lambda identifier:{77:source_image,101:output_image}[identifier]
        fake_DM.GetImageDocumentByID.return_value=document
        documents=[dict(document_id=3,image_ids=[101],name="owned-result")]
        snapshot={key:source[key] for key in oracle.SOURCE_KEYS}
        with tempfile.TemporaryDirectory() as directory:
            manifest=Path(directory)/"manifest.json";manifest.write_text(json.dumps(dict(host_pid=os.getpid(),session="a"*32)))
            with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":"a"*32}),mock.patch.dict(sys.modules,{"DigitalMicrograph":fake_DM}), \
                 mock.patch.object(oracle,"load_context",return_value=context),mock.patch.object(oracle,"all_documents",return_value=documents) as docs, \
                 mock.patch.object(oracle,"image_observation",return_value=snapshot):
                for phase in ("after-release","after-stop"):
                    report=oracle.verify_measurements(str(manifest),phase)
                    self.assertTrue(report["output_observations"][0]["valid"])
                    self.assertEqual(report["output_observations"][0]["displays"][0]["document_id"],3)
                output_image.GetNumArray.return_value=np.zeros(8,dtype="<u4")
                with self.assertRaisesRegex(ValueError,"values/dtype differ"):oracle.verify_measurements(str(manifest),"after-stop")
                output_image.GetNumArray.return_value=checked["values"].copy()
                docs.return_value=[]
                with self.assertRaisesRegex(ValueError,"document set"):oracle.verify_measurements(str(manifest),"after-stop")
                fake_DM.FindImageByID.side_effect=lambda identifier:source_image if identifier==77 else None
                report=oracle.verify_measurements(str(manifest),"after-close")
                self.assertFalse(report["output_observations"][0]["valid"])
                fake_DM.FindImageByID.side_effect=lambda identifier:source_image if identifier==77 else output_image
                with self.assertRaisesRegex(ValueError,"remains valid"):oracle.verify_measurements(str(manifest),"after-close")


if __name__ == "__main__":unittest.main()
