# RFC：让 Agent 帮助生成 GMS 原生兼容层

> **状态：PROPOSAL / 文档构想，不代表功能已经实现。**
>
> **实施时机：** 等当前 feature/native-bridge-mvp 的原生分析功能扩展任务完成并审查后，再单独立项。
>
> **基线：** 已有限定验证的 Windows x64 GMS 3.53.4137.0 原生适配器。其它构建未经验证，一律不得因为本 RFC 自动放行。
>
> **目标：** 为第三方 Agent 提供可调用的独立兼容性工具，让 Agent 协助用户分析自己合法取得的 GMS 安装、生成版本专用候选 Adapter，并通过独立验证逐项启用功能。

## 1. 一句话愿景

**mcp-dm 让 Agent 使用 DigitalMicrograph；未来的兼容层工具让 Agent 帮助 mcp-dm 适配新的 DigitalMicrograph 构建。**

新用户的 GMS 与已支持版本不一致时，不必由维护者亲自重复整理全部导出表、调用约定和接口差异。用户可以让自己选择的 Agent 借助本地工具生成一份**可审查、默认禁用**的新版本适配候选，再通过明确的验证关卡提交兼容性 PR。

这是 **agent-assisted compatibility engineering**，不是“让 AI 自动生成一个能安全运行的未知 DLL”。

### 与当前任务的关系

- 当前优先级仍是接通原生统计、FFT、滤波、读写和结果交付等采集后分析功能。
- 本 RFC **不实现代码、不变更 Native Bridge、不改变 main 或默认 v0.6 行为**。
- 先积累一个构建上真正可用的功能和 ABI 证据，再把它们用于跨版本差异分析；不让未来适配器架构打断正在进行的功能开发。
- 普通 Agent 客户端使用验收与“兼容层生成工具被 Agent 调用”是不同工作；本 RFC 不提前宣布任何客户端测试通过。

## 2. 架构：独立启动，再由已验证适配器连接 DM

~~~text
任意支持工具调用的 Agent（Codex / DeepSeek 驱动的 Agent / 其它 Agent）
    |
    v
gms-compat-generator：独立 CLI + 可选 MCP 封装
    |
    +--> 本地只读采集：构建/模块指纹、版本、架构、PE 导出表
    |
    +--> 离线差异：与已验证 ABI 清单匹配、标记不确定项
    |
    +--> 候选生成：版本专用 AdapterProfile / C++ shim / 验收用例
    |
    +--> 离线编译和模拟：不加载真实 DM，不触碰已装插件
    |
    +--> 人工授权的独立 GMS 合成数据资格验证
    |
    v
按构建、模块和操作保存的已验证能力记录
    |
    v
既有 mcp-dm Node MCP / 请求状态 / 结果管理
    |
    v
仅选择已验证的 GMS Native Adapter
    |
    v
DigitalMicrograph 内置原生接口
~~~

**关键：兼容工具不能依赖目标版本的 mcp-dm 原生插件已经工作。** 否则不兼容版本无法启动工具来修复自身。CLI 在 DM 外部运行，MCP 只是同一套可控操作的可选外壳。

生成的候选代码不能自动被当前运行的 DM 载入，也不能直接替换正在加载的插件 DLL。安装、实机验收、启用和社区合并是分开的步骤。

## 3. 复用哪些现有“指针与 ABI 证据”

当前仓库不是一份可以直接对所有版本使用的函数指针表；已有的是**固定构建上的已知函数入口、调用约定、对象布局及部分静态候选证据**。这些很适合作为差分基线，但不能原样套到新构建。

