# 原生桥验收流程

本页说明合成输入、严格 stdio MCP 客户端和独立宿主 oracle 的验收流程。
**当前仍为 HOLD。** 真实严格 MCP 已通过有标定及缺单位输入的 raw mean、
元数据与限制、安全错误、裁剪 ID 恢复/冲突，以及指定裁剪 ID 的 Show 原生
完成回执。实际可见文档、文档数量、本轮独立全像素/源不变、STOP 后文档持有、
关闭文档后的最后引用释放及正常退出/移除尚未完成，不能继承旧版本 PASS。

已保留会话的原生 IPC 已 STOP，宿主和已加载 DLL 的正常清理仍待完成。
若历史 STOP 缺少提交前保存的 `stop-request.json`，不得由回执反填；按
[解锁清单](UNLOCK_CHECKLIST.md)收集独立观察，其结果始终为 UNVERIFIED。
不重发旧 crop、Show 或 STOP，不强杀宿主或移除加载中的 DLL。

以下新验收使用空闲、串行的指定构建测试会话，仅操作自己创建的合成图。
默认 v0.6 Python 后端及既有客户端配置保持不变，不启动常驻 Python listener。
raw mean 不应用空间或强度标定；已识别的不可用空间标定须明确报告。
crop 仍要求有效空间标定。缺单位均值有有限实机证据，其它无效空间数字仍仅有
离线 surrogate 覆盖。验收不涉及硬件或真实实验数据。

## 准备新的合成会话

1. 按 [INSTALL.md](INSTALL.md) 在 DM 正常关闭时安装本实验拥有的 DLL。
   使用新的私有状态、证据目录及 manifest，不覆盖已有记录。
2. 启动测试 DM 前设置新 session 和证据目录，让 DM 继承它们：

   ```powershell
   $env:DM_NATIVE_SESSION = [guid]::NewGuid().ToString('N')
   $trialDirectory = Join-Path $env:LOCALAPPDATA ('mcp-dm\native-trial-' + [guid]::NewGuid().ToString('N'))
   New-Item -ItemType Directory -Path $trialDirectory | Out-Null
   $env:DM_NATIVE_EVIDENCE_DIR = $trialDirectory
   $trialFixtureScript = (Resolve-Path .\experiments\native-bridge\mvp\create_trial_fixture.py).Path
   ```

3. 正常启动获准的空闲测试 DM，在其自身的一次性 Python 入口执行
   `$trialFixtureScript` 一次。等待脚本结束后才开始原生请求，不在外部 Python
   执行它。脚本创建 CAL、RAW、UINT16、NONFINITE 合成目标及私有
   `trial-answers.json`，不读取、重命名或修改已有图像。
4. 保留生成时的源 NPY、像素/文件摘要和标定。独立答案来自这些数组，不能由
   native mean 回执反推。确认本次宿主 PID、session 和允许操作的显式图像 ID。
   断开其它 MCP 连接，避免并发图像操作。

## 严格协议与原生数值检查

变量指向本次新会话及已核对的 DM PID：

```powershell
$answersFile = Join-Path $trialDirectory 'trial-answers.json'
$protocolEvidence = Join-Path $trialDirectory 'trial-acceptance'
python -B .\experiments\native-bridge\mvp\accept_trial_mcp.py --answers $answersFile --evidence-directory $protocolEvidence --expected-host-pid $testDmPid
```

[accept_trial_mcp.py](accept_trial_mcp.py) 只启动并关闭自己的 Node stdio 子进程，
不启动或关闭 DM。它检查真实 backend、构建门、宿主/执行线程、图像身份、
shape/dtype、两轴标定与 raw mean；支持类型的缺单位均值须保留逐轴问题。
不支持类型、非有限均值、缺失图像、缺请求 ID、无单位 crop 和冲突参数须按
明确的 RPC 或原生 failed 错误拒绝，unknown/timeout 不能算正确拒绝。

`dm_crop` 和 `dm_native_show` 必须在提交前保存 request ID、session 和参数。
裁剪返回的新 ID、原请求 QUERY、显式重复和冲突应互相对应；等待超时、取消
或断连后只查询原 session 的同一 ID，不自动重发操作。STOP 或重启后不承诺
恢复旧记录。协议客户端会先记录提交 ID，再发送请求。

`dm_native_show` 仅接受本插件仍持有的 crop 工作副本。它不另做数据副本、
不接文件路径、不保存文件。完成回执不能代替实际可见文档、唯一文档及生命周期
检查，也不代表模型收到图像。Native SaveAs 的字符串 ABI 和不覆盖语义尚未
充分确认，不能用 Python 回退伪装原生文件交付。

