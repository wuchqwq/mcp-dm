# Execution Coordinator：image 与 structure worker

现有 `image_*` 工具继续直接调用，不要求安装 Agent、Skill 或创建分析会话。
`ImageWorkspace` 和 `StructureWorkspace` 的写队列、等待取消和执行截止时间已迁到
`lib/runtime/execution_coordinator.mjs`；旧 Promise 链已删除，没有两套队列。
科学计算、文件格式、标定、对象校验和原请求日志仍由各自原 Python worker 负责。
`createServerRuntime` 显式创建共享实例并传给两个适配器；未安装 Skills 仍可直调工具。

## 代码与未来归属

| 模块 | 当前职责及未来归属 |
| --- | --- |
| `lib/runtime/execution_coordinator.mjs` | 可独立复制导入的确定性执行机制；未来属于科研 Agent 通用 Runtime |
| `lib/image_workspace.mjs` | 显式配置、资源键、Python 子进程、数据/响应边界及 PNG；独立科学适配器，过渡期保持旧工具兼容 |
| `lib/structure_workspace.mjs` | 同一端口下的结构适配器，保持自身查询与终止策略，未来独立科学模块 |
| `tools/image_workspace.py` | 既有科学算法、不可变对象和请求日志；本切片未修改，未来独立科学模块 |
| `lib/tools/image_module.mjs` | provider 自身的工具登记与调用契约；不成为跨 provider 全局注册表 |
| DM Python/C++、原生请求与 ABI 门禁 | 长期留在 mcp-dm；本切片未迁入 Coordinator |

Runtime 只依赖 Node 内建 `node:crypto`，不读取环境变量、不导入 server、
workspace、DM/GMS 或 Windows API。资源身份由适配器明确提供。
不创建新仓库；跨仓公开协议与兼容过渡稳定后再迁移，不能跨仓直接导入私有适配器。

## 一个真实执行接口

```js
import {ExecutionCoordinator} from './lib/runtime/execution_coordinator.mjs';

const coordinator = new ExecutionCoordinator();
const wait = coordinator.invoke({
  operation: 'explicit_tool_name',
  requestId: 'saved-before-submission', // inspection 可显式为 null
  parameters: {object_id: 'fixed-input-reference', value: 3},
  resourceKeys: ['opaque-provider-write-resource'],
  timeoutMs: 120000,
}, {
  start(acceptedParameters) {
    // provider.startTask 是适配器提供的方法，不是新的公开 MCP 工具。
    return provider.startTask(acceptedParameters);
  },
}, {signal});

const result = await wait;             // 保持 provider 的原结果/原错误
await wait.workerDone;                 // 实际工作关闭，独立于客户端等待
const observation = wait.receipt();     // 内部、非持久化的执行观察副本
await coordinator.whenIdle();          // drain；不是宿主 STOP/进程退出
```

`start` 必须同步返回 `{result, closed, requestStop?}`：

- `result` 是适配器验证后的结果 Promise，拒绝时保留原 Error。
- `closed` 只能在实际工作不再占用资源时履行；对本适配器就是子进程 `close`。
  返回结果、发出 kill、kill 返回 false、进程 `error` 或 stdin 错误都不能代替 close。
- `requestStop` 是可选的受限终止请求。image 路径保留原有超时 kill 策略；
  普通客户端取消不调用它，响应超限仍由适配器终止其自己的 worker。
  structure 不提供 requestStop：超时、取消及响应超限均只停止等待，不终止 worker。
- 同步抛出只能表示工作尚未开始；已经启动后必须返回生命周期句柄并通过
  `result` 拒绝。否则适配器无法证明安全资源占用。
- 生命周期缺失或 `closed` 拒绝时，明确报告未知并保留资源，不能猜测已退出。

参数在入队前按有限纯 JSON 验证、复制、递归冻结并计算 SHA-256；
后续修改调用方原对象不能改变已接收任务。该哈希是 Runtime 的输入观察，
不是 Python 规范化参数哈希的替代，也不建立第二份去重事实。

## 排队、取消与超时

相同资源按提交顺序串行；多资源任务不会被后来共享任一资源的任务插队。
无冲突任务可以执行，显式只读查询不占写资源。
截止时间从实际启动开始计算，不把排队时长偷偷算进原 image worker 限额。

| 情况 | 行为 |
| --- | --- |
| 入队前或排队中取消 | 移除任务，不调用 start，不启动 Python、不生成请求日志 |
| 启动后取消 | 只结束该客户端等待；worker、截止时间及写资源继续有效 |
| 到达执行截止时间 | 先记录等待超时，再请求终止；不能声称回滚或终止成功 |
| 终止失败或 worker 提前报错 | 写资源仍等实际 close，截止时间防护仍有效 |
| 关闭后异步验证尚未返回 | 资源可释放，但结果等待仍有截止时间；不向已关闭的工作重复发终止请求 |
| 晚到结果 | 更新本执行观察；不能向已取消的 MCP 请求再次响应，不改变其他请求或科学版本 |

