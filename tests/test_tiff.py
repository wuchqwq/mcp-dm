"""Independent TIFF decoding tests (validation Python: numpy + tifffile)."""
import pathlib
import runpy
import tempfile
import unittest

import numpy as np
import tifffile

write_tiff = runpy.run_path(str(pathlib.Path(__file__).parents[1] / "bridge" / "lossless_tiff.py"))["write_tiff"]


class ScientificTiffTests(unittest.TestCase):
    def test_raw_dtype_values_and_embedded_calibration(self):
        metadata = {"calibration": [
            {"unit": "nm", "scale": 0.125, "calibrated_value_at_pixel_zero": 2.5},
            {"unit": "nm", "scale": 0.375, "calibrated_value_at_pixel_zero": -1.5}],
            "intensity_calibration": {"scale": 1.0, "origin": 0.0}}
        with tempfile.TemporaryDirectory() as td:
            for dtype in ["uint8", "uint16", "uint32", "int8", "int16", "int32", "float32", "float64", ">u4", ">f8"]:
                with self.subTest(dtype=dtype):
                    dt = np.dtype(dtype)
                    a = np.arange(77).reshape(7, 11).astype(dt)
                    if dt.kind == "u" and dt.itemsize == 4:
                        a[2, 3] = 3000000001  # exceeds exact float32 integer range
                    if dt.kind == "i":
                        a[2, 3] = -17
                    if dt.kind == "f":
                        a[2, 3] = 1.2345678901234567
                    a.flags.writeable = False
                    snapshot = a.copy()
                    dest = pathlib.Path(td) / (dtype.replace(">", "big") + ".tif")
                    write_tiff(str(dest), a, metadata)
                    with tifffile.TiffFile(dest) as f:
                        b = f.asarray()
                        self.assertEqual(b.dtype.kind, a.dtype.kind)
                        self.assertEqual(b.dtype.itemsize, a.dtype.itemsize)
                        np.testing.assert_array_equal(b, a)
                        self.assertEqual(f.pages[0].tags[65003].value, "nm")
                        self.assertEqual(f.pages[0].tags[65006].value, 2.5)
                        self.assertEqual(f.pages[0].tags[65010].value, 0.375)
                        self.assertIn('"dm_mcp":', f.pages[0].description)
                    np.testing.assert_array_equal(a, snapshot)
                    with self.assertRaises(FileExistsError):
                        write_tiff(str(dest), a, metadata)

    def test_noncontiguous_selection_and_invalid_shape(self):
        with tempfile.TemporaryDirectory() as td:
            a = np.arange(400, dtype="uint32").reshape(20, 20)[1:17:2, 2:18:3]
            dest = pathlib.Path(td) / "roi.tif"
            write_tiff(str(dest), a, {})
            np.testing.assert_array_equal(tifffile.imread(dest), a)
            for bad in [np.zeros((2, 3, 4)), np.zeros((0, 3)), np.zeros((3, 3), dtype="complex64")]:
                with self.assertRaises(ValueError):
                    write_tiff(str(pathlib.Path(td) / "bad.tif"), bad, {})


if __name__ == "__main__":
    unittest.main()
