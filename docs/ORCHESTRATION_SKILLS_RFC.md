# RFC：mcp-dm 运行时重构——确定性调度层 + 渐进式 Skills

> 状态：设计提案，非已实现功能。提出日期：2026-10-27。基线 `main@dc3e58448c82559d94fca2c22b6bbdeb9f68b5d8`。这项方向由项目所有者明确批准；优先于 `docs/NEXT_ANALYSIS_DEVELOPMENT.md` 中“暂缓新通用调度层”的旧安排。PR #27 的 GMS 兼容性研究是平行分支，不在本轮改造范围内。

## 一、为什么进行真正的架构调整

mcp-dm 的核心定位从“DM 的操作接口”发展为“让通用 Agent 使用专业显微与晶体学工具，并与人在 DM 中接力”。科学内核与原生 ABI 已有实质成果，但随着独立 TIFF、CIF/XYZ、diffsims、标定、中心修订、显示窗口和数值回传加入，接线方式逐渐失衡：

- `server.mjs` 同时负责 MCP 协议、后端开关、工具目录、工具校验与 `callTool` 的分支分派。每增加一组能力都会进一步修改总入口。
- `lib/image_workspace.mjs`、`lib/structure_workspace.mjs` 各自实现队列、进程启动、截止时间、取消后恢复及 PNG 返回；这些是执行机制，不应与科学能力捆绑。
- 实验对象、取向、测量与标定已经有不可变证据，但“我现在分析的哪一版？”仍需 Agent 跨工具手工维护，旧数据容易误用。
- 当前只有 `skills/dm-2d-analysis/SKILL.md` 这一早期专业 Skill，其他使用经验散落在越来越长的 Agent/README 文档中。

**设计目标是一次真正的模块化重构，而不是只多写几份 Skill。** 将“怎样使用科研工具”放进可选 Skills；将“如何可靠选择/执行/恢复工具与保持当前科学状态”放进确定性的调度层；将“具体科学计算和 DM 原生调用”留在原有适配器。

## 二、目标结构（控制面 / 科学执行面）

```text
Researcher ⇄ Host Agent (唯一的推理/决策者)
                 │  按需加载 Skill
                 ▼
   Skill Pack：microscopy-router / observe / diffraction /
               revision / dm-handoff
                 │  明确的工具意图、可追溯科学输入
                 ▼
 MCP Server（仅 MCP 协议／兼容工具名）
                 │
     Orchestration Runtime（确定性控制面）
     ├─ ToolRegistry + CapabilityResolver
     ├─ Dispatch / ExecutionGraph + ResourceLimits
     ├─ RequestJournal / Status / Recovery
     ├─ AnalysisContext + Revision/Dependency checks
     └─ DomainContracts / Provenance / StructuredFailure
                 │
           明确选择适配器
       ┌─────────┼──────────┬───────────┐
       ▼         ▼          ▼           ▼
    DM Python  DM Native  TIFF/Image  ASE/Diffraction
       │         │          │           │
    GMS host  qualified   independent  independent
              C++ ABI     Python       Python
```

*调度层不能有一个隐藏的“自动判断材料物相”规划器；LLM 仍根据实验问题选择下一项操作。调度层负责确定性执行、安全边界和科学上下文。**不建设多 Agent 管理器**，不负责启动/分配/审查子代理；这与 pstack 的大型软件开发 `orch` 不同。*

## 三、稳定接口与科学对象边界

### 1. ToolRegistry / CapabilityResolver

每组工具提供明确登记的模块描述：现有 MCP 名称与输入 schema、handler、作用的科学对象类型、输入和输出的坐标域、是否有副作用、是否需要 `request_id`、并发/资源范围、后端身份、可选安装条件及运行时能力门禁。

- 保留现有 `dm_*`、`image_*`、`structure_*` 名称及兼容 schema；先用注册器代替 `server.mjs` 中的散落分支，不要求研究者迁移全部旧调用。
- 启动时拒绝重复命名、非法 schema、缺失 handler 和未显式启用的适配器。新模块只需注册其入口/能力，不修改核心 `callTool` 的分支树。
- 可用性以实际环境/宿主/原生版本与每操作资格为准；目录里有某工具**不等于**已经支持任意 dtype、构建或数据域。
- 未显式选择后端绝不自动 DM→Python fallback；只读预览、科学数值和写回效果分别标注。

### 2. AnalysisContext（轻量但是真实的当前任务状态）

