// Offline callbacks exercise the production one-shot adapter, never GMS.
#define NB_ROI_TEST_NO_MAIN
#include "roi_adapter_tests.cpp"
#undef NB_ROI_TEST_NO_MAIN
namespace {
nb::RoiLine353 profile_line353{2,1,7,1};
std::string profile_fault353;
int profile_calls353=0,profile_line_calls353=0,profile_value_calls353=0;
bool profile_is_line353(void*) { return !roi_fake353.rectangle; }
nb::RoiLine353* profile_get_line353(void*,nb::RoiLine353* out) {
    ++profile_line_calls353;*out=profile_line353;
    if(profile_fault353=="line-return")return nullptr;
    if(profile_fault353=="line-changed" && profile_line_calls353>1)out->x1-=1;
    return out;
}
void profile_intensity_fake353(void* image,float* origin,float* scale,void* unit) {
    *origin=3.25f;*scale=-2.5f;fill(static_cast<MsvcWString353*>(unit),L"arb");
    if(static_cast<FakeImage*>(image)->generated && profile_fault353=="intensity")*scale=1;
}
void* profile_extract_fake353(void* source,double x0,double y0,double x1,double y1,std::uint32_t width) {
    ++profile_calls353;check(source==&fake && width==1);
    check(x0==profile_line353.x0 && y0==profile_line353.y0 && x1==profile_line353.x1 && y1==profile_line353.y1);
    if(profile_fault353=="null")return nullptr;
    if(profile_fault353=="alias") { InterlockedIncrement64(&fake.references);return &fake; }
    auto* output=new FakeImage;
    output->generated=true;output->id=next_image_id++;output->dimensions=1;output->code=12;
    output->width=static_cast<std::uint32_t>(std::floor(std::hypot(x1-x0,y1-y0)))+1;output->height=1;
    output->origin[0]=0;output->scale[0]=fake.scale[0];output->unit[0]=fake.unit[0];
    if(profile_fault353=="rank")output->dimensions=2;
    if(profile_fault353=="dtype")output->code=2;
    if(profile_fault353=="packing")output->packing=2;
    if(profile_fault353=="samples")++output->width;
    if(profile_fault353=="calibration")output->origin[0]=1;
    registry.emplace(output->id,output);return output;
}
double profile_real_fake353(const void* image,const nb::NativeDataIndex1D353* index) {
    const auto* data=static_cast<const FakeImage*>(image);
    check(data->generated && data->dimensions==1 && index->dimensions==1 && index->padding==0 && index->x>=0 && index->x<data->width);
    ++profile_value_calls353;
    return profile_fault353=="nonfinite"?std::numeric_limits<double>::infinity():1234567890.125+index->x;
}
void setup_profile_fake353() {
    shutdown_native();setup_roi_fake353();
    fake.scale[0]=fake.scale[1]=0.25f;roi_fake353.rectangle=false;
    profile_line353={2,1,7,1};profile_fault353.clear();profile_calls353=profile_line_calls353=profile_value_calls353=0;
    line_api353={profile_is_line353,profile_get_line353,profile_extract_fake353,profile_intensity_fake353,profile_real_fake353};
}
NativeRequest profile_request353() { return {"profile-test","PROFILE",{17,31,9,7,2,1,7,1,1}}; }
void expect_profile_failure353(const char* message,bool called=false,NativeRequest request=profile_request353()) {
    try { execute_native(request);check(false); }
    catch(const std::runtime_error& e) { if(std::string(e.what())!=message)std::cerr<<"expected "<<message<<" got "<<e.what()<<'\n';check(std::string(e.what())==message); }
    check(profile_calls353==(called?1:0));check(retained_results.empty() && registry.size()==1 && fake.references==1 && roi_fake353.references==1);
    check(profile_value_calls353==(profile_fault353=="nonfinite"?1:0));
    check(roi_hold_created353==roi_hold_freed353);
}
}
int main(int argc,char** argv) {
    try {
        setup_profile_fake353();
        nb::HostObservation observed;nb353_observe_entries(observed);
        check(observed.valid_entry_contracts.count("line_profile_extract")==1);
        check(observed.valid_entry_contracts.count("roi_is_line")==1 && observed.valid_entry_contracts.count("roi_line")==1);
        const auto saved_line=line_api353;line_api353=LineApi353{};observed.valid_entry_contracts.clear();nb353_observe_entries(observed);
        check(!observed.valid_entry_contracts.count("line_profile_extract") && !observed.valid_entry_contracts.count("roi_is_line") && !observed.valid_entry_contracts.count("roi_line"));
        check(observed.valid_entry_contracts.count("roi_rectangle")==1);line_api353=saved_line;
        const auto result=execute_native(profile_request353());
        check(nb::valid_json(result));check(profile_calls353==1 && profile_value_calls353==6);
        check(result.find("\"dtype\":\"float64\"")!=std::string::npos);
        check(result.find("\"ndim\":1,\"data_type_code\":12")!=std::string::npos);
        check(result.find("\"shape\":[6]")!=std::string::npos && result.find("\"retention\":{")!=std::string::npos);
        check(retained_results.size()==1 && retained_result_bytes==48 && fake.references==1 && roi_fake353.references==1);
        if(argc==2){std::ofstream out(argv[1]);out<<result<<'\n';check(out.good());}
        if(argc==3){
            std::ofstream out(argv[1]);out<<result<<'\n';check(out.good());
            std::ofstream rois(argv[2]);rois<<"{\"backend\":\"digitalmicrograph-native\",\"image_id\":17,\"image\":"<<metadata(&fake,false)
                <<",\"displays\":"<<collect_rois353({&fake},17,fake.width,fake.height,true)
                <<",\"coordinate_rule\":\"half-open pixel rectangle [x0,y0,x1,y1]; no rounding or clipping\",\"source_write_requested\":false,\"snapshot_atomic\":false}\n";
            check(rois.good());
        }
        const auto id=retained_results.begin()->first,token=retained_results.begin()->second.retention_token;
        const auto before_docs=document_calls;
        try{execute_native({"show-profile","SHOW",{id}});check(false);}catch(const std::runtime_error& e){check(std::string(e.what())=="native_show_requires_qualified_2d_result");}
        check(document_calls==before_docs);
        for(const auto* op:{"MEAN","SUMMARY","FFT","PREVIEW","READ","CROP"}) {
            NativeRequest req{"old-2d",op,{id}};
            if(req.op=="PREVIEW")req.args={id,8,8};
            if(req.op=="READ" || req.op=="CROP")req.args={id,0,0,1,1};
            const auto calls=profile_value_calls353;
            try{execute_native(req);check(false);}catch(const std::runtime_error&){}
            check(profile_value_calls353==calls);
        }
        check(execute_native({"release-profile","RELEASE",{id,token}}).find("\"released_now\":true")!=std::string::npos);
        check(registry.size()==1 && retained_result_bytes==0);
        for(const auto& item:std::vector<std::pair<const char*,const char*>>{
            {"null","native_profile_missing_output"},{"alias","native_profile_output_identity_invalid"},
            {"rank","native_profile_output_descriptor_mismatch"},{"dtype","native_profile_output_descriptor_mismatch"},
            {"packing","native_profile_output_descriptor_mismatch"},{"samples","native_profile_output_descriptor_mismatch"},
            {"calibration","native_profile_output_calibration_mismatch"},{"intensity","native_profile_output_intensity_calibration_mismatch"},
            {"nonfinite","native_profile_nonfinite_value"}}){setup_profile_fake353();profile_fault353=item.first;expect_profile_failure353(item.second,true);}
        setup_profile_fake353();profile_fault353="line-changed";expect_profile_failure353("native_profile_source_snapshot_changed");
        setup_profile_fake353();profile_fault353="line-return";expect_profile_failure353("native_roi_line_return_mismatch");
        setup_profile_fake353();fake.scale[1]=0.5f;expect_profile_failure353("native_profile_requires_equal_signed_spatial_scales_and_units");
        setup_profile_fake353();auto wrong=profile_request353();wrong.args[8]=2;expect_profile_failure353("native_profile_requires_width_one",false,wrong);
        setup_profile_fake353();wrong=profile_request353();wrong.args[1]=30;expect_profile_failure353("native_profile_gui_line_missing",false,wrong);
        setup_profile_fake353();wrong=profile_request353();wrong.args[6]=8;expect_profile_failure353("native_profile_gui_line_changed",false,wrong);
        setup_profile_fake353();roi_fake353.rotation=10;expect_profile_failure353("rotated_line");
        setup_profile_fake353();roi_fault353="nonidentity-mapping";expect_profile_failure353("unsupported_coordinate_mapping");
        setup_profile_fake353();fake.scale[0]=fake.scale[1]=-0.25f;check(execute_native(profile_request353()).find("\"distance_step\":0.25")!=std::string::npos);
        setup_profile_fake353();profile_line353={7,1,2,1};auto reverse=profile_request353();reverse.args={17,31,9,7,7,1,2,1,1};
        check(execute_native(reverse).find("\"source_sample_step_xy\":[-1,0]")!=std::string::npos);
        setup_profile_fake353();profile_line353={2,1,2,6};auto vertical=profile_request353();vertical.args={17,31,9,7,2,1,2,6,1};
        check(execute_native(vertical).find("\"source_sample_step_xy\":[0,1]")!=std::string::npos);
        setup_profile_fake353();fake.code=11;check(execute_native(profile_request353()).find("\"dtype\":\"float64\"")!=std::string::npos);
        for(bool unresolved:{false,true}) {
            setup_profile_fake353();RetainedResult tracked{};tracked.value.image=&fake;InterlockedIncrement64(&fake.references);
            tracked.scientific_unresolved=unresolved;tracked.scientific_result=unresolved?"null":"{}";
            retained_results.emplace(17,std::move(tracked));
            try{execute_native(profile_request353());check(false);}catch(const std::runtime_error& e){check(std::string(e.what())=="native_profile_scientific_source_context_unsupported");}
            check(profile_calls353==0 && fake.references==2);shutdown_native();check(fake.references==1);
        }
        setup_profile_fake353();
        for(const auto& item:std::vector<std::pair<nb::RoiLine353,const char*>>{
            {{1,1,1,1},"empty_line"},{{1.5f,1,5,1},"fractional_line"},{{1,1,4,4},"unsupported_line_orientation"},
            {{1,1,8192,1},"out_of_bounds_line"},{{0,0,4096,0},"line_sample_budget"}})
            check(std::string(nb::roi_line_issue353(item.first,8192,8192))==item.second);
        check(nb::profile_samples353({0,0,4095,0},4096,2)==4096);
        std::string bytes;nb::append_profile_float64_le353(bytes,1234567890.125);check(bytes.size()==8);
        const auto contract=nb::operation_contract("PROFILE");check(contract && contract->arguments==9);
        shutdown_native();
        std::cout<<assertions<<" line profile adapter assertions passed (offline callbacks only)\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
