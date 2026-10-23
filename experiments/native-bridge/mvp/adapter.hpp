#pragma once
#include <cstdint>
#include <string>
#include <vector>

// This is an internal, statically linked boundary. No C++ library object is
// passed across a vendor DLL ABI; dm_adapter.cpp owns all vendor interaction.
struct NativeRequest {
    std::string id;
    std::string op;
    std::vector<std::uint32_t> args;
};

// These three functions run only on the plugin startup / window thread.
// execute_native returns one complete, bounded JSON value or throws.
void initialize_native();
std::string execute_native(const NativeRequest& request);
void shutdown_native();
