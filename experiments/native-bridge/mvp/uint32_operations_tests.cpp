// Ownership, descriptor and admission surrogates. No vendor code is loaded;
// synthetic FFT/filter callbacks do not establish native numerical semantics.
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main

namespace {
NativeRef* u32_unary(NativeRef* out,const NativeRef* source) {
    operation_fake(out,source,nullptr,0);
    if(out->image && operation_fault!="dtype") static_cast<FakeImage*>(out->image)->code=2;
    return operation_fault=="return_pointer" ? nullptr : out;
}
NativeRef* u32_binary(NativeRef* out,const NativeRef* a,const NativeRef* b) {
    check(static_cast<FakeImage*>(b->image)->code==11);
    return u32_unary(out,a);
}
void rejected(const NativeRequest& request,const char* error) {
    const auto count=retained_results.size();const auto bytes=retained_result_bytes;
    std::string actual;
    try{execute_native(request);}catch(const std::runtime_error& e){actual=e.what();}
    if(actual!=error)throw std::runtime_error(std::string("request ")+request.id+" expected "+error+", received "+actual);
    check(actual==error);
    check(count==retained_results.size() && bytes==retained_result_bytes && fake.references==1);
}
void contains(const std::string& text,const char* fragment){check(text.find(fragment)!=std::string::npos);}
}
int main(){
    try{
        inject_fake();operation_tracking=true;fake.code=11;fake.width=fake.height=8;
        fake.pixels.assign(64,1);fake.uint32_pixels.assign(64,16777217);const auto original=fake.uint32_pixels;
        api.negate=api.abs=api.square=u32_unary;api.add=api.subtract=api.multiply=u32_binary;
        api.sobel_filter=api.laplace_filter=u32_unary;
        const auto status=execute_native({"status","STATUS",{}});
        check(status.find("prepared_")==std::string::npos);
        for(const auto* group:{"native_uint32_display","native_uint32_image_arithmetic","native_uint32_filters","native_uint32_fft"}){
            check(qualified_capability353(group));
            for(const bool binding:{false,true}){
                bool caught=false;try{nb::require_uint32_admission353(false,binding,group);}
                catch(const std::runtime_error&){caught=true;}check(caught);
            }
        }
        for(const auto* op:{"UNARY","BINARY"})for(unsigned code=1;code<=3;++code){
            const auto result=execute_native({"arithmetic",op,std::string(op)=="BINARY"?
                std::vector<std::uint32_t>{17,17,code}:std::vector<std::uint32_t>{17,code}});
            check(nb::valid_json(result));contains(result,"\"output_dtype\":\"float32\"");
            contains(result,"DM native operator output; no bridge pixel cast");
            contains(result,"binary32 result; not lossless for arbitrary uint32 inputs");
            const auto& record=retained_results.rbegin()->second;
            check(record.data_type_code==2 && record.uint32_operation_lineage);
            contains(record.semantics,"binary64 native arithmetic then binary32 result");
        }
        const auto changed_id=retained_results.begin()->first;
        auto* changed=registry.at(changed_id);changed->code=11;
        const auto documents_before=document_calls,shows_before=show_calls;
        rejected({"changed-dtype","SHOW",{changed_id}},"native_show_result_descriptor_changed");
        check(document_calls==documents_before && show_calls==shows_before && changed->references==1);
        changed->code=2;
        std::vector<std::uint32_t> shown;
        for(unsigned code=1;code<=4;++code){
            const auto result=execute_native({"filter","FILTER",{17,code}});
            check(nb::valid_json(result));const auto id=retained_results.rbegin()->first;
            const auto type=(code==1||code==4)?11u:2u;
            check(retained_results.at(id).data_type_code==type && retained_results.at(id).uint32_operation_lineage);
            contains(result,type==11?"\"output_dtype\":\"uint32\"":"\"output_dtype\":\"float32\"");
            if(type==11){contains(execute_native({"show","SHOW",{id}}),"\"image\":");shown.push_back(id);}
        }
        execute_native({"fft","FFT",{17}});const auto fft_id=retained_results.rbegin()->first;
        const auto inverse=execute_native({"inverse","IFFT",{fft_id}});const auto inverse_id=retained_results.rbegin()->first;
        contains(inverse,"\"input_dtypes\":[\"complex64\"]");
        for(const auto* op:{"REAL","IMAG","VENDOR_ARG","VENDOR_NORM"}){
            const auto result=execute_native({op,op,{fft_id}});
            contains(result,"\"input_dtypes\":[\"complex64\"]");contains(result,"\"output_dtype\":\"float32\"");
            check(retained_results.rbegin()->second.uint32_operation_lineage);
        }
        contains(execute_native({"inverse-real","REAL",{inverse_id}}),"uint32 ancestry");
        const auto before=operation_calls;
        fake.width=257;rejected({"large","FILTER",{17,1}},"native_filter_input_over_budget");
        rejected({"non-power-two","FFT",{17}},"native_fft_requires_power_of_two_dimensions_4_to_1024");
        fake.width=2048;
        rejected({"large","FFT",{17}},"native_fft_input_over_budget");fake.width=8;
        check(before==operation_calls);
        fake.width=fake.height=3;rejected({"small","FFT",{17}},"native_fft_requires_power_of_two_dimensions_4_to_1024");
        fake.width=fake.height=8;check(before==operation_calls);
        const auto saved=retained_result_bytes;retained_result_bytes=nb::kCropRetainedBytes;
        rejected({"budget","UNARY",{17,1}},"native_result_retained_bytes_over_budget");
        retained_result_bytes=saved;check(before==operation_calls);
        api.square=nullptr;
        rejected({"missing","UNARY",{17,1}},"native_uint32_symbol_unavailable:native_uint32_image_arithmetic");
        api.square=u32_unary;check(before==operation_calls);
        operation_fault="dtype";
        rejected({"dtype","UNARY",{17,1}},"native_arithmetic_output_descriptor_mismatch");
        check(!registry.count(last_output_id));operation_fault="throw";
        rejected({"throw","UNARY",{17,1}},"surrogate operation failure");
        check(!registry.count(last_output_id));operation_fault.clear();
        FakeImage right=fake;right.id=18;right.code=2;registry.emplace(18,&right);
        const auto calls=operation_calls;
        rejected({"mixed","BINARY",{17,18,1}},"native_binary_dtype_mismatch");
        check(calls==operation_calls && right.references==1);registry.erase(18);
        check(fake.uint32_pixels==original && fake.references==1);
        shutdown_native();check(retained_results.empty()&&!retained_result_bytes);
        for(const auto id:shown)check(registry.count(id)&&registry.at(id)->references==1);
        close_surrogate_documents();check(registry.size()==1&&fake.references==1);
        std::cout<<"PASS uint32 operation contracts "<<assertions<<" assertions; synthetic callbacks only\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
