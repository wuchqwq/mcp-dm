# Codex 接续：先证明现成客户端能连续完成一个显微任务

> 2026-10-27 所有者安排：先收尾 PR #30–#34，随后在 Codex 中继续；DSH 暂缓。本文是下一阶段任务，不是 Codex、真实 DM 或模型视觉已经验收通过的声明。执行前读取最新 main 和 PR 状态；不要重复合并已整合的祖先分支。

## 已有基础，不要重写

本次候选基线为 PR #34 `3d95edb0236e839180d20a9665bba3c7bc127227`，继承 #33 → #32 → #31 → #30：

- ToolRegistry 与显式 provider 组装；旧 MCP 工具保持直接调用。
- image/structure 共用单进程 ExecutionCoordinator；科学结果日志仍由原 provider 负责。
- 可选 AnalysisContext：不可变引用、CAS 修订、过时依赖与正常进程重启后的查询。
- `skills/scientific-agent/` 中的 `microscopy-router`、`microscopy-observe-revise`、`crystallography-compare` 及 schema 示例检查。
- 已有本地图像 panel、TIFF/FFT/标定/测量/结构工具；不要另建聊天软件或图像状态库。

查看 `docs/ANALYSIS_CONTEXT.md`、`docs/EXECUTION_COORDINATOR.md`、`README.agent.md`。运行记录见 PR 收尾评论与 GitHub Actions 的 source-bound summary/log artifacts。历史测试失败不因新一次成功被擦除；合成回归不等于真实客户端或宿主验收。

## 第一项交付：Codex 最小可用接入，不先打包商城插件

从整合后的 main 开新功能分支；先检查工作树、现有 Codex 配置和已安装版本，保留本地未提交工作与其他 MCP/Skills。通过本机 Codex 的实际帮助/配置契约核实注册方式，不把网页上的新插件格式假定为所有已安装客户端都支持。

复用 `server.mjs` 和 `setup/register_codex.ps1`。现有注册脚本主要面向默认 Python bridge，不要声称它已经配置了独立 images/structures/context。按实际需要增加明确的模式/路径参数或小型配置生成器，保留旧参数行为、同名拒绝、预检查和不覆盖策略。后端必须显式选择，不能在 DM 失败后改用独立计算来掩盖失败。

先测试无需 GMS 的独立科学模式：

- `DM_MCP_BACKEND=images`
- `DM_IMAGE_WORKSPACE`、`DM_IMAGE_PYTHON`：独立输出目录和外部 Python
- 需要结构对照时才加 `DM_STRUCTURE_WORKSPACE`、`DM_STRUCTURE_PYTHON`
- 连续分析时加 `DM_ANALYSIS_CONTEXT_WORKSPACE`
- 诊断执行等待时可加 `DM_MCP_EXECUTION_OBSERVABILITY=1`

目录、解释器和配置由开发 Agent 解析并检查，不让研究者手写 JSON、内部 ID 或依赖哈希。保持任意脚本执行门禁关闭。依赖只能安装到明确授权的独立环境，不修改 GMS 管理的 Python。

共享现有 Skills 源文件；按实际客户端发现规则显式安装或引用，并验证路由 Skill 的相对文档链接仍可解析。不得覆盖已有同名 Skill，也不因 MCP 注册成功就声称 Skill 已被加载。第一版不制作第二套 Skills，不引入模型代理服务或多 Agent 管理。

## 验收顺序与证据

### A. 真实 Codex + 合成 TIFF，不启动 DM

固定一个小型、公开可提交的非对称合成样例，含独立已知频率/尺度依据。让真实 Codex 完成：打开指定帧 → 实际查看返回图像 → 明确 ROI → 外部 FFT → 少量测量/标注 → 用户更改显示或一个点/尺度 → 只更新受影响结果 → 新目录导出。

随后重新建立客户端连接，用已保存的命名分析继续。核对未变的复数 FFT 和源数组哈希，不重算、不重复创建科学结果。故意停止一次等待后查询原 request_id；不要把断连、超时或 MCP 进程退出说成计算已撤销。

分别记录：工具可发现、调用实际成功、模型实际收到了图像、用户实际看到了图像。PNG 路径、MCP image block 和窗口可见不是同一条验收证据。安装了 Skills 也不证明模型使用了它；记录实际触发/阅读和调用轨迹。

当前 Coordinator 不提供跨 MCP 进程全局科学写锁。首轮只让一个客户端执行一个科学工作区的写任务；不要借此测试未经设计的跨客户端并发写。

### B. 同一客户端 + 已授权的本地 DM

仅在 A 通过且有明确本机操作授权后，读取真实后端身份、明确图像与标定，以合成工作图或只读实验副本完成一次接力。默认 Python 与实验 Native 分开记录。

Native 仍只接受原有精确构建指纹、操作/dtype/尺寸/单位和会话资格；没有新增 ABI 资格。真实 DM、模型看图、用户操作和数值读回分别记录。不要强退 DM、热替换已加载 DLL、覆盖原图、扩大导入范围或自动重放未知结果。

### C. 用实际阻塞决定下一项改动

先完成观察/FFT/修订的最短路径；CIF/取向/diffsims 对照随后按需要接入，不要求每次看图都走完整判相流程。暂不设计新的科研 Agent Runtime、任务图、通用 UI、远程 DM 服务或科学算法。

## 提交与分工

交付一个小型 Codex 接入 PR，写明使用的客户端版本/模式、实际执行步骤、手工步骤减少、通过/失败/未测范围和唯一下一阻塞点。配置/安装测试与真实客户端测试分开。缺本机 DM 时可以先完成 A，但必须把 B 标为 NOT_TESTED。

DSH 本轮不开发、不安装、不创建适配目录。GMS 兼容性 PR #27 与 Draft #3 继续独立，不改其分支、证据或资格。下一阶段功能不要自行合并 main。
