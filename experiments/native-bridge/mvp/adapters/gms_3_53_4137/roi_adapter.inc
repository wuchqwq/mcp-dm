// Include inside the fixed-profile implementation after ImageRef/metadata.
// Fixed native getters only: no Python, evaluator, front image, window search,
// display creation, ROI mutation or generic function-name interface.
struct LineApi353 {
    bool (*is_line)(void*) = nullptr;
    nb::RoiLine353* (*line)(void*, nb::RoiLine353*) = nullptr;
    void* (*extract)(void*,double,double,double,double,std::uint32_t) = nullptr;
    void (*intensity_calibration)(void*,float*,float*,void*) = nullptr;
    double (*real_value)(const void*,const nb::NativeDataIndex1D353*) = nullptr;
    bool ready() const { return is_line && line && extract && intensity_calibration && real_value; }
} line_api353;
struct LineTarget353 {
    std::uint32_t document_id, display_id, roi_id;
    LineTarget353(std::uint32_t doc,std::uint32_t display,std::uint32_t roi) : document_id(doc),display_id(display),roi_id(roi) {}
    bool found = false;
    nb::RoiLine353 line{};
    const char* issue = "native_profile_gui_line_missing";
    std::string json;
};
struct RoiApi353 {
    std::size_t (*display_count)(const NativeRef*, const NativeRef*) = nullptr;
    void* (*display_at)(void*, std::uint32_t) = nullptr;
    void* (*resolve_display)(void*) = nullptr;
    void* (*display_image)(void*) = nullptr;
    std::uint32_t (*roi_count)(void*) = nullptr;
    NativeRef* (*roi_at)(void*, NativeRef*, std::uint32_t) = nullptr;
    std::int32_t (*roi_id)(void*) = nullptr;
    bool (*is_rectangle)(void*) = nullptr;
    nb::RoiRectangle353* (*rectangle)(void*, nb::RoiRectangle353*) = nullptr;
    bool (*selected)(void*, const NativeRef*) = nullptr;
    void (*dimensions)(void*, nb::RoiDimensions353*) = nullptr;
    nb::RoiMapping353* (*mapping)(void*, nb::RoiMapping353*, const NativeRef*) = nullptr;
    nb::RoiSliceId353* (*slice_id)(void*, nb::RoiSliceId353*) = nullptr;
    Delete destroy_display = nullptr, destroy_roi = nullptr;
    const void* raster_vtable = nullptr;
    const void* simple_source_vtable = nullptr;
    const void* simple_source_count = nullptr;
    const void* simple_source_slice_id = nullptr;
    const void* simple_source_extents = nullptr;
    bool ready() const {
        return display_count && display_at && resolve_display && display_image &&
            roi_count && roi_at && roi_id && is_rectangle && rectangle && selected &&
            dimensions && mapping && slice_id && destroy_display && destroy_roi && raster_vtable &&
            simple_source_vtable && simple_source_count && simple_source_slice_id && simple_source_extents;
    }
} roi_api353;

