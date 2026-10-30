"""Synthetic PE fixtures for offline gms-compat tests.

Nothing here contains vendor code, vendor names or real binaries. Every byte is
generated below so the tests can run anywhere and remain reviewable. The files
are structurally valid PE images with an export table, import table and an
optional VS_VERSIONINFO resource.
"""
import os
import struct

_MACHINES = {"x86": 0x014C, "x64": 0x8664, "arm64": 0xAA64}
_SECTION_RVA = 0x1000
_RAW_POINTER = 0x400
_SECTION_CHARACTERISTICS = 0x60000020  # code | execute | read
_DATA_CHARACTERISTICS = 0x40000040  # initialized data | read


def _align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


class _Blob(object):
    """Append-only section builder that hands out RVAs."""

    def __init__(self):
        self.data = bytearray()

    def tell(self):
        return _SECTION_RVA + len(self.data)

    def pad(self, boundary):
        while len(self.data) % boundary:
            self.data.append(0)

    def add(self, payload, boundary=4):
        self.pad(boundary)
        rva = self.tell()
        self.data.extend(payload)
        return rva

    def reserve(self, size, boundary=4):
        return self.add(b"\x00" * size, boundary)

    def patch(self, rva, payload):
        offset = rva - _SECTION_RVA
        self.data[offset:offset + len(payload)] = payload

    def cstring(self, text):
        return self.add(text.encode("ascii") + b"\x00", 2)


def _utf16z(text):
    return text.encode("utf-16-le") + b"\x00\x00"


def _version_info(file_version, product_version):
    fixed = struct.pack(
        "<13I", 0xFEEF04BD, 0x00010000,
        (file_version[0] << 16) | file_version[1],
        (file_version[2] << 16) | file_version[3],
        (product_version[0] << 16) | product_version[1],
        (product_version[2] << 16) | product_version[3],
        0x3F, 0, 0x40004, 1, 0, 0, 0)
    key = _utf16z("VS_VERSION_INFO")
    header_length = 6 + len(key)
    header_length = _align(header_length, 4)
    total = header_length + len(fixed)
    header = struct.pack("<HHH", total, len(fixed), 0) + key
    header += b"\x00" * (_align(len(header), 4) - len(header))
    return header + fixed


def _resource_section(blob, version_payload):
    """Emit a minimal RT_VERSION resource tree and return its root RVA."""
    base_rva = blob.tell()
    # Layout: root dir, type dir, name dir, data entry, payload.
    root_offset = 0
    type_dir_offset = 24
    name_dir_offset = 48
    data_entry_offset = 72
    payload_offset = 88

    root = struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1)
    root += struct.pack("<II", 16, type_dir_offset | 0x80000000)
    type_dir = struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1)
    type_dir += struct.pack("<II", 1, name_dir_offset | 0x80000000)
    name_dir = struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1)
    name_dir += struct.pack("<II", 0x409, data_entry_offset)
    data_entry = struct.pack("<IIII", base_rva + payload_offset, len(version_payload),
                             0, 0)
    assert len(root) == 24 and len(type_dir) == 24 and len(name_dir) == 24
    assert len(data_entry) == 16 and data_entry_offset < payload_offset
    blob.add(root + type_dir + name_dir + data_entry, 4)
    blob.add(version_payload, 4)
    return base_rva


