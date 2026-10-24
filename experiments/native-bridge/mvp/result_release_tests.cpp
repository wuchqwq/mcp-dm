// Exercise the actual version adapter with fake C-shaped vendor callbacks.
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main

int main() {
    try {
        inject_fake(); operation_tracking = true;
        fake.pixels.resize(fake.width*fake.height);
        for (unsigned i=0;i<fake.pixels.size();++i) fake.pixels[i]=static_cast<float>(i)-20.25f;
        const auto original = fake.pixels;
        const auto created = execute_native({"owned-crop", "CROP", {17, 1, 1, 5, 4}});
        const auto id = retained_results.begin()->first;
        const auto token = retained_results.at(id).retention_token;
        check(token > 0 && created.find("\"retention\":{") != std::string::npos);
        const auto bytes = retained_result_bytes;
        for (const auto& args : {std::vector<std::uint32_t>{17, token}, {id, token+1}, {id, 0}}) {
            try { execute_native({"invalid", "RELEASE", args}); check(false); }
            catch (const std::runtime_error&) { check(retained_results.size()==1 && retained_result_bytes==bytes && fake.references==1); }
        }
        check(execute_native({"info-before", "RESULT_INFO", {id,token}}).find("\"plugin_retained\":true") != std::string::npos);
        const auto released = execute_native({"release", "RELEASE", {id,token}});
        check(released.find("\"released_now\":true") != std::string::npos);
        check(retained_results.empty() && retained_result_bytes==0 && registry.count(id)==0);
        const auto destroyed = destructions;
        check(execute_native({"release-again", "RELEASE", {id,token}}).find("\"released_now\":false") != std::string::npos);
        check(destructions==destroyed);
        check(execute_native({"info-after", "RESULT_INFO", {id,token}}).find("\"available_for_native_processing\":false") != std::string::npos);
        for (const char* op : {"READ","SHOW","MEAN"}) {
            try { execute_native({"released-input",op,op==std::string("READ") ? std::vector<std::uint32_t>{id,0,0,1,1} : std::vector<std::uint32_t>{id}}); check(false); }
            catch (const std::runtime_error& error) { check(std::string(error.what())=="native_result_released_or_reused_id"); }
        }
        // Reused numeric IDs cannot authorize release of another retained object.
        next_image_id=id;
        execute_native({"reused-crop","CROP",{17,1,1,5,4}});
        const auto replacement_token=retained_results.at(id).retention_token;
        check(replacement_token!=token);
        execute_native({"old-token-again","RELEASE",{id,token}});
        check(retained_results.at(id).retention_token==replacement_token && retained_result_bytes==bytes);
        execute_native({"show-owned","SHOW",{id}});
        check(registry.at(id)->references==2 && host_documents.size()==1);
        execute_native({"release-shown","RELEASE",{id,replacement_token}});
        check(registry.count(id)==1 && registry.at(id)->references==1 && host_documents.size()==1 && retained_result_bytes==0);
        // Simulate the host closing its own document, not a plugin operation.
        close_surrogate_documents();
        check(registry.count(id)==0);
        // Capacity is reusable, with a new token every time and no eviction.
        std::uint32_t previous_token=replacement_token;
        for (unsigned i=0;i<40;++i) {
            execute_native({"cycle-"+std::to_string(i),"CROP",{17,0,0,3,3}});
            const auto entry=retained_results.begin();const auto image_id=entry->first, current=entry->second.retention_token;
            check(current>previous_token);previous_token=current;
            execute_native({"cycle-release-"+std::to_string(i),"RELEASE",{image_id,current}});
            check(retained_results.empty() && retained_result_bytes==0);
        }
        check(fake.pixels==original && fake.references==1);
        // History is immutable even after a later native release, and duplicate
        // release requests do not dispatch the adapter twice.
        const std::string session(32,'a');
        nb::Core core(session,123,GetCurrentThreadId());
        core.set_worker(GetCurrentThreadId()+1);core.mark_ready(GetCurrentThreadId());
        auto submit=[&](const std::string& text) {
            const auto parsed=nb::parse_line("NB2 "+session+" "+text);
            const auto admission=core.accept(parsed);
            if(admission.dispatch_token) {
                auto record=core.begin(admission.dispatch_token,GetCurrentThreadId());
                core.finish(record,execute_native(record->request));
            }
            return core.accept(nb::parse_line("NB2 "+session+" "+parsed.request.id+" QUERY")).receipt;
        };
        const auto creation_history=submit("core-crop CROP 17 0 0 3 3");
        auto entry=retained_results.begin();const auto core_id=entry->first, core_token=entry->second.retention_token;
        const std::string release_args=std::to_string(core_id)+" "+std::to_string(core_token);
        const auto release_history=submit("core-release RELEASE "+release_args);
        check(submit("core-release RELEASE "+release_args)==release_history);
        check(submit("core-crop QUERY")==creation_history);
        check(core.accept(nb::parse_line("NB2 "+session+" core-release RELEASE 17 1")).receipt.find("id_conflict")!=std::string::npos);
        check(retained_results.empty() && retained_result_bytes==0);
        // Live Fourier descendants carry their own metadata/reference; the
        // original FFT and inverse are not kept solely for provenance.
        fake.width=fake.height=8;fake.pixels.resize(64);
        execute_native({"dep-fft","FFT",{17}});
        const auto fft=last_retained_result353, fft_token=retained_results.at(fft).retention_token;
        execute_native({"dep-inverse","IFFT",{fft}});
        const auto inverse=last_retained_result353, inverse_token=retained_results.at(inverse).retention_token;
        execute_native({"dep-release-fft","RELEASE",{fft,fft_token}});
        execute_native({"dep-real","REAL",{inverse}});
        const auto real=last_retained_result353, real_token=retained_results.at(real).retention_token;
        execute_native({"dep-release-inverse","RELEASE",{inverse,inverse_token}});
        check(retained_results.size()==1 && retained_results.count(real)==1);
        check(execute_native({"dep-read-real","READ",{real,0,0,2,2}}).find("tracked_fourier")!=std::string::npos);
        execute_native({"dep-release-real","RELEASE",{real,real_token}});
        check(retained_results.empty() && retained_result_bytes==0 && fake.references==1);
        shutdown_native();check(released_results353.empty());
        std::cout << "PASS result reference release " << assertions << " assertions; synthetic callbacks only\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
