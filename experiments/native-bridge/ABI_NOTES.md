# Fixed-build native adapter ABI notes

These notes describe a narrow x64 adapter for GMS 3.53.4137.0. The findings
below were checked against local export tables and machine code. They are
**static evidence**, not a claim that the new adapter has executed successfully
inside DM. Runtime acceptance belongs in RESULTS.md.

Resolve exported symbols with `GetModuleHandleW` and `GetProcAddress`. Do not load a
second copy of a host module. Require the allowlisted host/module identities,
architecture, and all required symbols before acquiring an image reference.
The SDK compatibility export alone does not identify the image ABI.
The SHOW candidate additionally needs non-exported typed entrypoints; its
separate full-binary and executable-entry gates are described below. This is
not permission to guess another build's addresses or revive the old PE resolver.

## Image identity and ownership

Use the numeric-ID interface `GMS::Image::FindByID(unsigned long)`. The older
probe's `FindImageAsObject(unsigned __int64)` compares an object-address token;
it is not a replacement for lookup using the number returned by `GetID()`.

The adapter's explicit Win64 call shapes are:

```cpp
struct NativeImageRef { void* image; }; // size 8, alignment 8
using FindByID = NativeImageRef* (*)(NativeImageRef* out, uint32_t id);
using FindByIndex = NativeImageRef* (*)(NativeImageRef* out, uint32_t index);
using CountAllImages = uint32_t (*)();
using GetID = uint32_t (*)(const void* image);
using GetDimensions = uint32_t (*)(const void* image);
using GetNthDimension = uint32_t (*)(const void* image, int32_t dimension);
using GetDataType = uint32_t (*)(const void* image);
using GetMean = double (*)(const NativeImageRef* image);
using DeleteImage = void (*)(void* image);
```

Static methods returning `ref_ptr<Image>` receive the hidden result pointer
first, then the declared arguments. They write one pointer and return the
result-buffer address. Do not substitute an unexplained two-pointer array.
The returned non-null image owns one strong reference. A missing ID produces
an empty reference; verify the returned object's `GetID()` before using it.

On this adapter's fixed build the image's first field is a signed 64-bit
intrusive reference count, not a vtable. Release one owned reference with an
atomic 64-bit decrement, invoking `Gatan::ref_ptr_delete(Image*)` **only if the
new count is zero**. The exported function is a final destructor/deallocator;
calling it directly on every successful lookup would destroy a live image.
Use an ownership guard on every early-return path and never release a borrowed
pointer. Do not copy an owned reference unless the corresponding increment
also occurs.

The exact lookup and final-deletion exports are:

```text
?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z
?FindByIndex@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z
?CountAllImages@Image@GMS@@SAKXZ
?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z
```

## Descriptors, calibration, and statistics

`GetNthDimension` is the native size getter; no `GetDimensionSize` export was
found in the inspected module. Validate each dimension index against the
previously obtained dimension count. DM dimension 0 is x and dimension 1 is y;
an exported row-major 2D shape is consequently `[size_y, size_x]`.

`GetDataType` reads the native descriptor and does not require touching pixels.
The first numerical adapter can accept only known code 2 (`float32`) and two
dimensions. Other codes must remain explicitly unsupported rather than being
inferred from byte count or appearance. Existing Python dtype mapping can be
reused later only with separately accepted native cases.

Calibration's explicit call shape is:

```cpp
using GetDimensionCalibration = void (*)(
    void* image, uint32_t dimension, float* origin, float* scale,
    void* msvc_wstring_or_null, int32_t format);
```

Both numeric outputs are binary32. With format 0 the output origin is the
physical coordinate at index zero, so `physical(i) = origin + i * scale`.
Preserve negative scales. Format 1 returns the stored index-origin convention
instead; do not mix the two. Null numeric outputs and a null string output are
explicitly handled by the inspected implementation. Validate dimensions and
reject non-finite values before publishing usable calibration.

