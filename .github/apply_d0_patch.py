"""One-shot builder. Not part of the deliverable candidate."""
from pathlib import Path
import hashlib
import ast


def read_checked(name, sha):
    raw = Path(name).read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual != sha:
        raise RuntimeError('Unexpected baseline for ' + name)
    return raw.decode('utf-8')


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected one patch anchor: ' + repr(old[:100]))
    return text.replace(old, new, 1)


def write(name, text):
    with open(name, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print('Updated', name)


s = read_checked('server.mjs', '839633ae0bcb088e969af24dd187e4b3cf076170')
start = s.index('function runAnalysisWorker(payload, signal) {')
end = s.index('\nfunction requireFile(', start)
s = s[:start] + '''function runAnalysisWorker(payload, signal) {
  if (signal?.aborted) return Promise.reject(new Error("请求已取消，尚未启动本地分析进程"));
  const body = JSON.stringify(payload);
  if (Buffer.byteLength(body, "utf8") > 1024 * 1024) {
    return Promise.reject(new Error("分析请求超过 1 MiB；未启动进程"));
  }
  const child = spawn(ANALYSIS_PYTHON, [ANALYSIS_WORKER], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  return new Promise((resolve, reject) => {
    let chunks = [], bytes = 0, stderr = "", settled = false, discardOutput = false;
    const queryHint = "结果状态未知；使用 dm_2d_result 查询对应 capture_dir/result_dir，勿自动重试。";
    // Settling a client wait is not the end of the child process lifetime.
    const settle = (fn, value) => {
      if (!settled) { settled = true; signal?.removeEventListener("abort", onAbort); fn(value); }
    };
    const killChild = () => { try { child.kill(); } catch {} };
    const discard = () => { discardOutput = true; chunks = []; };
    const onAbort = () => {
      discard();
      settle(reject, new Error("已停止等待；本地计算可能仍在执行。" + queryHint));
    };
    // This deadline survives cancellation. Termination is requested, never
    // represented as proof that all side effects were rolled back.
    const timer = setTimeout(() => {
      discard(); killChild();
      settle(reject, new Error("本地分析达到运行时限，已请求终止进程；" + queryHint));
    }, ANALYSIS_WORKER_TIMEOUT_MS);
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", onAbort); };
    signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout.on("data", chunk => {
      if (discardOutput) return;
      bytes += chunk.length;
      if (bytes > 4 * 1024 * 1024) {
        discard(); killChild();
        settle(reject, new Error("本地分析响应超过 4 MiB；" + queryHint));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.on("data", chunk => { if (stderr.length < 8192) stderr += chunk.toString("utf8").slice(0, 8192 - stderr.length); });
    child.once("error", err => {
      cleanup(); discard();
      settle(reject, new Error("无法启动独立分析 Python（DM_ANALYSIS_PYTHON）: " + err.message));
    });
    const inputError = err => {
      discard(); killChild();
      settle(reject, new Error("本地分析输入管道失败: " + err.message + "；" + queryHint));
    };
    // EPIPE must be a tool error, not an unhandled EventEmitter error that
    // terminates the MCP server and all of the client's other tool calls.
    child.stdin.on("error", inputError);
    child.once("close", code => {
      cleanup();
      if (settled) return;
      try {
        let reply;
        try { reply = JSON.parse(Buffer.concat(chunks, bytes).toString("utf8")); }
        catch { throw new Error("本地分析进程没有返回有效 JSON" + (stderr ? ": " + stderr : "")); }
        if (!reply || typeof reply !== "object" || Array.isArray(reply)) throw new Error("本地分析返回无效响应对象");
        if (code !== 0 || reply.ok !== true) throw new Error(reply.error || stderr || "本地分析进程失败");
        const result = reply.result;
        if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("本地分析返回无效 result 对象");
        const content = [{ type: "text", text: JSON.stringify(result, null, 2) }];
        if (payload.action === "preview") {
          if (!Number.isSafeInteger(result.preview_bytes) || result.preview_bytes < 0 || typeof result.preview_path !== "string") {
            throw new Error("本地预览缺少有效 PNG 路径或字节数");
          }
          if (result.preview_bytes <= 2 * 1024 * 1024) {
            const image = requireFile(result.preview_path);
            content.push({ type: "image", data: image.toString("base64"), mimeType: "image/png" });
          } else {
            result.inline_image = "omitted: PNG exceeds 2 MiB; open preview_path locally";
            content[0].text = JSON.stringify(result, null, 2);
          }
        }
        settle(resolve, { content });
      } catch (err) { settle(reject, err); }
    });
    try { child.stdin.end(body); } catch (err) { inputError(err); }
    if (signal?.aborted) onAbort();
  });
}
''' + s[end:]
s = replace_once(s, '任何工具报错时先调它。', 'DM 连接或原生操作出错时检查它；本地预览/报告依赖错误应检查 DM_ANALYSIS_PYTHON，不要因此重启 DM。')
s = replace_once(s, '返回去均值前后的 DC、频谱格点坐标', '返回去均值后的 DC、频谱格点坐标')
s = replace_once(s, '返回 MCP image block，并保留本地 PNG 路径。', '返回 MCP image block、本地 PNG 路径及捕获时的标定。只看图无需调用 dm_2d_analyze；不能显示图片时明确说明，不假装看见。')
old = '''  if (args.image_id !== undefined && !(Number.isSafeInteger(args.image_id) || /^(front|[0-9]+)$/.test(args.image_id))) throw new RpcError(-32602, 'image_id 必须是整数或 "front"');'''
new = '''  if (args.image_id !== undefined && args.image_id !== "front") {
    const numericId = typeof args.image_id === "string" && /^[0-9]+$/.test(args.image_id) ? Number(args.image_id) : args.image_id;
    if (!Number.isSafeInteger(numericId) || numericId < 0) throw new RpcError(-32602, 'image_id 必须是非负安全整数或 "front"，请使用 dm_datasets 返回的 ID');
  }
  if (args.roi && (args.roi[2] <= args.roi[0] || args.roi[3] <= args.roi[1])) throw new RpcError(-32602, "roi 必须是正面积的原图坐标区域，右下边界不包含");
  if (args.profile && args.profile.start.every((v, i) => v === args.profile.end[i])) throw new RpcError(-32602, "profile 两个端点不能重合；请使用原图像素中心坐标");'''
s = replace_once(s, old, new)
s = replace_once(s, '!args.operation_id || args.operation_id.length > 128', '!args.operation_id.trim() || args.operation_id.length > 128')
write('server.mjs', s)

s = read_checked('tools/analysis_worker.py', 'd3e4e0bfd933370c8758873eae6af9a6ad5e8952')
s = replace_once(s, '''    return {"state": "complete", "capture_id": info["capture_id"],
            "input_sha256": info["input_sha256"], "preview_path": output,''', '''    return {"state": "complete", "capture_id": info["capture_id"],
            "source_image_id": info.get("source_image_id"),
            "working_calibration_xy": info["working_calibration_xy"],
            "calibration_coordinate_frame": "captured pixel centers; source coordinates subtract source_rect_xyxy origin first",
            "intensity_calibration": info.get("intensity_calibration"),
            "intensity_values": "raw pixels; intensity origin/scale have not been applied",
            "input_metadata_sha256": manifest["input_metadata_sha256"],
            "input_sha256": info["input_sha256"], "preview_path": output,''')
s = replace_once(s, 'or not operation_id or len(operation_id) > 128:', 'or not operation_id.strip() or len(operation_id) > 128:')
ast.parse(s)
write('tools/analysis_worker.py', s)

for name, section in (
    ('README.md', '''\n## 普通客户端测试版本（D0 → 本机 P0）\n\n核心 MCP 不依赖 Codex。需要预览的通用 stdio 配置见 [mcp.preview.json.example](mcp.preview.json.example)，核心工具配置仍使用 [mcp.json.example](mcp.json.example)。必须替换所有绝对路径占位符，不自动覆盖客户端配置。\n\n[本机客户端验收](docs/CLIENT_ACCEPTANCE.md) 包含 WorkBuddy 官方配置参考、手动创建的两张合成图和短任务。先在新会话不用 Skill、不读源码、不临时写替代分析脚本，检查模型能否凭工具说明完成基本操作；失败后再单独记录带 Skill 的辅助测试。\n\nD0 只表示代码、合成回归和交付准备完成；本次真实 DM、WorkBuddy 图像显示、模型看图及操作正确性仍须本机 P0 验收。当前桥一次服务一个持续连接：测试前断开其它 MCP 客户端，不要因 busy/unknown 重启 DM 或重复注入桥。详见 [D0 交接边界](docs/D0_HANDOFF.md)。\n'''),
    ('README.en.md', '''\n## General-client candidate (D0 → local P0)\n\nThe core MCP does not depend on Codex. For previews use [mcp.preview.json.example](mcp.preview.json.example); [mcp.json.example](mcp.json.example) remains the core-only configuration. Replace all absolute-path placeholders and merge one server entry without overwriting other client settings.\n\n[Local client acceptance](docs/CLIENT_ACCEPTANCE.md) provides official WorkBuddy configuration references, two manually created synthetic images and short tasks. Start a fresh session without the optional Skill, source-code reading or substitute analysis scripts. Measure whether tool descriptions alone are usable; record Skill-assisted retries separately.\n\nD0 covers code, synthetic regression and delivery readiness only. Real DM, WorkBuddy image rendering, model vision and actual operations still require local P0 acceptance. The bridge serves one persistent client connection at a time: disconnect other MCP clients first. Busy/unknown must not trigger DM restarts or duplicate bridge injection. See [D0 handoff](docs/D0_HANDOFF.md).\n''')
):
    text = Path(name).read_text(encoding='utf-8')
    write(name, text.rstrip() + '\n' + section)
p = Path('.gitignore')
s = p.read_text(encoding='utf-8')
for entry in ('.analysis-env/', '.preview-test-env/', '.workbuddy/'):
    if entry not in s.splitlines():
        s += '\n' + entry + '\n'
write(str(p), s)