在不可变对象之上持久保存小型当前工作上下文：`analysis_id`、活动捕获/帧/ROI/频谱、有效标定及中心版本、峰位/测量集合、参考结构/取向、模拟和候选假设、待处理结果。只保存引用和修订关系，**不复制图像数组，也不创建第二套科学事实数据库**。

- 显式的“继续当前分析”可解析用户在此分析中选中的版本；“历史复核”仍固定原证据。多个分析可以并存，不猜全局最新 DM 窗口。
- 活动上下文更新必须带旧版本/预期修订号，使用原子提交/CAS 防止后台迟到的旧结果覆盖用户的新选择。
- 修订依赖有确定性失效规则：仅改 gamma/视图不使测量失效；改尺度使相应物理测量/对照过时但不重新计算同一复数 FFT；改中心仅更新中心参考端点；新捕获/新 FFT producer/新科学 ROI 不允许沿用旧点位身份。
- 每次跨工具组合都校验既有科学网格、坐标域、标定与来源；Skill 的文字指导不能替代这一层硬校验。

### 3. Dispatch / ExecutionGraph / RequestJournal

调度层既支持现有单一工具直调，也允许 Agent 提交**显式且有限的任务步骤/依赖图**；Agent 可以下一轮增加、取消或修改步骤，非固定流水线。

- 一个步骤的输入是明确的对象引用和参数，输出为新的不可变科学对象/显示对象/DM 新工作图及可查询执行回执。关联 `request_id`、参数哈希、来源版本。
- 对 DM 宿主和已有原生对象操作施加串行/资源保护；外部相互独立的只读分析可在有界并发下执行。不为“并行”擅自引入多 Agent。
- 统一阶段状态 `queued → starting → validating → running → persisting → completed/failed/unknown`（具体命名可优化）。取消等待/超时不代表副作用已撤销；原 ID 查询/恢复先于任何重试。
- 在原有强约束 API 上复用请求日志与能力门禁。不要在调度层重复实现 FFT、diffsims、DM ABI、数值导入或文件格式解析。
- 把科学不一致、输入非法、能力不支持、状态过期、执行/传输超时分成结构化失败类别，并返回可行动的诊断；不存在“失败后随便换算/切后端试试”。

### 4. DomainContracts（科学契约）

建议统一类型/元数据协议而非强行统一内部 NumPy/GMS 对象：

`ScientificArrayRef`、`ImageViewRef`、`CalibrationRevisionRef`、`CenterRevisionRef`、`MeasurementRef`、`StructureRef`、`OrientationRef`、`SimulationRef`、`ComparisonRef`、`OperationReceipt`。

必须保留直接/倒易空间、`cycles` 与 `radians`、单位与轴序、符号尺度、source/frame/ROI/FFT producer、模拟近似、用户/Agent 推断与实验确认等区分。外部数据仅可通过明确且验证过的适配/交接进入其他后端。

## 四、Skill 包：专业知识按需加载

以现有 `skills/dm-2d-analysis` 为起点，形成以下可选技能。最初可只迁移 4 个，避免堆重复文档：

1. `microscopy-router`：短入口。识别用户目标、已知数据/能力和需要加载的技能；允许直接走任一原有 MCP 工具。
2. `microscopy-observe`：DM/TIFF 的观察、取帧/ROI、显示与 FFT、未知标尺下的像素分析。
3. `diffraction-reasoning`：CIF/XYZ、晶向晶面、运动学模拟、实验-理论几何比较、多候选、异常/未匹配证据。
4. `analysis-revision`：中心、标尺、点位、实验上下文纠正后的依赖更新及历史/当前区分。
5. `dm-handoff`：DM 当前半成品捕获、有界写回、再次观察与资格/原图保护。

原则：Skill 提供选择策略、限制解释、失败后的合理下一步，**不是每次强制运行的固定步骤**。科研数学、单位/坐标变换和副作用保护必须留在程序契约里。Skill 可通过兼容客户端安装/发现；未安装时现有 MCP 继续运行。

为 Skill 增加机器检查：工具名称是否存在、示例参数能否通过当前 schema、所引支持条件是否有效。对真实用户语言设置基准任务，在同一输入和模型下比较有无 Skill 时误调用、无谓重算、重复询问和完成率，不以“Skill 数量”衡量效果。

## 五、迁移顺序（目标明确，纵向实施，完成后删旧接线）

