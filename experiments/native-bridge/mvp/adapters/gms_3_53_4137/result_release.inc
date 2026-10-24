// Only bridge-owned references are released. No new vendor function or layout.
void reject_released_inputs353(const NativeRequest& request) {
    if (request.op == "STATUS" || request.op == "DATASETS" || request.op == "RELEASE" || request.op == "RESULT_INFO") return;
    const unsigned inputs = request.op == "BINARY" ? 2u : request.args.empty() ? 0u : 1u;
    for (unsigned i = 0; i < inputs; ++i)
        if (released_image_ids353.count(request.args.at(i)) && !retained_results.count(request.args.at(i)))
            throw std::runtime_error("native_result_released_or_reused_id");
}

std::string attach_retention353(const NativeRequest& request, std::string result) {
    if (request.op != "CROP" && request.op != "UNARY" && request.op != "BINARY" && request.op != "FILTER" && request.op != "PROFILE" && !nb::is_fft_operation353(request.op)) return result;
    const auto found = retained_results.find(last_retained_result353);
    if (found == retained_results.end() || found->second.request_id != request.id || result.empty() || result.back() != '}')
        throw std::runtime_error("native_result_retention_identity_missing");
    result.pop_back();
    return result + ",\"retention\":{\"token\":" + std::to_string(found->second.retention_token) +
        ",\"creation_request_id\":" + nb::quote(request.id) +
        ",\"state_at_creation\":\"plugin_retained\",\"identity_scope\":\"bridge token in this native session, not a host image ID\"}}";
}

std::string result_lifecycle353(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 2 || !request.args[0] || !request.args[1])
        throw std::runtime_error("native_result_identity_requires_id_and_retention_token");
    const auto id = request.args[0], token = request.args[1];
    auto owned = retained_results.find(id);
    auto old = released_results353.find(token);
    const bool retained = owned != retained_results.end() && owned->second.retention_token == token;
    if (!retained && (old == released_results353.end() || old->second.image_id != id))
        throw std::runtime_error("native_result_not_owned_or_token_mismatch");
    const std::string producer = retained ? owned->second.request_id : old->second.creation_request_id;
    const auto bytes = retained ? owned->second.bytes : old->second.bytes;
    bool released_now = false;
    if (request.op == "RELEASE" && retained) {
        if (retained_result_bytes < bytes || !owned->second.value.image ||
            api.id(owned->second.value.image) != id ||
            !accessible_memory(owned->second.value.image, sizeof(LONG64)) ||
            InterlockedCompareExchange64(static_cast<volatile LONG64*>(owned->second.value.image), 0, 0) <= 0) {
            fatal_abi = true;
            throw std::runtime_error("native_release_owned_reference_identity_invalid");
        }
        // Allocate bookkeeping before changing ownership. This token is ours,
        // not a vendor ROI ID or an exposed pointer. Core bounds the session's
        // accepted requests; this small tombstone table is bounded too.
        if (released_results353.size() >= nb::kMaxOperationRecords)
            throw std::runtime_error("native_release_history_capacity");
        released_results353.emplace(token, ReleasedResult353{id, producer, bytes});
        released_image_ids353.insert(id);
        release_image(owned->second.value);
        retained_result_bytes -= bytes;
        retained_results.erase(owned);
        released_now = true;
        require_ready();
    }
    const bool available = request.op == "RESULT_INFO" && retained;
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << id
      << ",\"retention_token\":" << token << ",\"creation_request_id\":" << nb::quote(producer)
      << ",\"plugin_retained\":" << (available ? "true" : "false")
      << ",\"available_for_native_processing\":" << (available ? "true" : "false")
      << ",\"released\":" << (available ? "false" : "true")
      << ",\"released_now\":" << (released_now ? "true" : "false")
      << ",\"result_bytes\":" << bytes << ",\"retained_result_count\":" << retained_results.size()
      << ",\"retained_result_bytes\":" << retained_result_bytes
      << ",\"document_closed\":false,\"source_write_requested\":false,\"native_object_existence\":\"not_probed\""
      << ",\"scope\":\"plugin reference only; shown document may still hold the image; old creation receipt is unchanged\"}";
    return stream.str();
}
