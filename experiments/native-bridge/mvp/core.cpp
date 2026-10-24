#include "core.hpp"
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <utility>
#include <vector>

namespace nb {
namespace {
// One closed operation/result-schema registry. QUERY refers to these original
// operations, never an adapter-provided discriminator or arbitrary symbol.
constexpr OperationContract kContracts[] = {
    {"STATUS", 0, "status"}, {"DATASETS", 0, "datasets"}, {"INFO", 1, "image_info"},
    {"MEAN", 1, "native_mean"}, {"SUMMARY", 1, "native_summary"},
    {"CROP", 5, "image_crop"}, {"SHOW", 1, "image_delivery"}, {"STOP", 0, "ipc_stop"},
    {"UNARY", 2, "native_image_operation"}, {"BINARY", 3, "native_image_operation"},
    {"FILTER", 2, "native_image_operation"},
    {"PREVIEW", 3, "native_preview"},
    {"READ", 5, "native_data_snapshot"},
    {"FFT", 1, "native_fourier_operation", 2}, {"IFFT", 1, "native_fourier_operation", 2},
    {"REAL", 1, "native_fourier_operation", 2}, {"IMAG", 1, "native_fourier_operation", 2},
    {"VENDOR_ARG", 1, "native_fourier_operation", 2}, {"VENDOR_NORM", 1, "native_fourier_operation", 2},
};
bool valid_id(const std::string& s) {
    if (s.empty() || s.size() > 64) return false;
    for (unsigned char c : s) if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
        (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    return true;
}
std::uint32_t uint32(const std::string& s) {
    if (s.empty()) throw ProtocolError("bad_argument", "empty unsigned integer");
    std::uint32_t v = 0;
    for (unsigned char c : s) {
        if (c < '0' || c > '9') throw ProtocolError("bad_argument", "arguments must be unsigned decimal integers");
        const unsigned d = c - '0';
        if (v > (std::numeric_limits<std::uint32_t>::max() - d) / 10)
            throw ProtocolError("bad_argument", "unsigned integer overflow");
        v = v * 10 + d;
    }
    return v;
}
std::uint64_t micros(std::chrono::steady_clock::duration d) {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(d).count());
}
// Result validation is deliberately bounded and independent of the adapter.
class JsonCheck {
    const std::string& s; std::size_t i = 0;
    void ws() { while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) ++i; }
    bool ch(char c) { ws(); if (i == s.size() || s[i] != c) return false; ++i; return true; }
    bool string() {
        if (!ch('"')) return false;
        while (i < s.size()) {
            unsigned char c = static_cast<unsigned char>(s[i++]);
            if (c == '"') return true;
            if (c < 32) return false; // The complete JSON text is UTF-8 validated.
            if (c == '\\') {
                if (i == s.size()) return false;
                char e = s[i++];
                if (e == 'u') {
                    for (int k = 0; k < 4; ++k) if (i == s.size() || !std::isxdigit(static_cast<unsigned char>(s[i++]))) return false;
                } else if (std::string("\"\\/bfnrt").find(e) == std::string::npos) return false;
            }
        }
        return false;
    }
    bool number() {
        const auto begin = i;
        if (i < s.size() && s[i] == '-') ++i;
        if (i == s.size()) return false;
        if (s[i] == '0') ++i;
        else { if (s[i] < '1' || s[i] > '9') return false; while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i; }
        if (i < s.size() && s[i] == '.') {
            ++i; auto start = i; while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i; if (start == i) return false;
        }
        if (i < s.size() && (s[i] == 'e' || s[i] == 'E')) {
            ++i; if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
            auto start = i; while (i < s.size() && s[i] >= '0' && s[i] <= '9') ++i; if (start == i) return false;
        }
        const std::string token = s.substr(begin, i - begin);
        char* end = nullptr;
        const double parsed = std::strtod(token.c_str(), &end);
        return i > begin && end == token.c_str() + token.size() && std::isfinite(parsed);
    }
    bool value(unsigned depth) {
        if (depth > 32) return false;
        ws(); if (i == s.size()) return false;
        char c = s[i];
        if (c == '"') return string();
        if (c == '{') {
            ++i; if (ch('}')) return true;
            do { if (!string() || !ch(':') || !value(depth + 1)) return false; } while (ch(','));
            return ch('}');
        }
        if (c == '[') {
            ++i; if (ch(']')) return true;
            do { if (!value(depth + 1)) return false; } while (ch(','));
            return ch(']');
        }
        for (const char* word : {"true", "false", "null"}) {
            std::string literal(word); if (s.compare(i, literal.size(), literal) == 0) { i += literal.size(); return true; }
        }
        return number();
    }
public:
    explicit JsonCheck(const std::string& text) : s(text) {}
    bool check() { if (!value(0)) return false; ws(); return i == s.size(); }
};
}

