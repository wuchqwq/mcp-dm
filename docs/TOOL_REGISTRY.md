# 服务端 ToolRegistry 与工具模块

本切片把工具登记、输入校验与分派从 `server.mjs` 的逐工具分支移到显式模块。
已有 MCP 工具名称、schema、后端选择、科学计算与原请求恢复约定保持不变。
普通客户端可以继续直接调用工具，不需要先安装 Skill 或创建分析会话。

## 两种注册表的边界

这里的 registry 是 **mcp-dm provider 自己的服务端能力目录**。它不决定下一步科研策略，
不管理其他 Agent，也不是未来科研 Agent 的跨 provider 全局注册表。

| 位置 | 当前职责 |
| --- | --- |
| `lib/runtime/tool_registry.mjs`、`schema.mjs` | 可移植的登记、schema 校验与确定性单工具分派；不导入 DM、provider 配置或科学 workspace |
| `lib/tools/create_server_runtime.mjs`、`builtin_modules.mjs` | mcp-dm 自身的显式 provider 组装、既有后端选择和可选模块配置 |
| `lib/tools/*_module.mjs` | 将既有 DM、图像、面板、结构适配器登记为工具；保留原队列、数值检查与恢复机制 |
| `server.mjs` | MCP 协议、请求取消及协议响应；不按科研工具名称维护新的分派树 |

未来科研 Agent 仓库可拥有通用科学工具、Skills、全局路由和执行协调。
它通过公开 MCP／科学数据交接协议使用 mcp-dm，不能反向让 mcp-dm 依赖该 Agent，
也不能跨仓直接绑定 GMS 私有对象或 ABI。当前没有创建第二个仓库、复制一套运行时，
或删除既有独立 `image_*`／`structure_*` 入口。长期边界见
[RFC](ORCHESTRATION_SKILLS_RFC.md)。

## 工具模块怎样登记

模块对象必须显式包含 `id`、`enabled: true`、`instructions` 与 `tools`。
每个工具条目包含：

- `definition`：原 MCP `name`、`description`、`inputSchema`。
- `execute(args, {signal})`：调用已有适配器的 handler。
- `contract`：后端、科学输入输出、副作用、资源限制及恢复说明。

通用 `ToolRegistry` 提供以下接口：

| 接口 | 行为 |
| --- | --- |
| `register(module)` | 校验整个模块后原子登记；拒绝重复名称、非法 schema、缺少 handler／契约和未显式启用的模块 |
| `unregister(moduleId)` | 未封闭时移除该模块的目录和入口，调用其可选关闭钩子；不存在则返回 `false` |
| `seal()` | 封闭本次组装；此后不能增删模块 |
| `listTools()` | 返回兼容的 MCP 工具定义副本 |
| `describe(name)`／`describeAll()` | 返回内部声明式契约副本；未登记工具返回 `null` |
| `call(name, args, {signal})` | 按同一个登记条目校验参数并调用 handler；未知名称明确拒绝 |
| `close()` | 调用已登记模块的可选关闭钩子 |

不扫描用户目录、不接受数据中的任意 import 路径，也不自动安装第三方模块。
`additionalModules` 是宿主程序明确传入的可信模块对象，不是公开脚本执行接口。
默认 provider 组装完成后立即 `seal()`；本轮不提供运行中的热卸载服务。

`schema.mjs` 保留旧入口的基本参数校验及错误语义，不是新引入的完整
JSON Schema 引擎。相互排斥字段、科学对象关系和具体数据资格仍由适配器
及 worker 检查；新增模块也须提供这些检查，不能仅凭通过登记就声称输入合格。

## provider 组装与配置

`createServerRuntime({env, additionalModules = [], disabledModules})` 位于
`lib/tools/create_server_runtime.mjs`，返回 `{registry, instructions, backend, close}`。
例如，开发者可在独立 Node 脚本中检查已配置目录：

```js
import {createServerRuntime} from './lib/tools/create_server_runtime.mjs';

const runtime = createServerRuntime({env: process.env});
try {
  const definitions = runtime.registry.listTools();
  const fftContract = runtime.registry.describe('image_fft'); // 未启用时为 null
  // contract 查询不会启动科学计算，也不会资格确认宿主或数据。
} finally {
  runtime.close();
}
```

MCP 客户端继续使用 `tools/list` 与 `tools/call`。`describe` 是内部 API，
本轮没有新增 registry 查询类 MCP 工具，也没有把内部 handler 暴露给客户端。

| 模块 ID | 启用条件与边界 |
| --- | --- |
| `dm-python` | 默认 `DM_MCP_BACKEND=python`；保留 v0.6 路径 |
| `dm-native` | 显式 `DM_MCP_BACKEND=native`；保留精确构建、每操作资格和会话门禁 |
| `images` | 显式 `DM_IMAGE_WORKSPACE`，或 `DM_MCP_BACKEND=images`；使用独立 Python，不连接 DM |
| `image-panel` | 跟随已启用的 `images`；仍调用同一图像对象与工具，不新增科学状态库 |
| `structures` | 显式 `DM_STRUCTURE_WORKSPACE`；使用已有独立 ASE／diffsims 环境 |

配置和依赖安装仍见 [Agent 指南](../README.agent.md)、
[像素图像工具](PIXEL_IMAGE_WORKFLOW.md) 与
[结构／衍射工具](STRUCTURE_DIFFRACTION_TOOLS.md)。没有可用适配器时不会隐式换后端。

可用 `DM_MCP_DISABLED_MODULES=image-panel` 在启动时关闭一个可选模块；
或者由宿主程序传入 `disabledModules: ['image-panel']`。
允许的可选 ID 为 `images`、`image-panel`、`structures`。
关闭 `images` 也不组装依赖它的面板。未知或核心模块 ID 明确拒绝。
配置只影响下一次显式组装，不是客户端越权启停后端的工具。

