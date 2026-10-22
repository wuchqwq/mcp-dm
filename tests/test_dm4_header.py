# -*- coding: utf-8 -*-
"""Original synthetic DM4 wire fixtures for the narrow seek-only header index.

No Gatan process, user data, external DM writer, or socket is used. Wire fields
are built from explicit big-endian DM4 framing and little-endian typed values;
the fixture builder deliberately does not import production framing constants.
"""

import builtins
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock


sys.dont_write_bytecode = True
BRIDGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge"))


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_header_test", os.path.join(BRIDGE_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


header = load("dm4_header")


def entry(kind, label, contents):
    encoded = label.encode("utf-8")
    return struct.pack(">BH", kind, len(encoded)) + encoded + struct.pack(">Q", len(contents)) + contents


def group(label, children):
    return entry(20, label, b"\x01\x01" + struct.pack(">Q", len(children)) + b"".join(children))


def typed(label, descriptor, value):
    description = struct.pack(">Q", len(descriptor)) + b"".join(struct.pack(">Q", value) for value in descriptor)
    return entry(21, label, b"%%%%" + description + value)


def scalar(label, value, type_code=3):
    formats = {3: "<i", 6: "<f", 7: "<d", 8: "<?"}
    return typed(label, [type_code], struct.pack(formats[type_code], value))