void initialize_roi353(HMODULE module) noexcept {
    try {
        RoiApi353 next;
        next.display_count = rva_symbol<decltype(next.display_count)>(module, entry_rva("roi_image_display_count"));
        next.display_at = rva_symbol<decltype(next.display_at)>(module, entry_rva("roi_image_display_at"));
        next.resolve_display = rva_symbol<decltype(next.resolve_display)>(module, entry_rva("roi_resolve_display"));
        next.display_image = rva_symbol<decltype(next.display_image)>(module, entry_rva("roi_display_image"));
        next.roi_count = rva_symbol<decltype(next.roi_count)>(module, entry_rva("roi_raster_count"));
        next.roi_at = rva_symbol<decltype(next.roi_at)>(module, entry_rva("roi_raster_at"));
        next.roi_id = rva_symbol<decltype(next.roi_id)>(module, entry_rva("roi_id"));
        next.is_rectangle = rva_symbol<decltype(next.is_rectangle)>(module, entry_rva("roi_is_rectangle"));
        next.rectangle = rva_symbol<decltype(next.rectangle)>(module, entry_rva("roi_rectangle"));
        next.selected = rva_symbol<decltype(next.selected)>(module, entry_rva("roi_is_selected"));
        next.dimensions = rva_symbol<decltype(next.dimensions)>(module, entry_rva("roi_raster_dimensions"));
        next.mapping = rva_symbol<decltype(next.mapping)>(module, entry_rva("roi_raster_mapping"));
        next.slice_id = rva_symbol<decltype(next.slice_id)>(module, entry_rva("roi_raster_slice_id"));
        next.destroy_display = rva_symbol<Delete>(module, entry_rva("roi_destroy_display_holder"));
        next.destroy_roi = rva_symbol<Delete>(module, entry_rva("roi_destroy_roi"));
        next.raster_vtable = reinterpret_cast<const unsigned char*>(module) + nb::gms353::kRasterRoiVtableRva353;
        next.simple_source_vtable = reinterpret_cast<const unsigned char*>(module) + nb::gms353::kSimpleImageSourceVtableRva353;
        next.simple_source_count = reinterpret_cast<const void*>(rva_symbol<Delete>(module, entry_rva("roi_simple_source_count")));
        next.simple_source_slice_id = reinterpret_cast<const void*>(rva_symbol<Delete>(module, entry_rva("roi_simple_source_slice_id")));
        next.simple_source_extents = reinterpret_cast<const void*>(rva_symbol<Delete>(module, entry_rva("roi_simple_source_extents")));
        if (!accessible_memory(next.raster_vtable, nb::kRasterRoiGetSlot353 + sizeof(void*)))
            throw std::runtime_error("native_roi_vtable_unreadable");
        const auto* table = static_cast<const unsigned char*>(next.raster_vtable);
        if (*reinterpret_cast<const void* const*>(table + nb::kRasterRoiCountSlot353) != reinterpret_cast<const void*>(next.roi_count) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiGetSlot353) != reinterpret_cast<const void*>(next.roi_at) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiDimensionsSlot353) != reinterpret_cast<const void*>(next.dimensions) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiMappingSlot353) != reinterpret_cast<const void*>(next.mapping) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiSliceIdSlot353) != reinterpret_cast<const void*>(next.slice_id))
            throw std::runtime_error("native_roi_vtable_contract_mismatch");
        const auto* source_table = static_cast<const unsigned char*>(next.simple_source_vtable);
        if (!accessible_memory(source_table, nb::kSimpleSourceExtentsSlot353 + sizeof(void*)) ||
            *reinterpret_cast<const void* const*>(source_table + nb::kSimpleSourceCountSlot353) != next.simple_source_count ||
            *reinterpret_cast<const void* const*>(source_table + nb::kSimpleSourceSliceIdSlot353) != next.simple_source_slice_id ||
            *reinterpret_cast<const void* const*>(source_table + nb::kSimpleSourceExtentsSlot353) != next.simple_source_extents)
            throw std::runtime_error("native_roi_source_vtable_contract_mismatch");
        roi_api353 = next;
    } catch (...) { roi_api353 = RoiApi353{}; }
}

std::int32_t roi_identity_field353(const void* object, std::size_t offset) {
    if (!object || !accessible_memory(object, offset + sizeof(std::int32_t))) {
        fatal_abi = true;
        throw std::runtime_error("native_roi_identity_unreadable");
    }
    const auto value = *reinterpret_cast<const std::int32_t*>(static_cast<const unsigned char*>(object) + offset);
    if (value < 0) throw std::runtime_error("native_roi_identity_invalid");
    return value;
}

void validate_roi_object353(void* value, std::size_t bytes) {
    if (!value || !accessible_memory(value, bytes) || !reference_counter(value, 0) ||
        InterlockedCompareExchange64(reference_counter(value, 0), 0, 0) <= 0) {
        fatal_abi = true;
        throw std::runtime_error("native_roi_invalid_owned_reference");
    }
}

