"""Independent exact geometry distinguishes index bounds from error tolerance."""

import unittest

import numpy as np

from crystallography import indexing


class CrystalGateControls(unittest.TestCase):
    def test_fixed_diamond_001_higher_orders_need_index4_not_looser_tolerances(self):
        # Conventional diamond permits these even reflections: h+k+l is 4n.
        # Project analytically along [001]; no search output makes the fixture.
        a_nm = .3566986
        hkl = np.array([[2, 2, 0], [-2, -2, 0], [2, -2, 0], [-2, 2, 0],
                        [4, 0, 0], [-4, 0, 0], [0, 4, 0], [0, -4, 0]])
        observed = hkl[:, :2] / a_nm
        before = observed.tobytes()
        options = dict(calibrated=True, centerings=["F"],
                       candidate_lattice_nm={"F": a_nm}, relative_tolerance=.03,
                       angle_tolerance_deg=2., max_unmatched=0, max_candidates=3)

        low = indexing.index_cubic(observed, max_index=3, **options)
        high = indexing.index_cubic(observed, max_index=4, **options)

        self.assertEqual(low["candidates"], [])
        self.assertEqual(low["search"]["total_distinct_candidates"], 0)
        self.assertTrue(high["candidates"])
        for result in (low, high):
            self.assertEqual(result["tolerances"],
                             {"relative_radial": .03, "angle_deg": 2., "max_unmatched": 0})
            self.assertTrue(result["search"]["anchor_enumeration_exhausted"])
            self.assertFalse(result["ambiguity"]["unique_chemical_phase_claim"])
        self.assertEqual(low["search"]["max_index"], 3)
        self.assertEqual(high["search"]["max_index"], 4)
        candidate = high["candidates"][0]
        self.assertEqual(candidate["matched_count"], 8)
        self.assertEqual(candidate["unmatched_observation_indices"], [])
        self.assertEqual(candidate["lattice_parameter_source"], "fixed_reference")
        self.assertEqual(candidate["lattice_parameter_nm"], a_nm)
        self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvw"]), [0, 0, 1])
        orientation = np.asarray(candidate["crystal_to_image_orientation"])
        np.testing.assert_allclose(orientation @ orientation.T, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(orientation), 1., places=12)
        for point in candidate["observations"]:
            self.assertTrue(point["matched"])
            predicted = orientation @ np.asarray(point["hkl"]) / a_nm
            np.testing.assert_allclose(predicted[:2], observed[point["observation_index"]],
                                       rtol=0, atol=1e-10)
            self.assertAlmostEqual(predicted[2], 0., places=10)
        self.assertEqual(observed.tobytes(), before)


if __name__ == "__main__":
    unittest.main()
