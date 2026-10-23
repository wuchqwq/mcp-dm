# 原生周期任务：真实验收与失败边界 / Native periodic entry

**结论：原生文件入口已在真实 DM 中通过小型合成验收，可以在没有 Python
serve loop 的情况下接收外部请求。但目前不能整体替换生产 Bridge。**
纯原生读取和统计通过；另行测试的 busy 时段 Python 监听器唤醒导致宿主异常
退出，这条混合路径为 FAIL，已默认隔离，不再复试或自动重启。

**English:** Native main-thread periodic file dispatch is experimentally viable:
registration returns, external requests receive matching replies, ordinary
foreground Python can run between requests, and bounded synthetic image reads,
calibration, ROI statistics and cleanup passed. However, a separate listener
wake overlapping a normal background Python script was followed by a real host
crash with a Python access violation. This does **not** establish a safe
replacement for the current Bridge; the listener/busy prototype is quarantined.

All changes are isolated in `experiments/` on `experiment/dm-native-periodic`.
Production Bridge, Node protocol, launcher, environment and the 21 tools are
unchanged. No hardware, real experimental data, `/ef`, forced process termination,
automatic restart or arbitrary-code MCP endpoint was used.

## 机制与官方依据

外部进程关闭并 fsync 临时文件，以同目录硬链接原子发布固定请求；原生
`AddMainThreadPeriodicTask` 在主线程定期检查，每次只处理一个有界请求，写回
带 session、request ID、slot 和执行计数的结果。注册脚本随后正常结束。