`GMSImageProcessing::GetMean(ref_ptr<Image> const&)` returns binary64 in the
normal Win64 floating-point return register. It obtains image data, locks a
data layout, and calls the native layout mean. This path does not fetch or
apply the image's intensity calibration: label the result as **raw pixel
intensity mean**. A finite fractional or negative mean must retain its sign
and precision in the wire representation. Reject or explicitly encode
non-finite results; never multiply by 1000 and cast to an unsigned integer.
No public pixel-lock structure is required merely to call this native mean.

The corresponding exports are:

```text
?GetID@Image@GMS@@QEBAKXZ
?GetDimensions@Image@GMS@@QEBAKXZ
?GetNthDimension@Image@GMS@@QEBAKJ@Z
?GetDataType@Image@GMS@@QEBAKXZ
?GetDimensionCalibration@Image@GMS@@QEAAXKPEAM0PEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@J@Z
?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z
```

## FFT interface investigation: not qualified

Bounded local machine-code inspection supports the existing one-pointer image
reference and caller-provided output-reference shape for the exported FFT,
Real_FFT and Packed_FFT candidates. They impose different descriptor/packing
constraints; FFT must not be selected merely because the input is real
float32. The real-input path includes a native packed-to-complex conversion
branch, strong-reference handling and native frequency-calibration transfer.

These are partial static findings, not a production call contract. Exact
complex representation, normalization, data centering/phase, usable reciprocal
axes, source preservation, workspace bounds and end-to-end output ownership
remain unqualified. Native raw-origin arithmetic does not establish NumPy
fftshift equivalence. Existing mean/crop or Python FFT passes do not qualify
these candidates, and crop-only SHOW does not provide FFT-result delivery.

No production function binding, FFT protocol operation or MCP tool is added.
Scientific processing must remain in DM; MCP/C++ adapts verified calls and
hands off results. See [FFT readiness](mvp/FFT_READINESS.md) for unresolved
conditions and the separate offline/real-host acceptance sequence.

## MSVC string ABI shim

Do not pass a MinGW `std::wstring` to an MSVC-built host. The fixed-build shim
uses an explicitly represented, aligned 32-byte string object:

```cpp
struct alignas(8) MsvcWideString {
    union { uint16_t small[8]; uint16_t* heap; } storage; // offset 0
    uint64_t length;                                   // offset 16
    uint64_t capacity;                                 // offset 24
};
```

An empty output string has length 0, capacity 7 and `small[0] == 0`. Capacity
at most 7 selects the inline buffer; greater capacity selects `heap`. Length
excludes the terminator. Validate length against capacity and an output budget
before copying UTF-16. Convert with a bounded Windows UTF-16/UTF-8 conversion.
Never use the local C++ library's string destructor, `delete`, or `free` on this
object.

The inspected vendor destruction path frees heap storage as follows:

1. Check capacity arithmetic before calculating `bytes = (capacity + 1) * 2`.
2. For bytes below 4096, pass the heap pointer to the matching deallocator.
3. For bytes at least 4096, the exposed pointer is 32-byte aligned. Its preceding
   pointer-sized word stores the original allocation address. Verify that
   address precedes the exposed pointer and that their difference is from 8
   through 39 bytes, inclusive; release the original allocation address.
4. Reset the local representation after release so a guard cannot free twice.

The matching deallocation path in the inspected build is ordinal 1487 of the
already loaded `mfc140.dll`. Resolve that ordinal with `GetProcAddress`, and
require its exact module identity as part of the ABI allowlist. This is a
layout-specific shim with a verified matching allocation path, not a public
vendor string-destructor API. Malformed layout must fail closed; exceptions
are not a substitute for correct ABI or allocator pairing.

Image names can use the same representation through:

```cpp
using GetUnicodeName = MsvcWideString* (*)(
    const void* image, MsvcWideString* fresh_output);
```

Unlike static image lookup, this member method receives `this` first and its
hidden result pointer second. It constructs the output itself. Use fresh
storage and release the returned representation exactly once.

```text
?GetUnicodeName@Image@GMS@@QEBA?AV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@XZ
```

## Bounded enumeration

Prefer `CountAllImages` plus zero-based `FindByIndex` over the more complicated
`EnumImages` functional callback and allocator-specific vector ABI. Reject a
count over the output budget before lookup. Acquire each image, copy only the
required metadata, and release it promptly. Verify counts before and after,
and detect duplicate IDs. This is enumeration of the native registry, which
may include images without visible document windows. State that scope.

