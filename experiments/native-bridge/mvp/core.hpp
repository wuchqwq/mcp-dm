#pragma once
#include "adapter.hpp"
#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>

namespace nb {
constexpr std::size_t kMaxFrame = 512; // Includes the final LF byte.
constexpr std::size_t kMaxReply = 128 * 1024; // Includes the final LF byte.
constexpr std::size_t kMaxRecords = 1024;
constexpr std::size_t kMaxOperationRecords = kMaxRecords - 1; // One STOP receipt is reserved.
struct ProtocolError : std::runtime_error {
    std::string code;
    ProtocolError(std::string c, std::string m) : std::runtime_error(m), code(std::move(c)) {}
};
struct Parsed { std::string session; NativeRequest request; };
struct OperationContract { const char* operation; unsigned arguments; const char* result_type; unsigned result_version = 1; };
const OperationContract* operation_contract(const std::string& operation) noexcept;
bool valid_session(const std::string& value);
bool valid_utf8(const std::string& value);
Parsed parse_line(const std::string& line);
std::string quote(const std::string& value);
bool valid_json(const std::string& value);

struct Record {
    const NativeRequest request;
    const std::uint64_t token;
    const std::chrono::steady_clock::time_point submitted;
    std::chrono::steady_clock::time_point started;
    std::string state = "queued", result, code, error;
    std::uint32_t exec_tid = 0;
    std::uint64_t queue_us = 0, execute_us = 0;
    Record(NativeRequest r, std::uint64_t t)
        : request(std::move(r)), token(t), submitted(std::chrono::steady_clock::now()) {}
};
struct Admission { std::string receipt; std::uint64_t dispatch_token = 0; bool stop = false; };
class Core {
public:
    Core(std::string session, std::uint32_t host_pid, std::uint32_t host_tid);
    void set_worker(std::uint32_t tid);
    void mark_ready(std::uint32_t current_tid);
    Admission accept(const Parsed& parsed);
    std::shared_ptr<Record> begin(std::uint64_t token, std::uint32_t tid);
    void finish(const std::shared_ptr<Record>& record, const std::string& result,
                const std::string& code = {}, const std::string& error = {});
    void dispatch_failed(std::uint64_t token);
    void close();
    std::string failure(const std::string& id, const std::string& code, const std::string& message) const;
    const std::string& session() const { return session_; }
    std::uint32_t host_tid() const { return host_tid_; }
private:
    std::string receipt_locked(const Record& r) const;
    std::string unknown_locked(const std::string& id) const;
    std::string failure_locked(const std::string& id, const std::string& code, const std::string& message,
                               const Record* original = nullptr) const;
    std::string prefix_locked(const std::string& id, const std::string& state,
                              std::uint32_t exec_tid, std::uint64_t queue_us, std::uint64_t execute_us,
                              const Record* original = nullptr) const;
    mutable std::mutex mutex_;
    const std::string session_;
    const std::uint32_t host_pid_, host_tid_;
    std::uint32_t worker_tid_ = 0;
    std::uint64_t next_token_ = 1;
    bool ready_ = false, closing_ = false;
    std::map<std::string, std::shared_ptr<Record>> records_;
    std::shared_ptr<Record> inflight_;
};
} // namespace nb
