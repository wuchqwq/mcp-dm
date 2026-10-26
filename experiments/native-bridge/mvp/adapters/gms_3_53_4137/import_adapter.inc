// Exact-profile numerical data handoff only. No processing algorithm, raw pixel
// pointer, opaque lock object, script execution, file SaveAs or automatic SHOW.
struct ImportApi353 {
    void (*set_real_value)(void*, const nb::NativeDataIndex2D353*, double) = nullptr;
} import_api353;
void initialize_import353(HMODULE image) noexcept {
    try { import_api353.set_real_value = symbol<decltype(import_api353.set_real_value)>(image,
        "?SetRealValue@Image@GMS@@QEAAXAEBVDataIndex@Imaging@Gatan@@N@Z"); }
    catch (...) { import_api353 = ImportApi353{}; }
}
std::string import_digest353(const std::string& bytes) {
    BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    struct Guard { BCRYPT_ALG_HANDLE* a; BCRYPT_HASH_HANDLE* h;
        ~Guard() { if (*h) BCryptDestroyHash(*h); if (*a) BCryptCloseAlgorithmProvider(*a, 0); }
    } guard{&algorithm, &hash};
    unsigned char digest[32]{};
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
        BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) < 0 ||
        BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<char*>(bytes.data())), static_cast<ULONG>(bytes.size()), 0) < 0 ||
        BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0)
        throw std::runtime_error("native_import_hash_failed");
    constexpr char hex[] = "0123456789abcdef"; std::string result;
    for (const auto value : digest) { result += hex[value >> 4]; result += hex[value & 15]; }
    return result;
}
std::wstring import_environment353(const wchar_t* key) {
    const auto count = GetEnvironmentVariableW(key, nullptr, 0);
    if (!count || count > 30000) throw std::runtime_error("native_import_environment_missing_or_over_budget");
    std::wstring value(count, L'\0');
    if (GetEnvironmentVariableW(key, &value[0], count) != count-1)
        throw std::runtime_error("native_import_environment_changed");
    value.resize(count-1); return value;
}
// Packaged Windows clients can virtualize a LOCALAPPDATA subtree without a
// filesystem reparse point. Bind the complete fixed session directory to its
// opened DOS path; exact final-file path/identity checks remain unchanged.
std::wstring import_staging_directory353(const std::wstring& local) {
    for (std::size_t end = 3; end <= local.size(); ++end) {
        if (end != local.size() && local[end] != L'\\') continue;
        const auto prefix = local.substr(0,end); const auto attributes = GetFileAttributesW(prefix.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) || !(attributes & FILE_ATTRIBUTE_DIRECTORY))
            throw std::runtime_error("native_import_local_root_reparse_or_missing_path");
    }
    const auto handle = CreateFileW(local.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ,nullptr,OPEN_EXISTING,
                                    FILE_FLAG_OPEN_REPARSE_POINT|FILE_FLAG_BACKUP_SEMANTICS,nullptr);
    if(handle==INVALID_HANDLE_VALUE)throw std::runtime_error("native_import_local_root_open_failed");
    struct Guard {HANDLE value;~Guard(){CloseHandle(value);}} guard{handle};
    BY_HANDLE_FILE_INFORMATION information{};
    if(!GetFileInformationByHandle(handle,&information)||!(information.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)||
        (information.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT))throw std::runtime_error("native_import_local_root_identity_invalid");
    std::wstring final_path(32768,L'\0');
    const auto length=GetFinalPathNameByHandleW(handle,&final_path[0],static_cast<DWORD>(final_path.size()),FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    if(!length||length>=final_path.size())throw std::runtime_error("native_import_local_root_canonical_unavailable");
    final_path.resize(length);
    if(final_path.size()<7||final_path.compare(0,4,L"\\\\?\\")!=0||final_path[5]!=L':'||final_path[6]!=L'\\'||
       !((final_path[4]>=L'A'&&final_path[4]<=L'Z')||(final_path[4]>=L'a'&&final_path[4]<=L'z'))||final_path.find(L"..")!=std::wstring::npos)
        throw std::runtime_error("native_import_local_root_not_local_dos_path");
    final_path.erase(0,4);while(final_path.size()>3&&final_path.back()==L'\\')final_path.pop_back();return final_path;
}
std::wstring import_root353() {
    auto local = import_environment353(L"LOCALAPPDATA");
    std::replace(local.begin(), local.end(), L'/', L'\\');
    if (local.size() < 3 || local[1] != L':' || local[2] != L'\\' || local.find(L"..") != std::wstring::npos)
        throw std::runtime_error("native_import_requires_local_absolute_root");
    const auto wide_session = import_environment353(L"DM_NATIVE_SESSION");
    const std::string session(wide_session.begin(), wide_session.end());
    if (!std::all_of(wide_session.begin(), wide_session.end(), [](wchar_t c) { return c >= 0 && c <= 127; }) || !nb::valid_session(session))
        throw std::runtime_error("native_import_session_invalid");
    return import_staging_directory353(local + (local.back()==L'\\'?L"mcp-dm\\native-import\\":L"\\mcp-dm\\native-import\\") + wide_session);
}
// Every path component and the opened file are checked. FILE_SHARE_READ refuses
// concurrent writers/deletion; bytes/hash are captured from this same handle.
std::string import_file353(const std::wstring& file, std::size_t maximum) {
    for (std::size_t end = 3; end <= file.size(); ++end) {
        if (end != file.size() && file[end] != L'\\') continue;
        const auto prefix = file.substr(0, end); const auto attributes = GetFileAttributesW(prefix.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) ||
            (end < file.size() && !(attributes & FILE_ATTRIBUTE_DIRECTORY)))
            throw std::runtime_error("native_import_reparse_or_missing_path");
    }
    const auto handle = CreateFileW(file.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                                    FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (handle == INVALID_HANDLE_VALUE) throw std::runtime_error("native_import_file_open_failed");
    struct Guard { HANDLE h; ~Guard() { CloseHandle(h); } } guard{handle};
    BY_HANDLE_FILE_INFORMATION before{}, after{};
    if (!GetFileInformationByHandle(handle, &before) || before.nFileSizeHigh ||
        !before.nFileSizeLow || before.nFileSizeLow > maximum ||
        (before.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)))
        throw std::runtime_error("native_import_invalid_file_size_or_type");
    std::wstring final_path(32768, L'\0');
    const auto length = GetFinalPathNameByHandleW(handle, &final_path[0], static_cast<DWORD>(final_path.size()), FILE_NAME_NORMALIZED);
    if (!length || length >= final_path.size()) throw std::runtime_error("native_import_final_path_unavailable");
    final_path.resize(length); const auto expected = L"\\\\?\\" + file;
    if (CompareStringOrdinal(final_path.data(), static_cast<int>(final_path.size()), expected.data(), static_cast<int>(expected.size()), TRUE) != CSTR_EQUAL)
        throw std::runtime_error("native_import_opened_path_changed");
    std::string bytes(before.nFileSizeLow, '\0'); DWORD total = 0;
    while (total < bytes.size()) { DWORD count = 0;
        if (!ReadFile(handle, &bytes[total], static_cast<DWORD>(bytes.size()-total), &count, nullptr) || !count)
            throw std::runtime_error("native_import_short_read");
        total += count;
    }
    if (!GetFileInformationByHandle(handle, &after) || before.nFileIndexHigh != after.nFileIndexHigh ||
        before.nFileIndexLow != after.nFileIndexLow || before.nFileSizeLow != after.nFileSizeLow ||
        before.nFileSizeHigh != after.nFileSizeHigh || before.dwVolumeSerialNumber != after.dwVolumeSerialNumber ||
        CompareFileTime(&before.ftLastWriteTime, &after.ftLastWriteTime) != 0)
        throw std::runtime_error("native_import_file_changed_during_read");
    return bytes;
}
struct ImportPacket353 { nb::ImportSpec353 spec; std::vector<float> pixels; std::string manifest; };
ImportPacket353 load_import353(const NativeRequest& request) {
    auto spec = nb::import_spec353(request.args); const auto root = import_root353();
    const std::wstring ticket(spec.ticket.begin(), spec.ticket.end());
    const auto npy = import_file353(root + L"\\" + ticket + L".npy", nb::kImportBytes353 + nb::kImportHeader353 + 12);
    const auto manifest = import_file353(root + L"\\" + ticket + L".json", nb::kImportManifest353);
    if (import_digest353(npy) != spec.npy_sha256 || import_digest353(manifest) != spec.manifest_sha256)
        throw std::runtime_error("native_import_staged_hash_mismatch");
    const auto first = manifest.find_first_not_of(" \r\n\t"), last = manifest.find_last_not_of(" \r\n\t");
    if (!nb::valid_json(manifest) || first == std::string::npos || manifest[first] != '{' || manifest[last] != '}')
        throw std::runtime_error("native_import_manifest_must_be_utf8_json_object");
    if (nb::quote(manifest).size() > nb::kImportQuotedManifest353)
        throw std::runtime_error("native_import_manifest_encoded_response_over_budget");
    return {spec, nb::import_npy353(npy, spec), manifest};
}
void validate_import_output353(void* image, std::uint32_t id, const nb::ImportSpec353& spec) {
    require_ready();
    if (!id || api.id(image) != id || api.ndim(image) != 2 || api.dtype(image) != 2 ||
        packing_style(image) != 1 || api.dimension(image, 0) != spec.width || api.dimension(image, 1) != spec.height)
        throw std::runtime_error("native_import_output_descriptor_mismatch");
}
std::string execute_import_packet353(const NativeRequest& request, const ImportPacket353& packet) {
    require_ready();
    if (!qualified_capability353("native_numeric_import"))
        throw std::runtime_error("native_operation_not_qualified:native_numeric_import");
    if (!histogram_api353.create_image || !histogram_api353.set_dimension_calibration || !import_api353.set_real_value || !api.real_value || !api.packing)
        throw std::runtime_error("native_import_interface_unavailable");
    const auto spec = nb::import_spec353(request.args);
    if (spec.ticket != packet.spec.ticket || spec.npy_sha256 != packet.spec.npy_sha256 ||
        spec.manifest_sha256 != packet.spec.manifest_sha256 || spec.width != packet.spec.width || spec.height != packet.spec.height ||
        spec.domain != packet.spec.domain || spec.unit != packet.spec.unit ||
        nb::import_bits353(spec.origin[0]) != nb::import_bits353(packet.spec.origin[0]) ||
        nb::import_bits353(spec.origin[1]) != nb::import_bits353(packet.spec.origin[1]) ||
        nb::import_bits353(spec.scale[0]) != nb::import_bits353(packet.spec.scale[0]) ||
        nb::import_bits353(spec.scale[1]) != nb::import_bits353(packet.spec.scale[1]) ||
        packet.pixels.size() != static_cast<std::size_t>(spec.width)*spec.height ||
        packet.manifest.size() > nb::kImportManifest353 || !nb::valid_json(packet.manifest) || import_digest353(packet.manifest) != spec.manifest_sha256)
        throw std::runtime_error("native_import_packet_identity_mismatch");
    for (const auto value : packet.pixels) if (!std::isfinite(value)) throw std::runtime_error("native_import_nonfinite_pixel");
    if (nb::quote(packet.manifest).size() > nb::kImportQuotedManifest353)
        throw std::runtime_error("native_import_manifest_encoded_response_over_budget");
    const auto bytes = static_cast<std::uint64_t>(packet.pixels.size())*4;
    if (retained_results.size() >= nb::kCropRetainedCount || retained_result_bytes > nb::kCropRetainedBytes || bytes > nb::kCropRetainedBytes-retained_result_bytes)
        throw std::runtime_error("native_result_retention_capacity");
    if (!api.count || !api.find_index) throw std::runtime_error("native_import_registry_interface_unavailable");
    const auto count = api.count();
    if (count > 128) throw std::runtime_error("native_import_registry_over_budget");
    std::set<std::uint32_t> prior_ids;
    std::vector<std::unique_ptr<ImageRef>> prior_references;
    for (std::uint32_t i = 0; i < count; ++i) {
        auto held = std::make_unique<ImageRef>(api.find_index, i);
        const auto id = api.id(held->value.image);
        if (!id || !prior_ids.insert(id).second) throw std::runtime_error("native_import_registry_identity_invalid");
        prior_references.push_back(std::move(held));
    }
    if (api.count() != count) throw std::runtime_error("native_import_registry_changed");
    const std::wstring name = L"MCP_IMPORT_" + std::wstring(request.id.begin(), request.id.end());
    const nb::NativeDataSize353 size{2, 0, {spec.width, spec.height, 0, 0, 0}};
    const nb::NativeCharRange353 name_range{name.data(), name.data()+name.size()};
    ImageRef output;
    NativeRef* returned = nullptr;
    try { returned = histogram_api353.create_image(&output.value, &size, 2, &name_range); }
    catch (...) {
        if (output.value.image) {
            try { validate_histogram_owned353(output.value.image); }
            catch (...) { output.relinquish(); throw; }
        }
        throw;
    }
    require_ready();
    if (output.value.image) {
        try { validate_histogram_owned353(output.value.image); }
        catch (...) { output.relinquish(); throw; }
    }
    if (returned != &output.value || !output.value.image) throw std::runtime_error("native_import_null_output");
    const auto output_id = api.id(output.value.image);
    validate_import_output353(output.value.image, output_id, spec);
    if (prior_ids.count(output_id) || retained_results.count(output_id)) throw std::runtime_error("native_import_output_alias");
    for (std::uint32_t y = 0; y < spec.height; ++y) for (std::uint32_t x = 0; x < spec.width; ++x) {
        const nb::NativeDataIndex2D353 index{2, 0, x, y};
        import_api353.set_real_value(output.value.image, &index, static_cast<double>(packet.pixels[static_cast<std::size_t>(y)*spec.width+x]));
        require_ready();
    }
    const auto unit = nb::import_unit353(spec.unit); const nb::NativeCharRange353 unit_range{unit.data(), unit.data()+unit.size()};
    for (unsigned axis = 0; axis < 2; ++axis) {
        // Format 1 accepts raw pixel-index origin; no inverse physical-unit
        // divide is introduced, and signed scale remains the exact binary32.
        histogram_api353.set_dimension_calibration(output.value.image, axis, spec.origin[axis], spec.scale[axis], &unit_range, 1);
        require_ready(); const auto actual = crop_axis_calibration(output.value.image, axis, false);
        const float zero = -(spec.origin[axis]*spec.scale[axis]);
        const auto unit_utf8 = unit.empty() ? std::string{} : [&unit]() {
            const auto count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, unit.data(), static_cast<int>(unit.size()), nullptr, 0, nullptr, nullptr);
            if (count <= 0) throw std::runtime_error("native_import_unit_not_utf8");
            std::string text(count, '\0'); WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, unit.data(), static_cast<int>(unit.size()), &text[0], count, nullptr, nullptr); return text;
        }();
        if (nb::import_bits353(actual.origin) != nb::import_bits353(spec.origin[axis]) ||
            nb::import_bits353(actual.scale) != nb::import_bits353(spec.scale[axis]) ||
            nb::import_bits353(actual.zero) != nb::import_bits353(zero) || actual.unit != unit_utf8)
            throw std::runtime_error("native_import_calibration_readback_mismatch");
    }
    validate_import_output353(output.value.image, output_id, spec);
    for (std::uint32_t y = 0; y < spec.height; ++y) for (std::uint32_t x = 0; x < spec.width; ++x) {
        const nb::NativeDataIndex2D353 index{2, 0, x, y}; const auto actual = api.real_value(output.value.image, &index);
        require_ready(); const auto expected = packet.pixels[static_cast<std::size_t>(y)*spec.width+x];
        if (!std::isfinite(actual) || actual != static_cast<double>(expected) ||
            (expected == 0 && std::signbit(actual) != std::signbit(expected)))
            throw std::runtime_error("native_import_pixel_readback_mismatch");
    }
    validate_import_output353(output.value.image, output_id, spec);
    const auto descriptor = metadata(output.value.image, false);
    auto context = json_stream(); context << "{\"schema_version\":1,\"ticket\":" << nb::quote(spec.ticket)
        << ",\"npy_sha256\":" << nb::quote(spec.npy_sha256) << ",\"manifest_sha256\":" << nb::quote(spec.manifest_sha256)
        << ",\"coordinate_domain\":" << nb::quote(nb::import_domain353(spec.domain)) << ",\"manifest_json\":" << nb::quote(packet.manifest)
        << ",\"scope\":\"external immutable input at import; current DM values remain mutable; no embedded DM tags\"}";
    std::string external_context = context.str();
    auto result = json_stream(); result << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"IMPORT\",\"image_id\":" << output_id
        << ",\"image\":" << descriptor << ",\"shape\":[" << spec.height << ',' << spec.width << "],\"dtype\":\"float32\",\"axes\":[\"y\",\"x\"]"
        << ",\"external_import\":" << external_context << ",\"pixel_readback_exact\":true,\"calibration_readback_exact\":true"
        << ",\"qualification\":\"CANDIDATE_BUILD_NOT_RELEASE_QUALIFIED\""
        << ",\"operator\":\"GMS::Image::CreateImage + GMS::Image::SetRealValue\",\"computation\":\"data handoff only; scientific values computed externally\""
        << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw external numeric values\",\"visible_dm_document\":false,\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto value = result.str(); if (!nb::valid_json(value) || value.size() > nb::kMaxReply-2048) throw std::runtime_error("native_import_result_over_budget");
    retain_native_result(output, output_id, bytes, request, "GMS::Image::CreateImage + GMS::Image::SetRealValue", {}, {}, descriptor,
        "external fixed float32 NPY copied to a new DM image; no numerical processing or source write");
    retained_results.at(output_id).import_context = std::move(external_context);
    return value;
}
std::string execute_import353(const NativeRequest& request) {
    require_ready();
    if (!qualified_capability353("native_numeric_import")) throw std::runtime_error("native_operation_not_qualified:native_numeric_import");
    return execute_import_packet353(request, load_import353(request));
}