The registry can change between individual calls. The first adapter requires
an idle host and no editing or closing source images during a request. A
matching count does not prove an atomic registry or pixel snapshot. Do not
claim concurrent-edit protection or call `FindByIndex` outside the checked
range: the vendor's out-of-range path can throw a host error.

## Independent crop contract

`CreateSlicedImage` makes a sliced object whose image data retains the original
backing seed. It must not be described as an independent pixel copy.

The better candidate is `Image::GetSubSliceAsImage(DataSlice const&)`: the
inspected path creates a new image, copies selected data into its backing
storage, then transfers slice calibration and notifies calibration changes.
The Win64 shape is:

```cpp
using GetSubSliceAsImage = NativeImageRef* (*)(
    const void* source, NativeImageRef* out, const void* data_slice);
```

The inspected slice representation has alignment 8 and size 176:

```cpp
struct SliceAxis {
    uint32_t source_dimension; // axis-record offset 0
    uint32_t padding;
    int64_t length;            // offset 8
    int64_t step;              // offset 16
};
struct NativeDataSlice {
    uint32_t source_dimensions; // offset 0
    uint32_t padding0;
    int64_t source_start[5];     // offset 8
    uint32_t output_dimensions;  // offset 48
    uint32_t padding1;
    SliceAxis output_axes[5];    // offset 56, stride 24
};
```

Its size is independently constrained by the containing image-data object's
member boundary and by the fifth axis record's final field. No vtable or heap
member appears in this representation. Validate offsets and size at compile
time; do not substitute guessed opaque storage.

For a half-open 2D rectangle `[x0,y0,x1,y1]`, use two source dimensions,
starts `{x0,y0}`, two output dimensions, and output-axis records
`{0,x1-x0,1}` and `{1,y1-y0,1}`. Reject invalid or out-of-bounds rectangles and
bound output allocation before calling DM. The expected physical output
zero is `source_zero + start * source_scale`; signed scales remain unchanged.
The returned reference has the same ownership rule as lookup.

```text
?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z
```

This is the static contract used by the fixed-build MVP's experimental crop.
Earlier separate actual-host acceptance covered new/repeated object identity, shape,
dtype, every selected pixel against an independent oracle, signed calibration,
source invariance, and retained-output release after STOP. It does not certify
other builds, concurrent image work or every vendor-failure path. Current
limited runtime evidence and the ASCII-qualified/non-ASCII name boundary are
recorded in [RESULTS.md](RESULTS.md); static ABI notes alone are not acceptance.

## Visible-document SHOW candidate

SHOW accepts only an exact numeric ID in this plugin session's retained crop
registry. On the host thread, `FindByID` must agree with both the stored native
pointer and numeric ID. It then calls the native factory for a document
containing that image, followed by the document display entrypoint. It never
selects a front image, user name or most-recent window.

These typed entrypoints have no applicable public DLL exports in the inspected
build. The candidate binds the fixed-build entries only after complete
host/module SHA256 and version gates pass, then verifies the entry lies in
that module's image, an executable section and a committed executable memory
page. No vendor function addresses, RVA values or private build hashes are
needed in this document.

Only native pointers and explicit POD layout cross the boundary. The returned
document holder is 16 bytes: a 64-bit reference count followed by a native
document pointer. The Window remains opaque except for its separately proven
fixed-build 64-bit reference counter. Each return is one owned reference. Local
guards release Window first, then the document holder; only a count reaching
zero calls its matched vendor final destructor. Never use MinGW `free` or
`delete`, retain a borrowed pointer, or assume a C++ standard-library ABI.

The plugin retains neither document nor Window. STOP releases its crop
reference and must not close a shown document. Actual document ownership after
STOP requires a separate host test from hidden-output release. Empty returns
fail explicitly; malformed layout latches the adapter disabled without guessed
destruction. A successful hash/page gate is not vendor crash isolation, and
MinGW catches do not establish safe handling of MSVC native exceptions.

