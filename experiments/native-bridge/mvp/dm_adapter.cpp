// Common native entrypoints. ABI layouts, exact symbols/RVAs and scientific
// operators are isolated in a qualified version implementation.
#include "adapter.hpp"
#include "core.hpp"
#include "adapter_profile.hpp"
#include "adapter_identity_win.hpp"
#include "adapters/gms_3_53_4137/profile.hpp"

// Compile the version adapter in this TU so its existing ownership surrogates
// remain direct tests of the actual implementation, not a second implementation.
#define initialize_native nb353_initialize
#define execute_native nb353_execute
#define shutdown_native nb353_shutdown
#include "adapters/gms_3_53_4137/implementation.inc"
#undef initialize_native
#undef execute_native
#undef shutdown_native
#include "adapter_dispatch.inc"
