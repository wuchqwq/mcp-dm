# 原生 SUMMARY 独立验收

`dm_native_summary` 是现有实验性 native 后端的第七个工具，直接调用 DM 内置的
`GetMinimum`、`GetMaximum`、`GetSum`、`GetMean`。只支持有界二维 float32 图像，
最多 4,194,304 像素，返回原始像素强度，不应用强度标定。它不是完整
`dm_stats`，不提供标准差、方差、预览、保存或另一套科学计算后端。

**本轮有限实机 PASS：** 新 DLL 的目标构建/宿主门、严格 stdio MCP 和独立
宿主 oracle 已通过，包含非平凡强度标定下的 raw 值、缺空间单位、安全错误，
以及源像素、空间和强度标定、文档数不变。证据来自同一严格 session 的独立
合成输入，不代表真实实验数据、其它类型/构建、并发调用、模型视觉或文件交付
已验收。SHOW 的可见文档及生命周期另见 [RESULTS](../RESULTS.md)。

## 边界与成功条件

- 宿主必须空闲，请求串行；四个 reduction 是独立原生调用，
  `snapshot_atomic:false`，不保证用户同时编辑源图时取得一致快照。
- 已识别的缺单位或不可用空间标定不妨碍 raw 摘要，但须报告
  `calibration_complete:false` 和每轴 `usable/issue`。不猜单位，不吞 native/ABI
  失败；crop 继续严格要求可用空间标定。
- 只读 SUMMARY 的 `request_id` 可省略并生成 UUID；验收显式保存 ID、session、
  tool 和参数。crop/SHOW 等副作用工具仍要求提交前保存的 ID。
- 超时、取消、断连不代表原生操作停止。只在原 session 查询同一 ID，不自动
  重发。STOP、宿主退出/重启或新 session 均不承诺恢复旧记录。
- 通用 NB1 QUERY 不携带原操作。下述客户端和 oracle 依据原始请求记录继续
  核对操作、参数与返回字段；不能宣称通用客户端能识别任意删除了操作特征的
  畸形恢复结果。

## 准备与一次性合成输入

按 [INSTALL](INSTALL.md) 准备指定构建及其 manifest。安装/移除必须在 DM 正常
关闭后进行，保留既有客户端配置和默认 v0.6 后端。使用新的私有证据目录和
新的 session，在启动测试 DM 前设置环境，让插件继承同一 session：

```powershell
$env:DM_NATIVE_SESSION = [guid]::NewGuid().ToString('N')
$summaryDirectory = Join-Path $env:LOCALAPPDATA ('mcp-dm\summary-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $summaryDirectory | Out-Null
$env:DM_NATIVE_EVIDENCE_DIR = $summaryDirectory
```

**先正常启动 DM，等待初始化完成并保持空闲，再手工执行一次性脚本。** 本轮
在启动时通过 `/es` 包装 `runpy` 的尝试失败，已保留失败证据；下面的流程不
宣称支持初始化阶段执行。不要用重复启动或重复注入代替检查失败原因。

在 DM 自身的一次性 Python 入口执行，替换占位路径及插件已继承的 session：

```python
import os, runpy
os.environ["DM_NATIVE_EVIDENCE_DIR"] = r"<本次新私有目录>"
os.environ["DM_NATIVE_SESSION"] = "<本次session>"
summary_rc = runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\create_summary_fixture.py")["main"]()
if summary_rc != 0:
    raise RuntimeError("SUMMARY fixture failed; retain its diagnostic file")
```

这里显式调用 `main()`，不以 `run_name="__main__"` 触发 `SystemExit`。
[create_summary_fixture.py](create_summary_fixture.py) 仅创建新的合成源与其文档，
写入私有 NPY 和 `summary-truth.json`，没有 listener。输入分别用于默认强度、
非平凡强度标定、缺空间单位、不支持类型与非有限值对照。四个 raw 答案为
预先独立手工枚举值，不由 native 回执反推。

`RECORDED` 只表示输入及读回已记录，不是 native PASS。truth 保存同一宿主的
实际 PID、session、明确图像 ID、初始文档数、NPY/像素摘要、两种空间 origin、
带符号尺度/单位及强度标定。任何创建失败保留 FAIL；不覆盖已有 truth/NPY，
不读取、改名、修改或关闭无关源图。

