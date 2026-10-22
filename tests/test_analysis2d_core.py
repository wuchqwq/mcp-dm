"""Independent synthetic oracles for the shared 2D kernels."""
import importlib.util
import math
import os
import unittest

import numpy as np


CORE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "analysis2d_core.py"))
spec = importlib.util.spec_from_file_location("analysis2d_core_test", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


CAL = [
    {"axis": "x", "scale": -0.25, "unit": "nm", "calibrated_value_at_pixel_zero": 1.25},
    {"axis": "y", "scale": 0.5, "unit": "nm", "calibrated_value_at_pixel_zero": -2.5},
]


class Analysis2DCoreTests(unittest.TestCase):
    def test_statistics_are_finite_only_and_use_population_stddev(self):
        values = np.array([[1.0, np.nan, 3.0], [np.inf, 5.0, 7.0]])
        original = values.copy()
        result = core.statistics(values)
        self.assertEqual((result["total_count"], result["finite_count"], result["nan_count"], result["inf_count"]), (6, 4, 1, 1))
        self.assertEqual(result["mean"], 4.0)
        self.assertAlmostEqual(result["stddev"], math.sqrt(5.0))
        np.testing.assert_array_equal(values, original)

    def test_profile_on_analytic_plane_and_signed_anisotropic_calibration(self):
        yy, xx = np.indices((7, 9), dtype="float64")
        plane = 2.0 * xx + 3.0 * yy + 4.0
        result = core.profile(plane, CAL, 2, 1, 2, 5, 1)
        self.assertEqual(result["values"], [11.0, 14.0, 17.0, 20.0, 23.0])
        self.assertEqual(result["unit"], "nm")
        self.assertAlmostEqual(result["distance"][-1], 2.0)
        wide = core.profile(plane, CAL, 3, 3, 5, 3, 2)
        self.assertEqual(wide["width_offsets"], [-0.5, 0.5])
        self.assertEqual(wide["values"], [19.0, 21.0, 23.0])

    def test_non_square_cosine_has_known_full_fft_bins_and_calibrated_frequency(self):
        height, width, cycles, amplitude = 12, 20, 4, 2.0
        yy, xx = np.indices((height, width), dtype="float64")
        wave = amplitude * np.cos(2 * np.pi * cycles * xx / width)
        original = wave.copy()
        summary, magnitude = core.fft(wave, CAL, 4)
        cy, cx = height // 2, width // 2
        expected_peak = height * width * amplitude / 2.0
        self.assertAlmostEqual(magnitude[cy, cx + cycles], expected_peak, places=10)
        self.assertAlmostEqual(magnitude[cy, cx - cycles], expected_peak, places=10)
        self.assertAlmostEqual(magnitude[cy, cx], 0.0, places=10)
        self.assertIn((0, cycles), {(p["dy"], p["dx"]) for p in summary["peaks"]})
        peak = next(p for p in summary["peaks"] if p["dx"] == cycles and p["dy"] == 0)
        self.assertAlmostEqual(peak["fx"], -0.8)
        self.assertAlmostEqual(peak["frequency"], 0.8)
        self.assertAlmostEqual(peak["spacing"], 1.25)
        np.testing.assert_array_equal(wave, original)

    def test_fft_rejects_nonfinite_without_imputation(self):
        with self.assertRaisesRegex(ValueError, "NaN/Inf"):
            core.fft(np.array([[1.0, np.inf]]), CAL)


if __name__ == "__main__":
    unittest.main()
