# 可修订的当前分析引用

AnalysisContext 帮 Agent 记住“现在看哪一版”，不规定下一项科学分析。
可以从 TIFF 帧、已有 FFT、已处理的捕获或已有模拟开始，不要求重跑原始流程。
旧 `image_*`／`structure_*`／`dm_*` 工具仍可直接使用，不要求上下文或 Skills。

## 启用与归属

在已有独立图像／结构工具配置上，显式增加 `DM_ANALYSIS_CONTEXT_WORKSPACE`，
值为专用绝对目录。Agent 负责配置路径、内部 ID 和工具参数，研究者描述任务与更正即可。
可选 `DM_MCP_EXECUTION_OBSERVABILITY=1` 提供执行观察；两者互相不强制依赖。
`DM_MCP_DISABLED_MODULES=analysis-context` 可在下次组装时禁用上下文，原科学工具保持可用。
不会自动安装任何 Skill、不修改 GMS Python，也不切换计算后端。

| 文件 | 职责／未来归属 |
| --- | --- |
| `lib/runtime/analysis_context.mjs` | 只管理小型引用、依赖、CAS 与原上下文提交恢复；未来科研 Agent Runtime |
| `lib/runtime/file_context_store.mjs` | 显式本地存储端口，版本链和原子独占发布；未来科研 Agent 存储适配器 |
| `lib/analysis_context_bindings.mjs` | 通过已验证科学 provider 元数据绑定真实网格、标定、producer、结构与测量身份；过渡期科学适配器 |
| `lib/tools/analysis_context_module.mjs` | 可选服务端能力登记和参数适配；未来迁移前保留 MCP 兼容入口 |
| `skills/scientific-agent/` | 按需使用的科研 Agent 技能源文件；未来 Agent 仓库；本轮不自动安装 |

通用 Runtime 不读取 DM 环境变量，不导入 GMS、server 或科学 worker；可以单独复制导入。
未来新 Agent 必须使用公开 MCP／版本化交接端口，不能跨仓绑定 DM 私有实现。
当前没有物理迁仓，mcp-dm 不依赖新 Agent。

## 正式工具

| 工具 | 用法 |
| --- | --- |
| `analysis_create` | 提交前选定 `analysis_id`、`request_id`，说明 `reason`，创建空的命名分析 |
| `analysis_read` | 按 `analysis_id` 读取当前；或显式 `revision` 复查历史；或 `request_id` 恢复原上下文提交，后二者互斥 |
| `analysis_update` | 使用工作开始前读到的 `expected_revision`，保存 `request_id`、`reason` 和明确的 `selections` |
| `analysis_proposal` | 读取 CAS 失败时另存的历史提议，不应用它、不重做科学计算 |

selections 的单值引用为 `{provider:"image"或"structure", object_id:已返回的ID}`。
点位和测量为引用数组，其余为单引用；`null` 撤下当前选择。
Agent 不需要计算依赖哈希或复制工作区路径，适配器负责解析并验证这些信息。
点位引用来自已保存测量的坐标锚点，不把 PNG 箭头位置变成新的科学点位。

先支持这些角色：`experiment`、`fft`、`display`、`calibration`、`center`、`points`、
`measurements`、`reference`、`orientation`、`simulation`、`registration`、`comparison`。
已保存对象的真实类型必须允许对应角色；不能把图像预览当模拟强度或结构原子。

## 修订时哪些结果受影响

- 只换显示对象，不使 FFT、点位或测量失效。
- 修订尺度或中心，原 FFT 和点位锚点保留；测量、配准、比较及旧物理显示标为 stale。
- 修订点位，需要相应新测量、配准与比较；不重算未变的复数 FFT。
- 更换原实验网格／帧／科学 ROI／FFT producer，不能沿用旧点位或旧几何。
- 更换参考结构或科学取向，使依赖的模拟、配准与比较过时。
- 已有比较数值不匹配候选结构时，可以作为当前有效证据保留；active 不等于物相确认。

尺度／中心应选择对应新 wrapper 的 calibration／center 角色，不把原实验或原 FFT
替换为显示修改来绕开来源检查。中心修订会产生新标定版本；只选择 center 时，
工具把已选 calibration 同步到该验证过的新 wrapper。反向只改尺度时，已选 center
也跟随该同一记录，保留实际 DC。显式给出两者时仍严格检查，不默默调和矛盾。
固定数学 FFT 的 DC 仍不能移动。

真正重算测量继续调用现有 `image_remeasure`；配准与比较继续调用现有
`structure_register`／`structure_compare`。上下文只接收保存完毕的新引用，
不实现第二套算法、不暗中修正尺度或为拟合增加镜像／伸缩。
适配器会检查真实保存的 grid、标定修订、点位、结构／取向、模拟和测量路径；
仅替换依赖哈希不能把旧测量、别源 FFT 或旧比较重新标成有效。

## 晚到结果、取消与恢复

工作开始前读当前 revision；各 provider 完成后先保存自己的结果，再尝试推进引用。
若期间用户更新了当前选择，旧 expected_revision 的提交返回 `state:historical`，
新结果保存在历史提议中，当前分析不变。不同 provider 的结果不能整体回滚，
CAS 失败也不授权重新执行科学操作。

上下文写入的 `request_id` 和参数哈希只存在于已有版本／历史提议中，
不建第二份科学任务日志。相同 ID 同参数返回原上下文结果，改参数拒绝。
取消或丢响应后，`analysis_read` 查询原 context request_id；
科学结果仍用原 `image_result`／`structure_result`，执行观察用 `execution_*`。
查询旧请求返回旧版本，不能冒充当前选择或新捕获。

## 存储与验证边界

每版只含 scoped ref、manifest 哈希、小型网格／标定／点位元数据及依赖状态。
不复制 NPY、像素、复数频谱、原子数组或模拟强度，不取得科学日志权威。
引用绑定 provider、显式 workspace、journal-session 和 object ID。
删除或替换原工作区不能得到无条件恢复保证。

版本为不可变文件、带父哈希链；先写完整临时文件并 fsync，再独占发布下一版本。
并发写同一 expected_revision 只允许一个胜者；部分临时文件不会成为成功版本。
损坏、缺失版本或超预算明确拒绝，不自动修补。追加前检查累计预算，避免写成不可读历史。
这是本地文件系统上的正常进程关闭／重开恢复，不承诺任意网络文件系统或断电持久性。

上下文读取显示保留的引用和依赖状态，不代表重新检查活体 DM。
实际使用引用时，原 provider 仍执行自己的对象、文件、标定与资格检查。
本轮验收区分纯状态／存储、传输替身、实际 stdio 科学 worker、Skills 契约验证；
不把它们当成真实 DM、浏览器或普通模型客户端验收。

## Skills

短入口 `microscopy-router` 按任务选择观察／修订或晶体学对照指导，
`microscopy-observe-revise` 说明像素域、显示、尺度与当前引用的接续，
`crystallography-compare` 说明结构、取向、运动学模拟及独立验证反射。
它们提供决策依据，不固定执行顺序，不把 FCC/BCC/HCP 或候选结构当成唯一入口。
示例工具名和参数通过实际定义校验；这不是模型 A/B 效果或自动判相证明。