## 契约描述不等于资格验证

`describe` 包含：

- `backend`、`inputs`、`outputs`：科学来源、对象类型和坐标域。
- `effects`：副作用类别、是否修改源数据及 `request_id` 要求。
- `gates`：仍由既有适配器逐调用验证的能力门禁。
- `execution`：已有资源键、序列化、预算与取消行为说明。
- `recovery`：原请求查询入口、身份字段和可恢复范围。

其中 `availability.runtimeQualification` 明确为 `not_probed`。
目录存在只说明显式登记了入口，不能证明 DM 正在运行、ABI 匹配、依赖已安装，
也不能把某个算子的已验证 dtype 范围扩大到其他数据。
这些诊断不是第二套资格状态；真实调用仍由原生／科学适配器执行硬校验。

`execution.resourceKeys` 和预算是当前适配器约束的声明，不是已经实现的新调度器。
本轮没有提取公共 worker 队列、数据库、任务图或新的重试策略。
已开始请求取消等待后仍可能完成；继续使用原 `image_result`、`structure_result`
或同一原生会话的 `dm_native_result` 查询。不得因目录重构重新提交未知副作用操作。
可见窗口、科学结果和 viewer-close 的恢复命名空间也保持各自边界。

## 版本与兼容策略

`describe` 的 `contractVersion: 1` 只标识当前**内部工具模块契约**。
它不是 MCP 协议版本、科学数组格式或原生结果版本的升级，也不是已经发布的
跨仓 `compat_version` 协议。MCP `2024-11-05`、既有工具名称／schema／result／error，
以及现有科学 schema-1、NB2 和各算子的 result version 都按原约定保留。
修改描述文字或移动模块文件不能成为修改这些兼容契约的理由。

真正分仓之前，须先发布独立、带版本的 wire capability／科学 handoff 契约，
明确协商、错误、来源、身份和版本兼容规则；随后为旧 `image_*`／`structure_*`
入口公布过渡与弃用窗口，不能直接移除或让客户端自行猜测迁移方式。
新 Agent 不能导入本仓库的私有 workspace、worker 或 GMS adapter 来绕开该边界，
mcp-dm 也不能反向依赖新 Agent。

RFC 后续 C／D／E 的 Coordinator、统一 OperationReceipt 状态、修订感知
AnalysisContext 与迁移后的 Skill 包尚未在本切片实现。
当前模块只是描述并委托现有队列、请求 journal 与不变对象，不能称为已经统一了执行状态。

## 下一切片的接口消费边界（建议，尚未实现）

| 消费方 | 建议的输入与责任边界 |
| --- | --- |
| Execution Coordinator | 接收明确的工具名、参数、输入版本引用及预先保存的请求身份，通过 provider 的 `invoke`／`recover` 端口执行；资源键由 provider 提供，不通过 DM 环境变量或 Windows 路径猜测身份。原始错误与回执保留，未知副作用状态不自动重发。 |
| Analysis Context | `read(analysisId)` 与 `commit(expectedRevision, patch, dependencyProof)` 仅管理引用及 CAS 修订。显示更改、尺度／中心修订和新 capture／FFT producer 分别应用已有依赖规则；晚到结果不能覆盖更新的人工选择。 |
| 专业 Skills | 在未来 Agent 侧声明所需工具、契约版本、可校验示例和科学限制。它们消费 provider 能力，旧工具直调仍独立可用；Skill 不能授权脚本或突破资格。 |

这些是后续接口方案，不是已经发布的新方法或跨仓协议。本轮不创建对应空壳类、
数据库、任务图或后台模型服务。下一步可先让一条既有 image worker 路径消费执行协调接口，
证明资源占用持续到实际 worker 关闭、取消后原 ID 恢复以及错误保真，再扩大迁移。

`dm_python_module.mjs` 中原有 `dm_2d_preview`／`dm_2d_analyze`／`dm_2d_result`
外部 helper 路由也属于兼容接线；它们的通用执行与科学部分应按职责后续迁出。
DM 捕获、原生操作、会话请求权威、ABI 门禁和受限写回继续归 mcp-dm。

## 跨工具科学验收

`tests/tool-registry-science-mcp.test.mjs` 通过真实 stdio server 调用登记后的工具：

无标尺合成 TIFF 的像素测量 → 有来源的 signed XY 标定 → 显式 ROI FFT →
原频率坐标测量 → CIF／晶带轴／diffsims → 拟合与独立反射验证 →
更正尺度与峰位 → 更新测量和比较 → PNG／科学 NPY 导出 → 新客户端查询原请求。

用例以可手算周期图的解析频谱为独立参考，核对实际 MCP 图片内容、无隐藏后端切换、
固定实验尺度的配准、原复数 FFT 哈希、原文件不变和唯一 FFT 提交记录。
更正尺度后若候选不再匹配，必须保留失配；不通过拟合伸缩或放宽门限恢复“成功”。
旧请求恢复的是原版本，不冒充重新观察或自动使用新标尺。

在已经准备好的独立科学环境下分别运行：

```powershell
node --test tests/tool-registry.test.mjs
# DM_STRUCTURE_PYTHON 指向已安装图像、ASE、diffsims 依赖的独立解释器。
node --test tests/tool-registry-science-mcp.test.mjs
```

这证明合成科学工具与 MCP 图片内容的组合契约，不等于真实 DM、浏览器、
普通模型客户端实际看见图或真实材料判相验收。
后续执行协调、修订感知 AnalysisContext 与 Skills 只按 RFC 的消费边界逐步实施，
不能将此目录切片写成已经完成的全局 Agent 平台。