// All references below are borrowed under the retained display holder. No
// refcount is inferred from these pointers and no new virtual call is made.
const void* roi_borrowed_pointer353(const void* object, std::size_t offset) {
    if (!object || !accessible_memory(object, offset + sizeof(void*))) {
        fatal_abi = true; throw std::runtime_error("native_roi_source_layout_unreadable");
    }
    const auto* value = *reinterpret_cast<const void* const*>(static_cast<const unsigned char*>(object) + offset);
    if (!value) throw std::runtime_error("native_roi_source_binding_missing");
    return value;
}
bool roi_direct_source353(void* display, void* image) {
    const auto* source = roi_borrowed_pointer353(display, nb::kRasterImageSourceOffset353);
    const auto* implementation = roi_borrowed_pointer353(source, nb::kImageSourceImplementationOffset353);
    if (roi_borrowed_pointer353(implementation, 0) != roi_api353.simple_source_vtable) return false;
    const auto* table = static_cast<const unsigned char*>(roi_api353.simple_source_vtable);
    if (!accessible_memory(table, nb::kSimpleSourceExtentsSlot353 + sizeof(void*)) ||
        *reinterpret_cast<const void* const*>(table + nb::kSimpleSourceCountSlot353) != roi_api353.simple_source_count ||
        *reinterpret_cast<const void* const*>(table + nb::kSimpleSourceSliceIdSlot353) != roi_api353.simple_source_slice_id ||
        *reinterpret_cast<const void* const*>(table + nb::kSimpleSourceExtentsSlot353) != roi_api353.simple_source_extents) {
        fatal_abi = true; throw std::runtime_error("native_roi_source_vtable_contract_mismatch");
    }
    if (roi_borrowed_pointer353(implementation, nb::kSimpleSourceImageOffset353) != image)
        throw std::runtime_error("native_roi_direct_source_image_mismatch");
    return true;
}