def text(label, value):
    encoded = value.encode("utf-16-le")
    return typed(label, [20, 4, len(encoded) // 2], encoded)


def fixture(dm_dimensions=(11, 7, 5, 3), dtype_code=6, itemsize=1,
            missing_units=None, scale_override=None, origin_override=None,
            payload_type=10, payload_count=None, payload_delta=0,
            thumbnail=False, unknown_group=False):
    count = 1
    for size in dm_dimensions:
        count *= size
    count = count if payload_count is None else payload_count
    payload = bytes(bytearray((i % 251) for i in range(count * itemsize + payload_delta)))
    dimension_tags = [scalar("", size) for size in dm_dimensions]
    axes = []
    for axis in range(len(dm_dimensions)):
        unit = "1/nm" if axis < 2 else "nm"
        scale = (.125, -.25, .05, .1)[axis] if axis < 4 else 1
        origin = (5.5, 3, 0, -1.25)[axis] if axis < 4 else 0
        if scale_override is not None and axis == 0:
            scale = scale_override
        if origin_override is not None and axis == 0:
            origin = origin_override
        children = [scalar("Origin", origin, 7), scalar("Scale", scale, 7)]
        if missing_units != axis:
            children.append(text("Units", unit))
        axes.append(group("", children))
    image_data = group("ImageData", [
        scalar("DataType", dtype_code),
        group("Dimensions", dimension_tags),
        group("Calibrations", [group("Dimension", axes)]),
        typed("Data", [20, payload_type, count], payload),
    ])
    images = [group("", [text("Name", "Synthetic non-square 4D"), image_data])]
    if thumbnail:
        rgb = group("", [text("Name", "RGB thumbnail"), group("ImageData", [
            scalar("DataType", 23), group("Dimensions", [scalar("", 2), scalar("", 2)]),
            typed("Data", [20, 5, 4], bytes(range(16))),
        ])])
        images.insert(0, rgb)
    root_children = [group("ImageList", images)]
    if unknown_group:
        # Deliberately uninterpretable body in an unneeded group: its declared
        # span must be skipped, not decoded as pixel or metadata content.
        root_children.append(entry(20, "IrrelevantMetadata", b"not-a-taggroup" * 100))
    root = b"\x01\x01" + struct.pack(">Q", len(root_children)) + b"".join(root_children)
    # Native DM4 declares bytes after the initial 16-byte version/size/endian.
    result = struct.pack(">IQI", 4, len(root), 1) + root
    data_marker = b"\x15\x00\x04Data"
    data_tag = result.rfind(data_marker)
    span_position = data_tag + len(data_marker)
    payload_position = span_position + 8 + 4 + 8 + 3 * 8
    return result, (payload_position, payload_position + len(payload)), span_position


class GuardedFile(object):
    def __init__(self, stream, forbidden, reads):
        self.stream = stream
        self.forbidden = forbidden
        self.reads = reads

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *arguments):
        return self.stream.__exit__(*arguments)

    def read(self, count=-1):
        if count < 0:
            raise AssertionError("header reader attempted an unbounded read")
        start = self.stream.tell()
        stop = start + count
        self.reads.append((start, stop))
        if start < self.forbidden[1] and stop > self.forbidden[0]:
            raise AssertionError("header reader attempted to read image pixel bytes")
        return self.stream.read(count)


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm4_header_synthetic_")
        self.path = os.path.join(self.temp.name, "fixture.dm4")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        with open(self.path, "wb") as stream:
            stream.write(data)
        return self.path

    def read(self, **kwargs):
        data, _, _ = fixture(**kwargs)
        return header.HeaderIndex(self.write(data))

    def test_independent_wire_fixture_dimensions_dtype_and_offsets(self):
        data, payload, _ = fixture()
        result = header.HeaderIndex(self.write(data))
        self.assertEqual(len(result.datasets), 1)
        dataset = result.datasets[0]
        self.assertEqual(dataset["dm_dimensions"], [11, 7, 5, 3])
        self.assertEqual(dataset["shape"], [3, 5, 7, 11])
        self.assertEqual(dataset["dtype"], "u1")
        self.assertEqual(dataset["data_offset"], payload[0])
        self.assertEqual(dataset["data_bytes"], payload[1] - payload[0])
        self.assertEqual(dataset["name"], "Synthetic non-square 4D")
        self.assertEqual(result.header_end, len(data))

    def test_calibration_axis_reversal_and_raw_pixel_origin_formula(self):
        axes = self.read().datasets[0]["calibration"]
        self.assertEqual([axis["numpy_axis"] for axis in axes], [3, 2, 1, 0])
        self.assertEqual([axis["unit"] for axis in axes], ["1/nm", "1/nm", "nm", "nm"])
        self.assertEqual(axes[0]["calibrated_value_at_pixel_zero"], -5.5 * .125)
        self.assertEqual(axes[1]["calibrated_value_at_pixel_zero"], -3 * -.25)
        self.assertEqual(axes[3]["calibrated_value_at_pixel_zero"], 1.25 * .1)

    def test_never_reads_pixel_payload_and_header_read_budget_is_small(self):
        data, payload, _ = fixture(dm_dimensions=(128, 128, 8, 4))
        self.write(data)
        original_open = builtins.open
        reads = []
        def guarded_open(path, mode="r", *args, **kwargs):
            self.assertEqual(mode, "rb")
            return GuardedFile(original_open(path, mode, *args, **kwargs), payload, reads)
        with mock.patch.object(builtins, "open", side_effect=guarded_open):
            result = header.HeaderIndex(self.path)
        self.assertTrue(reads)
        self.assertEqual(result.bytes_read, sum(stop-start for start, stop in reads))
        self.assertLess(result.bytes_read, 4096)
        self.assertLess(result.bytes_read, len(data) // 50)
        self.assertFalse(result.describe()["pixel_payload_read"])

    def test_thumbnail_storage_number_is_preserved_and_rgb_not_indexed(self):
        dataset = self.read(thumbnail=True).datasets
        self.assertEqual(len(dataset), 1)
        self.assertEqual(dataset[0]["storage_key"], "2")

    def test_unneeded_group_is_skipped_by_declared_span(self):
        self.assertEqual(self.read(unknown_group=True).datasets[0]["shape"], [3, 5, 7, 11])

    def test_missing_units_on_any_axis_is_not_guessed(self):
        for axis in range(4):
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, "origin/unit"):
                self.read(missing_units=axis)

    def test_missing_nonfinite_or_zero_axis_calibration_is_rejected(self):
        for arguments in [dict(scale_override=0), dict(scale_override=float("nan")),
                          dict(scale_override=float("inf")), dict(origin_override=float("nan"))]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.read(**arguments)

    def test_wrong_payload_count_or_byte_length_is_rejected(self):
        for arguments in [dict(payload_count=1000), dict(payload_delta=-1), dict(payload_delta=1)]:
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "disagree"):
                self.read(**arguments)

    def test_declared_primitive_encoding_must_match_image_dtype(self):
        # uint8 ImageData with a uint16 descriptor and only N bytes is malformed,
        # even if dimension product and the descriptor count both happen to be N.
        with self.assertRaises(ValueError):
            self.read(payload_type=4)

    def test_invalid_dimensions_are_rejected(self):
        for dimensions in [(), (0, 7, 5, 3), (11, 7, 5, 3, 2)]:
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                self.read(dm_dimensions=dimensions)

    def test_supported_non_uint8_scalar_dataset_header_can_be_indexed(self):
        result = self.read(dtype_code=10, itemsize=2, payload_type=4)
        self.assertEqual(result.datasets[0]["dtype"], "<u2")
        self.assertEqual(result.datasets[0]["data_bytes"], 3 * 5 * 7 * 11 * 2)

    def test_wrong_version_endian_or_declared_oversize_rejected(self):
        data, _, _ = fixture()
        for head in [struct.pack(">IQI", 3, len(data)-16, 1),
                     struct.pack(">IQI", 4, len(data)-16, 0),
                     struct.pack(">IQI", 4, len(data)+1, 1)]:
            with self.subTest(head=head), self.assertRaises(ValueError):
                header.HeaderIndex(self.write(head + data[16:]))

    def test_partial_header_or_truncated_payload_never_indexes_successfully(self):
        data, payload, _ = fixture()
        for stop in [0, 4, 15, 20, payload[0]-1, payload[0]+2, len(data)-1]:
            with self.subTest(stop=stop), self.assertRaises(ValueError):
                header.HeaderIndex(self.write(data[:stop]))

    def test_bad_tag_span_cannot_leave_parent_or_file(self):
        data, _, span_position = fixture()
        bad = bytearray(data)
        bad[span_position:span_position+8] = struct.pack(">Q", len(data))
        with self.assertRaisesRegex(ValueError, "span"):
            header.HeaderIndex(self.write(bad))

    def test_parent_group_span_must_match_consumed_group(self):
        data, _, _ = fixture()
        position = data.index(b"ImageList") + len(b"ImageList")
        span = struct.unpack(">Q", data[position:position+8])[0]
        bad = bytearray(data)
        bad[position:position+8] = struct.pack(">Q", span-1)
        with self.assertRaises(ValueError):
            header.HeaderIndex(self.write(bad))

    def test_typed_delimiter_and_descriptor_count_are_bounded(self):
        data, _, span_position = fixture()
        content = span_position + 8
        for start, encoded in [(content, b"BAD!"),
                               (content+4, struct.pack(">Q", 0)),
                               (content+4, struct.pack(">Q", 129))]:
            bad = bytearray(data)
            bad[start:start+len(encoded)] = encoded
            with self.subTest(start=start, encoded=encoded), self.assertRaises(ValueError):
                header.HeaderIndex(self.write(bad))

    def test_group_count_depth_and_read_budget_are_bounded(self):
        data, _, _ = fixture()
        self.write(data)
        for name, maximum in [("MAX_ENTRIES", 10), ("MAX_DEPTH", 3), ("MAX_HEADER_BYTES", 64)]:
            with self.subTest(limit=name), mock.patch.object(header, name, maximum), self.assertRaises(ValueError):
                header.HeaderIndex(self.path)

    def test_large_native_document_open_guard_precedes_any_dm_file_api(self):
        bridge = load("dm_bridge")
        fake = mock.Mock()
        backend = bridge.DmBackend(fake)
        with mock.patch.object(bridge.os.path, "isfile", return_value=True), \
             mock.patch.object(bridge.os.path, "getsize", return_value=bridge.MAX_NATIVE_OPEN_BYTES+1), \
             self.assertRaisesRegex(RuntimeError, "dm_4dstem_open"):
            backend.open_file("F:/synthetic-large.dm4", False)
        fake.OpenImage.assert_not_called()
        fake.NewImageDocumentFromFile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
