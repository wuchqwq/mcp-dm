"""Independent, hand-enumerable geometry controls; no DM or real sample."""
import math
import unittest

from crystallography.geometry import calibration_map, measure_geometry, GeometryError


class GeometryTests(unittest.TestCase):
    def mapping(self, **kw):
        spec = dict(mode="explicit", scale_xy=[0.5, -0.25], zero_xy=[13., -7.],
                    unit="1/nm", convention="cycles_per_length", basis="synthetic reference")
        spec.update(kw)
        return calibration_map(spec)

    def test_signed_anisotropic_axes_nonzero_centre_and_origin(self):
        result = measure_geometry([10., 20.], [dict(id="a", xy=[12., 20.]),
                                              dict(id="b", xy=[10., 16.]),
                                              dict(id="c", xy=[12., 16.])], self.mapping())
        self.assertEqual(result["spots"][0]["g_xy_cycles_per_nm"], [1., 0.])
        self.assertEqual(result["spots"][1]["g_xy_cycles_per_nm"], [0., 1.])
        self.assertEqual(result["spots"][0]["absolute_coordinate_xy"], [19., -12.])
        self.assertAlmostEqual(result["spots"][2]["d_nm"], 1 / math.sqrt(2))
        self.assertEqual([v["angle_deg"] for v in result["angles"]], [90., 45., 45.])
        self.assertAlmostEqual(result["spots"][2]["length_ratio_to_first"], math.sqrt(2))
        self.assertEqual(result["spots"][0]["uncertainty_status"], "UNKNOWN")

    def test_radian_angstrom_and_cycles_nm_are_identical(self):
        a = self.mapping(scale_xy=[0.1 * 2 * math.pi, -0.05 * 2 * math.pi],
                         unit="rad/angstrom", convention="radians_per_length")
        b = self.mapping(scale_xy=[1., -0.5])
        for k in range(2):
            self.assertAlmostEqual(a["scale_xy"][k], b["scale_xy"][k])

    def test_shared_centre_angle_error_is_not_two_independent_centres(self):
        mapping = self.mapping(scale_xy=[1., 1.], scale_sigma_xy=[0., 0.])
        result = measure_geometry([0., 0.], [dict(id="a", xy=[10., 0.], sigma_px=[0., 0.]),
                                             dict(id="b", xy=[0., 10.], sigma_px=[0., 0.])],
                                  mapping, center_sigma_px=[1., 1.])
        self.assertAlmostEqual(result["angles"][0]["sigma_deg"], math.degrees(math.sqrt(.02)))
        self.assertAlmostEqual(result["spots"][0]["g_sigma"], 1.)
        self.assertAlmostEqual(result["spots"][0]["d_sigma_nm"], .01)

    def test_common_isotropic_scale_error_cancels_from_angle(self):
        # Only x scale uncertain, horizontal vectors' direction stays unchanged.
        result = measure_geometry([0., 0.], [dict(id="a", xy=[10., 0.], sigma_px=[0., 0.]),
                                             dict(id="b", xy=[-10., 0.], sigma_px=[0., 0.])],
                                  self.mapping(scale_xy=[1., 1.], scale_sigma_xy=[.1, 0.]), [0., 0.])
        self.assertEqual(result["angles"][0]["angle_deg"], 180.)
        self.assertEqual(result["angles"][0]["sigma_deg"], 0.)

    def test_missing_absolute_calibration_never_invents_d(self):
        for usable in (True, False):
            mapping = calibration_map(dict(mode="relative", isotropic_pixel_geometry_confirmed=usable))
            result = measure_geometry([0., 0.], [dict(id="a", xy=[1., 0.]), dict(id="b", xy=[1., 1.])], mapping)
            self.assertIsNone(result["spots"][0]["d_nm"])
            self.assertEqual(result["angles"][0]["angle_deg"], 45. if usable else None)
            self.assertEqual(result["spots"][0]["length_ratio_to_first"], 1. if usable else None)

    def test_geometry_limitations_do_not_deny_upstream_automatic_localization(self):
        result = measure_geometry([0., 0.], [dict(id="a", xy=[1., 0.])], self.mapping())
        self.assertTrue(any("optional automatic localization" in item for item in result["limitations"]))
        self.assertNotIn("No automatic peak localization or centre estimation", result["limitations"])

    def test_capture_xy_axes_convert_units_independently(self):
        axes = [dict(scale=-.2, calibrated_value_at_pixel_zero=9., unit="1/nm"),
                dict(scale=.03, calibrated_value_at_pixel_zero=-2., unit="1/angstrom")]
        mapping = calibration_map(dict(mode="capture_axes", convention="cycles_per_length"), axes)
        self.assertEqual(mapping["scale_xy"], [-.2, .3])
        self.assertEqual(mapping["zero_xy"], [9., -20.])

    def test_explicit_bad_inputs_refuse(self):
        for kw in (dict(scale_xy=[0, 1]), dict(scale_xy=[True, 1]), dict(unit="counts"),
                   dict(convention="guess"), dict(basis=""), dict(scale_sigma_xy=[-1, 0]),
                   dict(unit="rad/nm", convention="cycles_per_length")):
            with self.subTest(kw=kw), self.assertRaises(GeometryError):
                self.mapping(**kw)
        for spots in ([dict(id="a", xy=[0, 0])],
                      [dict(id="a", xy=[1, 0]), dict(id="b", xy=[1, 0])],
                      [dict(id="a", xy=[math.nan, 0])],
                      [dict(id="a", xy=[1, 0]), dict(id="a", xy=[2, 1])]):
            with self.subTest(spots=spots), self.assertRaises(GeometryError):
                measure_geometry([0, 0], spots, self.mapping())


if __name__ == "__main__":
    unittest.main()