std::string collect_rois353(const NativeRef& image, std::uint32_t image_id,
                           std::uint32_t width, std::uint32_t height, bool include_lines = false, LineTarget353* target = nullptr) {
    NativeRef document_filter{};
    const auto count = roi_api353.display_count(&image, &document_filter);
    if (count > nb::kRoiDisplayLimit353) throw std::runtime_error("native_roi_display_budget");
    std::set<std::pair<std::int32_t, std::int32_t>> displays;
    std::uint32_t total = 0;
    auto out = json_stream(); out << '[';
    for (std::uint32_t index = 0; index < count; ++index) {
        require_ready();
        ShowRef holder(roi_api353.display_at(image.image, index), 0, roi_api353.destroy_display);
        if (!holder.value) throw std::runtime_error("native_roi_display_missing");
        try { validate_roi_object353(holder.value, sizeof(nb::RoiComponentHolder353)); }
        catch (...) { holder.abandon_invalid_layout(); throw; }
        const auto* fields = static_cast<const nb::RoiComponentHolder353*>(holder.value);
        auto* display = roi_api353.resolve_display(holder.value);
        if (!display) throw std::runtime_error("native_roi_display_invalid");
        const auto document_id = roi_identity_field353(fields->document, nb::kDocumentIdentityOffset353);
        const auto display_id = roi_identity_field353(display, nb::kComponentIdentityOffset353);
        if (fields->component_id != display_id || !displays.emplace(document_id, display_id).second)
            throw std::runtime_error("native_roi_display_identity_changed");
        ImageRef back;
        back.value.image = roi_api353.display_image(holder.value);
        if (!back.value.image) throw std::runtime_error("native_roi_reverse_image_missing");
        try { validate_roi_object353(back.value.image, sizeof(std::int64_t)); }
        catch (...) { back.relinquish(); throw; }
        if (back.value.image != image.image || api.id(back.value.image) != image_id)
            throw std::runtime_error("native_roi_reverse_image_mismatch");
        if (index) out << ',';
        out << "{\"document_id\":" << document_id << ",\"display_id\":" << display_id
            << ",\"display_identity\":{\"document_id\":" << document_id << ",\"display_id\":" << display_id << '}';
        if (!accessible_memory(display, sizeof(void*))) {
            fatal_abi = true; throw std::runtime_error("native_roi_display_unreadable");
        }
        if (*static_cast<const void* const*>(display) != roi_api353.raster_vtable) {
            out << ",\"display_type\":\"unsupported\",\"slice_ids\":null,\"source_layout\":null,\"roi_count\":null,\"rois\":[],\"issue\":\"unsupported_display_type\"}";
            continue;
        }
        const auto* table = static_cast<const unsigned char*>(roi_api353.raster_vtable);
        if (!accessible_memory(table, nb::kRasterRoiGetSlot353 + sizeof(void*)) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiCountSlot353) != reinterpret_cast<const void*>(roi_api353.roi_count) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiGetSlot353) != reinterpret_cast<const void*>(roi_api353.roi_at) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiDimensionsSlot353) != reinterpret_cast<const void*>(roi_api353.dimensions) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiMappingSlot353) != reinterpret_cast<const void*>(roi_api353.mapping) ||
            *reinterpret_cast<const void* const*>(table + nb::kRasterRoiSliceIdSlot353) != reinterpret_cast<const void*>(roi_api353.slice_id)) {
            fatal_abi = true; throw std::runtime_error("native_roi_vtable_contract_mismatch");
        }
        // Direct proven raster getter: the vendor SF wrapper's exception-to-zero
        // translation is deliberately bypassed. A native failure is not empty.
        nb::RoiDimensions353 dimensions{};
        roi_api353.dimensions(display, &dimensions);
        if (dimensions.count != 2 || dimensions.valid != 1)
            throw std::runtime_error("native_roi_display_dimensions_mismatch");
        nb::RoiSliceId353 slice_id{};
        if (roi_api353.slice_id(display, &slice_id) != &slice_id || slice_id.count > 5)
            throw std::runtime_error("native_roi_display_slice_id_invalid");
        const bool direct_source = roi_direct_source353(display, image.image);
        const bool standard_slice = slice_id.count == 1 && slice_id.components[0] == 0;
        const auto roi_count = roi_api353.roi_count(display);
        if (roi_count > nb::kRoiPerDisplayLimit353 || roi_count > nb::kRoiTotalLimit353 - total)
            throw std::runtime_error("native_roi_count_budget");
        total += roi_count;
        std::set<std::int32_t> ids;
        out << ",\"display_type\":\"raster\",\"slice_ids\":[";
        for (std::uint32_t axis = 0; axis < slice_id.count; ++axis) { if (axis) out << ','; out << slice_id.components[axis]; }
        out << "],\"source_layout\":" << nb::quote(direct_source ? "direct_image_canonical_xy" : "unsupported")
            << ",\"roi_count\":" << roi_count << ",\"rois\":[";
        for (std::uint32_t roi_index = 0; roi_index < roi_count; ++roi_index) {
            require_ready(); NativeRef acquired;
            ShowRef roi(nullptr, 0, roi_api353.destroy_roi);
            try {
                const auto* returned = roi_api353.roi_at(display, &acquired, roi_index);
                roi.value = acquired.image;
                if (returned != &acquired || !acquired.image) throw std::runtime_error("native_roi_lookup_mismatch");
            } catch (...) {
                // A C-shaped vendor callback can write an owned output before
                // reporting a failure. Validate its complete layout before a
                // final deleter can run, just as on the normal return path.
                roi.value = acquired.image;
                if (roi.value) {
                    try { validate_roi_object353(roi.value, nb::kRoiRotationOffset353 + sizeof(double)); }
                    catch (...) { roi.abandon_invalid_layout(); throw; }
                }
                throw;
            }
            try { validate_roi_object353(roi.value, nb::kRoiRotationOffset353 + sizeof(double)); }
            catch (...) { roi.abandon_invalid_layout(); throw; }
            const auto id = roi_api353.roi_id(roi.value);
            if (id < 0 || !ids.insert(id).second) throw std::runtime_error("native_roi_identity_changed");
            const bool selected = roi_api353.selected(display, &acquired);
            const bool rectangle = roi_api353.is_rectangle(roi.value);
            const bool line = !rectangle && include_lines && line_api353.ready() && line_api353.is_line(roi.value);
            const double rotation = *reinterpret_cast<const double*>(static_cast<const unsigned char*>(roi.value) + nb::kRoiRotationOffset353);
            if (!std::isfinite(rotation)) throw std::runtime_error("native_roi_nonfinite_rotation");
            if (roi_index) out << ',';
            out << "{\"roi_id\":" << id << ",\"selected\":" << (selected ? "true" : "false") << ",\"rotation_degrees\":" << rotation;
            if (line) {
                nb::RoiLine353 raw{};
                if (line_api353.line(roi.value, &raw) != &raw) throw std::runtime_error("native_roi_line_return_mismatch");
                const auto* issue = nb::roi_line_issue353(raw, width, height);
                nb::RoiMapping353 mapping{};
                if (roi_api353.mapping(display, &mapping, &acquired) != &mapping) throw std::runtime_error("native_roi_mapping_return_mismatch");
                for (float value : {mapping.offset_x,mapping.offset_y,mapping.scale_x,mapping.scale_y})
                    if (!std::isfinite(value)) throw std::runtime_error("native_roi_nonfinite_mapping");
                if (!mapping.scale_x || !mapping.scale_y) throw std::runtime_error("native_roi_invalid_mapping");
                const bool standard = mapping.offset_x == 0 && mapping.offset_y == 0 &&
                    mapping.scale_x == 1.0f/static_cast<float>(width) && mapping.scale_y == 1.0f/static_cast<float>(height);
                const bool aligned = direct_source && standard_slice && standard;
                if (!standard) issue = "unsupported_coordinate_mapping";
                if (!direct_source || !standard_slice) issue = "unsupported_image_source";
                if (rotation != 0) issue = "rotated_line";
                auto detail = json_stream();
                detail << "\"raw_line\":{\"x0\":" << raw.x0 << ",\"y0\":" << raw.y0 << ",\"x1\":" << raw.x1 << ",\"y1\":" << raw.y1
                    << "},\"coordinate_mapping\":{\"offset\":[" << mapping.offset_x << ',' << mapping.offset_y << "],\"scale\":[" << mapping.scale_x << ',' << mapping.scale_y
                    << "],\"identity\":" << (mapping.offset_x == 0 && mapping.offset_y == 0 && mapping.scale_x == 1 && mapping.scale_y == 1 ? "true":"false")
                    << ",\"space\":\"source_pixel_to_normalized_display\",\"source_pixel_aligned\":" << (aligned?"true":"false") << '}';
                out << ",\"type\":\"line\",\"raw_rectangle\":null,\"rect\":null," << detail.str() << ",\"line\":";
                if (issue) out << "null"; else out << '[' << raw.x0 << ',' << raw.y0 << ',' << raw.x1 << ',' << raw.y1 << ']';
                out << ",\"analysis_eligible\":" << (issue?"false":"true") << ",\"issue\":" << (issue?nb::quote(issue):"null") << '}';
                if (target && target->document_id == static_cast<std::uint32_t>(document_id) && target->display_id == static_cast<std::uint32_t>(display_id) && target->roi_id == static_cast<std::uint32_t>(id)) {
                    if (target->found) throw std::runtime_error("native_profile_gui_line_ambiguous");
                    target->found = true; target->line = raw; target->issue = issue;
                    auto binding = json_stream();
                    binding << "{\"document_id\":" << document_id << ",\"display_id\":" << display_id << ",\"roi_id\":" << id << ',' << detail.str()
                        << ",\"effective_line\":[" << raw.x0 << ',' << raw.y0 << ',' << raw.x1 << ',' << raw.y1
                        << "],\"rotation_degrees\":" << rotation << ",\"source_layout\":" << nb::quote(direct_source?"direct_image_canonical_xy":"unsupported") << ",\"slice_ids\":[";
                    for (std::uint32_t i=0;i<slice_id.count;++i) { if(i)binding<<',';binding<<slice_id.components[i]; }
                    binding << "]}"; target->json = binding.str();
                }
            } else if (!rectangle) {
                out << ",\"type\":\"unsupported\",\"raw_line\":null,\"line\":null,\"raw_rectangle\":null,\"coordinate_mapping\":null,\"rect\":null,\"analysis_eligible\":false,\"issue\":\"unsupported_roi_type\"}";
            } else {
                nb::RoiRectangle353 r{};
                if (roi_api353.rectangle(roi.value, &r) != &r) throw std::runtime_error("native_roi_rectangle_return_mismatch");
                const auto* issue = nb::roi_rectangle_issue353(r, width, height);
                nb::RoiMapping353 mapping{};
                if (roi_api353.mapping(display, &mapping, &acquired) != &mapping)
                    throw std::runtime_error("native_roi_mapping_return_mismatch");
                for (float value : {mapping.offset_x, mapping.offset_y, mapping.scale_x, mapping.scale_y})
                    if (!std::isfinite(value)) throw std::runtime_error("native_roi_nonfinite_mapping");
                if (mapping.scale_x == 0 || mapping.scale_y == 0)
                    throw std::runtime_error("native_roi_invalid_mapping");
                const bool identity = mapping.offset_x == 0 && mapping.offset_y == 0 && mapping.scale_x == 1 && mapping.scale_y == 1;
                // The exact Simple implementation returns the retained image's
                // own GetSize without projection or axis permutation. Its
                // default single full-source SliceId is [0], not spatial axes.
                const bool standard_mapping = mapping.offset_x == 0 && mapping.offset_y == 0 &&
                    mapping.scale_x == 1.0f / static_cast<float>(width) &&
                    mapping.scale_y == 1.0f / static_cast<float>(height);
                const bool source_pixel_aligned = direct_source && standard_slice && standard_mapping;
                if (!standard_mapping) issue = "unsupported_coordinate_mapping";
                if (!direct_source || !standard_slice) issue = "unsupported_image_source";
                if (rotation != 0) issue = "rotated_rectangle";
                out << ",\"type\":\"rectangle\",\"raw_line\":null,\"line\":null,\"raw_rectangle\":{\"top\":" << r.top << ",\"left\":" << r.left
                    << ",\"bottom\":" << r.bottom << ",\"right\":" << r.right << "},\"coordinate_mapping\":{\"offset\":["
                    << mapping.offset_x << ',' << mapping.offset_y << "],\"scale\":[" << mapping.scale_x << ',' << mapping.scale_y
                    << "],\"identity\":" << (identity ? "true" : "false")
                    << ",\"space\":\"source_pixel_to_normalized_display\",\"source_pixel_aligned\":"
                    << (source_pixel_aligned ? "true" : "false") << "},\"rect\":";
                if (issue) out << "null";
                else out << '[' << r.left << ',' << r.top << ',' << r.right << ',' << r.bottom << ']';
                out << ",\"analysis_eligible\":" << (issue ? "false" : "true") << ",\"issue\":" << (issue ? nb::quote(issue) : "null") << '}';
            }
            if (roi_api353.roi_id(roi.value) != id || roi_api353.is_rectangle(roi.value) != rectangle ||
                (line && !line_api353.is_line(roi.value)))
                throw std::runtime_error("native_roi_identity_changed");
        }
        if (roi_api353.roi_count(display) != roi_count ||
            roi_identity_field353(display, nb::kComponentIdentityOffset353) != display_id ||
            roi_identity_field353(fields->document, nb::kDocumentIdentityOffset353) != document_id)
            throw std::runtime_error("native_roi_set_changed");
        out << "],\"issue\":null}";
    }
    if (roi_api353.display_count(&image, &document_filter) != count)
        throw std::runtime_error("native_roi_display_set_changed");
    out << ']'; require_ready(); return out.str();
}

