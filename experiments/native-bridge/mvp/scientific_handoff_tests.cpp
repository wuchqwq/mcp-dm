// Test the actual adapter's metadata propagation with synthetic callbacks only.
// No vendor DLL, DM host, physical FFT or real document is executed.
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main
#include <fstream>

int main(int argc, char** argv) {
    try {
        inject_fake(); operation_tracking = true;
        fake.width = fake.height = 8; fake.pixels.resize(64);
        for (unsigned i = 0; i < 64; ++i) fake.pixels[i] = static_cast<float>(i) - 31.25f;
        const auto original = fake.pixels;
        execute_native({"fft-source", "FFT", {17}});
        const auto fft = retained_results.rbegin()->first;
        const auto phase_receipt = execute_native({"phase-source", "VENDOR_ARG", {fft}});
        const auto phase = retained_results.rbegin()->first;
        check(retained_results.at(phase).scientific_result == phase_receipt);
        check(retained_results.at(phase).scientific_operation == "VENDOR_ARG");
        execute_native({"crop-phase", "CROP", {phase, 1, 1, 7, 7}});
        const auto cropped = retained_results.rbegin()->first;
        check(retained_results.at(cropped).scientific_result == phase_receipt);
        check(retained_results.at(cropped).scientific_offset[0] == 1);
        check(retained_results.at(cropped).scientific_offset[1] == 1);
        const auto read = execute_native({"read-phase", "READ", {cropped, 2, 1, 5, 4}});
        check(nb::valid_json(read));
        check(read.find("\"scientific_context\":{\"schema_version\":1,\"status\":\"tracked_fourier\"") != std::string::npos);
        check(read.find("\"request_id\":\"phase-source\"") != std::string::npos);
        check(read.find("\"source_offset_xy\":[1,1]") != std::string::npos);
        check(read.find("\"phase_units\":\"radians\"") != std::string::npos);
        if (argc == 2) {
            std::ofstream output(argv[1], std::ios::binary);
            if (!output) throw std::runtime_error("cannot create surrogate packet");
            output << "{\"args\":[" << cropped << ",2,1,5,4],\"result\":" << read << "}\n";
            if (!output) throw std::runtime_error("cannot write surrogate packet");
        }
        execute_native({"square-phase", "UNARY", {cropped, 3}});
        const auto squared = retained_results.rbegin()->first;
        check(retained_results.at(squared).scientific_processing == std::vector<std::string>{"GMSImageProcessing::Square"});
        const auto processed = execute_native({"read-squared", "READ", {squared, 0, 0, 2, 2}});
        check(processed.find("\"postprocessing\":[\"GMSImageProcessing::Square\"]") != std::string::npos);
        // A mutation of the creation-time descriptor cannot silently retain old coordinates.
        auto* changed = registry.at(cropped); const auto old_origin = changed->origin[0]; changed->origin[0] += 1;
        const auto points = point_calls;
        try { execute_native({"changed", "READ", {cropped, 0, 0, 1, 1}}); check(false); }
        catch (const std::runtime_error& error) { check(std::string(error.what()) == "native_read_scientific_metadata_changed"); }
        check(point_calls == points); changed->origin[0] = old_origin;
        // No inference of a complete scientific lineage from mixed/binary results.
        execute_native({"binary-phase", "BINARY", {phase, phase, 1}});
        const auto mixed = retained_results.rbegin()->first;
        check(retained_results.at(mixed).scientific_unresolved);
        check(execute_native({"mixed-read", "READ", {mixed, 0, 0, 1, 1}}).find("\"status\":\"unresolved_lineage\"") != std::string::npos);
        execute_native({"mixed-crop", "CROP", {mixed, 0, 0, 2, 2}});
        check(retained_results.rbegin()->second.scientific_unresolved);
        check(fake.pixels == original && fake.references == 1);
        shutdown_native(); check(retained_results.empty() && retained_result_bytes == 0);
        check(registry.size() == 1 && fake.references == 1 && !fatal_abi);
        std::cout << "PASS scientific handoff " << assertions << " assertions; synthetic callbacks only\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
