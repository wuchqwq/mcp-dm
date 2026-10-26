// Windows offline candidate: actual adapter, C-shaped synthetic callbacks only.
// No vendor DLL, DM process, native ABI qualification or browser is implied.
#include <filesystem>
#include <fstream>
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main

namespace {
int import_creates = 0, import_writes = 0, import_axes = 0;
std::string import_fault;
NativeRef* import_create_fake(NativeRef* out, const nb::NativeDataSize353* size, std::uint32_t type,
                              const nb::NativeCharRange353* name) {
    ++import_creates; check(type == 2 && size->dimensions == 2 && size->size[2] == 0 && name->end > name->begin);
    if (import_fault == "null") return out;
    if (import_fault == "alias") { InterlockedIncrement64(&fake.references); out->image = &fake; return out; }
    auto item = std::make_unique<FakeImage>(); item->id = next_image_id++; item->generated = true;
    item->width = static_cast<std::uint32_t>(size->size[0]); item->height = static_cast<std::uint32_t>(size->size[1]);
    item->pixels.assign(static_cast<std::size_t>(item->width)*item->height, 0);
    if (import_fault == "rank") item->dimensions = 3;
    if (import_fault == "dtype") item->code = 11;
    if (import_fault == "packing") item->packing = 2;
    registry.emplace(item->id, item.get()); out->image = item.release();
    if (import_fault == "create_throw") throw std::runtime_error("synthetic constructor failure");
    return out;
}
void import_set_fake(void* image, const nb::NativeDataIndex2D353* index, double value) {
    ++import_writes; auto* item = static_cast<FakeImage*>(image);
    check(item != &fake && item->generated && index->dimensions == 2 && index->padding == 0);
    check(index->x >= 0 && index->y >= 0 && index->x < item->width && index->y < item->height);
    if (import_fault == "write_throw" && import_writes == 3) throw std::runtime_error("synthetic write failure");
    item->pixels.at(static_cast<std::size_t>(index->y)*item->width+index->x) = static_cast<float>(value);
    if (import_fault == "changed_pixel" && import_writes == 1) item->pixels.front() = 42;
}
void import_axis_fake(void* image, std::uint32_t axis, float origin, float scale,
                      const nb::NativeCharRange353* unit, std::int32_t format) {
    ++import_axes; check(axis < 2 && format == 1); auto* item = static_cast<FakeImage*>(image);
    item->origin[axis] = origin; item->scale[axis] = scale; item->unit[axis].assign(unit->begin, unit->end);
    if (import_fault == "calibration") item->scale[axis] *= 2;
}
std::string synthetic_npy(const std::vector<float>& values, unsigned h, unsigned w, unsigned version=1) {
    std::string header = "{'descr': '<f4', 'fortran_order': False, 'shape': (" + std::to_string(h) + ", " + std::to_string(w) + "), }";
    const auto prefix = version == 1 ? 10u : 12u;
    while ((prefix+header.size()+1)%64) header += ' '; header += '\n';
    std::string bytes("\x93NUMPY", 6); bytes += static_cast<char>(version); bytes += '\0';
    for (unsigned i=0;i<(version==1?2u:4u);++i) bytes += static_cast<char>((header.size()>>(8*i))&255);
    bytes += header;
    for (const auto value : values) { const auto bits=nb::import_bits353(value); for(unsigned i=0;i<4;++i)bytes+=static_cast<char>((bits>>(8*i))&255); }
    return bytes;
}
std::vector<std::uint32_t> import_args(const std::string& npy, const std::string& manifest, unsigned w=4, unsigned h=3, unsigned packed=17) {
    std::vector<std::uint32_t> args(27, 0); args[0]=0x12345678;args[1]=0x9abcdef0;args[2]=0x11223344;args[3]=0x55667788;
    for (const auto start : {4u,12u}) { const auto digest=import_digest353(start==4?npy:manifest); for(unsigned i=0;i<8;++i)args[start+i]=static_cast<std::uint32_t>(std::stoull(digest.substr(i*8,8),nullptr,16)); }
    args[20]=w;args[21]=h;args[22]=nb::import_bits353(2.5f);args[23]=nb::import_bits353(-.25f);
    args[24]=nb::import_bits353(-3.25f);args[25]=nb::import_bits353(.125f);args[26]=packed;return args;
}
void setup_import() {
    shutdown_native(); close_surrogate_documents(); inject_fake();
    fake.width=4;fake.height=3;fake.code=2;fake.dimensions=2;fake.packing=1;fake.pixels.assign(12,7.25f);
    import_creates=import_writes=import_axes=0; import_fault.clear();invalid_scale=false;calibration_throws=false;preview_fault.clear();
    histogram_api353.create_image=import_create_fake;histogram_api353.set_dimension_calibration=import_axis_fake;import_api353.set_real_value=import_set_fake;
}
void expect_import_fail(const NativeRequest& r, const ImportPacket353& p, const std::string& expected, bool before_create) {
    const auto created=import_creates,writes=import_writes; bool failed=false;
    try { execute_import_packet353(r,p); } catch(const std::runtime_error& e) { failed=true; if(e.what()!=expected)std::cerr<<"expected "<<expected<<" got "<<e.what()<<'\n';check(e.what()==expected); }
    check(failed && retained_results.empty() && retained_result_bytes==0 && registry.size()==1 && fake.references==1);
    check(fake.pixels==std::vector<float>(12,7.25f));if(before_create)check(created==import_creates&&writes==import_writes);
}
#ifdef NB_IMPORT_QUALIFICATION_BUILD
// Real Windows file I/O and the real request registry; only vendor callbacks
// are synthetic. Staging is confined to a freshly owned temporary directory.
struct ImportStagingFixture {
    std::filesystem::path base, root;
    std::wstring old_local, old_session;
    bool had_local = false, had_session = false;
    static std::wstring old_environment(const wchar_t* key, bool& existed) {
        const auto n=GetEnvironmentVariableW(key,nullptr,0);existed=n>0;if(!n)return {};
        std::wstring value(n,L'\0');check(GetEnvironmentVariableW(key,&value[0],n)==n-1);value.resize(n-1);return value;
    }
    ImportStagingFixture() {
        wchar_t temporary[MAX_PATH+1]{};check(GetTempPathW(MAX_PATH,temporary)>0);
        base=std::filesystem::path(temporary)/(L"mcp-import-offline-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64()));
        check(!std::filesystem::exists(base));root=base/L"mcp-dm"/L"native-import"/std::wstring(32,L'a');
        std::filesystem::create_directories(root);old_local=old_environment(L"LOCALAPPDATA",had_local);old_session=old_environment(L"DM_NATIVE_SESSION",had_session);
        check(SetEnvironmentVariableW(L"LOCALAPPDATA",base.c_str())!=0);check(SetEnvironmentVariableW(L"DM_NATIVE_SESSION",std::wstring(32,L'a').c_str())!=0);
    }
    ~ImportStagingFixture() {
        SetEnvironmentVariableW(L"LOCALAPPDATA",had_local?old_local.c_str():nullptr);SetEnvironmentVariableW(L"DM_NATIVE_SESSION",had_session?old_session.c_str():nullptr);
        // Absolute target was allocated above and never accepted from input.
        if(base.is_absolute()&&base.filename().wstring().find(L"mcp-import-offline-")==0){std::error_code ignored;std::filesystem::remove_all(base,ignored);}
    }
    std::filesystem::path path(const nb::ImportSpec353& spec,const wchar_t* suffix)const{return root/(std::wstring(spec.ticket.begin(),spec.ticket.end())+suffix);}
    void write(const nb::ImportSpec353& spec,const std::string& npy,const std::string& manifest)const {
        for(const auto& entry:std::vector<std::pair<std::filesystem::path,std::string>>{{path(spec,L".npy"),npy},{path(spec,L".json"),manifest}}){std::ofstream out(entry.first,std::ios::binary|std::ios::trunc);out.write(entry.second.data(),static_cast<std::streamsize>(entry.second.size()));check(out.good());}
    }
};
void fixed_root_and_recovery_tests(const std::string& npy,const std::string& manifest,const std::vector<float>& pixels) {
    ImportStagingFixture files;auto args=import_args(npy,manifest);const auto spec=nb::import_spec353(args);files.write(spec,npy,manifest);
    setup_import();const NativeRequest request{"saved-file-import","IMPORT",args};
    const auto packet=load_import353(request);check(packet.pixels==pixels&&packet.manifest==manifest);
    const auto reject_before_vendor=[&](const NativeRequest& input,const std::string& expected){const auto creates=import_creates,writes=import_writes;bool failed=false;try{execute_native(input);}catch(const std::runtime_error& e){failed=true;check(e.what()==expected);}check(failed&&creates==import_creates&&writes==import_writes&&retained_results.empty());};
    check(SetEnvironmentVariableW(L"DM_NATIVE_SESSION",std::wstring(32,L'\u0161').c_str())!=0);reject_before_vendor(request,"native_import_session_invalid");check(SetEnvironmentVariableW(L"DM_NATIVE_SESSION",std::wstring(32,L'a').c_str())!=0);
    files.write(spec,npy+"x",manifest);reject_before_vendor(request,"native_import_staged_hash_mismatch");files.write(spec,npy,manifest);
    auto wrong=args;wrong[4]^=1;reject_before_vendor({"wrong-hash","IMPORT",wrong},"native_import_staged_hash_mismatch");
    const auto writer=CreateFileW(files.path(spec,L".npy").c_str(),GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);check(writer!=INVALID_HANDLE_VALUE);
    reject_before_vendor(request,"native_import_file_open_failed");CloseHandle(writer);
    std::string malformed=npy;malformed[11]='!';auto malformed_args=import_args(malformed,manifest);files.write(spec,malformed,manifest);reject_before_vendor({"bad-npy","IMPORT",malformed_args},"native_import_requires_canonical_float32_npy");files.write(spec,npy,manifest);
    auto mismatched=npy;mismatched.at(mismatched.find("'descr'"))='"';auto mismatched_args=import_args(mismatched,manifest);files.write(spec,mismatched,manifest);reject_before_vendor({"mismatched-header-quotes","IMPORT",mismatched_args},"native_import_requires_canonical_float32_npy");files.write(spec,npy,manifest);
    const std::string invalid_utf8="{\"source\":\"\xc0\xaf\"}";auto invalid_args=import_args(npy,invalid_utf8);files.write(spec,npy,invalid_utf8);reject_before_vendor({"bad-utf8","IMPORT",invalid_args},"native_import_manifest_must_be_utf8_json_object");
    const std::string oversized="{\"source\":\""+std::string(9000,'\\')+"\"}";check(nb::valid_json(oversized));auto oversized_args=import_args(npy,oversized);files.write(spec,npy,oversized);reject_before_vendor({"large-sidecar","IMPORT",oversized_args},"native_import_manifest_encoded_response_over_budget");
    files.write(spec,npy,manifest);
    nb::Core core(std::string(32,'a'),123,321);core.set_worker(777);core.mark_ready(321);
    auto line=std::string("NB2 ")+std::string(32,'a')+" saved-file-import IMPORT";for(const auto arg:args)line+=' '+std::to_string(arg);
    const auto accepted=core.accept(nb::parse_line(line));check(accepted.dispatch_token!=0);check(core.accept(nb::parse_line(line)).dispatch_token==0);
    auto conflict=line;const auto last=conflict.find_last_of(' ');conflict.replace(last+1,std::string::npos,"0");check(core.accept(nb::parse_line(conflict)).receipt.find("id_conflict")!=std::string::npos);
    const auto active=core.begin(accepted.dispatch_token,321);check(active!=nullptr);core.finish(active,execute_native(request));check(import_creates==1&&import_writes==12);
    const auto completed=core.accept(nb::parse_line(std::string("NB2 ")+std::string(32,'a')+" saved-file-import QUERY")).receipt;check(completed.find("\"state\":\"completed\"")!=std::string::npos&&completed.find("native_numeric_import")!=std::string::npos);
    // A later client can retrieve the completed operation after staged inputs
    // disappear. No new creation, no automatic resubmission, same image ID.
    check(std::filesystem::remove(files.path(spec,L".npy")));check(std::filesystem::remove(files.path(spec,L".json")));
    check(core.accept(nb::parse_line(line)).receipt==completed);check(!core.begin(accepted.dispatch_token,321));check(import_creates==1&&retained_results.size()==1);
    check(fake.pixels==std::vector<float>(12,7.25f));shutdown_native();
}
void localappdata_atomic_publication_test(const std::string& npy,const std::string& manifest,const std::vector<float>& pixels) {
    // Real Windows LocalAppData can be OS-virtualized for a packaged launcher.
    // Publish exactly as Node does (new temp -> hardlink -> unlink temp), under
    // a new owned session only. Never alter any existing staging session.
    const auto local=import_environment353(L"LOCALAPPDATA");unsigned char random[16]{};
    check(BCryptGenRandom(nullptr,random,sizeof(random),BCRYPT_USE_SYSTEM_PREFERRED_RNG)>=0);
    constexpr char hex[]="0123456789abcdef";std::string session;for(const auto b:random){session+=hex[b>>4];session+=hex[b&15];}
    const auto root=std::filesystem::path(local)/L"mcp-dm"/L"native-import"/std::wstring(session.begin(),session.end());
    std::filesystem::create_directories(root.parent_path());check(CreateDirectoryW(root.c_str(),nullptr)!=0);
    bool existed=false;const auto prior=ImportStagingFixture::old_environment(L"DM_NATIVE_SESSION",existed);
    auto args=import_args(npy,manifest);const auto spec=nb::import_spec353(args);const std::wstring ticket(spec.ticket.begin(),spec.ticket.end());
    struct Cleanup {std::filesystem::path root;std::wstring ticket,prior;bool existed;
        ~Cleanup(){SetEnvironmentVariableW(L"DM_NATIVE_SESSION",existed?prior.c_str():nullptr);for(const auto* suffix:{L".npy",L".json",L".npy.publication-test.tmp",L".json.publication-test.tmp"})DeleteFileW((root/(ticket+suffix)).c_str());RemoveDirectoryW(root.c_str());}
    } cleanup{root,ticket,prior,existed};
    check(SetEnvironmentVariableW(L"DM_NATIVE_SESSION",std::wstring(session.begin(),session.end()).c_str())!=0);
    for(const auto& item:std::vector<std::pair<std::wstring,std::string>>{{L".npy",npy},{L".json",manifest}}){
        const auto target=root/(ticket+item.first),temporary=root/(ticket+item.first+L".publication-test.tmp");
        const auto handle=CreateFileW(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);check(handle!=INVALID_HANDLE_VALUE);
        DWORD written=0;const auto ok=WriteFile(handle,item.second.data(),static_cast<DWORD>(item.second.size()),&written,nullptr)&&FlushFileBuffers(handle);CloseHandle(handle);check(ok&&written==item.second.size());
        check(CreateHardLinkW(target.c_str(),temporary.c_str(),nullptr)!=0);check(DeleteFileW(temporary.c_str())!=0);
    }
    setup_import();const auto result=load_import353({"localappdata-atomic-publication","IMPORT",args});check(result.pixels==pixels&&result.manifest==manifest);check(import_creates==0&&import_writes==0);shutdown_native();
}
#endif
}
int main(int argc, char** argv) {
    try {
        const std::vector<float> pixels={-0.0f,0.0f,-1.25f,2.5f,100.125f,-800,16777216,1.0f,.125f,-.0625f,5,9};
        const auto npy=synthetic_npy(pixels,3,4);const std::string manifest="{\"source\":\"independent synthetic input\",\"computation\":\"external\"}";
        auto args=import_args(npy,manifest);const NativeRequest request{"import-synthetic","IMPORT",args};
        auto packet=ImportPacket353{nb::import_spec353(args),pixels,manifest};
        check(nb::import_npy353(npy,packet.spec).size()==pixels.size());
        check(nb::import_npy353(synthetic_npy(pixels,3,4,2),packet.spec).size()==pixels.size());
        auto double_quoted=npy;std::replace(double_quoted.begin()+10,double_quoted.begin()+10+static_cast<unsigned char>(double_quoted[8]),'\'', '"');check(nb::import_npy353(double_quoted,packet.spec).size()==pixels.size());
        for(const auto* key:{"'descr'","'<f4'","'fortran_order'","'shape'"}){auto mismatched=npy;mismatched.at(mismatched.find(key))='"';try{nb::import_npy353(mismatched,packet.spec);check(false);}catch(const std::runtime_error& e){check(std::string(e.what())=="native_import_requires_canonical_float32_npy");}}
        for(const auto invalid : {0u,16385u,UINT32_MAX}) {auto bad=args;bad[20]=invalid;try{nb::import_spec353(bad);check(false);}catch(const std::runtime_error&){check(true);}}
        for(const auto packed : {7u,16u+4u,32u+1u,48u}) {auto bad=args;bad[26]=packed;try{nb::import_spec353(bad);check(false);}catch(const std::runtime_error&){check(true);}}
        for(const auto index:{22u,23u,24u,25u}){auto bad=args;bad[index]=nb::import_bits353(std::numeric_limits<float>::max());bad[index==22?23:index==24?25: index]=nb::import_bits353(std::numeric_limits<float>::max());try{nb::import_spec353(bad);check(false);}catch(const std::runtime_error&){check(true);}}
        for (auto bad : {npy+'x',npy.substr(1),synthetic_npy({std::numeric_limits<float>::infinity()},1,1)}) {
            try{nb::import_npy353(bad,packet.spec);check(false);}catch(const std::runtime_error&){check(true);}
        }
        setup_import();
#ifndef NB_IMPORT_QUALIFICATION_BUILD
        (void)argc; (void)argv;
        expect_import_fail(request,packet,"native_operation_not_qualified:native_numeric_import",true);
        std::cout<<"import shipping-disabled tests passed "<<assertions<<" assertions; no vendor calls\n";return 0;
#else
        auto created=attach_retention353(request,execute_import_packet353(request,packet));check(nb::valid_json(created));check(import_creates==1&&import_writes==12&&import_axes==2);
        if(argc==2){std::ofstream file(argv[1],std::ios::binary);file<<"{\"args\":[";for(std::size_t i=0;i<args.size();++i){if(i)file<<',';file<<args[i];}file<<"],\"result\":"<<created<<'}';check(file.good());}
        check(retained_results.size()==1&&retained_result_bytes==48&&fake.references==1);
        const auto id=retained_results.begin()->first;const auto* output=static_cast<const FakeImage*>(retained_results.begin()->second.value.image);
        for(std::size_t i=0;i<pixels.size();++i)check(nb::import_bits353(output->pixels[i])==nb::import_bits353(pixels[i]));
        check(output->scale[0]==-.25f&&output->origin[1]==-3.25f&&output->unit[0]==L"nm");
        check(execute_native({"import-read","READ",{id,0,0,4,3}}).find("\"operation\":\"IMPORT\"")!=std::string::npos);
        auto* editable=static_cast<FakeImage*>(retained_results.begin()->second.value.image);editable->pixels[0]=17.75f;editable->origin[0]=3.5f;
        const auto edited_read=execute_native({"read-after-user-edit","READ",{id,0,0,4,3}});
        const auto expected_bytes=nb::read_base64_353(std::string(reinterpret_cast<const char*>(editable->pixels.data()),editable->pixels.size()*sizeof(float)));
        check(edited_read.find(expected_bytes)!=std::string::npos&&edited_read.find("\"origin\":3.5")!=std::string::npos);
        check(edited_read.find("creation identity only; current values/calibration are fresh and may differ")!=std::string::npos);
        check(retained_results.begin()->second.metadata.find("\"origin\":2.5")!=std::string::npos);
        check(execute_native({"info-after-user-edit","INFO",{id}}).find("creation identity only; current values/calibration are fresh and may differ")!=std::string::npos);
        editable->pixels=pixels;editable->origin[0]=2.5f;
        check(execute_native({"import-show","SHOW",{id}}).find("\"document_visible\":true")!=std::string::npos);
        shutdown_native();check(host_documents.size()==1&&static_cast<FakeImage*>(host_documents.begin()->second->image)->pixels==pixels);
        close_surrogate_documents();check(registry.size()==1&&fake.references==1);
        for(const auto& fault : std::vector<std::pair<std::string,std::string>>{{"null","native_import_null_output"},{"alias","native_import_output_alias"},{"rank","native_import_output_descriptor_mismatch"},{"dtype","native_import_output_descriptor_mismatch"},{"packing","native_import_output_descriptor_mismatch"},{"create_throw","synthetic constructor failure"},{"write_throw","synthetic write failure"},{"changed_pixel","native_import_pixel_readback_mismatch"},{"calibration","native_import_calibration_readback_mismatch"}}) {
            setup_import();import_fault=fault.first;expect_import_fail(request,packet,fault.second,false);
        }
        setup_import();auto corrupt=packet;corrupt.pixels[0]=std::numeric_limits<float>::quiet_NaN();expect_import_fail(request,corrupt,"native_import_nonfinite_pixel",true);
        setup_import();corrupt=packet;corrupt.manifest="{}";expect_import_fail(request,corrupt,"native_import_packet_identity_mismatch",true);
        setup_import();auto unknown_args=args;unknown_args[26]=0;auto unknown=packet;unknown.spec=nb::import_spec353(unknown_args);check(nb::valid_json(execute_import_packet353({"unknown","IMPORT",unknown_args},unknown)));check(retained_results.begin()->second.metadata.find("\"calibration_complete\":false")!=std::string::npos);
        shutdown_native();
        fixed_root_and_recovery_tests(npy,manifest,pixels);
        localappdata_atomic_publication_test(npy,manifest,pixels);
        std::cout<<"import candidate adapter tests passed "<<assertions<<" assertions; C-shaped fakes only, no DM\n";return 0;
#endif
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
