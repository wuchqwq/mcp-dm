"""Read-only static PE inspection.

This module never loads the inspected module, never resolves an address and
never executes bytes from the target file. It only reads a byte range from a
caller-named file and decodes documented PE/COFF structures.

Python 3.7 compatible; standard library only.
"""
import hashlib
import mmap
import os
import struct

MACHINE_NAMES = {
    0x014C: "x86",
    0x8664: "x64",
    0xAA64: "arm64",
    0x01C4: "arm",
    0x0200: "ia64",
}

FORMAT_NAMES = {0x10B: "pe32", 0x20B: "pe32+"}

_DIR_EXPORT = 0
_DIR_IMPORT = 1
_DIR_RESOURCE = 2
_DIR_DELAY_IMPORT = 13

_RT_VERSION = 16
_VS_FIXEDFILEINFO_SIGNATURE = 0xFEEF04BD
_SCN_MEM_EXECUTE = 0x20000000

DEFAULT_MAX_FILE_BYTES = 1024 * 1024 * 1024
_MAX_SECTIONS = 256
_MAX_EXPORTS = 262144
_MAX_IMPORT_DESCRIPTORS = 4096
_MAX_NAME_BYTES = 1024
_MAX_RESOURCE_DEPTH = 3
_MAX_RESOURCE_ENTRIES = 4096
_MAX_RESOURCE_BYTES = 1024 * 1024


class PeFormatError(Exception):
    """Stable, machine-readable inspection failure.

    ``code`` is the stable identifier reported to callers. ``detail`` is a
    bounded hint that never contains an absolute path.
    """

    def __init__(self, code, detail=""):
        Exception.__init__(self, code if not detail else "%s: %s" % (code, detail))
        self.code = code
        self.detail = detail


def _u16(blob, offset):
    return struct.unpack_from("<H", blob, offset)[0]


def _u32(blob, offset):
    return struct.unpack_from("<I", blob, offset)[0]


def _u64(blob, offset):
    return struct.unpack_from("<Q", blob, offset)[0]


def _cstring(blob, offset, limit=_MAX_NAME_BYTES):
    """Bounded NUL-terminated ASCII read with deterministic replacement."""
    end = offset
    stop = min(len(blob), offset + limit)
    while end < stop and blob[end] != 0:
        end += 1
    return blob[offset:end].decode("ascii", "backslashreplace")


def sha256_of_file(handle):
    digest = hashlib.sha256()
    handle.seek(0)
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def _join_version(ms, ls):
    return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


class Section(object):
    __slots__ = ("name", "virtual_address", "virtual_size", "raw_size", "raw_pointer",
                 "characteristics")

    def __init__(self, name, virtual_address, virtual_size, raw_size, raw_pointer,
                 characteristics):
        self.name = name
        self.virtual_address = virtual_address
        self.virtual_size = virtual_size
        self.raw_size = raw_size
        self.raw_pointer = raw_pointer
        self.characteristics = characteristics

    @property
    def executable(self):
        return bool(self.characteristics & _SCN_MEM_EXECUTE)

    def as_dict(self):
        return {
            "name": self.name,
            "virtual_address": self.virtual_address,
            "virtual_size": self.virtual_size,
            "raw_size": self.raw_size,
            "characteristics": "0x%08x" % self.characteristics,
            "executable": self.executable,
        }


