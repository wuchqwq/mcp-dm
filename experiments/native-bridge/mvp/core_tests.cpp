#include "core.hpp"
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0;
void require(bool condition) { ++checks; if (!condition) throw std::runtime_error("core check " + std::to_string(checks) + " failed"); }
const std::string session(32, 'a');
nb::Parsed parse(const std::string& tail) { return nb::parse_line("NB1 " + session + " " + tail); }
void reject(const std::string& s) { try { nb::parse_line(s); require(false); } catch (const nb::ProtocolError&) { require(true); } }
}
int main() {
    try {
        for (const auto& tail : {"id STATUS", "id DATASETS", "id QUERY", "id STOP", "id INFO 0", "id MEAN 4294967295", "id CROP 1 0 0 4 3"}) require(!parse(tail).request.op.empty());
        for (const auto& tail : {"id STATUSX", "id STATUS 1", "id INFO", "id INFO -1", "id INFO +1", "id INFO 4294967296", "id INFO 1x", "id MEAN 1.2", "id CROP 1 0 0 1", "id CROP 1 0 0 1 2 3", "bad.id STATUS", "id  STATUS", "id STATUS ", "id\tSTATUS"}) reject("NB1 " + session + " " + tail);
        reject(""); reject("NB2 " + session + " id STATUS"); reject("NB1 " + std::string(32, 'A') + " id STATUS");
        reject("NB1 " + session + " " + std::string(65, 'i') + " STATUS"); reject("NB1 " + session + " id STATUS\n");
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
        auto duplicate = core.accept(parse("a MEAN 1")); require(duplicate.dispatch_token == 0); require(duplicate.receipt == a.receipt);
        require(core.accept(parse("a MEAN 2")).receipt.find("id_conflict") != std::string::npos);
        require(core.accept(parse("b MEAN 1")).receipt.find("busy") != std::string::npos);
        require(core.accept(parse("absent QUERY")).receipt.find("unknown") != std::string::npos);
        auto record = core.begin(a.dispatch_token, 321); require(record != nullptr);
        require(core.accept(parse("a QUERY")).receipt.find("running") != std::string::npos);
        core.finish(record, "{\"mean\":-1.25}");
        auto completed = core.accept(parse("a QUERY")).receipt;
        require(completed.find("-1.25") != std::string::npos); require(completed.find("\"exec_tid\":321") != std::string::npos);
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
        nb::Core capacity(session, 1, 1); capacity.mark_ready(1);
        for (std::size_t i = 0; i < nb::kMaxOperationRecords; ++i) {
            auto input = parse("c" + std::to_string(i) + " STATUS"); auto accepted = capacity.accept(input);
            auto rr = capacity.begin(accepted.dispatch_token, 1); require(rr != nullptr); capacity.finish(rr, "{}");
        }
        require(capacity.accept(parse("overflow STATUS")).receipt.find("record_capacity") != std::string::npos);
        auto stop = capacity.accept(parse("stop_at_capacity STOP"));
        require(stop.stop); require(stop.receipt.find("completed") != std::string::npos);
        require(capacity.accept(parse("stop_at_capacity QUERY")).receipt.find("ipc_stopped") != std::string::npos);
        require(capacity.accept(parse("c0 QUERY")).receipt.find("completed") != std::string::npos);
        std::cout << "PASS " << checks << " native core assertions (offline synthetic only)\n"; return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