SHOW can have UI effects before a later failure or timeout. Save its original
session/ID before dispatch, QUERY that ID and do not automatically call SHOW
again. The result explicitly denies file saving and model visual verification.
The candidate's native completed receipt and explicit-image correlation
passed a limited actual-host MCP check. A later new strict session independently
passed actual visibility, unique-document count, ownership after STOP and final
image release after normal document closure. This qualifies only the explicit
plugin-crop document path on the pinned build, not saving or model vision.
See [RESULTS.md](RESULTS.md) for the distinct runtime evidence boundaries.

## Legacy Python and native Unicode paths

Static inspection of the pinned Python wrapper confirms that the name and
unit setters obtain UTF-8 bytes, then pass through a vendor narrow-string
service with encoding argument zero. The getters request narrow bytes with
that argument, try Python's UTF-8 decoder and fall back to `bytes` after a
decode error. Separately, the inspected GMS encoding resolver maps zero to
the Windows system code page. The exact indirect binding from the Python
string service to that implementation is not fully established. These facts
identify a compatibility risk; they do not prove the complete cause of the
earlier failed comparison or the historical process's actual code page.

The native bridge takes the vendor UTF-16 name and calibration-unit getters
directly and converts the fixed-build string POD with explicit `CP_UTF8` and
strict invalid-character checking, preserving vendor allocation ownership.
A legacy Python setter/getter round trip can conceal a stored-Unicode
difference and is not a UI or native-string truth oracle. No reverse-codec
guess or product encoding change is justified by this inspection.

Non-ASCII interoperation remains **NOT_QUALIFIED**. Future synthetic tests
must record UI-entered characters separately from Python-set names, preserve
legacy getter result type/raw bytes as well as text code points, and compare
the native/MCP result for the exact image ID. Units need their own comparison.
The legacy probe now records typed getter observations: text and exact code
points, or raw byte hex/length with decoding explicitly not attempted. Even
valid UTF-8 byte sequences remain bytes. Lone surrogates, getter exceptions
and unexpected types are retained as diagnostic failures; encoding exceptions
also retain the original input and byte/character range. Its status is only
RECORDED or FAIL, with qualification always NOT_QUALIFIED. Offline fake-getter
tests qualify this retention behavior, not the stored host characters. No real
Unicode probe was executed in this offline continuation, and the independent
UI/native/MCP comparison remains pending.

## Native SUMMARY reductions

SUMMARY binds the same pinned processing module's exact decorated GetMinimum,
GetMaximum and GetSum exports, each taking `const NativeRef*` and returning a
native double, together with the existing GetMean binding. The static wrapper
review follows vendor image-data/layout reduction paths; no bridge pixel kernel
or value derived from another returned scalar is used. A strong image reference,
explicit numeric ID, bounded 2D float32 shape and the existing readiness/ABI gates
remain required. Each call's finite result and readiness are checked before the
next call; a failure yields no partial successful summary.

The raw-intensity contract was separately checked in a new real host with
nontrivial intensity origin/negative scale/unit, plus default and missing spatial
unit controls. Strict MCP and an independent same-PID oracle matched the raw
values and verified full source pixels, spatial/intensity calibration and
document invariance. This is a limited synthetic qualification, not a proof for
other dtypes, versions or concurrent source edits. The four native calls are
sequential with `snapshot_atomic:false`. Generic NB1 QUERY carries no original
operation; independent acceptance continues semantic checks using its original
tool/ID/parameter ledger. See [SUMMARY acceptance](mvp/SUMMARY_ACCEPTANCE.md).

## Minimum runtime verification order

After offline protocol/lifecycle tests pass, use a prepared idle test session:
host/module identity and symbols; host callback readiness; numeric lookup and
matching ID; dimensions and type; calibration and string ownership;
one raw native mean against an independent non-constant oracle; repeated
acquire/release; close the synthetic source and verify stale ID failure.
Then run the MCP chain, and only afterward independently accept crop.
Qualify non-ASCII naming interoperability separately; a correct UTF-16/UTF-8
conversion does not establish agreement with legacy Python name bindings.

Thread equality is evidence of callback placement, not evidence that arbitrary
user scripts may run concurrently with native image work. Do not test a new
image ABI in an unverified working DM session or after an access violation.