std::string execute_rois353(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 1) throw std::runtime_error("native_roi_requires_image_id");
    if (!roi_api353.ready()) throw std::runtime_error("native_roi_bindings_unavailable");
    ImageRef image(api.find_id, request.args[0]);
    const auto descriptor = fft_image353(image.value.image);
    if (descriptor.id != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    if (descriptor.dimensions != 2 || (descriptor.data_type != 2 && descriptor.data_type != nb::kUint32Code353) ||
        descriptor.packing != 1 || !descriptor.width || !descriptor.height ||
        static_cast<std::uint64_t>(descriptor.width) * descriptor.height > 4194304)
        throw std::runtime_error("native_roi_requires_bounded_ordinary_float32_or_uint32_2d");
    const auto info = metadata(image.value.image, false);
    const bool include_lines = qualified_capability353("native_line_profile") && line_api353.ready();
    const auto snapshot = collect_rois353(image.value, descriptor.id, descriptor.width, descriptor.height, include_lines);
    // IDs, counts, selection and geometry are reread. This detects changes, but
    // does not claim a host lock, an atomic GUI snapshot or immunity to ABA edits.
    if (collect_rois353(image.value, descriptor.id, descriptor.width, descriptor.height, include_lines) != snapshot ||
        metadata(image.value.image, false) != info || api.id(image.value.image) != descriptor.id)
        throw std::runtime_error("native_roi_snapshot_changed");
    return "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" + std::to_string(descriptor.id) +
        ",\"image\":" + info + ",\"displays\":" + snapshot +
        ",\"coordinate_rule\":\"half-open pixel rectangle [x0,y0,x1,y1]; no rounding or clipping\","
        "\"source_write_requested\":false,\"snapshot_atomic\":false}";
}