- **PR A：架构与兼容契约。** 固定现有默认/原生/独立模式的 `tools/list`、关键错误语义、只读数据路径和禁用能力。提交一条可实际运行的跨工具合成闭环。明确旧文档中“不建调度层”已由所有者决策修订。
- **PR B：ToolRegistry 与模块式适配器登记。** 把散落工具目录、条件判断、分派入口移出 `server.mjs`；以可配置、显式登记的能力组装成完整目录。保留旧工具名与调用契约。用增/删一个可选模块的测试证明不再修改总分派函数。
- **PR C：执行协调与状态/恢复。** 提取独立 Python worker 的共通队列/截止时间/返回校验逻辑，接入统一的 `OperationReceipt`、阶段诊断和资源键；保留 native 现有独立会话/原始请求恢复语义，不作危险的表面统一。先迁一条最常用路径跑通。普通工具直调不能变慢到不可用。
- **PR D：AnalysisContext 与依赖管理。** 用不可变引用和 CAS 实现“继续当前分析”；打通显示/尺度/中心/点位/新捕获的更新规则，实际从一次更正继续完成结构对照。允许没有上下文的原有工具直调，不能强制先创建 session。
- **PR E：专业 Skills + 验证。** 迁移现有冗长提示到按需加载技能，做自动校验与真实任务 A/B 评测；删去重复说明和废弃的临时分派代码，维护清晰的模块边界。

这些是**架构迁移的结果边界**，不是要求 Codex 为每个阶段先写一堆抽象类。可以调整 PR 分割，但每个交付必须包含一条实际用户路径及回归证据，禁止仅新增空壳类或三套并存的旧/新真相状态。旧接口迁入后要删掉多余内部实现，而不是永久双轨。

## 六、端到端验收（“新增和移除功能变容易”必须可证明）

1. 在原有默认 v0.6、原生实验模式及独立图像/结构模式下，工具名称与参数兼容；已验证数值/错误及原生资格不倒退。
2. 仅通过登记/取消一个可选工具模块，工具目录和执行路径能变化，无需给总入口添加新的 `if(name...)`；模块缺失时其他模块仍能正常工作。
3. TIFF/DM 已捕获的图 → ROI/FFT → 标定/中心 → 多点测量 → CIF/UVW → diffsims → 配准比较；中途更正尺度或峰位，正确地只更新依赖，并保留原始频谱和旧证据。
4. 模拟超时/取消/晚返回，原请求查询有效，旧结果不能覆盖新分析版本；不重复执行有副作用的 DM 数值导入。
5. 原图、私有数据与源代码隔离；普通 XYZ 缺晶胞仍可观察；未知标尺仍可像素域操作；不能默认把候选假设升级为确认。
6. 端到端执行时增加的开销有基准，客户端未安装任何 Skill 仍可以直调全部已合格工具。
7. 真实 DM／浏览器／实验数据验收分别记录，离线 CI 不冒充真实宿主通过。

## 七、明确不做

- **不做多 Agent 管理**：不设计子代理池、任务委派策略、多模型投票、PR 项目管理或常驻多 Agent 运行服务。
- 不建新科研 GUI/聊天产品、不开发硬件控制、不重写科学计算/私有 ABI、不通过脚本执行绕过资格、不让单一 Skill 成为必经的判断流水线。
- 不把 orchestrator 或 Skill 本身当作数值正确性来源，也不让任意第三方目录通过自动发现获得执行权限。
- PR #27 的 GMS ABI 兼容性 CLI 继续独立评审；通过 registry 声明可用的未来资格，但本次不改其实现。

## 八、给 Codex 的起步指令

从 `main` 核对本 RFC、`AGENTS.md`、现有工具目录及测试；若 RFC 尚未合并，明确以该 RFC PR 为设计基线，在单独实现分支工作。先完成 **PR A/B 的第一个端到端纵向切片**：建立注册器和能力清单，迁移独立 image 与 structure 两组，再接通现有 DM 后端，确保 `tools/list` 和原有调用可完全兼容。用一条跨工具合成任务证明通过注册器运行；新增/移除一个测试工具组不能再修改 `server.mjs` 分派条件。顺便建立新运行时的状态/事件接口设计，但不要先造没有消费方的大调度数据库。写出后续 C/D/E 的可执行切片并开 PR，不自动合并。任何未验证 DM/Windows 范围都保持 HOLD。