`receiptVersion:1` 的内部观察记录包含原请求 ID、操作名、参数哈希、资源、
执行状态、`waitState`、`closed` 及适用的 deadline/stop 诊断。
`state:completed` 只表示适配器结果已返回；`state:failed` 只表示该结果 Promise
被拒绝，可能仍是传输故障或未知副作用状态。它们**不是持久科学回执**。
不伪造 worker 未上报的 validating/persisting 阶段，也不更新当前 Analysis Context。
`executionId` 是 Coordinator 实例内序号，不是跨客户端恢复 ID。

## 恢复只能查询

```js
const recovered = await coordinator.recover({
  operation: 'existing_result_query',
  requestId: originalSavedId,
  parameters: {query_request_id: originalSavedId},
  resourceKeys: [],
  timeoutMs: 120000,
}, {query: accepted => provider.queryOriginal(accepted)}, {signal});
```

recover 不调用 start，不占写资源，不自动重试失败或未知的操作。
ImageWorkspace 将它连接到现有 `image_result`，可在写任务运行时读取请求记录。
已有 Python 日志仍负责相同 ID 同参数返回原对象、改参数拒绝、prepared/损坏
记录报告未知，以及成功对象和文件哈希检查。新客户端不依赖旧 Coordinator
内存；显式查询原工作区及原 ID 即可。查询失败不授权重新提交。

此切片只在一个 Coordinator 实例内排队；server 中 image/structure 共用一个实例。
独立构造 workspace 时可显式注入实例。它不是跨进程文件锁，
不能保证两个独立 MCP 进程的不同请求彼此串行。原有日志排他创建仍保护
同 ID，不把它扩大成跨进程全局调度保证。
`instance.queue` 仅保留为该写资源的 drain getter，不维护旧队列。
MCP 进程退出不构成后台任务托管或续跑保证；新进程只查询已有持久证据，
prepared/未知记录仍保持未知。DM 的 STOP/跨宿主会话恢复语义没有改变。

## 兼容、验收及下一步

MCP 名称、schema、instructions、成功结果、科学格式、默认 v0.6 配置及 ABI
门禁保持原约定。取消/超时沿用原 image 提示；Python 科学错误继续以原文本
和 MCP `isError` 返回。新增拒绝伪造的 worker 请求/对象身份，不把别单结果当成功。
没有增加公开执行工具、自动 fallback、任意脚本执行或新依赖。

针对性测试：

```powershell
node --test tests/execution-coordinator.test.mjs
node --test tests/execution-coordinator-image.test.mjs
node --test tests/execution-coordinator-mcp.test.mjs
node --test tests/image-worker-lifecycle.test.mjs
```

纯执行测试用可控 Promise；进程接口负例明确使用传输替身。
stdio 验收运行实际 Python 科学 worker，在其真实 prepared 日志 fsync 后
通过仅用于测试的屏障控制时序：取消、排队、终止失败、原 ID 查询、独立数值
核对、MCP PNG、无覆盖导出及新客户端恢复分别检查。它不是 DM、浏览器或模型看图验收。

structure worker 已复用同一生命周期接口；分析上下文应
继续保存现有不可变引用及 CAS 修订，而不是让执行观察代替科学对象权威。
执行层本身没有任务图、Context 存储或多 Agent 管理。
依赖它的[独立 Context／Skills 切片](ANALYSIS_CONTEXT.md)只保存分析引用及 CAS 修订。

## 工作容量与可查询的执行观察

资源冲突和进程容量分别约束：默认最多2个 work worker、1个 query worker。
有空闲资源不代表有进程名额；结果已返回也不代表名额释放，仍等 actual close。
查询使用保留容量，不被长计算占满；观察工具本身不启动进程，也不等待科学资源。
不增加任何科学工具的原始超时。计时采用单调时钟，分别保留入队、启动、运行、
停止等待、deadline 与实际 close 时间；runMs 是 worker 生命周期，包含 Python 启动、
模块导入与退出，不冒称算法内核耗时。没有 worker 未报告的内部阶段。

显式配置 `DM_MCP_EXECUTION_OBSERVABILITY=1` 后增加两个只读工具：

- `execution_list(provider, request_id?, limit?)`：查询该已配置 image/structure provider 的最近观察。
- `execution_info(provider, execution_id)`：查询 list 返回的 executionToken。

观察包含 `{provider, workspace, session, requestId}` 范围与每次执行唯一 token。
外部 session 为保留工作区请求日志的 `workspace-journal-v1` 命名空间，不冒充 DM 宿主会话；
不同 provider、工作区和运行时 token 不能混查。同 ID 跨 image/structure 不串单。
不能删除/替换工作区后承诺原日志恢复。最多保留256个终态观察；活跃任务不能被历史挤走。
观察不会自然沿 async handler 的 Promise 属性传递，因此正式通过单独模块登记这些接口。
它们不替代 image_result/structure_result；重启后原请求查询仍以各自持久日志为准。

完整工程回归使用 `npm test`，将独立测试文件并行数固定为2；每个文件仍执行全部用例，
内部受控长任务／查询并发也保留。多个测试各自启动独立 MCP 进程，并不共享一个容量池。
无限制地并行这些进程会把 Python 导入／worker 生命周期拉长，触发专为超时注入设置的短门限；
这与一个 server 的资源排队不同。比较正常／受控负载时保持相同输入、原截止时间及数值门限，
分别报告 queueMs 和 worker 生命周期，不通过放宽超时隐藏失败。
