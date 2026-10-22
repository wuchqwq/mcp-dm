"""Narrow seek-only DM4 dataset index; no pixel payload is loaded.

Supports the DM4 tag framing and scalar dimension/calibration records needed
for explicit 4D-STEM indexing. Unknown tags are skipped by their declared byte
span, never interpreted as an image. This is not a general metadata decoder.
"""
import math
import os
import struct


MAX_HEADER_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 25000
MAX_DEPTH = 48
SCALARS = {2: 'h', 3: 'i', 4: 'H', 5: 'I', 6: 'f', 7: 'd',
           8: '?', 9: 'b', 10: 'b', 11: 'q', 12: 'Q'}
DTYPES = {1: ('<i2', 2), 2: ('<f4', 4), 6: ('u1', 1), 7: ('<i4', 4),
          9: ('i1', 1), 10: ('<u2', 2), 11: ('<u4', 4), 12: ('<f8', 8)}
PIXEL_ENCODINGS = {1: 2, 2: 6, 6: 10, 7: 3, 9: 9, 10: 4, 11: 5, 12: 7}


class HeaderIndex(object):
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.size = os.path.getsize(self.path)
        self.bytes_read = 0
        self.entries = 0
        self.tags = {}
        self.payloads = {}
        with open(self.path, 'rb') as stream:
            self.stream = stream
            version, declared, endian = struct.unpack('>IQI', self._read(16))
            if version != 4 or endian != 1:
                raise ValueError('Only little-endian DM4 is supported by the bounded index')
            if declared > self.size or self.size < 26:
                raise ValueError('Invalid DM4 size header')
            self.declared_size = declared
            self._group((), self.size, 0)
            self.header_end = stream.tell()
        del self.stream
        self.datasets = self._datasets()
        if not self.datasets:
            raise ValueError('No indexed real scalar image dataset in DM4')

    def _read(self, count):
        if count < 0 or self.bytes_read + count > MAX_HEADER_BYTES:
            raise ValueError('DM4 header read budget exceeded')
        data = self.stream.read(count)
        self.bytes_read += len(data)
        if len(data) != count:
            raise ValueError('Truncated DM4 header')
        return data

    def _number(self, fmt):
        return struct.unpack('>' + fmt, self._read(struct.calcsize('>' + fmt)))[0]

    @staticmethod
    def _text(data):
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('cp1252')

    def _needed_group(self, path):
        if len(path) == 1:
            return path[0] == 'ImageList'
        if path[0] != 'ImageList':
            return False
        if len(path) == 2:
            return True
        if path[2] != 'ImageData':
            return False
        return len(path) <= 3 or path[3] in ('Dimensions', 'Calibrations')

    def _group(self, parent, boundary, depth):
        if depth > MAX_DEPTH:
            raise ValueError('DM4 tag nesting exceeds limit')
        self._read(2)  # sorted/open flags
        count = self._number('Q')
        if count > MAX_ENTRIES:
            raise ValueError('DM4 tag count exceeds limit')
        for ordinal in range(1, count + 1):
            self.entries += 1
            if self.entries > MAX_ENTRIES:
                raise ValueError('DM4 cumulative tag count exceeds limit')
            kind = self._number('B')
            length = self._number('H')
            label = self._text(self._read(length)) if length else str(ordinal)
            span = self._number('Q')
            start = self.stream.tell()
            end = start + span
            if end > boundary or end > self.size or span < 0:
                raise ValueError('DM4 tag byte span leaves its parent/file')
            path = parent + (label,)
            if kind == 20:
                if self._needed_group(path):
                    self._group(path, end, depth + 1)
                    if self.stream.tell() != end:
                        raise ValueError('DM4 group length mismatch at ' + '/'.join(path))
            elif kind == 21:
                self._data(path, end)
            else:
                raise ValueError('Unsupported DM4 tag entry kind')
            self.stream.seek(end)

    def _data(self, path, end):
        # Read only fields required to establish an indexed dataset. Other
        # metadata is deliberately not decoded by this narrow reader.
        if path[0] != 'ImageList' or len(path) < 3:
            return
        wanted = (len(path) == 3 and path[2] == 'Name') or (
            path[2] == 'ImageData' and (path[3:] == ('Data',) or path[3:] == ('DataType',)
                or (len(path) == 5 and path[3] == 'Dimensions')
                or (len(path) == 7 and path[3:5] == ('Calibrations', 'Dimension'))))
        if not wanted:
            return
        if self._read(4) != b'%%%%':
            raise ValueError('Invalid DM4 typed-tag delimiter')
        ndesc = self._number('Q')
        if not 1 <= ndesc <= 128:
            raise ValueError('Unsupported DM4 type descriptor size')
        descriptor = tuple(self._number('Q') for _ in range(ndesc))
        offset = self.stream.tell()
        available = end - offset
        if path[2:] == ('ImageData', 'Data'):
            if len(descriptor) != 3 or descriptor[0] != 20:
                raise ValueError('Only flat primitive DM4 image payloads are indexed')
            self.payloads[path[:2]] = {'offset': offset, 'bytes': available,
                                        'descriptor': list(descriptor)}
            return
        if len(descriptor) == 1 and descriptor[0] in SCALARS:
            fmt = '<' + SCALARS[descriptor[0]]
            if available != struct.calcsize(fmt):
                raise ValueError('Scalar DM4 calibration payload length mismatch')
            value = struct.unpack(fmt, self._read(available))[0]
        elif len(descriptor) == 3 and descriptor[0] == 20 and descriptor[1] in (4, 9, 10):
            size = descriptor[2] * (2 if descriptor[1] == 4 else 1)
            if size != available or size > 65536:
                raise ValueError('DM4 calibration string exceeds supported bounds')
            value = self._read(size).decode('utf-16-le' if descriptor[1] == 4 else 'utf-8')
        else:
            raise ValueError('Unsupported DM4 dimension/name calibration encoding')
        self.tags[path] = value

    def _datasets(self):
        result = []
        for prefix, payload in sorted(self.payloads.items()):
            base = prefix + ('ImageData',)
            code = self.tags.get(base + ('DataType',))
            if code not in DTYPES:  # e.g. RGB thumbnail: never a real scalar cube
                continue
            dimensions = []
            d = 1
            while base + ('Dimensions', str(d)) in self.tags:
                size = self.tags[base + ('Dimensions', str(d))]
                if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                    raise ValueError('Invalid DM4 dimension size')
                dimensions.append(size)
                d += 1
            if not 1 <= len(dimensions) <= 4:
                raise ValueError('Unsupported image dimensionality')
            dtype, itemsize = DTYPES[code]
            if payload['descriptor'][1] != PIXEL_ENCODINGS[code]:
                raise ValueError('DM4 primitive array encoding disagrees with image dtype')
            elements = 1
            for size in dimensions:
                elements *= size
            if elements * itemsize != payload['bytes'] or elements != payload['descriptor'][2]:
                raise ValueError('DM4 dimensions and payload byte/count metadata disagree')
            axes = []
            for dm_dimension, size in enumerate(dimensions):
                calbase = base + ('Calibrations', 'Dimension', str(dm_dimension + 1))
                scale = self.tags.get(calbase + ('Scale',))
                origin = self.tags.get(calbase + ('Origin',))
                unit = self.tags.get(calbase + ('Units',))
                if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale == 0:
                    raise ValueError('Missing/nonfinite DM4 axis scale')
                if not isinstance(origin, (int, float)) or not math.isfinite(origin) or not isinstance(unit, str):
                    raise ValueError('Missing/nonfinite DM4 axis origin/unit')
                axes.append({'dm_dimension': dm_dimension, 'numpy_axis': len(dimensions)-1-dm_dimension,
                             'size': size, 'scale': scale, 'unit': unit, 'raw_pixel_origin': origin,
                             'calibrated_value_at_pixel_zero': -origin * scale})
            result.append({'storage_key': prefix[-1], 'name': self.tags.get(prefix + ('Name',)),
                           'shape': list(reversed(dimensions)), 'dm_dimensions': dimensions,
                           'dtype': dtype, 'data_type_code': code, 'data_offset': payload['offset'],
                           'data_bytes': payload['bytes'], 'calibration': axes})
        return result

    def describe(self):
        return {'path': self.path, 'size_bytes': self.size, 'format': 'DM4 little-endian',
                'reader': 'dm_mcp.dm4_header (seek-only narrow index)',
                'header_bytes_read': self.bytes_read, 'header_entries_visited': self.entries,
                'pixel_payload_read': False, 'datasets': self.datasets}
