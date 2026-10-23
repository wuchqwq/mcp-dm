# 解锁后的最短操作顺序

当前仍为 **HOLD**。本页是之后的人工操作清单，本轮离线工作没有操作 DM、
更换 DLL 或完成任何桌面验收。保留原会话及全部历史记录，不重发旧 crop、
Show 或 STOP。原 session 不在了，就把旧会话的剩余项目标为 NOT_TESTED；
不能用新宿主或新图像补出旧会话的 PASS。

## 先完成保留会话的观察和正常清理

1. **只解锁并查看原测试 DM。** 确认它仍是空闲合成测试会话，没有采集、
   未保存的用户工作或并发编辑。保持已加载 DLL，先不要重启、编译安装或移除。
   使用私有交接中的原证据目录、session、图像 ID 和 manifest，不能按最新窗口猜。
2. **运行一次后置核对，观察实际窗口。** 在该 DM 的一次性 Python 入口使用
   下方代码。脚本会用实际 `os.getpid()` 对照原回执，检查源/裁剪全像素、
   dtype、标定、独立内存及唯一文档。独立确认该文档在 UI 中实际可见；
   回执或 Python 枚举本身不证明可见，更不证明模型看到了图。
3. **仅用 UI 正常关闭此次交付的裁剪文档。** 保留其它合成源，不在脚本外
   留图像对象或 NumPy view。DM 继续运行时，再运行第二段代码，核对该输出 ID
   已失效、总文档数恢复、其它源未变。退出整个 DM 不能代替这一步。
4. **保存结果，再正常退出测试 DM。** 对 FAIL/异常保留新记录，不自动重做操作
   或重启使它通过。仅处理本次测试文档，不关闭无关用户文档，不自动保存覆盖源。
5. **确认 DM 已完全正常退出后，按原 manifest 清理。** 使用
   [INSTALL.md](INSTALL.md#stop-ipc-close-the-test-host-and-remove) 的 Remove 流程，
   先 WhatIf，再执行；只移除归属本实验且校验未变的 DLL。其它 DM 仍开着时
   管理器会拒绝；不要强杀、清空插件目录或对加载中的 DLL 操作。

原会话若缺少**提交前保存的 `stop-request.json`**，严格 STOP 身份资格仍为
**UNVERIFIED**，不得从旧回执反填。仅为继续收集原会话的独立观察，可显式使用
`observe_legacy_stop`；此模式始终输出 UNVERIFIED，永远不能生成 PASS。
已存在但错误的请求记录、错误实际 PID 或错误 STOP 回执仍会拒绝。
它不会连接原生 IPC、重发请求或改/关闭文档。

先在 DM 内执行（替换三个私有路径/会话占位值；本机另有已填好的私有清单）：

```python
import os, runpy
os.environ["DM_NATIVE_EVIDENCE_DIR"] = r"<原证据目录>"
os.environ["DM_NATIVE_SESSION"] = "<原session>"
os.environ["DM_NATIVE_ORACLE_MODE"] = "observe_legacy_stop"
runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\verify_trial.py", run_name="__main__")
```

仅关闭交付文档后，在**同一 DM** 的一次性入口执行：

```python
import runpy
runpy.run_path(r"<仓库绝对路径>\experiments\native-bridge\mvp\verify_trial_closed.py", run_name="__main__")
```

新文件分别为 `trial-observation-after_stop.json`、
`trial-observation-after_close.json`；不覆盖历史 `trial-independent-*`。
若这些目标已有文件，保留它们并停止重复运行，不删文件来重试。
严格验收不会接受这些观察记录作为 PASS 前置证据。

## 之后的新会话资格与 WorkBuddy 盲测

原会话清理完毕后，按 [WorkBuddy 试用包](WORKBUDDY_TRIAL.md) 准备新的空闲
合成会话、证据目录和独立 native 客户端入口。此步骤不沿用 STOP 后的旧 IPC；
本轮没有执行它。默认 v0.6 配置保持原样，main 的已审核心与 feature 的 Show
候选须区分，后续整合见 [分支差异方案](INTEGRATION_PLAN.md)。

- 新严格会话不设置观察模式（清除 `DM_NATIVE_ORACLE_MODE`），完整核对须先
  before_stop，再通过原 helper **预存请求后单次 STOP**，之后 after_stop，
  正常关闭交付文档，最后 after_close。每步保存新文件，缺原始证据不能补造。
- STOP 使用新 ID、明确宿主 PID，并将 `--request-record` 指向本次
  `stop-request.json`，`--evidence` 指向 `stop-receipt.json`。请求记录必须已
  exclusive-write、flush/fsync 完成，才允许管道连接和提交，详见 INSTALL。
- 盲测 Agent 只收到目标范围、session、请求参数和短提示；**不提供答案、
  fixture 源码或严格协议预检结果**。操作者保留源 NPY/答案作独立审阅。
- 用一段提示完成状态、显式 ID 选择、两类 raw mean、预存 ID 裁剪、裁剪均值、
  对同结果 ID 的 Show 和错误拒绝。超时/取消只 QUERY 原 ID，不自动重发。
  让 Agent 保存原始工具回执，操作者单独核数值、源不变及文档/生命周期。
- WorkBuddy 真实调用、UI 显示、模型看图和文件保存分别记录。固定协议客户端
  的 summary/oracle 不能冒充 WorkBuddy 结果，也不能直接认领另一个 Agent 的输出。
  没做的项保持 NOT_TESTED；Show 不提供永久文件保存。

Unicode 可在主交付/正常清理之外另建合成会话诊断，不阻塞已独立完成的检查。
诊断记录区分旧 getter 的 str/bytes，不猜编码；实际 UI、原生 UTF-16 和 MCP
UTF-8 仍需按同一明确 ID 比较。诊断文件完整也不代表 Unicode 已通过。
