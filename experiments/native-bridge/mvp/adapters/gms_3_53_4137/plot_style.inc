// Host line-plot presentation style.
//
// The script-level LinePlotImageDisplaySetHistogramStyle resolves its argument by
// unwrapping the script object and running __RTDynamicCast(..., &Annotation::TD,
// &LinePlotImageDisplay::TD, 0) before calling the internal setter. We already
// hold a native display pointer from the qualified display resolution path, so
// the equivalent work here is:
//   1. prove primary-object RTTI entirely inside the pinned module image,
//   2. call the setter,
//   3. read the same byte back through the host getter.
// Module pattern scans alone do not prove class layout, pointer adjustment or
// field exclusivity. This optional path remains unqualified until independent
// actual-host checks accept the stricter guards below.
PlotStyleGet plot_style_get353 = nullptr;
PlotStyleSet plot_style_set353 = nullptr;
std::uintptr_t gms_base353 = 0;
std::size_t gms_image_bytes353 = 0;
// Name stored in a LinePlotImageDisplay complete object locator.
constexpr char kLinePlotTypeName353[] = ".?AVLinePlotImageDisplay@@";
constexpr std::size_t kLinePlotTypeNameBytes353 = sizeof(kLinePlotTypeName353);
constexpr std::size_t kPlotStyleObjectBytes353 = 0x335;

std::size_t plot_style_module_size353(HMODULE module) {
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    if (!base || !accessible_memory(module, sizeof(IMAGE_DOS_HEADER))) return 0;
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(module);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 1024 * 1024 ||
        base > UINTPTR_MAX - static_cast<std::uint32_t>(dos->e_lfanew)) return 0;
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (!accessible_memory(nt, sizeof(*nt)) || nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC)
        return 0;
    return nt->OptionalHeader.SizeOfImage;
}
bool plot_style_module_memory353(const void* pointer, std::size_t bytes) {
    const auto address = reinterpret_cast<std::uintptr_t>(pointer);
    if (!gms_base353 || !gms_image_bytes353 || !bytes || address < gms_base353 ||
        address - gms_base353 >= gms_image_bytes353 || bytes > gms_image_bytes353 - (address - gms_base353) ||
        !accessible_memory(pointer, bytes)) return false;
    MEMORY_BASIC_INFORMATION region{};
    return VirtualQuery(pointer, &region, sizeof(region)) == sizeof(region) &&
        region.State == MEM_COMMIT && region.Type == MEM_IMAGE &&
        region.AllocationBase == reinterpret_cast<void*>(gms_base353);
}

void initialize_plot_style353(HMODULE gms) noexcept {
    try {
        gms_base353 = reinterpret_cast<std::uintptr_t>(gms);
        gms_image_bytes353 = plot_style_module_size353(gms);
        if (!gms_image_bytes353) throw std::runtime_error("native_plot_style_module_invalid");
        plot_style_get353 = rva_symbol<PlotStyleGet>(gms, entry_rva("plot_style_get"));
        plot_style_set353 = rva_symbol<PlotStyleSet>(gms, entry_rva("plot_style_set"));
    } catch (...) {
        plot_style_get353 = nullptr; plot_style_set353 = nullptr; gms_base353 = 0; gms_image_bytes353 = 0;
    }
}

// Reads the dynamic type name of a native object. The complete object locator is
// the pointer just before the vftable; its type descriptor is a 32-bit image RVA
// at +0x0C and the descriptor stores the decorated name at +0x10.
bool plot_style_type_matches353(void* object, const char* name, std::size_t bytes) {
    if (!object || bytes > 64 || !bytes || !accessible_memory(object, kPlotStyleObjectBytes353, true)) return false;
    const auto table_address = reinterpret_cast<std::uintptr_t>(*static_cast<void**>(object));
    if (table_address < sizeof(void*) || !plot_style_module_memory353(reinterpret_cast<const void*>(table_address - sizeof(void*)), 2 * sizeof(void*)))
        return false;
    const auto* locator = *reinterpret_cast<const unsigned char* const*>(table_address - sizeof(void*));
    if (!plot_style_module_memory353(locator, 24)) return false;
    // A decorated complete type name does not adjust a secondary base pointer.
    // Only the primary, non-construction object is admitted here.
    const auto* fields = reinterpret_cast<const std::uint32_t*>(locator);
    if (fields[0] != 1 || fields[1] != 0 || fields[2] != 0 ||
        fields[5] != reinterpret_cast<std::uintptr_t>(locator) - gms_base353) return false;
    const auto descriptor_rva = *reinterpret_cast<const std::uint32_t*>(locator + 0x0C);
    if (!descriptor_rva || descriptor_rva >= gms_image_bytes353 || fields[4] >= gms_image_bytes353) return false;
    if (!fields[4] || !plot_style_module_memory353(reinterpret_cast<const void*>(gms_base353 + fields[4]), 16)) return false;
    const auto* descriptor = reinterpret_cast<const unsigned char*>(gms_base353 + descriptor_rva);
    if (!plot_style_module_memory353(descriptor, 0x10 + bytes)) return false;
    return std::memcmp(descriptor + 0x10, name, bytes) == 0;
}

const char* apply_histogram_style353(const NativeRef& image, const char** reason) {
    *reason = "";
    if (!plot_style_get353 || !plot_style_set353 || !gms_base353) { *reason = "style_entrypoints_unavailable"; return "default"; }
    if (!roi_api353.display_count || !roi_api353.display_at || !roi_api353.resolve_display ||
        !roi_api353.display_image || !roi_api353.destroy_display) {
        *reason = "display_resolution_unavailable"; return "default";
    }
    NativeRef filter{};
    const auto count = roi_api353.display_count(&image, &filter);
    if (!count) { *reason = "document_has_no_display"; return "default"; }
    if (count > 4) { *reason = "display_count_over_budget"; return "default"; }
    for (std::uint32_t index = 0; index < count; ++index) {
        require_ready();
        ShowRef holder(roi_api353.display_at(image.image, index), 0, roi_api353.destroy_display);
        if (!holder.value) { *reason = "display_holder_missing"; return "default"; }
        try { validate_roi_object353(holder.value, sizeof(nb::RoiComponentHolder353)); }
        catch (...) { holder.abandon_invalid_layout(); throw; }
        auto* display = roi_api353.resolve_display(holder.value);
        if (!display) continue;
        ImageRef back;
        back.value.image = roi_api353.display_image(holder.value);
        if (!back.value.image) continue;
        try { validate_roi_object353(back.value.image, sizeof(std::int64_t)); }
        catch (...) { back.relinquish(); throw; }
        const bool same = back.value.image == image.image && api.id(back.value.image) == api.id(image.image);
        if (!same) continue;
        // A raster display also has a byte at the same offset; refuse anything
        // that is not proven to be the host's line plot object.
        if (!plot_style_type_matches353(display, kLinePlotTypeName353, kLinePlotTypeNameBytes353)) {
            *reason = "display_is_not_a_line_plot"; return "default";
        }
        if (plot_style_get353(display)) return "histogram";
        plot_style_set353(display, true);
        require_ready();
        if (!plot_style_get353(display)) { *reason = "style_flag_did_not_read_back"; return "default"; }
        return "histogram";
    }
    *reason = "display_for_image_not_found";
    return "default";
}
