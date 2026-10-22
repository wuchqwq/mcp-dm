"""DM native scalar dtype mapping; synthetic fakes and no real host required."""
import json
import os
import tempfile
import unittest

import numpy as np
from test_analysis import FakeImage, backend_for


class DatasetNativeDTypeTests(unittest.TestCase):
    @staticmethod
    def image(code):
        item = FakeImage(np.arange(20, dtype=np.float32).reshape(4, 5))
        item.GetDataType = lambda: code
        return item

    def test_known_native_scalar_types_without_pixel_access(self):
        for code, expected in [(1, "int16"), (2, "float32"), (6, "uint8"),
                               (7, "int32"), (9, "int8"), (10, "uint16"),
                               (11, "uint32"), (12, "float64")]:
            with self.subTest(code=code):
                img = self.image(code)
                def forbid_pixels():
                    raise AssertionError("listing must not map image pixels")
                img.GetNumArray = forbid_pixels
                response = backend_for(img).list_datasets()
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["datasets"][0]["dtype"], expected)
                self.assertEqual(response["datasets"][0]["data_type_code"], code)
                self.assertEqual(response["datasets"][0]["shape"], [4, 5])

    def test_unknown_or_noninteger_types_remain_unknown(self):
        for code in (None, True, "2", 0, 3, 4, 5, 8, 13, 255):
            with self.subTest(code=code):
                img = self.image(code)
                def forbid_pixels():
                    raise AssertionError("unknown dtype must not read pixels")
                img.GetNumArray = forbid_pixels
                entry = backend_for(img).list_datasets()["datasets"][0]
                self.assertIsNone(entry["dtype"])
                self.assertEqual(entry["data_type_code"], code)

    def test_real_scalar_capture_agrees_with_listing(self):
        img = self.image(2)
        backend = backend_for(img)
        listed = backend.list_datasets()["datasets"][0]
        with tempfile.TemporaryDirectory() as temp:
            capture = backend.capture2d(img.GetID(), [1, 1, 4, 3],
                                        os.path.join(temp, "new_capture"))
            self.assertEqual(capture["dtype"], listed["dtype"])
            with open(os.path.join(capture["capture_dir"], "input.json"), encoding="utf-8") as stream:
                meta = json.load(stream)
            self.assertEqual(meta["dtype"], listed["dtype"])
            saved = np.load(os.path.join(capture["capture_dir"], "input.npy"), allow_pickle=False)
            self.assertEqual(saved.dtype, np.dtype("float32"))
            np.testing.assert_array_equal(saved, img.array[1:3, 1:4])

    def test_unsupported_type_rejected_before_capture_directory_is_created(self):
        img = self.image(3)
        backend = backend_for(img)
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "new_capture")
            with self.assertRaisesRegex(ValueError, "未知或非实数"):
                backend.capture2d(img.GetID(), None, path)
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
