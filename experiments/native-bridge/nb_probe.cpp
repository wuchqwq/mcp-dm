// nb_probe: minimal native DigitalMicrograph plugin used to test whether an external
// request can be carried into the host thread and executed there, with an auditable
// receipt. No CRT, no SDK; kernel32 only.
//
// Design (deliberately narrow):
//   * worker thread  : owns the named pipe, parses/validates requests, never touches DM
//   * hidden window  : created on the plugin-load thread (the host thread)
//   * WndProc        : the only place where host work happens, on the host thread
//   * one in-flight request at a time; everything else is refused
//
// Protocol: one ASCII line per request, one ASCII line per reply.
//   PING <reqid>          -> OK <reqid> <recv_us> <post_us> <exec_us> <done_us> <recv_tid> <exec_tid>
//   IMG <reqid> <imageid> -> IMGDIMS <reqid> <dims> <exec_tid>      (native image lookup)
//   STOP                  -> BYE
// Anything else           -> ERR <reqid> bad-request

typedef unsigned int u32;
typedef unsigned long long u64;
typedef int i32;
typedef long long i64;
typedef void* HANDLE;
typedef void* HWND;
typedef void* HINSTANCE;
typedef void* HMODULE;
typedef unsigned long DWORD;
typedef int BOOL;
typedef unsigned long long ULONG_PTR;
typedef long long LRESULT;
typedef unsigned int UINT;
typedef unsigned long long WPARAM;
typedef long long LPARAM;
typedef char* LPSTR;
typedef const char* LPCSTR;
typedef void* LPVOID;

struct CRITICAL_SECTION_ { u64 opaque[8]; };
struct LARGE_INTEGER_ { i64 QuadPart; };
struct WNDCLASSA_ {
    UINT style;
    u32 pad0;
    LRESULT (*lpfnWndProc)(HWND, UINT, WPARAM, LPARAM);
    i32 cbClsExtra;
    i32 cbWndExtra;
    HINSTANCE hInstance;
    void* hIcon;
    void* hCursor;
    void* hbrBackground;
    LPCSTR lpszMenuName;
    LPCSTR lpszClassName;
};

extern "C" {
// kernel32
__declspec(dllimport) HANDLE __stdcall CreateThread(void*, unsigned long long,
                                                   u32(__stdcall*)(void*), void*, DWORD, DWORD*);
__declspec(dllimport) HANDLE __stdcall CreateNamedPipeA(LPCSTR, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, void*);
__declspec(dllimport) BOOL __stdcall ConnectNamedPipe(HANDLE, void*);
__declspec(dllimport) BOOL __stdcall DisconnectNamedPipe(HANDLE);
__declspec(dllimport) BOOL __stdcall ReadFile(HANDLE, LPVOID, DWORD, DWORD*, void*);
__declspec(dllimport) BOOL __stdcall WriteFile(HANDLE, const void*, DWORD, DWORD*, void*);
__declspec(dllimport) HANDLE __stdcall CreateFileA(LPCSTR, DWORD, DWORD, void*, DWORD, DWORD, void*);
__declspec(dllimport) BOOL __stdcall CloseHandle(HANDLE);
__declspec(dllimport) BOOL __stdcall FlushFileBuffers(HANDLE);
__declspec(dllimport) DWORD __stdcall GetCurrentThreadId(void);
__declspec(dllimport) BOOL __stdcall QueryPerformanceCounter(LARGE_INTEGER_*);
__declspec(dllimport) BOOL __stdcall QueryPerformanceFrequency(LARGE_INTEGER_*);
__declspec(dllimport) BOOL __stdcall PostMessageA(HWND, UINT, WPARAM, LPARAM);
__declspec(dllimport) unsigned short __stdcall RegisterClassA(const WNDCLASSA_*);
__declspec(dllimport) HWND __stdcall CreateWindowExA(DWORD, LPCSTR, LPCSTR, DWORD, i32, i32, i32, i32,
                                                     HWND, void*, HINSTANCE, void*);
__declspec(dllimport) LRESULT __stdcall DefWindowProcA(HWND, UINT, WPARAM, LPARAM);
__declspec(dllimport) BOOL __stdcall DestroyWindow(HWND);
__declspec(dllimport) HMODULE __stdcall GetModuleHandleA(LPCSTR);
__declspec(dllimport) void __stdcall InitializeCriticalSection(CRITICAL_SECTION_*);
__declspec(dllimport) void __stdcall EnterCriticalSection(CRITICAL_SECTION_*);
__declspec(dllimport) void __stdcall LeaveCriticalSection(CRITICAL_SECTION_*);
__declspec(dllimport) HANDLE __stdcall CreateEventA(void*, BOOL, BOOL, LPCSTR);
__declspec(dllimport) DWORD __stdcall WaitForSingleObject(HANDLE, DWORD);
__declspec(dllimport) BOOL __stdcall SetEvent(HANDLE);
__declspec(dllimport) void __stdcall Sleep(DWORD);
}