## STOP 前的独立核对

在同一 DM 的一次性 Python 入口执行，替换路径和 session 占位值：

```python
import os, runpy
os.environ["DM_NATIVE_EVIDENCE_DIR"] = r"<本次证据目录>"
os.environ["DM_NATIVE_SESSION"] = "<本次session>"
os.environ.pop("DM_NATIVE_ORACLE_MODE", None)
runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\verify_trial.py", run_name="__main__")
```

[verify_trial.py](verify_trial.py) 固定读取 `trial-acceptance/summary.json`。
STOP 前应生成新的 `trial-independent-before_stop.json`；它用实际 `os.getpid()`
核对回执宿主，逐像素比较源与裁剪、dtype/shape、独立内存、标定及包含明确输出
ID 的文档数量。另由操作者观察该文档确实可见；Python 枚举不等同于 UI 观察。
脚本不创建或关闭文档，图像和共享数组引用仅在核对函数内存活；不要在外部变量
中额外持有图像或 NumPy view。

## 预存请求并单次 STOP

完成 STOP 前检查、断开客户端并确认在途请求后，使用原 helper：

```powershell
$stopRequestId = 'stop-' + [guid]::NewGuid().ToString('N')
$stopRequestRecord = Join-Path $trialDirectory 'stop-request.json'
$stopReceipt = Join-Path $trialDirectory 'stop-receipt.json'
python -B .\experiments\native-bridge\mvp\stop_native.py --session $env:DM_NATIVE_SESSION --request-id $stopRequestId --expected-host-pid $testDmPid --request-record $stopRequestRecord --evidence $stopReceipt
```

[stop_native.py](stop_native.py) 独占创建原请求，写入协议、session、ID、STOP、
空参数、目标 PID 和精确 wire，完成 flush/fsync 并关闭文件后才连接管道。
已有请求或回执文件、写入失败都拒绝提交。目标 PID 必须是 DM，不是 helper
进程。连接或等待失败后保留原记录及未知状态，不自动再次 STOP 或换 ID 补造。

原始回执仅证明 IPC 确认；须另查实验管道/窗口清理。STOP 不关闭 DM，不关闭
已显示文档。严格 oracle 要求 STOP ID/session/op/args/PID/wire 与原请求一致，
回执属于实际宿主，重复 JSON 键也会拒绝。缺历史原请求的观察模式始终
UNVERIFIED，不能作为严格验收的前置证据。

## STOP 后、关闭文档及正常清理

1. 在同一 DM 再执行上述 `verify_trial.py`，严格模式应生成新的
   `trial-independent-after_stop.json`，独立检查显示文档仍持有正确输出。
2. 核对成功后，仅在 UI 正常关闭这次交付的 crop 文档，保留其它合成源。
   DM 继续运行时，在其内一次性执行：

   ```python
   import runpy
   runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\verify_trial_closed.py", run_name="__main__")
   ```

   [verify_trial_closed.py](verify_trial_closed.py) 检查输出 ID 失效、文档数恢复、
   其它源像素和标定未变，并生成 `trial-independent-after_close.json`。
   整个 DM 退出不能替代最后引用释放证明。
3. 保存结果，再正常退出测试 DM。确认没有 DM 进程后，按原 manifest 仅移除
   本实验拥有且校验未变的 DLL；详见 [INSTALL.md](INSTALL.md)。不关闭无关
   文档、不覆盖源文件、不强杀、不清空插件目录。

## 证据范围与记录

每个阶段分别记录 PASS / FAIL / NOT_TESTED，保存调用前 ID、原参数、原回执和
实际使用的源码版本。返回 `native_receipt` 不能单独证明事先已保存 ID。
数值回执、独立全像素/源不变、UI 可见性、文档持有、最后引用释放和文件持久化
各有自己的证据边界；没执行的检查不能因回执或旧版本结论自动 PASS。

`after_stop` 保存 truth、协议 summary、原 STOP 请求及回执的文件指纹，
`after_close` 必须匹配这些原始文件、实际 PID、模式和成功标志。保留原失败，
不改旧证据或手工补写指纹。离线故障注入验证了这些脚本的拒绝行为，但没有在
DM 中执行独立 oracle，也不解除当前 HOLD。

Unicode 诊断区分 legacy getter 的 str/bytes，保留原始字节及文本码点，不猜
编码。实际 UI、原生 UTF-16 与 MCP UTF-8 的同 ID 名称/单位对照仍须另行验证；
诊断文件完整也不构成 Unicode qualification。私有答案、数组、操作日志、
manifest、图像与本机路径不进入公开仓库。
