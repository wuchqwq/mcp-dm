// Host line-plot presentation style.
//
// The script-level LinePlotImageDisplaySetHistogramStyle resolves its argument by
// unwrapping the script object and running __RTDynamicCast(..., &Annotation::TD,
// &LinePlotImageDisplay::TD, 0) before calling the internal setter. We already
// hold a native display pointer from the qualified display resolution path, so
// the equivalent work here is:
//   1. prove the object's dynamic type through its own RTTI name,
//   2. call the setter,
//   3. read the same byte back through the host getter.
// The flag is a single byte; a scan of the module shows exactly one writer and
// one reader of that field, so nothing else can misinterpret it.
PlotStyleGet plot_style_get353 = nullptr;
PlotStyleSet plot_style_set353 = nullptr;
std::uintptr_t gms_base353 = 0;
// Name stored in a LinePlotImageDisplay complete object locator.
constexpr char kLinePlotTypeName353[] = ".?AVLinePlotImageDisplay@@";
constexpr std::size_t kLinePlotTypeNameBytes353 = sizeof(kLinePlotTypeName353);

void initialize_plot_style353(HMODULE gms) noexcept {
    try {
        gms_base353 = reinterpret_cast<std::uintptr_t>(gms);
        plot_style_get353 = rva_symbol<PlotStyleGet>(gms, entry_rva("plot_style_get"));
        plot_style_set353 = rva_symbol<PlotStyleSet>(gms, entry_rva("plot_style_set"));
    } catch (...) {
        plot_style_get353 = nullptr; plot_style_set353 = nullptr; gms_base353 = 0;
    }
}

// Reads the dynamic type name of a native object. The complete object locator is
// the pointer just before the vftable; its type descriptor is a 32-bit image RVA
// at +0x0C and the descriptor stores the decorated name at +0x10.
bool plot_style_type_matches353(void* object, const char* name, std::size_t bytes) {
    if (!object || !gms_base353 || !accessible_memory(object, sizeof(void*))) return false;
    auto* vftable = *static_cast<unsigned char**>(object);
    if (!vftable || !accessible_memory(vftable - sizeof(void*), sizeof(void*))) return false;
    auto* locator = *reinterpret_cast<unsigned char**>(vftable - sizeof(void*));
    if (!locator || !accessible_memory(locator, 0x10)) return false;
    const auto descriptor_rva = *reinterpret_cast<const std::uint32_t*>(locator + 0x0C);
    if (!descriptor_rva) return false;
    const auto* descriptor = reinterpret_cast<const unsigned char*>(gms_base353 + descriptor_rva);
    if (!accessible_memory(descriptor, 0x10 + bytes)) return false;
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
        const bool same = back.value.image == image.image;
        back.relinquish();
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