| 已有来源 | 可以复用的内容 | 使用边界 |
|---|---|---|
| experiments/native-bridge/mvp/dm_adapter.cpp | 已验证构建的模块校验、导出解析、固定 RVA、typed 函数指针、图像引用和字符串适配 | 只能作为 3.53 基线；不能直接将旧地址用于其它 DLL |
| experiments/native-bridge/ABI_NOTES.md | FindByID、ref_ptr、MSVC 字符串、标定、Show 文档/窗口引用等证据及已知风险 | 每条证据必须关联构建与验证级别 |
| experiments/native-bridge/mvp/crop_contract.hpp | 裁剪几何、半开坐标、标定与独立输出契约 | 属于对外语义，通常比内部地址更稳定；新版本仍需数值验收 |
| feature/native-bridge-mvp 的 show_contract.hpp | 文档 holder POD、引用和 Window 偏移等固定构建布局 | 属于高风险布局，不是跨版本常量 |
| feature/native-bridge-mvp 的 candidate_calls.hpp/.cpp 与 BATCH_CANDIDATES.md | 函数签名候选、精确导出名、unary/binary/reduction 形状、合成所有权测试 | **仍是 synthetic candidates**，不能当成已验证 DM 生产绑定 |
| feature/native-bridge-mvp 的 SUMMARY_ACCEPTANCE.md、TRIAL_ACCEPTANCE.md 与独立 oracles | 请求前记录、实际宿主身份、数值/标定/引用生命周期验收方法 | 只可复用方法和新建合成用例；旧构建 PASS 不会自动转移 |

上述 feature 文件目前不属于 main 已集成的原生能力；兼容工具实现应在当前大任务完成、分支状态重新核对后再对接，**不要为了写这个 RFC 把 feature 整体合并进 main**。

对于用户口中的“指针文件”，第一阶段要做的是把**已有函数指针声明、对象布局及 RVA/导出出处**整理成可追溯的机器可读 ABI 证据清单；不是制造一张能够绕过版本检查的万能地址列表。

## 4. Agent 可以调用哪些工具

以独立 CLI 为基础，并按需暴露同等语义的 MCP 接口。下述工具名只是未来设计草案，**本 PR 不提供它们**。

| 候选操作 | 输入 | 输出及安全边界 |
|---|---|---|
| inspect_installation | 用户明确授权的安装位置或选定的文件集合 | 本机版本、架构、模块清单、指纹；只读且不启动 DM |
| extract_abi_evidence | 选定 PE 模块及有限导出列表 | 符号、依赖、可静态确认的调用线索与证据来源 |
| compare_builds | 已验证基线清单 + 目标构建清单 | 匹配、变化、缺失、歧义与待核对 ABI 项 |
| propose_adapter | 版本差异报告 + 已验证的适配模板 | 默认禁用的候选 profile、受限 C++ 源码补丁及测试草案 |
| validate_offline | 候选代码 + 固定编译/测试配方 | 编译、接口检查、合成契约测试及机器可读报告 |
| prepare_live_acceptance | 明确操作、构建和用户授权 | 独立合成图验收步骤；**不自行安装或调用未知 ABI** |
| import_evidence | 真实测试产生的独立原始记录 | 校验构建/会话/请求/实验范围的一致性，报告证据不足 |
| propose_qualification | 已通过的证据 + 审查记录 | 生成待人工审核的兼容能力变更；不自动启用或合并 |

模型可以做调查、定位候选、解释歧义和建议修订；确定性的解析器、模式校验器和构建测试负责验证可机器判定的事实。**模型自报的置信度绝不是启用许可证。**

## 5. 版本专用 AdapterProfile：按操作声明能力

兼容信息应绑定**完整目标构建及必要模块指纹**，不只绑定“3.53”“3.6”这样的产品版本号。不同版本可能需要不同的插件 DLL；对外 MCP 接口保持稳定即可。

建议清单包括：

- 目标平台、构建、插件加载接口与必需的 exe/DLL SHA-256；
- 分模块导出符号或经单独验证的非导出入口；
- typed ABI：参数、隐式返回缓冲（sret）、返回类型、结构布局与对齐；
- 引用计数、借用/拥有关系、字符串分配与配对释放；
- 线程亲和、回调调度、错误与停止后清理契约；
- 各操作支持的 dtype、shape、预算、标定和输出语义；
- 每条记录的静态证据、离线测试及真实宿主验收状态。

例如，**非真实数据的结构示意**：

