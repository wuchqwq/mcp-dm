"""Offline hand-pattern/negative tests; fabricated evidence is not DM acceptance."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

MVP = Path(__file__).resolve().parents[1] / "experiments" / "native-bridge" / "mvp"
SPEC = importlib.util.spec_from_file_location("operations_math_oracle", str(MVP / "verify_operations_math.py"))
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


def impulse_expectations():
    source = np.zeros((7, 7), dtype=np.float32)
    source[3, 3] = 1
    values = {}
    values[1] = np.zeros_like(source)
    values[1][2:5, 2:5] = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.float32) / 16
    values[2] = np.zeros_like(source)
    root2 = np.float32(2 ** .5)
    values[2][2:5, 2:5] = [[root2, 2, root2], [2, 0, 2], [root2, 2, root2]]
    for opcode, center in ((3, 8), (4, 9)):
        values[opcode] = np.zeros_like(source)
        values[opcode][2:5, 2:5] = -1
        values[opcode][3, 3] = center
    return source, values


class FixedFilterPatterns(unittest.TestCase):
    def test_impulse_coefficients_from_hand_enumeration(self):
        source, expected = impulse_expectations()
        for opcode in (1, 2, 3, 4):
            with self.subTest(opcode=opcode):
                calculated, _ = ORACLE.filter_reference(source, opcode)
                np.testing.assert_array_equal(calculated, expected[opcode])
                self.assertEqual(ORACLE.verify_filter(source, expected[opcode], opcode)["maximum_absolute_error"], 0)

    def test_linear_plane_and_nonconstant_original_border(self):
        source = np.array([[3 * x + 5 * y + 7 for x in range(8)] for y in range(7)], dtype=np.float32)
        magnitude = np.float32(2176 ** .5)  # (-8*3)^2 + (-8*5)^2, hand derived.
        for opcode in (1, 2, 3, 4):
            expected = source.copy() if opcode in (1, 4) else np.zeros_like(source)
            expected[1:-1, 1:-1] = source[1:-1, 1:-1] if opcode in (1, 4) else (magnitude if opcode == 2 else 0)
            calculated, tolerance = ORACLE.filter_reference(source, opcode)
            np.testing.assert_array_equal(calculated, expected)
            self.assertTrue(np.all(tolerance[0] == 0))
            ORACLE.verify_filter(source, expected, opcode)

    def test_wrong_kernel_sobel_sumabs_and_boundary_fail(self):
        source, expected = impulse_expectations()
        wrong = expected[2].copy(); wrong[2, 2] = 2  # sumabs(1,1), not sqrt(2).
        with self.assertRaisesRegex(RuntimeError, "predetermined"):
            ORACLE.verify_filter(source, wrong, 2)
        source = np.arange(49, dtype=np.float32).reshape(7, 7)
        for opcode in (1, 2, 3, 4):
            good, _ = ORACLE.filter_reference(source, opcode)
            good[0, 1] += np.float32(.000001)
            with self.assertRaisesRegex(RuntimeError, "predetermined"):
                ORACLE.verify_filter(source, good, opcode)

    def test_shape_dtype_nonfinite_and_enum_rejected(self):
        cases = [(np.zeros((4, 7), dtype=np.float32), 1), (np.zeros((7, 7), dtype=np.float64), 1),
                 (np.zeros((7, 7), dtype=np.float32), True), (np.zeros((7, 7), dtype=np.float32), 99)]
        bad = np.zeros((7, 7), dtype=np.float32); bad[0, 0] = np.nan
        cases.append((bad, 1))
        for values, opcode in cases:
            with self.assertRaises(RuntimeError): ORACLE.filter_reference(values, opcode)


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fabricated_evidence(directory):
    """Only tests identity rejection and math; these receipts never came from DM."""
    source, expected = impulse_expectations()
    source_file = directory / "synthetic-source.npy"
    np.save(str(source_file), source, allow_pickle=False)
    calibration = [{"dm_axis": 0, "origin": 1.25, "raw_origin": 5, "scale": -.25, "unit": "nm"},
                   {"dm_axis": 1, "origin": -2.5, "raw_origin": 5, "scale": .5, "unit": "nm"}]
    intensity = {"origin": 7.5, "scale": -2, "unit": "arb"}
    truth = {"schema": 1, "kind": "synthetic-only", "python_is_listener": False,
             "status": "RECORDED", "session": "a" * 32, "host_pid": 1234, "initial_document_count": 1,
             "images": [{"label": "FILTER_A", "id": 17, "source_npy": str(source_file), "dtype": "float32",
                         "shape": [7, 7], "source_file_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                         "pixel_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
                         "calibration": calibration, "intensity_calibration": intensity}]}
    operations = {"schema": 1, "kind": "synthetic-only", "status": "RECORDED", "session": "a" * 32,
                  "host_pid": 1234, "checks": [], "outputs": []}
    independent = {"schema": 1, "status": "RECORDED_PARTIAL_QUALIFICATION", "host_pid": 1234,
                   "session": "a" * 32, "source_protection": "PASS", "document_count": 1, "outputs": [],
                   "independent_memory": "PASS", "raw_views_and_wrappers_released": True, "output_count": 4}
    for opcode in (1, 2, 3, 4):
        image_id = 100 + opcode
        result = {"image_id": image_id, "backend": "digitalmicrograph-native", "computation": "DM native",
                  "source_write_requested": False}
        request_id = "fabricated-filter-%s" % opcode
        receipt = {"protocol": "NB2", "session": "a" * 32, "host_pid": 1234, "state": "completed", "id": request_id,
                   "original_operation": "FILTER", "normalized_args": [17, opcode],
                   "result_type": "native_image_operation", "result_version": 1, "result": result}
        operations["checks"].append({"id": request_id, "op": "FILTER", "args": [17, opcode], "receipt": receipt})
        operations["outputs"].append({"kind": "FILTER", "opcode": opcode, "image_id": image_id,
                                      "source_labels": ["FILTER_A"]})
        output_file = directory / ("synthetic-output-%s.npy" % opcode)
        np.save(str(output_file), expected[opcode], allow_pickle=False)
        independent["outputs"].append({"kind": "FILTER", "image_id": image_id, "status": "NOT_QUALIFIED",
                                       "dtype": "float32", "shape": [7, 7], "snapshot": str(output_file),
                                       "snapshot_file_sha256": hashlib.sha256(output_file.read_bytes()).hexdigest(),
                                       "pixel_sha256": hashlib.sha256(expected[opcode].tobytes()).hexdigest(),
                                       "source_labels": ["FILTER_A"], "opcode": opcode, "request_id": request_id,
                                       "calibration": copy.deepcopy(calibration),
                                       "intensity_calibration": copy.deepcopy(intensity)})
    return truth, operations, independent


def fabricated_fourier_evidence(directory):
    """Independent NumPy test oracle; still fabricated, never a DM run."""
    truth, operations, independent = fabricated_evidence(directory)
    originals = {
        "A": np.array([[1.25, -2.5, 3.75, 4], [-5, 6, 7, -8],
                       [9.25, 10, -11, 12], [13, 14.5, 15, -16]], dtype=np.float32),
        "CONSTANT": np.full((4, 4), 3.25, dtype=np.float32),
        "IMPULSE": np.zeros((4, 8), dtype=np.float32),
        "SINGLE_FREQUENCY": np.array([[1, 0, -1, 0], [2, 1, 0, 1],
                                      [1, 0, -1, 0], [0, -1, -2, -1]], dtype=np.float32),
    }
    originals["IMPULSE"][1, 2] = 1
    original_cal = truth["images"][0]["calibration"]
    next_id = 1000
    for index, (label, source) in enumerate(originals.items()):
        source_id = 20 + index
        source_file = directory / ("synthetic-" + label + ".npy")
        np.save(str(source_file), source, allow_pickle=False)
        truth["images"].append({"label": label, "id": source_id, "source_npy": str(source_file), "dtype": "float32",
                                "shape": list(source.shape), "source_file_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                                "pixel_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
                                "calibration": copy.deepcopy(original_cal),
                                "intensity_calibration": {"origin": 7.5, "scale": -2, "unit": "arb"}})
        forward = np.conjugate(np.fft.fftshift(np.fft.fft2(source))).astype(np.complex64)
        forward_cal, inverse_cal = [], []
        for axis in original_cal:
            dim = axis["dm_axis"]; length = source.shape[-1-dim]
            scale = 1 / (length * axis["scale"]); raw = (length + 1) / 2
            forward_cal.append({"dm_axis": dim, "origin": -raw*scale, "raw_origin": raw, "scale": scale, "unit": "1/nm"})
            inverse_cal.append({"dm_axis": dim, "origin": 0, "raw_origin": 0, "scale": axis["scale"], "unit": "nm"})
        fft_id, inverse_id = next_id, next_id + 3
        references = [("FFT", forward), ("REAL", forward.real), ("IMAG", forward.imag),
                      ("IFFT", source.astype(np.complex64)), ("IFFT_REAL", source)]
        if label == "A":
            references += [("VENDOR_ARG", np.angle(forward)),
                           ("VENDOR_NORM", forward.real * forward.real + forward.imag * forward.imag)]
        for kind, values in references:
            image_id = next_id; next_id += 1
            parent_id = source_id if kind == "FFT" else inverse_id if kind == "IFFT_REAL" else fft_id
            op = "REAL" if kind == "IFFT_REAL" else kind
            request_id = "fabricated-%s-%s" % (label, kind)
            result = {"image_id": image_id, "computation": "DM native", "source_write_requested": False}
            receipt = {"protocol": "NB2", "session": "a" * 32, "host_pid": 1234, "state": "completed", "id": request_id,
                       "original_operation": op, "normalized_args": [parent_id],
                       "result_type": "native_fourier_operation", "result_version": 1, "result": result}
            operations["checks"].append({"id": request_id, "op": op, "args": [parent_id], "receipt": receipt})
            entry = {"kind": kind, "image_id": image_id, "source_labels": [label]}
            if kind != "FFT": entry["parent_image_id"] = parent_id
            operations["outputs"].append(entry)
            output_file = directory / ("synthetic-%s-%s.npy" % (label, kind))
            np.save(str(output_file), values, allow_pickle=False)
            independent["outputs"].append(dict(entry, status="NOT_QUALIFIED", dtype=str(values.dtype), shape=list(values.shape),
                                                snapshot=str(output_file), snapshot_file_sha256=hashlib.sha256(output_file.read_bytes()).hexdigest(),
                                                pixel_sha256=hashlib.sha256(values.tobytes()).hexdigest(), request_id=request_id,
                                                calibration=copy.deepcopy(inverse_cal if kind in ("IFFT", "IFFT_REAL") else forward_cal),
                                                intensity_calibration={"origin": 0, "scale": 1, "unit": ""}))
    independent["output_count"] = len(independent["outputs"])
    return truth, operations, independent


class MathEvidenceBoundary(unittest.TestCase):
    def run_case(self, directory, mutate=None, old_output=False, include_fourier=False):
        factory = fabricated_fourier_evidence if include_fourier else fabricated_evidence
        truth, operations, independent = factory(directory)
        if mutate: mutate(truth, operations, independent)
        truth_file, ops_file, independent_file, output = [directory / name for name in
                                                         ("truth.json", "operations.json", "independent.json", "math.json")]
        independent["truth_sha256"] = write_json(truth_file, truth)
        independent["operations_report_sha256"] = write_json(ops_file, operations)
        if mutate and getattr(mutate, "hash_fault", False): independent["truth_sha256"] = "0" * 64
        write_json(independent_file, independent)
        if old_output: output.write_text("OLD EVIDENCE", encoding="utf-8")
        args = ["--truth", str(truth_file), "--operations-report", str(ops_file),
                "--independent", str(independent_file), "--output", str(output)]
        if include_fourier: args.append("--include-fourier")
        if old_output:
            with self.assertRaises(FileExistsError): ORACLE.main(args)
            self.assertEqual(output.read_text(encoding="utf-8"), "OLD EVIDENCE")
            return
        result = ORACLE.main(args)
        return result, json.loads(output.read_text(encoding="utf-8"))

    def test_complete_fabricated_boundary_is_only_filters(self):
        with tempfile.TemporaryDirectory() as name:
            code, report = self.run_case(Path(name))
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "PASS_FILTERS_ONLY")
            self.assertEqual(report["fft"], "NOT_QUALIFIED")
            self.assertEqual(report["ui_visibility"], "NOT_TESTED")
            self.assertEqual(report["lifecycle"], "NOT_TESTED")
            self.assertEqual(len(report["filters"]), 4)

    def test_identity_source_calibration_coverage_fail_closed(self):
        def source_file_changed(t, o, i):
            Path(t["images"][0]["source_npy"]).write_bytes(b"not original npy")
        def wrong_hash(t, o, i): pass
        wrong_hash.hash_fault = True
        mutations = [source_file_changed, wrong_hash,
                     lambda t, o, i: i.update(status="PASS"),
                     lambda t, o, i: i.update(source_protection="NOT_TESTED"),
                     lambda t, o, i: i.update(host_pid=1235),
                     lambda t, o, i: i.update(session="b" * 32),
                     lambda t, o, i: i.update(document_count=2),
                     lambda t, o, i: i.update(independent_memory="NOT_TESTED"),
                     lambda t, o, i: i.update(raw_views_and_wrappers_released=False),
                     lambda t, o, i: i.update(output_count=3),
                     lambda t, o, i: o["outputs"].pop(),
                     lambda t, o, i: o["outputs"][0].update(source_labels=["A"]),
                     lambda t, o, i: o["checks"][0]["receipt"].update(state="failed"),
                     lambda t, o, i: i["outputs"][0]["calibration"][0].update(scale=1),
                     lambda t, o, i: i["outputs"][0].update(snapshot_file_sha256="0" * 64),
                     lambda t, o, i: i["outputs"][0].update(pixel_sha256="0" * 64),
                     lambda t, o, i: i["outputs"][0].update(request_id="wrong-id"),
                     lambda t, o, i: i["outputs"][0].update(snapshot=i["outputs"][1]["snapshot"])]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as name:
                code, report = self.run_case(Path(name), mutate)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("error", report)

    def test_existing_evidence_protected(self):
        with tempfile.TemporaryDirectory() as name:
            self.run_case(Path(name), old_output=True)

    def test_fixed_fourier_matrix_matches_separate_numpy_test_oracle(self):
        with tempfile.TemporaryDirectory() as name:
            code, report = self.run_case(Path(name), include_fourier=True)
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "PASS_PREPARED_OPERATIONS_MATH")
            self.assertEqual(len(report["fourier"]), 22)
            self.assertEqual(report["ui_visibility"], "NOT_TESTED")
            self.assertIn("squared magnitude", report["fourier_convention"]["norm"])

    def test_sign_center_normalization_phase_power_and_calibration_fail(self):
        def change_snapshot(kind, transform):
            def mutate(truth, operations, independent):
                entry = next(value for value in independent["outputs"] if value["kind"] == kind and value["source_labels"] == ["A"])
                values = transform(np.load(entry["snapshot"], allow_pickle=False)).astype(entry["dtype"])
                np.save(entry["snapshot"], values, allow_pickle=False)
                entry["snapshot_file_sha256"] = hashlib.sha256(Path(entry["snapshot"]).read_bytes()).hexdigest()
                entry["pixel_sha256"] = hashlib.sha256(values.tobytes()).hexdigest()
            return mutate
        mutations = [change_snapshot("FFT", np.conjugate),
                     change_snapshot("FFT", lambda values: np.fft.ifftshift(values)),
                     change_snapshot("FFT", lambda values: values / 16),
                     change_snapshot("IFFT", lambda values: values * 16),
                     change_snapshot("VENDOR_ARG", lambda values: values * (180 / math.pi)),
                     change_snapshot("VENDOR_NORM", np.sqrt),
                     lambda t, o, i: next(value for value in i["outputs"] if value["kind"] == "FFT")["calibration"][0].update(raw_origin=2),
                     lambda t, o, i: next(value for value in i["outputs"] if value["kind"] == "IFFT")["calibration"][0].update(origin=1.25),
                     lambda t, o, i: next(value for value in i["outputs"] if value["kind"] == "IFFT")["intensity_calibration"].update(scale=-2),
                     lambda t, o, i: o["outputs"].pop()]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as name:
                code, report = self.run_case(Path(name), mutate, include_fourier=True)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "FAIL")  # Late errors cannot preserve FILTER PASS.
                self.assertIn("error", report)


class QuarterTurnReference(unittest.TestCase):
    def test_hand_constant_impulse_and_sine_sign(self):
        constant = np.full((4, 4), 3.25, dtype=np.float32)
        expected = np.zeros((4, 4), dtype=np.complex64); expected[2, 2] = 52
        np.testing.assert_array_equal(ORACLE.quarter_turn_dft(constant), expected)
        impulse = np.zeros((4, 8), dtype=np.float32); impulse[1, 2] = 1
        expected_impulse = np.array([[-1, -1j, 1, 1j, -1, -1j, 1, 1j],
                                     [-1j, 1, 1j, -1, -1j, 1, 1j, -1],
                                     [1, 1j, -1, -1j, 1, 1j, -1, -1j],
                                     [1j, -1, -1j, 1, 1j, -1, -1j, 1]], dtype=np.complex64)
        np.testing.assert_array_equal(ORACLE.quarter_turn_dft(impulse), expected_impulse)
        sine = np.array([[0] * 4, [1] * 4, [0] * 4, [-1] * 4], dtype=np.float32)
        expected_sine = np.zeros((4, 4), dtype=np.complex64); expected_sine[1, 2] = -8j; expected_sine[3, 2] = 8j
        np.testing.assert_array_equal(ORACLE.quarter_turn_dft(sine), expected_sine)

    def test_nonquarter_fixture_is_rejected_instead_of_fitting(self):
        values = np.zeros((4, 8), dtype=np.float32); values[1, 1] = 1
        with self.assertRaisesRegex(RuntimeError, "outside"):
            ORACLE.quarter_turn_dft(values)


if __name__ == "__main__": unittest.main()
