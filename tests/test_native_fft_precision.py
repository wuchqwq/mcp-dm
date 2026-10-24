"""Synthetic evidence tests only: no DM imports or host-qualification claim."""
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


def load(name):
    spec = importlib.util.spec_from_file_location(name, str(MVP / (name + ".py")))
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    return module


fixture_module = load("fft_precision_fixture")
verifier = load("verify_fft_precision")


class PrecisionEvidenceTests(unittest.TestCase):
    def package(self, directory):
        def save(label, values):
            name = label + ".npy"; path = Path(directory) / name
            with path.open("xb") as output: np.save(output, values, allow_pickle=False)
            return dict(file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), dtype=str(values.dtype), shape=list(values.shape))
        def receipt(op, args, index):
            return dict(id="fixed-" + str(index), request_id="fixed-" + str(index), state="completed", session="a" * 32, host_pid=1234,
                        exec_tid=10, worker_tid=11, original_operation=op, normalized_args=args,
                        result_type="native_data_snapshot" if op == "READ" else "native_fourier_operation", result_version=1 if op == "READ" else 2)
        f = dict(schema=1, status="RECORDED_SYNTHETIC_FIXTURE", policy=fixture_module.POLICY, host_pid=1234, session="a" * 32,
                 images={}, document_count_before=2, document_count_after=9, python_is_listener=False)
        o = dict(schema=1, status="RECORDED_SAME_HOST_PRECISION_COMPARISON", policy=fixture_module.POLICY, host_pid=1234, session="a" * 32,
                 source_pixels_unchanged=True, python_is_listener=False, cases={}, owned_direct_image_ids=[], document_count=21)
        for index, (label, values) in enumerate(fixture_module.arrays().items()):
            source_id = index + 1; fft_id = 100 + index * 3; inverse_id = fft_id + 1; real_id = fft_id + 2
            f["images"][label] = dict(save("source-" + label, values), id=source_id)
            spectrum = (np.fft.fftshift(np.fft.ifft2(values.astype(np.float32).astype(np.float64))) * values.size).astype(np.complex64)
            inverse = (np.fft.fft2(np.fft.ifftshift(spectrum.astype(np.complex128))) / values.size).astype(np.complex64)
            real = inverse.real.copy(order="C")
            row = dict(source_id=source_id, native={}, snapshots={}, direct_ids={})
            for kind, op, args, image_id, a in (("fft", "FFT", [source_id], fft_id, spectrum), ("ifft", "IFFT", [fft_id], inverse_id, inverse),
                                                ("real", "REAL", [inverse_id], real_id, real)):
                row["native"][kind] = dict(native_receipt=receipt(op, args, index * 4 + len(row["native"])), image_id=image_id,
                                           source_image_id=args[0], computation="DM native", image=dict(id=image_id, dtype=str(a.dtype), shape=list(a.shape)))
                row["snapshots"]["bridge_" + kind] = save(label + "-bridge-" + kind, a)
            row["native"]["read"] = dict(native_receipt=receipt("READ", [real_id, 0, 0, values.shape[1], values.shape[0]], index * 4 + 3),
                                          source_image_id=real_id, requested_rect=[0, 0, values.shape[1], values.shape[0]], effective_rect=[0, 0, values.shape[1], values.shape[0]],
                                          shape=list(values.shape), dtype="float32", byte_order="little", array_order="C", values_base64=base64.b64encode(real.tobytes()).decode("ascii"))
            for kind, a in (("fft", spectrum), ("ifft", inverse)):
                direct_id = 200 + len(o["owned_direct_image_ids"]); o["owned_direct_image_ids"].append(direct_id)
                row["direct_ids"][kind] = direct_id; row["snapshots"]["direct_" + kind] = save(label + "-direct-" + kind, a)
            o["cases"][label] = row
        self.write(directory, f, o)
        return f, o

    def write(self, directory, fixture, observation):
        for name, value in (("fixture.json", fixture), ("observation.json", observation)):
            (Path(directory) / name).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")

    def test_equivalence_does_not_erase_predeclared_numerical_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            self.package(directory); report = verifier.verify(directory, 1234, "a" * 32)
            self.assertEqual(report["direct_equivalence"], "PASS_BITWISE_ALL_CASES")
            self.assertEqual(report["status"], "FAIL_NUMERICAL_TOLERANCE")
            self.assertEqual(report["policy"]["inverse_max_absolute_error"], .5)
            self.assertEqual(report["cases"]["medium_uint32"]["uint32_to_float32_max_absolute_error"], 0)
            self.assertGreater(report["cases"]["high_uint32"]["uint32_to_float32_max_absolute_error"], .5)

    def test_independent_counterexamples_never_pass(self):
        mutations = {
            "wrong_host": lambda f, o: o.update(host_pid=9876),
            "wrong_session": lambda f, o: o.update(session="b" * 32),
            "relaxed_tolerance": lambda f, o: o["policy"].update(inverse_max_absolute_error=10000),
            "source_modified": lambda f, o: o.update(source_pixels_unchanged=False),
            "missing_case": lambda f, o: o["cases"].pop("high_float32"),
            "wrong_operation": lambda f, o: o["cases"]["low_uint32"]["native"]["ifft"]["native_receipt"].update(original_operation="FFT"),
            "wrong_parent": lambda f, o: o["cases"]["low_uint32"]["native"]["ifft"]["native_receipt"].update(normalized_args=[999]),
            "wrong_thread": lambda f, o: o["cases"]["high_uint32"]["native"]["fft"]["native_receipt"].update(exec_tid=20),
            "same_host_worker_thread": lambda f, o: [result["native_receipt"].update(worker_tid=result["native_receipt"]["exec_tid"]) for row in o["cases"].values() for result in row["native"].values()],
            "wrong_read_dtype": lambda f, o: o["cases"]["low_uint32"]["native"]["read"].update(dtype="uint32"),
            "wrong_read_bytes": lambda f, o: o["cases"]["low_uint32"]["native"]["read"].update(values_base64=base64.b64encode(b"\0" * 256).decode("ascii")),
            "invalid_base64": lambda f, o: o["cases"]["low_uint32"]["native"]["read"].update(values_base64="%%%"),
            "wrong_docs": lambda f, o: o.update(document_count=22),
            "direct_aliases_bridge": lambda f, o: o["cases"]["low_uint32"]["direct_ids"].update(fft=100),
            "claimed_direct_not_owned": lambda f, o: o.update(owned_direct_image_ids=[]),
            "nonfinite_metadata": lambda f, o: o["policy"].update(inverse_max_absolute_error=None),
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture, observation = self.package(directory)
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    f, o = copy.deepcopy(fixture), copy.deepcopy(observation); mutate(f, o); self.write(directory, f, o)
                    with self.assertRaises((ValueError, KeyError, TypeError)): verifier.verify(directory, 1234, "a" * 32)

    def test_rehashed_but_wrong_direct_values_and_component_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            f, o = self.package(directory)
            for key in ("direct_fft", "direct_ifft", "bridge_real"):
                with self.subTest(key=key):
                    entry = o["cases"]["medium_uint32"]["snapshots"][key]; path = Path(directory) / entry["file"]
                    original = path.read_bytes(); a = np.load(str(path), allow_pickle=False); a[1, 2] += 32
                    with path.open("wb") as output: np.save(output, a, allow_pickle=False)
                    old_hash = entry["sha256"]; entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest(); self.write(directory, f, o)
                    with self.assertRaises(ValueError): verifier.verify(directory)
                    path.write_bytes(original); entry["sha256"] = old_hash

    def test_no_observed_convention_search(self):
        a = fixture_module.arrays()["low_uint32"]
        wrong_sign = np.fft.fftshift(np.fft.fft2(a.astype(np.float64))).astype(np.complex64)
        inverse = a.astype(np.complex64); real = a.astype(np.float32)
        terms = verifier.error_terms(a, wrong_sign, inverse, real)
        self.assertEqual(terms["forward_tolerance"], "FAIL")
        with self.assertRaises(ValueError): verifier.error_terms(a, wrong_sign.astype(np.complex128), inverse, real)
        bad = inverse.copy(); bad[0, 0] = complex(float("nan"), 0)
        with self.assertRaises(ValueError): verifier.error_terms(a, wrong_sign, bad, real)

    def test_actual_process_and_environment_session_precede_DM_import(self):
        # Importing this acceptance helper does not import DigitalMicrograph.
        sys.path.insert(0, str(MVP))
        try: observer = load("observe_fft_precision")
        finally: sys.path.pop(0)
        with mock.patch.dict(os.environ, {"DM_NATIVE_SESSION": "a" * 32}):
            observer.validate_host_identity("a" * 32, os.getpid())
            for session, pid in (("a" * 32, os.getpid() + 1000), ("b" * 32, os.getpid()), ("a" * 32, True)):
                with self.subTest(session=session, pid=pid):
                    with self.assertRaises(RuntimeError): observer.create("unopened-output", session, pid)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError): observer.validate_host_identity("a" * 32, os.getpid())

    def test_claimed_huge_shape_is_rejected_before_numpy_load(self):
        with tempfile.TemporaryDirectory() as directory:
            stream = io.BytesIO()
            np.lib.format.write_array_header_1_0(stream, {
                "shape": (2 ** 40, 2 ** 40), "fortran_order": False, "descr": "<f4"})
            raw = stream.getvalue(); name = "malformed.npy"
            (Path(directory) / name).write_bytes(raw)
            descriptor = {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "dtype": "float32", "shape": [8, 8]}
            with mock.patch.object(np, "load", side_effect=AssertionError("must validate header before allocation")) as load:
                with self.assertRaisesRegex(ValueError, "header differs"):
                    verifier.read_array(directory, descriptor, "float32", [8, 8])
                load.assert_not_called()


if __name__ == "__main__": unittest.main()