Gatan [官方文件等待示例](https://www.gatan.com/sites/default/files/images/scripts/Having_a_script_wait_for_a_file_to_appear.s)
给出了原生周期文件检查方法；本实验没有使用其后续的无限信号等待。
任务移除、原生对象弱身份、文件、时钟和标定签名另经本机官方文档核对。
API 文档不构成 Python 重入、busy 判定或全部版本兼容性的保证。

## 真实 DM 验收

| 项目 | 状态 | 证据与范围 |
|---|---|---|
| 注册脚本返回后任务仍存活 | PASS | 后续外部进程发布请求，不再按 Execute，收到新 ID 回执 |
| 临时请求发布前不处理，发布后处理 | PASS | pending 时无回执，原子发布同一预留请求后得到对应结果 |
| 外部文件 → 原生任务 → 带 ID 结果 | PASS | 私有会话身份、请求 ID、slot 和结果完整对应 |
| 多个排队请求、重复 ID | PASS，有限序列 | 所有已发布槽均有结果；重复 ID（包括改变操作）被拒绝，执行计数不增加 |
| 明确失败与未知 | PASS，已测场景 | 固定 fail 返回 failed；未完成或缺失回执保留 unknown；无自动重发 |
| 普通前台 Python 共存 | PASS after probe repair | DM API 导入、进程绑定、原生对象/版本校验、计算 55；脚本前后原生请求均成功 |
| 合成图尺寸、dtype、标定与 ROI 数值 | PASS | 独立枚举对照、signed scale、非零物理原点和固定半开 ROI |
| 正常自动到期 | PASS | 到期回执、完整源像素/标定检查、所属图关闭、弱对象身份消失 |
| 外部 stop 与正常清理 | PASS | stop 请求后收到确认，再由独立原生脚本验证对象已释放 |
| 纯原生任务期间界面可操作 | PASS，有限观察 | 能打开/运行其他脚本；没有进行完整延迟基准或长期压力测试 |
| 空闲时原生任务唤醒 C1 Python 监听器 | PASS，独立实验 | 请求 nonce、ID、宿主、源数值和标定匹配；注册脚本已结束 |
| busy 时唤醒 C1 Python 监听器 | **FAIL：宿主崩溃** | 外部忙时请求后主进程退出，Windows Application Error/WER 记录 Python 访问冲突 |
| busy 请求计算结果与正常清理 | unknown / NOT_TESTED | 缺少完成、睡眠结束及正常注销回执；进程消失不能冒充成功清理 |
| 修正后的监听器安全隔离 | PASS，合成拒绝测试；原生 guard NOT_TESTED | starter 在导入宿主前拒绝，公开 request 拒绝；没有再次启动 DM 验证 native guard |
| 任意用户脚本的全局 busy 查询/安全接纳 | NOT_TESTED / 未建立 | 不能从窗口响应、周期 tick 或自己的标志文件推断 |
| 生产 21 工具迁移 | 未实施 | 不将以上结果扩展为生产兼容性承诺 |

源图是程序新建的显式 float32 斜坡，所有数值和标定均为合成 fixture，不是
私人实验数据。统计固定矩形的期望值通过手工可枚举公式建立。完整验收器同时
核对槽集合、预期返回码、执行计数、Python 前后往返和停止/释放条件。
文件成功传输与数值正确是两项独立检查。

## 失败记录保留与修正

1. 准备目录时首次缺少父目录，修复目录创建；不覆盖已有运行目录。
2. 初版普通 Python 回执无法证明在 DM 中产生，真实运行又遇到
   `FileExistsError`。保留旧回执，改为绑定既有 DM 进程并调用真正的 DM API。
3. 两次跨脚本类身份/自定义方法查询在宿主失败。最终共存校验只使用已验证的
   原生内置 API、弱对象有效性、版本和进程身份，通过后才计为 PASS。
   初轮失败没有被覆盖或写成从未发生。
4. 独立 busy 实验先完成了空闲唤醒，再由原生任务只启动一个固定的、没有 DM
   API 调用的后台 Python 睡眠脚本。记录确认其已开始，随后才发布监听器唤醒。
   唤醒缺少完成回执，宿主随即异常退出。日志指向 `python37.dll` 访问冲突；
   尚无符号栈证据确定具体绑定/锁/GIL 根因，也不推断所有版本都会如此。
5. 发现主进程退出后，没有新的分析/唤醒请求，没有强杀或自动重启；仅发布
   一次 stop 标记，未获确认。保留原始执行代码和 Windows 事件供本机检查；
   不将原始日志、转储、厂商文件、私人路径或进程标识提交到仓库。

既有 Python 回调线程检查并未阻止本次访问冲突。不能只凭“在主线程触发”或
在 Python 回调内增加 guard 就宣称安全；需要在触发解释器入口前建立可靠的
接纳/拒绝机制，而当前并未证明这种机制。

当前监听器生成器和请求入口默认拒绝执行；native hold 已停用，并加了仅针对
自己 busy 标志的保护。这些属于隔离措施，**不是已实机验证的修复**，也不是
通用 busy 查询。原始未隔离源码留在私有运行目录；当前文件不可冒充当时版本。

本次最终合成测试为 **23 项**，在开发 Python 和现有 GMS Python 宿主外环境
各通过一遍；旧 C1 合成回归另有 **33 项**通过。重复环境运行不相加成新的
宿主验收数。测试包括隔离入口在导入 DM 前拒绝，不构成 native guard 实机通过。

历史失败场景的关键调用顺序（仅供审查，当前已停用）：先由原生回调调用
`ExecutePythonScriptFile(fixed_sleep_file, 1)`，确认固定脚本已开始后，另一原生
回调对已绑定的合成 trigger 调用 `SetName`，让已注册的 Python 监听器进入。
不是从外部执行任意代码，也不是未知线程直接调用 DM API；这仍未能保证安全。

## 能替换什么，不能替换什么

- **外部请求入口：已证明候选机制成立。** 有界原生周期检查不需要常驻 Python
  执行脚本；小型读取、标定和统计可以直接走原生路径。
- **当前完整 Bridge：现在不能替换。** Python 监听器空闲时可调用，不代表能
  在任意正常 Python 执行时安全进入。忙时已有真实失败，不能交给 Agent 猜测
  窗口是否空闲，也不能把文件轮询本身当成解释器接纳机制。
- 暂保留现有 Bridge。后续优先评估原生有界读取/导出加宿主外 Python 计算。
  若需要在 DM 内进入 Python，则应先取得并
  验证 Gatan 支持的 Python 安全接纳/拒绝机制；不要迁移 21 个工具、扩展 4D
  或另建调度平台来绕过此问题。

TTL 只在下次原生回调检查，不能中断已经开始的调用、被阻塞的 UI 或宿主崩溃。
正常到期/停止通过，不构成崩溃恢复或 exactly-once 保证。有限请求序列未见
丢失/重复，不构成长期可靠性证明。本地目录也不是鉴权边界。