class PeImage(object):
    """Parsed, immutable view over a mapped PE file.

    Use :meth:`open` as a context manager. ``close`` only releases the mapping;
    it never unmaps or unloads a running process module.
    """

    def __init__(self, path, max_file_bytes=DEFAULT_MAX_FILE_BYTES):
        self.path = path
        self.max_file_bytes = max_file_bytes
        self.size_bytes = 0
        self.sha256 = None
        self.machine = 0
        self.machine_name = "unknown"
        self.format_name = "unknown"
        self.subsystem = 0
        self.timestamp = 0
        self.characteristics = 0
        self.image_base = 0
        self.size_of_image = 0
        self.sections = []
        self.data_directories = []
        self.version = {"file_version": None, "product_version": None, "source": "absent"}
        self._file = None
        self._map = None
        self._exports = None
        self._imports = None

    @classmethod
    def open(cls, path, max_file_bytes=DEFAULT_MAX_FILE_BYTES):
        image = cls(path, max_file_bytes)
        image._load()
        return image

    def close(self):
        if self._map is not None:
            try:
                self._map.close()
            finally:
                self._map = None
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # -- bounded access ----------------------------------------------------
    def _slice(self, offset, size, code="pe_truncated"):
        if offset < 0 or size < 0 or offset + size > len(self._map):
            raise PeFormatError(code)
        return self._map[offset:offset + size]

    def _load(self):
        try:
            info = os.stat(self.path)
        except OSError:
            raise PeFormatError("pe_file_missing")
        if not os.path.isfile(self.path):
            raise PeFormatError("pe_not_a_file")
        if info.st_size <= 0:
            raise PeFormatError("pe_file_empty")
        if info.st_size > self.max_file_bytes:
            raise PeFormatError("pe_file_too_large")
        self.size_bytes = info.st_size
        try:
            self._file = open(self.path, "rb")
        except OSError:
            raise PeFormatError("pe_file_unreadable")
        try:
            self.sha256 = sha256_of_file(self._file)
            self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            self._parse_headers()
            self.version = self._parse_version_resource()
        except PeFormatError:
            self.close()
            raise
        except (struct.error, ValueError, IndexError):
            self.close()
            raise PeFormatError("pe_structure_invalid")
        except OSError:
            self.close()
            raise PeFormatError("pe_file_unreadable")
        except Exception:
            self.close()
            raise PeFormatError("pe_structure_invalid")

    # -- headers -----------------------------------------------------------
    def _parse_headers(self):
        if len(self._map) < 64:
            raise PeFormatError("pe_dos_header_truncated")
        if _u16(self._map, 0) != 0x5A4D:
            raise PeFormatError("pe_dos_magic")
        lfanew = _u32(self._map, 0x3C)
        if lfanew < 64 or lfanew + 24 > len(self._map):
            raise PeFormatError("pe_lfanew_out_of_range")
        if _u32(self._map, lfanew) != 0x00004550:
            raise PeFormatError("pe_nt_signature")
        header = lfanew + 4
        self.machine = _u16(self._map, header)
        self.machine_name = MACHINE_NAMES.get(self.machine, "unknown")
        section_count = _u16(self._map, header + 2)
        self.timestamp = _u32(self._map, header + 4)
        optional_size = _u16(self._map, header + 16)
        self.characteristics = _u16(self._map, header + 18)
        if section_count == 0:
            raise PeFormatError("pe_section_table_empty")
        if section_count > _MAX_SECTIONS:
            raise PeFormatError("pe_section_table_too_many")
        optional = header + 20
        if optional_size < 2 or optional + optional_size > len(self._map):
            raise PeFormatError("pe_optional_header_truncated")
        magic = _u16(self._map, optional)
        if magic not in FORMAT_NAMES:
            raise PeFormatError("pe_optional_magic_unsupported")
        self.format_name = FORMAT_NAMES[magic]
        if magic == 0x20B:
            if optional_size < 112:
                raise PeFormatError("pe_optional_header_truncated")
            self.image_base = _u64(self._map, optional + 24)
            self.subsystem = _u16(self._map, optional + 68)
            directory_count = _u32(self._map, optional + 108)
            directory_offset = optional + 112
        else:
            if optional_size < 96:
                raise PeFormatError("pe_optional_header_truncated")
            self.image_base = _u32(self._map, optional + 28)
            self.subsystem = _u16(self._map, optional + 68)
            directory_count = _u32(self._map, optional + 92)
            directory_offset = optional + 96
        self.size_of_image = _u32(self._map, optional + 56)
        for index in range(min(directory_count, 16)):
            entry = directory_offset + index * 8
            if entry + 8 > optional + optional_size:
                raise PeFormatError("pe_data_directory_truncated")
            self.data_directories.append((_u32(self._map, entry), _u32(self._map, entry + 4)))
        table = optional + optional_size
        if table + section_count * 40 > len(self._map):
            raise PeFormatError("pe_section_table_truncated")
        for index in range(section_count):
            base = table + index * 40
            self.sections.append(Section(
                _cstring(self._map, base, 8),
                _u32(self._map, base + 12),
                _u32(self._map, base + 8),
                _u32(self._map, base + 16),
                _u32(self._map, base + 20),
                _u32(self._map, base + 36),
            ))
        if not self.sections:
            raise PeFormatError("pe_section_table_empty")

    def directory(self, index):
        if index >= len(self.data_directories):
            return (0, 0)
        return self.data_directories[index]

    def section_for_rva(self, rva):
        for section in self.sections:
            if section.virtual_address <= rva < section.virtual_address + max(
                    section.virtual_size, section.raw_size):
                return section
        return None

    def rva_to_offset(self, rva, size=1):
        if rva < 0:
            raise PeFormatError("pe_rva_unmapped")
        section = self.section_for_rva(rva)
        if section is None:
            # Only header-resident tables may live before the first section.
            if rva + size <= self.sections[0].virtual_address:
                self._slice(rva, size)
                return rva
            raise PeFormatError("pe_rva_unmapped")
        delta = rva - section.virtual_address
        if delta >= section.raw_size or delta + size > section.raw_size:
            raise PeFormatError("pe_rva_unmapped")
        offset = section.raw_pointer + delta
        if offset + size > len(self._map):
            raise PeFormatError("pe_truncated")
        return offset

    # -- exports -----------------------------------------------------------
    @property
    def exports(self):
        if self._exports is None:
            self._exports = self._parse_exports()
        return self._exports

    def _parse_exports(self):
        rva, size = self.directory(_DIR_EXPORT)
        if rva == 0 or size == 0:
            return []
        offset = self.rva_to_offset(rva, 40)
        blob = self._slice(offset, 40, "pe_export_directory_invalid")
        ordinal_base = _u32(blob, 16)
        function_count = _u32(blob, 20)
        name_count = _u32(blob, 24)
        functions_rva = _u32(blob, 28)
        names_rva = _u32(blob, 32)
        ordinals_rva = _u32(blob, 36)
        if function_count > _MAX_EXPORTS or name_count > _MAX_EXPORTS:
            raise PeFormatError("pe_export_table_too_large")
        if function_count and name_count > function_count:
            raise PeFormatError("pe_export_name_ordinal_mismatch")
        functions = self._read_u32_array(functions_rva, function_count,
                                         "pe_export_table_invalid")
        names = self._read_u32_array(names_rva, name_count, "pe_export_table_invalid")
        ordinals = self._read_u16_array(ordinals_rva, name_count, "pe_export_table_invalid")
        by_index = {}
        for position in range(name_count):
            index = ordinals[position]
            if index >= function_count:
                raise PeFormatError("pe_export_name_ordinal_mismatch")
            if names[position]:
                by_index[index] = self._read_name(names[position])
        entries = []
        for index in range(function_count):
            target = functions[index]
            if target == 0:
                continue
            item = {
                "ordinal": ordinal_base + index,
                "name": by_index.get(index),
                "rva": target,
                "section": None,
                "executable": False,
                "forwarder": None,
            }
            if rva <= target < rva + size:
                item["forwarder"] = self._read_name(target)
            else:
                section = self.section_for_rva(target)
                if section is not None:
                    item["section"] = section.name
                    item["executable"] = section.executable
            entries.append(item)
        entries.sort(key=lambda entry: (entry["ordinal"], entry["name"] or ""))
        return entries

    def _read_u32_array(self, rva, count, code):
        if count == 0:
            return []
        offset = self.rva_to_offset(rva, count * 4)
        return list(struct.unpack_from("<%dI" % count, self._slice(offset, count * 4, code), 0))

    def _read_u16_array(self, rva, count, code):
        if count == 0:
            return []
        offset = self.rva_to_offset(rva, count * 2)
        return list(struct.unpack_from("<%dH" % count, self._slice(offset, count * 2, code), 0))

    def _read_name(self, rva):
        return _cstring(self._map, self.rva_to_offset(rva, 1))

    # -- imports -----------------------------------------------------------
    @property
    def imports(self):
        if self._imports is None:
            self._imports = self._parse_imports()
        return self._imports

    def _parse_imports(self):
        found = {}
        self._collect_imports(self.directory(_DIR_IMPORT), False, found)
        self._collect_imports(self.directory(_DIR_DELAY_IMPORT), True, found)
        modules = []
        for name in sorted(found):
            record = found[name]
            modules.append({
                "module": name,
                "kind": record["kind"],
                "function_count": record["function_count"],
                "thunk_count_bounded": record["thunk_count_bounded"],
            })
        return modules

    def _collect_imports(self, directory, delay, found):
        rva, size = directory
        if rva == 0 or size == 0:
            return
        step = 32 if delay else 20
        for index in range(_MAX_IMPORT_DESCRIPTORS):
            entry_rva = rva + index * step
            offset = self.rva_to_offset(entry_rva, step)
            blob = self._slice(offset, step, "pe_import_directory_invalid")
            if not any(blob):
                return
            if delay:
                attributes = _u32(blob, 0)
                name_field = _u32(blob, 4)
                thunk_field = _u32(blob, 16)
                if not attributes & 0x1:
                    name_field = self._va_to_rva(name_field)
                    thunk_field = self._va_to_rva(thunk_field)
            else:
                name_field = _u32(blob, 12)
                thunk_field = _u32(blob, 0) or _u32(blob, 16)
            if name_field == 0:
                raise PeFormatError("pe_import_directory_invalid")
            module = self._read_name(name_field)
            count, bounded = self._count_thunks(thunk_field)
            kind = "delay_import" if delay else "import"
            record = found.get(module)
            if record is None:
                record = {"kind": kind, "function_count": 0, "thunk_count_bounded": False}
                found[module] = record
            elif record["kind"] != kind:
                record["kind"] = "import+delay_import"
            record["function_count"] = max(record["function_count"], count)
            record["thunk_count_bounded"] = record["thunk_count_bounded"] or bounded
        raise PeFormatError("pe_import_directory_too_large")

    def _va_to_rva(self, value):
        if value < self.image_base:
            raise PeFormatError("pe_import_directory_invalid")
        return value - self.image_base

    def _count_thunks(self, thunk_rva):
        """Count imported names/slots without following them.

        A thunk table is not executed or resolved; only its zero terminator is
        located. Returns ``(count, bounded)`` where ``bounded`` means the scan
        stopped at the per-module budget instead of at a terminator.
        """
        if thunk_rva == 0:
            return (0, True)
        width = 8 if self.format_name == "pe32+" else 4
        try:
            offset = self.rva_to_offset(thunk_rva, width)
        except PeFormatError:
            return (0, True)
        count = 0
        while count < 65536:
            if offset + width > len(self._map):
                return (count, True)
            value = _u64(self._map, offset) if width == 8 else _u32(self._map, offset)
            if value == 0:
                return (count, False)
            count += 1
            offset += width
        return (count, True)

    # -- version resource --------------------------------------------------
    def _parse_version_resource(self):
        result = {"file_version": None, "product_version": None, "source": "absent"}
        rva, size = self.directory(_DIR_RESOURCE)
        if rva == 0 or size == 0:
            return result
        try:
            data = self._find_version_resource(rva)
        except PeFormatError:
            result["source"] = "invalid_resource_directory"
            return result
        if data is None:
            return result
        try:
            fixed = self._read_vs_fixedfileinfo(data)
        except PeFormatError:
            result["source"] = "invalid_version_resource"
            return result
        if fixed is None:
            result["source"] = "version_resource_without_fixed_info"
            return result
        result["file_version"] = fixed[0]
        result["product_version"] = fixed[1]
        result["source"] = "vs_fixed_file_info"
        return result

    def _find_version_resource(self, base_rva):
        root = self.rva_to_offset(base_rva, 16)
        count = _u16(self._map, root + 12) + _u16(self._map, root + 14)
        if count == 0 or count > _MAX_RESOURCE_ENTRIES:
            raise PeFormatError("pe_resource_directory_invalid")
        target = None
        for index in range(count):
            entry = root + 16 + index * 8
            if entry + 8 > len(self._map):
                raise PeFormatError("pe_resource_directory_invalid")
            name = _u32(self._map, entry)
            if name & 0x80000000:
                continue
            if name == _RT_VERSION:
                target = _u32(self._map, entry + 4)
                break
        if target is None:
            return None
        if not target & 0x80000000:
            raise PeFormatError("pe_resource_directory_invalid")
        return self._descend_resource(base_rva, base_rva + (target & 0x7FFFFFFF), 0)

    def _descend_resource(self, base_rva, directory_rva, depth):
        if depth > _MAX_RESOURCE_DEPTH:
            raise PeFormatError("pe_resource_directory_invalid")
        offset = self.rva_to_offset(directory_rva, 16)
        count = _u16(self._map, offset + 12) + _u16(self._map, offset + 14)
        if count == 0 or count > _MAX_RESOURCE_ENTRIES:
            raise PeFormatError("pe_resource_directory_invalid")
        target = _u32(self._map, offset + 20)
        if target & 0x80000000:
            return self._descend_resource(base_rva, base_rva + (target & 0x7FFFFFFF), depth + 1)
        data_entry = self.rva_to_offset(base_rva + target, 16)
        data_rva = _u32(self._map, data_entry)
        data_size = _u32(self._map, data_entry + 4)
        if data_size == 0 or data_size > _MAX_RESOURCE_BYTES:
            raise PeFormatError("pe_resource_data_invalid")
        data_offset = self.rva_to_offset(data_rva, data_size)
        return self._slice(data_offset, data_size, "pe_resource_data_invalid")

    def _read_vs_fixedfileinfo(self, data):
        if len(data) < 40:
            raise PeFormatError("pe_version_resource_invalid")
        length = _u16(data, 0)
        value_length = _u16(data, 2)
        if length < 40 or length > len(data):
            raise PeFormatError("pe_version_resource_invalid")
        key = self._read_utf16z(data, 6)
        if key != "VS_VERSION_INFO":
            raise PeFormatError("pe_version_resource_invalid")
        cursor = (6 + (len(key) + 1) * 2 + 3) & ~3
        if cursor + 52 > length or value_length < 52:
            raise PeFormatError("pe_version_resource_invalid")
        if _u32(data, cursor) != _VS_FIXEDFILEINFO_SIGNATURE:
            raise PeFormatError("pe_version_resource_invalid")
        return (_join_version(_u32(data, cursor + 8), _u32(data, cursor + 12)),
                _join_version(_u32(data, cursor + 16), _u32(data, cursor + 20)))

    @staticmethod
    def _read_utf16z(data, offset, limit=64):
        chars = []
        cursor = offset
        while cursor + 1 < len(data) and len(chars) < limit:
            code = _u16(data, cursor)
            if code == 0:
                return "".join(chars)
            chars.append(chr(code))
            cursor += 2
        raise PeFormatError("pe_version_resource_invalid")


def inspect_module(path, max_file_bytes=DEFAULT_MAX_FILE_BYTES):
    """Return one manifest module record for ``path``. Static and read-only."""
    with PeImage.open(path, max_file_bytes=max_file_bytes) as image:
        exports = image.exports
        record = {
            "name": os.path.basename(path),
            "size_bytes": image.size_bytes,
            "sha256": image.sha256,
            "architecture": image.machine_name,
            "pe": {
                "format": image.format_name,
                "machine": "0x%04x" % image.machine,
                "subsystem": image.subsystem,
                "timestamp": image.timestamp,
                "characteristics": "0x%04x" % image.characteristics,
                "image_base": image.image_base,
                "size_of_image": image.size_of_image,
                "sections": [section.as_dict() for section in image.sections],
            },
            "version": image.version,
            "exports": exports,
            "export_summary": {
                "count": len(exports),
                "named": len([item for item in exports if item["name"]]),
                "unnamed": len([item for item in exports if not item["name"]]),
                "forwarded": len([item for item in exports if item["forwarder"]]),
                "in_executable_section": len([item for item in exports if item["executable"]]),
            },
            "imports": image.imports,
        }
    return record