// Freestanding C runtime bits: the compiler emits calls to these for struct copies
// and aggregate initialisation, and we deliberately do not link a CRT.
extern "C" void* memcpy(void* dst, const void* src, unsigned long long n) {
    unsigned char* d = (unsigned char*)dst;
    const unsigned char* s = (const unsigned char*)src;
    for (unsigned long long i = 0; i < n; ++i) d[i] = s[i];
    return dst;
}
extern "C" void* memset(void* dst, int value, unsigned long long n) {
    unsigned char* d = (unsigned char*)dst;
    for (unsigned long long i = 0; i < n; ++i) d[i] = (unsigned char)value;
    return dst;
}

// ---------------------------------------------------------------------------
// shared state
// ---------------------------------------------------------------------------
namespace {

constexpr const char* kPipeName = "\\\\.\\pipe\\dm_nb_probe";
constexpr const char* kLogPath = "C:\\ProgramData\\Gatan\\Plugins\\nb_probe.log";
constexpr UINT kMsgWork = 0x8001;  // WM_APP + 1

CRITICAL_SECTION_ g_lock;
bool g_lockReady = false;

HWND g_hwnd = nullptr;
HANDLE g_thread = nullptr;
HANDLE g_pipe = nullptr;
volatile u32 g_stop = 0;
DWORD g_hostTid = 0;
DWORD g_workerTid = 0;

i64 g_freq = 0;

struct Request {
    char line[512];
    u32 len;
    i64 t_recv;
    DWORD recv_tid;
    bool pending;
};

Request g_req;
volatile u32 g_hasWork = 0;
HANDLE g_doneEvent = nullptr;

// timings published by the host thread for the current request
volatile i64 g_t_exec = 0;
volatile i64 g_t_done = 0;
volatile DWORD g_exec_tid = 0;
u64 g_result = 0;
u32 g_resultKind = 0;  // 1 = ping, 2 = image dims, 3 = error

inline i64 Now() {
    LARGE_INTEGER_ t;
    QueryPerformanceCounter(&t);
    return t.QuadPart;
}

inline i64 ToUs(i64 delta) {
    if (g_freq == 0) return 0;
    return (delta * 1000000) / g_freq;
}

void AppendLog(const char* text) {
    HANDLE h = CreateFileA(kLogPath, 0x00000004u, 0x00000001u, nullptr, 4u, 0x00000080u, nullptr);
    if (h == nullptr || h == (HANDLE)(i64)-1) return;
    u32 len = 0;
    while (text[len] != '\0') ++len;
    DWORD written = 0;
    WriteFile(h, text, len, &written, nullptr);
    CloseHandle(h);
}

void AppendNum(const char* prefix, u64 value) {
    char buf[96];
    u32 i = 0;
    while (prefix[i] != '\0' && i < 40) { buf[i] = prefix[i]; ++i; }
    char tmp[24];
    u32 n = 0;
    if (value == 0) { tmp[n++] = '0'; }
    while (value != 0 && n < 24) {
        u32 d = (u32)(value % 10);
        tmp[n++] = (char)('0' + d);
        value /= 10;
    }
    while (n > 0) buf[i++] = tmp[--n];
    buf[i++] = '\n';
    buf[i] = '\0';
    AppendLog(buf);
}

// ---------------------------------------------------------------------------
// host-thread work
// ---------------------------------------------------------------------------
typedef void* (*FindImageAsObjectFn)(void* outRefPtr, u64 id);
typedef u32 (*GetDimensionsFn)(void* image);
typedef void (*RefPtrDeleteFn)(void* image);

FindImageAsObjectFn g_findImage = nullptr;
GetDimensionsFn g_getDims = nullptr;
RefPtrDeleteFn g_refPtrDelete = nullptr;

void ResolveImageApi() {
    HMODULE m = GetModuleHandleA("GMSImage.dll");
    if (m == nullptr) {
        AppendLog("[nb] GMSImage.dll not found\n");
        return;
    }
    // GetProcAddress is imported lazily by name below; declared here to keep the
    // import list small is not possible, so resolve through the export table by hand.
    (void)m;
}

// Minimal PE export resolver: avoids importing GetProcAddress/CreateToolhelp etc.
void* ResolveExport(HMODULE module, const char* name) {
    unsigned char* base = (unsigned char*)module;
    u32 peOff = *(u32*)(base + 0x3C);
    u32* nt = (u32*)(base + peOff);
    u32 optOff = peOff + 24;
    unsigned char* opt = base + optOff;
    u32 magic = *(u32*)opt;
    u32 ddOff = (magic == 0x20B) ? 112 : 96;
    u32 exportRva = *(u32*)(opt + ddOff);
    if (exportRva == 0) return nullptr;
    u32* exp = (u32*)(base + exportRva);
    u32 nameCount = exp[6];
    u32* names = (u32*)(base + exp[8]);
    u32* funcs = (u32*)(base + exp[7]);
    for (u32 i = 0; i < nameCount; ++i) {
        const char* candidate = (const char*)(base + names[i]);
        u32 j = 0;
        while (candidate[j] != '\0' && name[j] != '\0' && candidate[j] == name[j]) ++j;
        if (candidate[j] == '\0' && name[j] == '\0') {
            return base + funcs[i];
        }
    }
    return nullptr;
}

void DoPing() {
    g_resultKind = 1;
    g_result = 1;
}

void DoImageDims(u64 id) {
    g_resultKind = 3;
    g_result = 0;
    if (g_findImage == nullptr) {
        HMODULE m = GetModuleHandleA("GMSImage.dll");
        if (m != nullptr) {
            g_findImage = (FindImageAsObjectFn)ResolveExport(
                m, "?FindImageAsObject@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@_K@Z");
            g_getDims = (GetDimensionsFn)ResolveExport(m, "?GetDimensions@Image@GMS@@QEBAKXZ");
            g_refPtrDelete = (RefPtrDeleteFn)ResolveExport(m, "?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z");
        }
    }
    if (g_findImage == nullptr || g_getDims == nullptr) {
        AppendLog("[nb] image api unresolved\n");
        return;
    }
    void* refPtr[2] = {nullptr, nullptr};
    g_findImage(refPtr, id);
    void* image = refPtr[0];
    if (image == nullptr) {
        g_result = 0;
        return;
    }
    g_result = (u64)g_getDims(image);
    g_resultKind = 2;
    if (g_refPtrDelete != nullptr) {
        g_refPtrDelete(image);
    }
}

LRESULT __stdcall WndProc(HWND hwnd, UINT msg, WPARAM w, LPARAM l) {
    if (msg != kMsgWork) {
        return DefWindowProcA(hwnd, msg, w, l);
    }
    g_t_exec = Now();
    g_exec_tid = GetCurrentThreadId();

    char cmd[8] = {0};
    u64 arg = 0;
    if (g_lockReady) EnterCriticalSection(&g_lock);
    // copy the pending request so the worker can be released quickly
    char local[512];
    u32 len = g_req.len;
    for (u32 i = 0; i < len && i < 511; ++i) local[i] = g_req.line[i];
    local[len < 511 ? len : 511] = '\0';
    if (g_lockReady) LeaveCriticalSection(&g_lock);

    u32 k = 0;
    while (local[k] != '\0' && local[k] != ' ' && k < 7) { cmd[k] = local[k]; ++k; }
    cmd[k] = '\0';

    if (cmd[0] == 'I' && cmd[1] == 'M' && cmd[2] == 'G') {
        // parse id after second space
        u32 p = 0;
        u32 spaces = 0;
        while (local[p] != '\0' && spaces < 2) {
            if (local[p] == ' ') ++spaces;
            ++p;
        }
        while (local[p] >= '0' && local[p] <= '9') {
            arg = arg * 10 + (u64)(local[p] - '0');
            ++p;
        }
        DoImageDims(arg);
    } else {
        DoPing();
    }

    g_t_done = Now();
    SetEvent(g_doneEvent);
    return 0;
}

// ---------------------------------------------------------------------------
// worker thread: pipe only
// ---------------------------------------------------------------------------
u32 __stdcall Worker(void*) {
    g_workerTid = GetCurrentThreadId();
    AppendLog("[nb] worker started\n");

    while (g_stop == 0) {
        HANDLE pipe = CreateNamedPipeA(kPipeName, 3 /*PIPE_ACCESS_DUPLEX*/,
                                       0 /*PIPE_TYPE_BYTE*/, 1, 4096, 4096, 0, nullptr);
        if (pipe == (HANDLE)(i64)-1 || pipe == nullptr) {
            AppendLog("[nb] CreateNamedPipe failed\n");
            Sleep(200);
            continue;
        }
        BOOL connected = ConnectNamedPipe(pipe, nullptr);
        if (!connected) {
            // ERROR_PIPE_CONNECTED means a client raced us; treat as success
            // any other failure: drop and retry
        }
        if (g_stop != 0) {
            DisconnectNamedPipe(pipe);
            CloseHandle(pipe);
            break;
        }

        char buf[512];
        DWORD got = 0;
        if (ReadFile(pipe, buf, sizeof(buf) - 1, &got, nullptr) && got > 0) {
            buf[got] = '\0';
            // trim CR/LF
            while (got > 0 && (buf[got - 1] == '\n' || buf[got - 1] == '\r')) {
                buf[--got] = '\0';
            }

            if (buf[0] == 'S' && buf[1] == 'T' && buf[2] == 'O' && buf[3] == 'P') {
                g_stop = 1;
                const char* bye = "BYE\n";
                DWORD w = 0;
                WriteFile(pipe, bye, 4, &w, nullptr);
            } else if (buf[0] == 'P' || buf[0] == 'I') {
                i64 tRecv = Now();
                if (g_lockReady) EnterCriticalSection(&g_lock);
                for (u32 i = 0; i <= got && i < 511; ++i) g_req.line[i] = buf[i];
                g_req.len = got;
                g_req.recv_tid = g_workerTid;
                if (g_lockReady) LeaveCriticalSection(&g_lock);

                PostMessageA(g_hwnd, kMsgWork, 0, 0);
                i64 tPost = Now();
                DWORD wait = WaitForSingleObject(g_doneEvent, 5000);
                if (wait != 0) {
                    // The host thread did not pick the request up in time. Report
                    // unknown and do NOT retry: the request may still be queued.
                    const char* unknown = "UNKNOWN host-did-not-run\n";
                    DWORD w2 = 0;
                    WriteFile(pipe, unknown, 25, &w2, nullptr);
                    FlushFileBuffers(pipe);
                    DisconnectNamedPipe(pipe);
                    CloseHandle(pipe);
                    continue;
                }

                char reply[256];
                u32 n = 0;
                const char* tag = (g_resultKind == 2) ? "IMGDIMS " : "OK ";
                for (u32 i = 0; tag[i] != '\0'; ++i) reply[n++] = tag[i];
                // echo the request id (first token after command)
                u32 p = 0;
                while (buf[p] != '\0' && buf[p] != ' ') ++p;
                if (buf[p] == ' ') ++p;
                while (buf[p] != '\0' && buf[p] != ' ') reply[n++] = buf[p++];
                reply[n++] = ' ';
                // numbers
                u64 nums[4] = {(u64)ToUs(tRecv - tRecv), (u64)ToUs(tPost - tRecv),
                               (u64)ToUs(g_t_exec - tPost), (u64)ToUs(g_t_done - g_t_exec)};
                for (u32 i = 0; i < 4; ++i) {
                    char t[24];
                    u32 m = 0;
                    u64 v = nums[i];
                    if (v == 0) t[m++] = '0';
                    while (v != 0 && m < 24) { t[m++] = (char)('0' + v % 10); v /= 10; }
                    while (m > 0) reply[n++] = t[--m];
                    reply[n++] = ' ';
                }
                // result, then thread ids
                u64 extra[3] = {g_result, (u64)g_workerTid, (u64)g_exec_tid};
                for (u32 i = 0; i < 3; ++i) {
                    char t[24];
                    u32 m = 0;
                    u64 v = extra[i];
                    if (v == 0) t[m++] = '0';
                    while (v != 0 && m < 24) { t[m++] = (char)('0' + v % 10); v /= 10; }
                    while (m > 0) reply[n++] = t[--m];
                    reply[n++] = (i == 2) ? '\n' : ' ';
                }
                DWORD wrote = 0;
                WriteFile(pipe, reply, n, &wrote, nullptr);
            } else {
                const char* err = "ERR bad-request\n";
                DWORD w = 0;
                WriteFile(pipe, err, 18, &w, nullptr);
            }
        }
        // Wait until the client has drained the reply; DisconnectNamedPipe alone
        // discards buffered data.
        FlushFileBuffers(pipe);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
    AppendLog("[nb] worker exited\n");
    return 0;
}

}  // namespace

// ---------------------------------------------------------------------------
// plugin entry points
// ---------------------------------------------------------------------------
extern "C" __declspec(dllexport) void PlugInGetSDKVersion(int* major, int* minor) {
    if (major) *major = 3;
    if (minor) *minor = 5;
    AppendLog("[nb] PlugInGetSDKVersion\n");
}

extern "C" __declspec(dllexport) void DMPlugIn_Link_2(void* iface) {
    (void)iface;
    AppendLog("[nb] DMPlugIn_Link_2\n");
}

extern "C" __declspec(dllexport) void PlugInStartup(void) {
    g_hostTid = GetCurrentThreadId();
    AppendNum("[nb] PlugInStartup tid=", (u64)g_hostTid);

    LARGE_INTEGER_ f;
    QueryPerformanceFrequency(&f);
    g_freq = f.QuadPart;

    InitializeCriticalSection(&g_lock);
    g_lockReady = true;
    g_doneEvent = CreateEventA(nullptr, 0 /*auto reset*/, 0, nullptr);

    WNDCLASSA_ wc;
    unsigned char* raw = (unsigned char*)&wc;
    for (u32 i = 0; i < sizeof(wc); ++i) raw[i] = 0;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = GetModuleHandleA(nullptr);
    wc.lpszClassName = "nb_probe_wnd";
    unsigned short atom = RegisterClassA(&wc);
    if (atom == 0) {
        AppendLog("[nb] RegisterClass failed\n");
        return;
    }
    // HWND_MESSAGE = (HWND)-3 : message-only window, never shown
    g_hwnd = CreateWindowExA(0, "nb_probe_wnd", "nb", 0, 0, 0, 0, 0,
                             (HWND)(i64)-3, nullptr, wc.hInstance, nullptr);
    if (g_hwnd == nullptr) {
        AppendLog("[nb] CreateWindowEx failed\n");
        return;
    }
    AppendNum("[nb] window ok, hwnd=", (u64)(ULONG_PTR)g_hwnd);

    g_thread = CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
    if (g_thread == nullptr) {
        AppendLog("[nb] CreateThread failed\n");
    }
}

extern "C" __declspec(dllexport) void PlugInRegisterFloatingWindows(void) {
    AppendLog("[nb] PlugInRegisterFloatingWindows\n");
}

extern "C" __declspec(dllexport) void PlugInRun(void) {
    AppendLog("[nb] PlugInRun\n");
}

extern "C" __declspec(dllexport) void PlugInCleanup(void) {
    AppendLog("[nb] PlugInCleanup\n");
    g_stop = 1;
    // The worker may be blocked inside ConnectNamedPipe, where g_stop is invisible.
    // Wake it with a throw-away client connection so it can observe the flag and exit.
    HANDLE wake = CreateFileA(kPipeName, 0x40000000u, 0, nullptr, 3 /*OPEN_EXISTING*/, 0, nullptr);
    if (wake != nullptr && wake != (HANDLE)(i64)-1) {
        CloseHandle(wake);
    }
    if (g_thread != nullptr) {
        WaitForSingleObject(g_thread, 3000);
        CloseHandle(g_thread);
        g_thread = nullptr;
    }
    if (g_hwnd != nullptr) {
        DestroyWindow(g_hwnd);
        g_hwnd = nullptr;
    }
    AppendLog("[nb] cleanup done\n");
}

extern "C" __declspec(dllexport) int PlugInRequestClose(void) {
    AppendLog("[nb] PlugInRequestClose\n");
    return 1;
}

extern "C" __declspec(dllexport) void PlugInPrepareClose(void) {
    AppendLog("[nb] PlugInPrepareClose\n");
}

extern "C" __declspec(dllexport) void PlugInShutdown(void) {
    AppendLog("[nb] PlugInShutdown\n");
}
