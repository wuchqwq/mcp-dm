#pragma once
#include "../../adapter_profile.hpp"

// All fingerprints and qualification declarations belong to this adapter.
// Adding another version never extends this allowlist by approximate matching.
namespace nb::gms353 {
// Primary RasterImageDisplay vtable, cross-checked against this binary's RTTI
// and the exact native count/get implementations used by the SF wrappers.
inline constexpr std::uint32_t kRasterRoiVtableRva353 = 0xbbd298;
inline constexpr std::uint32_t kSimpleImageSourceVtableRva353 = 0xbfe468;
// Optional groups list every native entry they depend on. Losing a group never
// changes core ABI admission or turns a different group into a fallback.
inline CapabilityProfile operation_capability(const char* name, bool qualified, const char* scope,
                                               std::initializer_list<const char*> exports,
                                               bool finite_reductions = true) {
    CapabilityProfile capability{name, qualified, scope,
        {{"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"}}, {}};
    if (finite_reductions) {
        for (const auto* symbol : {
            "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z",
            "?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z",
            "?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z",
            "?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"})
            capability.symbols.push_back({"GMSImageProcessing.dll", symbol});
    }
    for (const auto* symbol : exports) capability.symbols.push_back({
        finite_reductions ? "GMSImageProcessing.dll" : "GMSImage.dll", symbol});
    return capability;
}
inline const AdapterProfile& profile() {
    static const AdapterProfile value{
        "gms-3.53.4137.0-windows-x64", {{3, 53, 4137, 0}}, "x64",
        {
            {"DigitalMicrograph.exe", "2f03ccd751b2abc7f55d3bda5b975895c3527660a03080618005a134d6fbfddb", true},
            {"GMSImage.dll", "0d8e22006a1023eb9f0de2b497ef1629c5a22c562741d3e4b0405d308590da3b", true},
            {"GMSImageProcessing.dll", "6be3044d049b6b2184404ea5adc2588d0677ae9b2f78ceb80169d315aef82042", true},
            {"GMS.dll", "9056884e38c090b7fff1cefe70150dc49d10dbc1f823fed6c7a661d255c01f93", true},
            {"mfc140.dll", "b784303d86232a1b316c79839aa78bf631b4fc182e55d9d947688adb066dff26", false},
        },
        {
            {"GMSImage.dll", "?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z"},
            {"GMSImage.dll", "?FindByIndex@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z"},
            {"GMSImage.dll", "?CountAllImages@Image@GMS@@SAKXZ"},
            {"GMSImage.dll", "?GetID@Image@GMS@@QEBAKXZ"},
            {"GMSImage.dll", "?GetDimensions@Image@GMS@@QEBAKXZ"},
            {"GMSImage.dll", "?GetDataType@Image@GMS@@QEBAKXZ"},
            {"GMSImage.dll", "?GetNthDimension@Image@GMS@@QEBAKJ@Z"},
            {"GMSImage.dll", "?GetDimensionCalibration@Image@GMS@@QEAAXKPEAM0PEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@J@Z"},
            {"GMSImage.dll", "?GetUnicodeName@Image@GMS@@QEBA?AV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@XZ"},
            {"GMSImage.dll", "?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z"},
            {"mfc140.dll", "#1487"},
        },
        {
            {"native_line_profile", true, "limited synthetic real-host qualification; float32/uint32 ordinary 2D direct-source; width1 integer axis-aligned GUI line; equal signed spatial scales and units; true 1D float64 snapshot <=4096 samples", {
                {"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"},
                {"GMSImage.dll", "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z"},
                {"GMSImage.dll", "?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z"}},
                {"roi_is_line", "roi_line", "line_profile_extract", "roi_image_display_count", "roi_image_display_at", "roi_resolve_display", "roi_display_image",
                 "roi_raster_count", "roi_raster_at", "roi_id", "roi_is_rectangle", "roi_rectangle", "roi_is_selected", "roi_raster_dimensions", "roi_raster_mapping", "roi_raster_slice_id",
                 "roi_simple_source_count", "roi_simple_source_slice_id", "roi_simple_source_extents", "roi_destroy_display_holder", "roi_destroy_roi"}},
            // Rank-one PROFILE delivery is a separate admission group. It reuses
            // the same document factory/entrypoints already qualified for 2D
            // results, but a 1D result must never enter through the 2D group or
            // be presented as a rewritten [1,N] raster.
            {"native_profile_display", true, "limited synthetic qualification; plugin-owned rank-1 float64 PROFILE result only; no file save; host decides the 1D display", {},
                {"image_get_or_create_document", "image_document_show", "destroy_document_holder", "destroy_window"}},
            {"native_histogram_display", true, "limited synthetic qualification; plugin-owned rank-1 uint32 HISTOGRAM count image only; no file save; host decides the 1D display", {},
                {"image_get_or_create_document", "image_document_show", "destroy_document_holder", "destroy_window"}},
            // Histogram bar style is a display-only preference of the host's own line
            // plot. It is applied only after the object is proven to be a
            // LinePlotImageDisplay by its own RTTI name, then read back.
            {"native_line_plot_style", true, "limited synthetic qualification; plugin-owned rank-1 HISTOGRAM document only; one-byte host style flag with a getter read-back; no scientific claim", {},
                {"image_get_or_create_document", "image_document_show", "destroy_document_holder", "destroy_window",
                 "roi_image_display_count", "roi_image_display_at", "roi_resolve_display", "roi_destroy_display_holder",
                 "plot_style_get", "plot_style_set"}},
            // Histogram creation and binning are vendor calls: the destination
            // is a native 1D uint32 image from Image::CreateImage and the counts
            // come from GMSImageProcessing::CalcHistogram. No bridge kernel.
            {"native_histogram", true, "limited synthetic qualification; float32 ordinary 2D <=4194304 pixels; caller range must cover the complete native source min/max; 2..4096 bins; uint32 native counts; optional left-edge intensity axis when the source intensity calibration is complete", {
                {"GMSImage.dll", "?CreateImage@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSize@Imaging@4@KAEBV?$char_range_t@_WU?$char_traits@_W@std@@@4@@Z"},
                {"GMSImage.dll", "?SetDimensionCalibration@Image@GMS@@QEAAXKMMAEBV?$char_range_t@_WU?$char_traits@_W@std@@@Gatan@@J@Z"},
                {"GMSImageProcessing.dll", "?CalcHistogram@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@0NN@Z"}}, {}},
            {"native_datasets", true, "bounded native registry and metadata", {}, {}},            {"native_result_release", true, "explicit own image ID plus bridge retention token; plugin reference only; no document closure", {}, {}},
            {"native_gui_rois", true, "readonly explicit ordinary 2D direct ImageSource_Simple raster; bounded rectangle snapshots; limited idle-host synthetic qualification",
                {{"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"}},
                {"roi_image_display_count", "roi_image_display_at", "roi_resolve_display", "roi_display_image",
                 "roi_raster_count", "roi_raster_at", "roi_id", "roi_is_rectangle", "roi_rectangle",
                 "roi_is_selected", "roi_raster_dimensions", "roi_raster_mapping", "roi_raster_slice_id",
                 "roi_simple_source_count", "roi_simple_source_slice_id", "roi_simple_source_extents",
                 "roi_destroy_display_holder", "roi_destroy_roi"}},
            {"native_mean", true, "raw float32 2D mean, <=4194304 pixels", {
                {"GMSImageProcessing.dll", "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"}}, {}},
            {"native_statistics", true, "raw float32 2D mean/minimum/maximum/sum, <=4194304 pixels", {
                {"GMSImageProcessing.dll", "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"},
                {"GMSImageProcessing.dll", "?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"},
                {"GMSImageProcessing.dll", "?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"},
                {"GMSImageProcessing.dll", "?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"}}, {}},
            {"native_crop", true, "float32 2D half-open pixel rectangle; complete spatial calibration", {
                {"GMSImage.dll", "?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z"}}, {}},
            {"native_display", true, "plugin-owned qualified result to visible DM document; not a file save", {},
                {"image_get_or_create_document", "image_document_show", "destroy_document_holder", "destroy_window"}},
            operation_capability("native_image_arithmetic", true, "float32 ordinary 2D; negate/abs/square and add/subtract/multiply; independent retained results", {
                "?Negate@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Abs@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Square@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
                "??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
                "??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z"}),
            operation_capability("native_fft", true, "float32 real forward; power-of-two axes 4..256; inverse/components only for own qualified Fourier results; explicit vendor calibration", {
                "?Real_FFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?IFFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Real@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Imag@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Arg@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Norm@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z"}),
            operation_capability("native_filters", true, "float32 ordinary 2D axes 5..256; smooth/sobel/laplace/sharpen; vendor border rules", {
                "?SmoothFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?SobelFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?LaplaceFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?SharpenFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z"}),
            operation_capability("native_preview", true, "float32 2D <=4194304 source pixels; <=128x128 sampled display PNG only", {
                "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z"}, false),
            operation_capability("native_read", true, "float32 2D <=4194304 source pixels; explicit ROI <=16384 samples/65536 bytes; numeric handoff, not native SaveAs", {
                "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z"}, false),
            {"native_uint32_mean", true, "uint32 ordinary 2D raw mean; <=2097152 pixels", {
                {"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"},
                {"GMSImageProcessing.dll", "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"}}, {}},
            operation_capability("native_uint32_statistics", true, "uint32 ordinary 2D raw statistics; <=2097152 pixels; exact integer sum budget", {}),
            {"native_uint32_crop", true, "uint32 ordinary 2D independent same-dtype crop; <=4194304 source pixels; <=4MiB output", {
                {"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"},
                {"GMSImage.dll", "?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z"}}, {}},
            operation_capability("native_uint32_preview", true, "uint32 ordinary 2D display-only sampled preview", {
                "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z"}, false),
            operation_capability("native_uint32_read", true, "uint32 ordinary 2D exact little-endian ROI; <=16384 samples/65536 bytes", {
                "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z"}, false),
            {"native_uint32_display", true, "limited synthetic qualification; own uint32 crop and Smooth/Sharpen filter outputs only", {
                {"GMSImage.dll", "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ"}},
                {"image_get_or_create_document", "image_document_show", "destroy_document_holder", "destroy_window"}},
            operation_capability("native_uint32_image_arithmetic", true, "limited synthetic qualification; uint32 2D same-dtype inputs; binary64 native arithmetic to float32; <=4MiB output; no bridge cast", {
                "?Negate@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Abs@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Square@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
                "??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
                "??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z"}),
            operation_capability("native_uint32_filters", true, "limited synthetic qualification; uint32 ordinary 2D axes5..256; Smooth/Sharpen saturated-truncated uint32, Sobel/Laplace float32", {
                "?SmoothFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?SobelFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?LaplaceFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?SharpenFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z"}),
            operation_capability("native_uint32_fft", true, "limited synthetic qualification; uint32 ordinary 2D power-of-two axes4..256; DM binary32 input conversion; full complex64; own paired inverse/components", {
                "?Real_FFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?IFFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Real@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Imag@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Arg@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z",
                "?Norm@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z"}),
            {"native_save", false, "NOT_QUALIFIED", {}, {}},
        },
        {
            {"image_get_or_create_document", "GMS.dll", 0x4c3040},
            {"image_document_show", "GMS.dll", 0x4b8a20},
            {"destroy_document_holder", "GMS.dll", 0x060e70},
            {"destroy_window", "GMS.dll", 0x57bab0},
            {"roi_image_display_count", "GMS.dll", 0x2d8370},
            {"roi_image_display_at", "GMS.dll", 0x4c2d10},
            {"roi_resolve_display", "GMS.dll", 0x3cbbc0},
            // One-byte display style flag of a LinePlotImageDisplay. The getter is
            // two instructions; the setter compares, stores and repaints. Both are
            // reached through the already qualified display resolution path.
            {"plot_style_get", "GMS.dll", 0x20b490},
            {"plot_style_set", "GMS.dll", 0x220cd0},
            {"roi_display_image", "GMS.dll", 0x3d2d20},
            {"roi_raster_count", "GMS.dll", 0x1a13a0},
            {"roi_raster_at", "GMS.dll", 0x1a4470},
            {"roi_id", "GMS.dll", 0x1bf530},
            {"roi_is_line", "GMS.dll", 0x1bfc00},
            {"roi_line", "GMS.dll", 0x1bf540},
            {"line_profile_extract", "GMS.dll", 0xa07730},
            {"roi_is_rectangle", "GMS.dll", 0x1bfc50},
            {"roi_rectangle", "GMS.dll", 0x1bf820},
            {"roi_is_selected", "GMS.dll", 0x2a9e60},
            {"roi_raster_dimensions", "GMS.dll", 0x1a3270},
            {"roi_raster_mapping", "GMS.dll", 0x2a5960},
            {"roi_raster_slice_id", "GMS.dll", 0x2a4300},
            {"roi_simple_source_count", "GMS.dll", 0x347b60},
            {"roi_simple_source_slice_id", "GMS.dll", 0x34cd90},
            {"roi_simple_source_extents", "GMS.dll", 0x34d4d0},
            {"roi_destroy_display_holder", "GMS.dll", 0x299800},
            {"roi_destroy_roi", "GMS.dll", 0x04fdd0},
        }
    };
    return value;
}
} // namespace nb::gms353