## 严格 stdio MCP

从外部终端运行；`$summaryHostPid` 必须是已独立核对的本次 DM PID，不是终端
或 Python 的 PID：

```powershell
$summaryTruth = Join-Path $summaryDirectory 'summary-truth.json'
$summaryAcceptance = Join-Path $summaryDirectory 'summary-acceptance'
python -B .\experiments\native-bridge\mvp\accept_summary_mcp.py --truth $summaryTruth --evidence-directory $summaryAcceptance --expected-host-pid $summaryHostPid
```

[accept_summary_mcp.py](accept_summary_mcp.py) 复用严格 stdio 客户端，只启动并
关闭自己的 Node 子进程，不启动/关闭 DM。新目录内的 `requests.jsonl` 在每个
新请求发送前持久保存 NB1 protocol/session/ID/op/args/host PID/wire 及 MCP
tool/参数，完成 flush/fsync 后才发送；`stdio-events.jsonl` 保留协议收发。

客户端核对实际 native backend、构建门、宿主/worker/执行线程、图像 ID、
shape/dtype、全部空间标定字段及四个有限 raw 标量。`operators` 必须精确指向
四个 DM 内置 reduction；不接受 Python 计算冒充 native。QUERY 必须恢复同一
结果与原回执。不支持类型、非有限结果及缺失 ID 必须明确 failed，
unknown/timeout 不算正确拒绝，随后有效请求仍须成功。

输出 `summary.json` 的 PASS **只限定 MCP 回执与独立 truth 对照**。
`source_invariance:NOT_TESTED_BY_CLIENT`、`independent_source_oracle_required:true`
明确要求下一步；NPY 文件 hash 未变不能单独证明 DM 内存源图未变。

## 同宿主独立 oracle

保持同一 DM、session 及源文档，不编辑源图。在其一次性 Python 入口执行：

```python
import os, runpy
os.environ["DM_NATIVE_EVIDENCE_DIR"] = r"<同一本次私有目录>"
os.environ["DM_NATIVE_SESSION"] = "<同一本次session>"
summary_rc = runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\verify_summary.py")["main"]()
if summary_rc != 0:
    raise RuntimeError("SUMMARY independent oracle failed; retain its diagnostic file")
```

[verify_summary.py](verify_summary.py) 使用实际 `os.getpid()`，绑定 truth、严格
MCP 报告及提交前请求记录的 session/PID/ID/op/参数。它从独立 NPY 和手工
答案核对四个标量及操作身份，并逐点检查所有源图的像素、dtype/shape、
NaN/正负 Inf 掩码、像素/文件摘要；同时检查 raw origin、physical zero、
signed scale/unit、强度 origin/scale/unit 和文档数量均未改变。

其临时图像引用局限在核对过程，不创建、显示、关闭或重新标定文档，不调用
native 算子或另起 listener；普通一次性 Python 应继续正常。新输出
`summary-independent.json` 才记录该独立范围的 PASS/FAIL。只有它与严格 MCP
均通过，才能声明本次 SUMMARY 数值与源保护通过。

所有输出独占创建，失败也保留，不用成功文件覆盖失败。路径变化可显式设置
`DM_NATIVE_SUMMARY_TRUTH` 和 `DM_NATIVE_SUMMARY_ACCEPTANCE_DIR`，但不能借此
更换实际宿主/session 或绕过绑定。执行 oracle 不需要重新提交 SUMMARY。

## 历史证据与后续清理

先前保留的旧会话已完成独立观察、正常退出和 manifest 所有权移除。其历史
STOP 缺原始提交前记录，身份资格始终 UNVERIFIED；后来的观察或正常退出不
能修复该证据，也不能继承为新会话严格验收。

SUMMARY 不创建新图像或文档，不用它的 PASS 代替 SHOW 的可见性、STOP 后
文档持有或关闭后的最后引用释放。需要 STOP 时按 [安装说明](INSTALL.md)
使用原 helper 预存请求并只提交一次；STOP 仅结束实验 IPC。后续正常关闭 DM
后按 manifest 仅移除本实验拥有的 DLL，不改既有客户端配置。