~~~json
{
  "schema_version": 1,
  "profile_id": "gms-build-example-not-qualified",
  "target": {
    "platform": "windows-x64",
    "version": "EXAMPLE",
    "module_sha256": {
      "DigitalMicrograph.exe": "UNVERIFIED_PLACEHOLDER",
      "GMSImage.dll": "UNVERIFIED_PLACEHOLDER"
    }
  },
  "state": "CANDIDATE_DISABLED",
  "operations": {
    "native_summary": {
      "abi_status": "STATIC_MATCH_ONLY",
      "scientific_status": "NOT_TESTED",
      "enabled": false
    },
    "native_show": {
      "abi_status": "REVIEW_REQUIRED",
      "scientific_status": "NOT_TESTED",
      "enabled": false
    }
  }
}
~~~

示例中的字段及占位符并非当前产品已经实现的配置格式，不可复制为受信任适配器。候选代码可以由工具生成，但运行时只能从经审查的**静态能力白名单**选择操作；不能接收 Agent 传来的任意 DLL、任意地址或函数签名并直接执行。

为避免“一项可选算子缺失使所有功能不可用”，最终可按模块/操作设置能力门禁；但必须先保持现有完整构建门禁的默认安全性，不能在没有新证据时放宽它。

## 6. 需要逐构建重新分析的 ABI 风险清单

从高风险到常规核对：

1. **插件宿主接口：** 加载、初始化、宿主线程、消息回调、STOP/退出与部分初始化失败清理。
2. **图像引用所有权：** FindByID/FindByIndex、ref_ptr 的返回/复制、计数位置、增减引用、最终销毁。错误释放可能导致宿主崩溃。
3. **字符串及分配器：** GetUnicodeName/标定单位、MSVC 字符串 POD、分配/释放路径和 Unicode 边界；绝不能靠“显示正常”证明释放安全。
4. **非导出文档接口：** Show 所需的函数位置、this/sret 形式、Document/Window holder 与引用偏移。重新编译可能改变 RVA。
5. **数值和图像算子：** 原生统计、裁剪、FFT、滤波、算术；分别检查输入 dtype、维度、complex/packed 布局、标定和返回对象。
6. **文件/预览接口：** 原生打开、科学保存、no-overwrite、输出重开、数据访问/锁及有界预览，不能用显示 PNG 冒充科学数据。

不同构建中即便导出函数名称一致，也可能更改对象布局或语义；函数相似度、相同汇编片段和新的 RVA 只提供**待验证线索**。

## 7. 资格状态与启用门禁

| 状态 | 定义 | 可用于未知目标 GMS 的实际处理？ |
|---|---|---|
| UNSUPPORTED | 没有匹配的构建适配器，或前置身份检查失败 | 否 |
| STATIC_CANDIDATE | 找到了可能对应的符号/代码和调用形状 | 否 |
| REVIEW_REQUIRED | 函数签名、对象布局、生命周期或其它关键证据不足 | 否 |
| OFFLINE_PASS | 候选编译和合成契约测试通过 | 否 |
| LIVE_PASS_LIMITED | 在明确的真实构建及小型合成样品上通过指定测试 | 仅限所验证范围、经授权使用 |
| QUALIFIED | 实机结果、失败路径、清理及审查证明达到该操作的发布门槛 | 仅对应精确构建和声明的操作、类型及限制 |

状态按**构建 × 操作 × 数据类型/结果布局**登记，不能把一次 GetMean 通过扩展为“整版 GMS 兼容”。

机器可以检查记录是否齐备、哈希是否匹配、测试是否通过；但**不能由 Agent 自己为自己的候选签发生产级资格**。高风险内存与文档操作尤其需要独立审查。即使通过资格验证，也不宣称能够隔离所有厂商原生访问冲突。

任何版本或必要模块不匹配、ABI 无法确认、验收记录缺失或新调用路径出现异常时，应 fail closed。不能静默回退旧的未知 ABI；默认 v0.6 Python/TCP 是否可用是单独的、显式的后端选择。

## 8. 最小开发里程碑（等当前原生功能大任务后再启动）