const OperationContract* operation_contract(const std::string& operation) noexcept {
    for (const auto& contract : kContracts) if (operation == contract.operation) return &contract;
    return nullptr;
}
bool valid_session(const std::string& s) {
    if (s.size() != 32) return false;
    for (char c : s) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    return true;
}
bool valid_utf8(const std::string& s) {
    std::size_t i = 0;
    while (i < s.size()) {
        const auto c = static_cast<unsigned char>(s[i++]);
        if (c < 0x80) continue;
        std::uint32_t cp = 0; unsigned count = 0; std::uint32_t minimum = 0;
        if (c >= 0xc2 && c <= 0xdf) { cp = c & 0x1f; count = 1; minimum = 0x80; }
        else if (c >= 0xe0 && c <= 0xef) { cp = c & 0x0f; count = 2; minimum = 0x800; }
        else if (c >= 0xf0 && c <= 0xf4) { cp = c & 0x07; count = 3; minimum = 0x10000; }
        else return false;
        if (count > s.size() - i) return false;
        for (unsigned j = 0; j < count; ++j) {
            auto continuation = static_cast<unsigned char>(s[i++]);
            if ((continuation & 0xc0) != 0x80) return false;
            cp = (cp << 6) | (continuation & 0x3f);
        }
        if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return false;
    }
    return true;
}
Parsed parse_line(const std::string& line) {
    if (line.empty() || line.size() >= kMaxFrame) throw ProtocolError("bad_frame", "frame must contain 1..511 ASCII bytes before LF");
    std::vector<std::string> fields; std::string field;
    for (unsigned char c : line) {
        if (c < 32 || c > 126) throw ProtocolError("bad_frame", "only printable ASCII and final LF are accepted");
        if (c == ' ') { if (field.empty()) throw ProtocolError("bad_frame", "fields require exactly one space"); fields.push_back(field); field.clear(); }
        else field += static_cast<char>(c);
    }
    if (field.empty()) throw ProtocolError("bad_frame", "trailing space");
    fields.push_back(field);
    if (fields.size() < 4 || fields[0] != "NB2") throw ProtocolError("bad_protocol", "expected NB2 session id operation; legacy NB1 is not accepted");
    if (!valid_session(fields[1])) throw ProtocolError("bad_session", "session must be 32 lowercase hexadecimal characters");
    if (!valid_id(fields[2])) throw ProtocolError("bad_id", "id must match [A-Za-z0-9_-]{1,64}");
    const auto& op = fields[3];
    const auto* contract = operation_contract(op);
    if (!contract && op != "QUERY")
        throw ProtocolError("bad_operation", "unsupported operation");
    const unsigned count = contract ? contract->arguments : 0;
    if (fields.size() != 4 + count) throw ProtocolError("bad_argument", "incorrect argument count");
    Parsed p; p.session = fields[1]; p.request.id = fields[2]; p.request.op = op;
    for (std::size_t i = 4; i < fields.size(); ++i) p.request.args.push_back(uint32(fields[i]));
    return p;
}
std::string quote(const std::string& s) {
    if (!valid_utf8(s)) throw std::runtime_error("string is not valid UTF-8");
    static constexpr char hex[] = "0123456789abcdef"; std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 32) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += static_cast<char>(c);
    }
    out += '"'; return out;
}
bool valid_json(const std::string& s) { return !s.empty() && s.size() < kMaxReply && valid_utf8(s) && JsonCheck(s).check(); }
Core::Core(std::string s, std::uint32_t pid, std::uint32_t tid) : session_(std::move(s)), host_pid_(pid), host_tid_(tid) {
    if (!valid_session(session_)) throw std::runtime_error("DM_NATIVE_SESSION must be 32 lowercase hexadecimal characters");
}
void Core::set_worker(std::uint32_t tid) { std::lock_guard<std::mutex> lock(mutex_); worker_tid_ = tid; }
void Core::mark_ready(std::uint32_t tid) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (tid != host_tid_) throw std::runtime_error("readiness callback on wrong host thread");
    if (!closing_) ready_ = true;
}
std::string Core::prefix_locked(const std::string& id, const std::string& state, std::uint32_t tid,
                               std::uint64_t q, std::uint64_t e, const Record* original) const {
    auto prefix = "{\"protocol\":\"NB2\",\"session\":" + quote(session_) + ",\"id\":" + quote(id) +
        ",\"state\":" + quote(state) + ",\"host_pid\":" + std::to_string(host_pid_) +
        ",\"worker_tid\":" + std::to_string(worker_tid_) + ",\"exec_tid\":" + std::to_string(tid) +
        ",\"timings_us\":{\"queue\":" + std::to_string(q) + ",\"execute\":" + std::to_string(e) + "}";
    if (!original) return prefix + ",\"original_operation\":null,\"normalized_args\":null,\"result_type\":null,\"result_version\":null";
    const auto& request = original->request;
    const auto* contract = operation_contract(request.op);
    if (!contract) throw std::logic_error("record contains an unsupported operation");
    prefix += ",\"original_operation\":" + quote(request.op) + ",\"normalized_args\":[";
    for (std::size_t i = 0; i < request.args.size(); ++i) {
        if (i) prefix += ',';
        prefix += std::to_string(request.args[i]);
    }
    return prefix + "],\"result_type\":" + quote(contract->result_type) + ",\"result_version\":" + std::to_string(contract->result_version);
}
std::string Core::failure_locked(const std::string& id, const std::string& code, const std::string& error,
                                 const Record* original) const {
    // Fixed-size error text prevents a malicious adapter exception growing a receipt.
    const std::string message = !valid_utf8(error) ? "error text is not valid UTF-8" :
        (error.size() <= 2048 ? error : "error text exceeded 2048-byte limit");
    return prefix_locked(id, "failed", 0, 0, 0, original) + ",\"code\":" + quote(code) + ",\"error\":" + quote(message) + "}\n";
}
std::string Core::failure(const std::string& id, const std::string& code, const std::string& msg) const {
    std::lock_guard<std::mutex> lock(mutex_); return failure_locked(id, code, msg);
}
std::string Core::unknown_locked(const std::string& id) const { return prefix_locked(id, "unknown", 0, 0, 0) + "}\n"; }
std::string Core::receipt_locked(const Record& r) const {
    auto out = prefix_locked(r.request.id, r.state, r.exec_tid, r.queue_us, r.execute_us, &r);
    if (r.state == "completed") out += ",\"result\":" + r.result;
    if (r.state == "failed") out += ",\"code\":" + quote(r.code) + ",\"error\":" + quote(r.error);
    return out + "}\n";
}
Admission Core::accept(const Parsed& p) {
    std::lock_guard<std::mutex> lock(mutex_); const auto& r = p.request;
    if (p.session != session_) return {failure_locked(r.id, "session_mismatch", "request belongs to a different bridge session")};
    auto it = records_.find(r.id);
    if (r.op == "QUERY") return {it == records_.end() ? unknown_locked(r.id) : receipt_locked(*it->second)};
    if (it != records_.end()) {
        if (it->second->request.op != r.op || it->second->request.args != r.args)
            return {failure_locked(r.id, "id_conflict", "id is already bound to different operation parameters", it->second.get())};
        return {receipt_locked(*it->second)};
    }
    if (closing_) return {failure_locked(r.id, "bridge_stopped", "bridge is stopping and accepts no new operations")};
    if (r.op != "STOP" && records_.size() >= kMaxOperationRecords)
        return {failure_locked(r.id, "record_capacity", "operation record capacity reached; one STOP receipt slot is reserved and no records were evicted")};
    if (r.op != "STOP" && !ready_) return {failure_locked(r.id, "bridge_not_ready", "host readiness callback has not run")};
    if (r.op != "STOP" && inflight_) return {failure_locked(r.id, "busy", "one operation is queued or running; query its original id")};
    auto record = std::make_shared<Record>(r, next_token_++); records_.emplace(r.id, record);
    if (r.op == "STOP") {
        closing_ = true; ready_ = false;
        if (inflight_ && inflight_->state == "queued") { inflight_->state = "failed"; inflight_->code = "bridge_stopped"; inflight_->error = "IPC stopped before host execution"; inflight_.reset(); }
        record->state = "completed"; record->result = "{\"ipc_stopped\":true}";
        return {receipt_locked(*record), 0, true};
    }
    inflight_ = record; return {receipt_locked(*record), record->token, false};
}
std::shared_ptr<Record> Core::begin(std::uint64_t token, std::uint32_t tid) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (tid != host_tid_) throw std::runtime_error("operation callback on wrong host thread");
    if (closing_ || !inflight_ || inflight_->token != token || inflight_->state != "queued") return {};
    auto r = inflight_; r->state = "running"; r->exec_tid = tid; r->started = std::chrono::steady_clock::now();
    r->queue_us = micros(r->started - r->submitted); return r;
}
void Core::finish(const std::shared_ptr<Record>& r, const std::string& result, const std::string& code, const std::string& error) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!r || r != inflight_ || r->state != "running") return;
    r->execute_us = micros(std::chrono::steady_clock::now() - r->started);
    if (!code.empty()) { r->state = "failed"; r->code = code; r->error = !valid_utf8(error) ? "adapter error text is not valid UTF-8" :
        (error.size() <= 2048 ? error : "adapter error exceeded 2048-byte limit"); }
    else if (result.size() >= kMaxReply) { r->state = "failed"; r->code = "response_too_large"; r->error = "adapter result alone exceeds the 128 KiB response bound"; }
    else if (!valid_json(result)) { r->state = "failed"; r->code = "invalid_adapter_result"; r->error = "adapter returned invalid JSON, UTF-8 or nonfinite numeric value"; }
    else {
        r->state = "completed"; r->result = result;
        if (receipt_locked(*r).size() > kMaxReply) { r->state = "failed"; r->result.clear(); r->code = "response_too_large"; r->error = "complete response exceeds 128 KiB; result was rejected"; }
    }
    inflight_.reset();
}
void Core::dispatch_failed(std::uint64_t token) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!inflight_ || inflight_->token != token || inflight_->state != "queued") return;
    inflight_->state = "failed"; inflight_->code = "dispatch_failed"; inflight_->error = "PostMessage failed"; inflight_.reset();
}
void Core::close() {
    std::lock_guard<std::mutex> lock(mutex_); closing_ = true; ready_ = false;
    if (inflight_ && inflight_->state == "queued") { inflight_->state = "failed"; inflight_->code = "bridge_stopped"; inflight_->error = "bridge cleanup before host execution"; inflight_.reset(); }
}
} // namespace nb