def build_pe_bytes(machine="x64", file_version=(3, 53, 4137, 0),
                   product_version=None, exports=None, imports=None,
                   with_version=True, ordinal_base=1, stub_padding=0):
    """Return a complete PE image as bytes.

    ``exports`` is a list of dicts: ``{"name": str, "forward": str|None}``.
    A ``forward`` export is written as a forwarder string inside the export
    directory range; otherwise the RVA points at a small deterministic stub.
    ``stub_padding`` shifts every non-forwarded export RVA, which lets tests
    model "same name, different address" without changing anything else.
    """
    exports = list(exports or [])
    imports = dict(imports or {})
    product_version = product_version or file_version
    is_64 = machine != "x86"
    machine_code = _MACHINES[machine]
    blob = _Blob()

    if stub_padding:
        blob.add(b"\x00" * stub_padding, 16)
    code = blob.add(b"\x90\xc3" * 8, 16)  # 8 deterministic 2-byte stubs
    stub_rvas = [code + index * 2 for index in range(8)]

    export_dir_rva = blob.reserve(40, 4)
    forwarder_rvas = []
    for entry in exports:
        if entry.get("forward"):
            forwarder_rvas.append(blob.cstring(entry["forward"]))
        else:
            forwarder_rvas.append(None)
    names_rva = [blob.cstring(entry["name"]) for entry in exports]
    forward_end = blob.tell()
    export_dir_size = max(forward_end - export_dir_rva, 40)

    function_table = blob.reserve(max(len(exports), 1) * 4, 4)
    name_table = blob.reserve(max(len(exports), 1) * 4, 4)
    ordinal_table = blob.reserve(max(len(exports), 1) * 2, 4)

    functions = []
    for index, entry in enumerate(exports):
        if entry.get("forward"):
            functions.append(forwarder_rvas[index])
        else:
            functions.append(stub_rvas[index % len(stub_rvas)])
    if exports:
        blob.patch(function_table, struct.pack("<%dI" % len(exports), *functions))
        blob.patch(name_table, struct.pack("<%dI" % len(exports), *names_rva))
        blob.patch(ordinal_table, struct.pack("<%dH" % len(exports),
                                              *range(len(exports))))
    blob.patch(export_dir_rva, struct.pack(
        "<IIHHIIIIIII", 0, 0, 0, 0, 0, ordinal_base,
        len(exports), len(exports), function_table, name_table, ordinal_table))

    # Import table: one descriptor per module plus a null terminator.
    import_rvas = {}
    for module, symbols in imports.items():
        thunk_rva = blob.reserve((len(symbols) + 1) * (8 if is_64 else 4), 4)
        width = 8 if is_64 else 4
        hints = []
        for symbol in symbols:
            hints.append(blob.cstring(symbol))
        values = [hint for hint in hints] + [0]
        if width == 8:
            blob.patch(thunk_rva, struct.pack("<%dQ" % len(values), *values))
        else:
            blob.patch(thunk_rva, struct.pack("<%dI" % len(values), *values))
        import_rvas[module] = (thunk_rva, blob.cstring(module))
    descriptors = []
    for module in sorted(import_rvas):
        thunk_rva, name_rva = import_rvas[module]
        descriptors.append((thunk_rva, 0, 0, name_rva, thunk_rva))
    import_dir_rva = 0
    import_dir_size = 0
    if descriptors:
        import_dir_rva = blob.reserve((len(descriptors) + 1) * 20, 4)
        payload = b"".join(struct.pack("<IIIII", *item) for item in descriptors)
        payload += b"\x00" * 20
        blob.patch(import_dir_rva, payload)
        import_dir_size = len(payload)

    resource_rva = 0
    resource_size = 0
    if with_version:
        resource_rva = _resource_section(blob, _version_info(file_version,
                                                             product_version))
        resource_size = blob.tell() - resource_rva

    section_payload = bytes(blob.data)
    section_size = _align(len(section_payload), 0x200)
    section_payload += b"\x00" * (section_size - len(section_payload))

    optional_size = 0xF0 if is_64 else 0xE0
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    headers = bytearray(24)
    headers[0:4] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", headers, 4, machine_code, 1, 0x5F000000, 0, 0,
                     optional_size, 0x0022)
    optional = bytearray(optional_size)
    struct.pack_into("<H", optional, 0, 0x20B if is_64 else 0x10B)
    struct.pack_into("<I", optional, 16, _SECTION_RVA)          # AddressOfEntryPoint
    struct.pack_into("<I", optional, 20, _SECTION_RVA)          # BaseOfCode
    if is_64:
        struct.pack_into("<Q", optional, 24, 0x140000000)       # ImageBase
        struct.pack_into("<I", optional, 32, 0x1000)            # SectionAlignment
        struct.pack_into("<I", optional, 36, 0x200)             # FileAlignment
        struct.pack_into("<I", optional, 56, _align(_SECTION_RVA + section_size, 0x1000))
        struct.pack_into("<I", optional, 60, 0x400)             # SizeOfHeaders
        struct.pack_into("<H", optional, 68, 3)                 # Subsystem: console
        struct.pack_into("<I", optional, 108, 16)               # NumberOfRvaAndSizes
        directory_offset = 112
    else:
        struct.pack_into("<I", optional, 28, 0x400000)
        struct.pack_into("<I", optional, 32, 0x1000)
        struct.pack_into("<I", optional, 36, 0x200)
        struct.pack_into("<I", optional, 56, _align(_SECTION_RVA + section_size, 0x1000))
        struct.pack_into("<I", optional, 60, 0x400)
        struct.pack_into("<H", optional, 68, 3)
        struct.pack_into("<I", optional, 92, 16)
        directory_offset = 96
    struct.pack_into("<I", optional, directory_offset + 0, export_dir_rva)
    struct.pack_into("<I", optional, directory_offset + 4, export_dir_size)
    if import_dir_rva:
        struct.pack_into("<I", optional, directory_offset + 8, import_dir_rva)
        struct.pack_into("<I", optional, directory_offset + 12, import_dir_size)
    if resource_rva:
        struct.pack_into("<I", optional, directory_offset + 16, resource_rva)
        struct.pack_into("<I", optional, directory_offset + 20, resource_size)
    section = bytearray(40)
    section[0:8] = b".text\x00\x00\x00"
    struct.pack_into("<IIIIIIHHI", section, 8, len(blob.data), _SECTION_RVA,
                     section_size, _RAW_POINTER, 0, 0, 0, 0, _SECTION_CHARACTERISTICS)

    image = bytes(dos) + bytes(headers) + bytes(optional) + bytes(section)
    image += b"\x00" * (_RAW_POINTER - len(image))
    return image + section_payload


def write_pe(path, **kwargs):
    payload = build_pe_bytes(**kwargs)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path