### Phase 0 — 清点可复用基线

冻结一个已验证的 3.53 适配器清单，整理来源映射：确切文件/符号、POD 偏移、引用所有权、函数出入参、检验状态。现有功能正在扩展，**以那时最新的代码与实际验收为准**，不以本 RFC 的旧文件清单为永恒事实。

### Phase 1 — 本地只读版本扫描

实现独立 CLI：输入授权目录，输出版本、PE 模块和 SHA-256、导出表及依赖的结构化报告。支持敏感路径脱敏；不用 DM 插件即可运行。自动化测试应使用自制小型 PE 合成文件，不要求厂商软件或许可证。

### Phase 2 — ABI 差异与候选生成

针对两个明确构建比较导出和候选函数，生成变化清单、风险等级、引用出处及候选 profile/shim。允许 Agent 协助解释差异，但**遇到指针所有权、隐藏 sret、字符串分配或非导出 RVA 不确定时，强制人工/独立验证**。

### Phase 3 — 离线构建与模拟

生成独立工作目录中的候选源和测试，复用已有 C++ POD、synthetic callbacks 与协议/状态测试。验证错误参数不进入厂商调用路径；生成器不得写入用户原有 GMS 安装或已加载 DLL。

### Phase 4 — 第二个真实构建的最小验证

在获得明确授权的空闲测试宿主上，先验证插件加载与状态，再验证图像 ID/尺寸/dtype/标定、统计、裁剪/对象释放，最后验证 Show、FFT 和保存。每个新接口使用独立数值和生命周期 oracle；发生访问冲突应停止该路径，保留失败证据，而不是反复盲试。

### Phase 5 — 社区贡献闭环

从候选生成可审查的 PR：版本指纹/能力矩阵、专用适配器、合成测试、实机证据摘要和可复现的用户验收指南。审核后才逐项开放能力。**不允许 Agent 自动合并、安装未验证 DLL、关闭或重启用户 DM。**

## 9. 首版验收标准

- 无法运行 mcp-dm native 的新构建仍能独立运行兼容分析 CLI，消除循环依赖。
- 用户授权的两个 PE 构建可以生成可复现的版本差异及来源追踪。
- 生成器能够输出**默认不可执行/禁用**的候选 profile 和类型明确的 shim，并完成纯离线测试。
- 引用计数、字符串 ABI、非导出 Show 等高风险差异必定要求独立验证，不由模型打分放行。
- 对不认识的 GMS 构建，当前原生功能继续安全拒绝；已验证 3.53 能力、默认 v0.6、MCP 语义和结果查询保持兼容。
- 第一个新构建适配实测时，能明确区分：生成成功、离线通过、真实宿主通过、按操作发布资格。
- 生成器和测试不把用户安装的厂商二进制、反编译实现、实验数据或机器私有路径直接推送到公共仓库。

## 10. 安全与开放协作

该工具处理的是用户有权分析的本地安装。应遵守适用许可和法律，不以规避许可、保护机制、采集/硬件控制或绕过安全检查为目标。不下载、替换或传播厂商 DLL。建议由本地分析程序处理原始文件，在线 AI 只接收用户明确允许共享的必要结构化证据；默认不上传二进制、机器代码、完整反编译内容或私有路径。

**本 RFC 的边界：只提案，不建立工具、不新增依赖、不运行 DLL、不改变任何现有的构建门禁和对外 MCP。**

---

### English summary

**Vision:** Let agents use DigitalMicrograph through mcp-dm, and let agents assist in adapting mcp-dm to additional GMS builds.

**Proposed approach:** An independent CLI/MCP compatibility workbench performs read-only local inventory, ABI diffing, provenance-tracked candidate generation, offline tests, and user-authorized live qualification. A generated adapter is disabled until independently reviewed and validated for a precise binary build and operation scope. The stable MCP protocol is shared across version-specific adapters.

**Status:** Future RFC only. No automatic compatibility, new supported GMS version, binary patching, SDK replacement guarantee, or executable compatibility generator is delivered by this document.
