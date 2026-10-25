#include "core.hpp"
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0;
void require(bool condition) { ++checks; if (!condition) throw std::runtime_error("core check " + std::to_string(checks) + " failed"); }
const std::string session(32, 'a');
nb::Parsed parse(const std::string& tail) { return nb::parse_line("NB2 " + session + " " + tail); }
void reject(const std::string& s) { try { nb::parse_line(s); require(false); } catch (const nb::ProtocolError&) { require(true); } }
void identity(const std::string& receipt, const std::string& op, const std::string& args, const std::string& type, unsigned version = 1) {
    require(receipt.find("\"protocol\":\"NB2\"") != std::string::npos);
    require(receipt.find("\"original_operation\":\"" + op + "\"") != std::string::npos);
    require(receipt.find("\"normalized_args\":" + args) != std::string::npos);
    require(receipt.find("\"result_type\":\"" + type + "\"") != std::string::npos);
    require(receipt.find("\"result_version\":" + std::to_string(version)) != std::string::npos);
}
void no_identity(const std::string& receipt) {
    for (const auto* key : {"original_operation", "normalized_args", "result_type", "result_version"})
        require(receipt.find(std::string("\"") + key + "\":null") != std::string::npos);
}
}
int main() {
    try {
        for (const auto& tail : {"id STATUS", "id DATASETS", "id QUERY", "id STOP", "id INFO 0", "id MEAN 4294967295", "id SUMMARY 0", "id SUMMARY 4294967295", "id CROP 1 0 0 4 3", "id SHOW 1", "id SHOW 4294967295", "id UNARY 7 1", "id BINARY 7 8 3"}) require(!parse(tail).request.op.empty());
        for (const auto& tail : {"id STATUSX", "id STATUS 1", "id INFO", "id INFO -1", "id INFO +1", "id INFO 4294967296", "id INFO 1x", "id MEAN 1.2", "id CROP 1 0 0 1", "id CROP 1 0 0 1 2 3", "bad.id STATUS", "id  STATUS", "id STATUS ", "id\tSTATUS"}) reject("NB2 " + session + " " + tail);
        reject(""); reject("NB1 " + session + " id STATUS"); reject("NB2 " + std::string(32, 'A') + " id STATUS");
        reject("NB2 " + session + " " + std::string(65, 'i') + " STATUS"); reject("NB2 " + session + " id STATUS\n");
        for (const auto& tail : {"id SHOW", "id SHOW 1 2", "id SHOW -1", "id SHOW +1", "id SHOW 1.5", "id SHOW 4294967296"})
            reject("NB2 " + session + " " + tail);
        for (const auto& tail : {"id SUMMARY", "id SUMMARY 1 2", "id SUMMARY -1", "id SUMMARY +1", "id SUMMARY 1.5", "id SUMMARY 4294967296", "id SUMMARY front"})
            reject("NB2 " + session + " " + tail);
        for (const auto& tail : {"id UNARY 7", "id UNARY 7 1 2", "id UNARY -1 1", "id BINARY 7 8", "id BINARY 7 8 3 4", "id BINARY 7 8 4294967296"})
            reject("NB2 " + session + " " + tail);
        for (const auto& tail : {"id FFT 7", "id IFFT 7", "id REAL 7", "id IMAG 7", "id VENDOR_ARG 7", "id VENDOR_NORM 7", "id FILTER 7 4", "id PREVIEW 7 128 128", "id READ 7 0 1 8 4"})
            require(!parse(tail).request.op.empty());
        for (const auto& tail : {"id FFT", "id FFT 7 8", "id REAL -1", "id FILTER 7", "id FILTER 7 1 2", "id PREVIEW 7 128", "id PREVIEW 7 128 128 1", "id PREVIEW 7 1 4294967296", "id READ 7 0 1 8", "id READ 7 0 1 8 4 5", "id READ 7 -1 0 8 4", "id READ 7 0 0 1.5 4", "id READ 7 0 0 4294967296 4"})
            reject("NB2 " + session + " " + tail);
        for (const auto& value : {"-1.25", "0.125", "{\"x\":[-2,0.25,true,null,\"hi\\u4e00\"]}", "1e-20"}) require(nb::valid_json(value));
        for (const auto& value : {"NaN", "Infinity", "01", "-", "1.", "1e", "{\"x\":1,}", "[1,]", "true false", "{\"x\":NaN}"}) require(!nb::valid_json(value));
        require(nb::quote(u8"中文 µm") == u8"\"中文 µm\"");
        require(nb::valid_json(u8"{\"name\":\"中文\",\"unit\":\"µm\"}"));
        require(!nb::valid_json("1e999"));
        for (const auto& bytes : {"\xc0\xaf", "\xed\xa0\x80", "\xf4\x90\x80\x80", "\xe4\xb8", "\x80"})
            require(!nb::valid_json(std::string("\"") + bytes + "\""));
        nb::Core core(session, 123, 321); core.set_worker(777);
        require(core.accept(parse("a STATUS")).receipt.find("bridge_not_ready") != std::string::npos);
        core.mark_ready(321);
        auto a = core.accept(parse("a MEAN 1")); require(a.dispatch_token != 0); require(a.receipt.find("queued") != std::string::npos);
        identity(a.receipt, "MEAN", "[1]", "native_mean");
        auto duplicate = core.accept(parse("a MEAN 1")); require(duplicate.dispatch_token == 0); require(duplicate.receipt == a.receipt);
        require(core.accept(parse("a MEAN 2")).receipt.find("id_conflict") != std::string::npos);
        identity(core.accept(parse("a SUMMARY 2")).receipt, "MEAN", "[1]", "native_mean");
        no_identity(core.accept(parse("b MEAN 1")).receipt);
        no_identity(core.accept(parse("absent QUERY")).receipt);
        require(core.accept(parse("b MEAN 1")).receipt.find("busy") != std::string::npos);
        require(core.accept(parse("absent QUERY")).receipt.find("unknown") != std::string::npos);
        auto record = core.begin(a.dispatch_token, 321); require(record != nullptr);
        require(core.accept(parse("a QUERY")).receipt.find("running") != std::string::npos);
        identity(core.accept(parse("a QUERY")).receipt, "MEAN", "[1]", "native_mean");
        core.finish(record, "{\"mean\":-1.25}");
        auto completed = core.accept(parse("a QUERY")).receipt;
        require(completed.find("-1.25") != std::string::npos); require(completed.find("\"exec_tid\":321") != std::string::npos);
        identity(completed, "MEAN", "[1]", "native_mean");
        auto b = core.accept(parse("b MEAN 2")); require(b.dispatch_token != 0);
        require(!core.begin(a.dispatch_token, 321)); // A delayed old message cannot execute B.
        auto br = core.begin(b.dispatch_token, 321); core.finish(br, "{\"mean\":0.125}");
        require(core.accept(parse("b QUERY")).receipt.find("0.125") != std::string::npos);
        auto c = core.accept(parse("c DATASETS")); auto cr = core.begin(c.dispatch_token, 321);
        core.finish(cr, "{\"x\":\"" + std::string(nb::kMaxReply - 100, 'x') + "\"}");
        require(core.accept(parse("c QUERY")).receipt.find("response_too_large") != std::string::npos);
        auto d = core.accept(parse("d DATASETS")); auto dr = core.begin(d.dispatch_token, 321); core.finish(dr, "NaN");
        require(core.accept(parse("d QUERY")).receipt.find("invalid_adapter_result") != std::string::npos);
        auto e = core.accept(parse("e MEAN 1")); core.close(); require(!core.begin(e.dispatch_token, 321));
        require(core.accept(parse("e QUERY")).receipt.find("bridge_stopped") != std::string::npos);
        require(core.accept(parse("f MEAN 1")).receipt.find("bridge_stopped") != std::string::npos);
        nb::Core summaries(session, 123, 321); summaries.set_worker(777); summaries.mark_ready(321);
        auto summary = summaries.accept(parse("summary SUMMARY 00017")); require(summary.dispatch_token != 0);
        identity(summary.receipt, "SUMMARY", "[17]", "native_summary");
        require(summaries.accept(parse("summary SUMMARY 17")).dispatch_token == 0);
        require(summaries.accept(parse("summary SUMMARY 18")).receipt.find("id_conflict") != std::string::npos);
        require(summaries.accept(parse("summary MEAN 17")).receipt.find("id_conflict") != std::string::npos);
        auto summary_record = summaries.begin(summary.dispatch_token, 321); require(summary_record != nullptr);
        require(summaries.accept(parse("summary QUERY")).receipt.find("running") != std::string::npos);
        summaries.finish(summary_record, "{\"minimum\":-2,\"maximum\":1,\"sum\":-1.25,\"mean\":-0.125}");
        const auto summary_receipt = summaries.accept(parse("summary QUERY")).receipt;
        require(summary_receipt.find("\"minimum\":-2") != std::string::npos);
        require(summary_receipt.find("\"sum\":-1.25") != std::string::npos);
        require(summaries.accept(parse("summary SUMMARY 17")).receipt == summary_receipt);
        require(!summaries.begin(summary.dispatch_token, 321));
        auto failed_summary = summaries.accept(parse("failed_summary SUMMARY 18"));
        summaries.finish(summaries.begin(failed_summary.dispatch_token, 321), {}, "native_error", "native_summary_nonfinite_result");
        const auto failed_receipt = summaries.accept(parse("failed_summary QUERY")).receipt;
        require(failed_receipt.find("\"state\":\"failed\"") != std::string::npos);
        require(failed_receipt.find("native_summary_nonfinite_result") != std::string::npos);
        require(failed_receipt.find("\"result\"") == std::string::npos);
        identity(failed_receipt, "SUMMARY", "[18]", "native_summary");
        nb::Core delivery(session, 1, 1); delivery.mark_ready(1);
        auto show = delivery.accept(parse("visible SHOW 100")); require(show.dispatch_token != 0);
        require(delivery.accept(parse("visible SHOW 100")).dispatch_token == 0);
        require(delivery.accept(parse("visible SHOW 101")).receipt.find("id_conflict") != std::string::npos);
        require(delivery.accept(parse("visible MEAN 100")).receipt.find("id_conflict") != std::string::npos);
        auto shown = delivery.begin(show.dispatch_token, 1); require(shown != nullptr);
        delivery.finish(shown, "{\"image_id\":100,\"delivery\":\"visible_dm_document\"}");
        auto show_again = delivery.accept(parse("visible SHOW 100"));
        require(show_again.dispatch_token == 0 && show_again.receipt.find("completed") != std::string::npos);
        auto queued_show = delivery.accept(parse("queued_show SHOW 100")); require(queued_show.dispatch_token != 0);
        require(delivery.accept(parse("delivery_stop STOP")).stop);
        require(!delivery.begin(queued_show.dispatch_token, 1));
        require(delivery.accept(parse("queued_show QUERY")).receipt.find("bridge_stopped") != std::string::npos);
        nb::Core capacity(session, 1, 1); capacity.mark_ready(1);
        for (std::size_t i = 0; i < nb::kMaxOperationRecords; ++i) {
            auto input = parse("c" + std::to_string(i) + " STATUS"); auto accepted = capacity.accept(input);
            auto rr = capacity.begin(accepted.dispatch_token, 1); require(rr != nullptr); capacity.finish(rr, "{}");
        }
        require(capacity.accept(parse("overflow STATUS")).receipt.find("record_capacity") != std::string::npos);
        auto stop = capacity.accept(parse("stop_at_capacity STOP"));
        require(stop.stop); require(stop.receipt.find("completed") != std::string::npos);
        identity(stop.receipt, "STOP", "[]", "ipc_stop");
        require(stop.receipt.find("\"exec_tid\":0") != std::string::npos);
        require(capacity.accept(parse("stop_at_capacity QUERY")).receipt.find("ipc_stopped") != std::string::npos);
        require(capacity.accept(parse("c0 QUERY")).receipt.find("completed") != std::string::npos);
        nb::Core all_types(session, 123, 321); all_types.set_worker(777); all_types.mark_ready(321);
        for (const auto& tail : {"s STATUS", "d DATASETS", "i INFO 3", "m MEAN 3", "u SUMMARY 3", "c CROP 3 1 2 4 6", "v SHOW 3", "un UNARY 3 2", "bi BINARY 3 4 1", "fl FILTER 3 4", "ft FFT 3", "if IFFT 3", "re REAL 3", "im IMAG 3", "ar VENDOR_ARG 3", "no VENDOR_NORM 3", "pr PREVIEW 3 128 128", "rd READ 3 0 0 8 4"}) {
            auto input = parse(tail); auto accepted = all_types.accept(input);
            const auto* contract = nb::operation_contract(input.request.op); require(contract != nullptr);
            auto active = all_types.begin(accepted.dispatch_token, 321); require(active != nullptr);
            all_types.finish(active, "{}", "native_error", "synthetic failure");
            const auto output = all_types.accept(parse(input.request.id + " QUERY")).receipt;
            require(output.find("\"result_version\":" + std::to_string(contract->result_version)) != std::string::npos);
            require(output.find(std::string("\"result_type\":\"") + contract->result_type + "\"") != std::string::npos);
            require(output.find("\"original_operation\":\"QUERY\"") == std::string::npos);
        }
        nb::Core snapshots(session, 123, 321); snapshots.set_worker(777); snapshots.mark_ready(321);
        auto snapshot = snapshots.accept(parse("read_snapshot READ 0003 0001 0 8 4"));
        identity(snapshot.receipt, "READ", "[3,1,0,8,4]", "native_data_snapshot");
        auto snapshot_active = snapshots.begin(snapshot.dispatch_token, 321);
        identity(snapshots.accept(parse("read_snapshot QUERY")).receipt, "READ", "[3,1,0,8,4]", "native_data_snapshot");
        snapshots.finish(snapshot_active, "{\"operation\":\"READ\"}");
        const auto snapshot_receipt = snapshots.accept(parse("read_snapshot QUERY")).receipt;
        identity(snapshot_receipt, "READ", "[3,1,0,8,4]", "native_data_snapshot");
        require(snapshots.accept(parse("read_snapshot READ 3 1 0 8 4")).receipt == snapshot_receipt);
        require(snapshots.accept(parse("read_snapshot READ 3 0 0 8 4")).receipt.find("id_conflict") != std::string::npos);
        require(!snapshots.begin(snapshot.dispatch_token, 321));
        for (const auto& tail : {"p PROFILE 17 31 9 7 2 1 7 1", "p PROFILE 17 31 9 7 2 1 7 1 1 0",
             "p PROFILE 17 31 9 7 -2 1 7 1 1", "p PROFILE 17 31 9 7 2.5 1 7 1 1", "p PROFILE 17 31 9 7 2 1 7 1 4294967296"})
            reject("NB2 " + session + " " + tail);
        nb::Core profiles(session, 123, 321); profiles.set_worker(777); profiles.mark_ready(321);
        auto profile = profiles.accept(parse("saved_profile PROFILE 0017 31 9 7 2 1 7 1 1"));
        identity(profile.receipt,"PROFILE","[17,31,9,7,2,1,7,1,1]","native_line_profile");
        require(profiles.accept(parse("saved_profile PROFILE 17 31 9 7 2 1 7 1 1")).dispatch_token == 0);
        auto profile_active = profiles.begin(profile.dispatch_token,321);require(profile_active != nullptr);
        identity(profiles.accept(parse("saved_profile QUERY")).receipt,"PROFILE","[17,31,9,7,2,1,7,1,1]","native_line_profile");
        profiles.finish(profile_active,"{\"image_id\":37,\"shape\":[6]}");
        const auto profile_receipt=profiles.accept(parse("saved_profile QUERY")).receipt;
        require(profile_receipt.find("\"image_id\":37")!=std::string::npos);
        require(profiles.accept(parse("saved_profile PROFILE 17 31 9 7 2 1 7 1 1")).receipt==profile_receipt);
        require(profiles.accept(parse("saved_profile PROFILE 17 31 9 7 2 1 8 1 1")).receipt.find("id_conflict")!=std::string::npos);
        require(profiles.accept(parse("saved_profile READ 17 0 0 1 1")).receipt.find("id_conflict")!=std::string::npos);
        require(!profiles.begin(profile.dispatch_token,321));
        nb::Core fourier(session, 123, 321); fourier.set_worker(777); fourier.mark_ready(321);
        for (const auto* op : {"FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"}) {
            const std::string id = std::string("v2_") + op;
            auto accepted = fourier.accept(parse(id + " " + op + " 3"));
            identity(accepted.receipt, op, "[3]", "native_fourier_operation", 2);
            auto active = fourier.begin(accepted.dispatch_token, 321);
            identity(fourier.accept(parse(id + " QUERY")).receipt, op, "[3]", "native_fourier_operation", 2);
            fourier.finish(active, "{}");
            identity(fourier.accept(parse(id + " QUERY")).receipt, op, "[3]", "native_fourier_operation", 2);
            identity(fourier.accept(parse(id + " " + op + " 4")).receipt, op, "[3]", "native_fourier_operation", 2);
        }
        std::cout << "PASS " << checks << " native core assertions (offline synthetic only)\n"; return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
