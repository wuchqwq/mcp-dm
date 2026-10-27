# Codex 独立显微图像模式

这条入口复用本仓库的 `server.mjs`、`image_*`、Image Panel 和可选
AnalysisContext，不需要 DigitalMicrograph。默认 Python bridge 注册方式保留。
请让开发 Agent 解析本机路径并执行；研究者不必填写对象 ID 或 JSON。

## 一次显式启用

先准备独立 Python >=3.10 环境，按 `requirements-images.txt` 安装依赖；
需要 CIF/模拟时才另加 `requirements-structure-tools.txt`。不要修改 GMS Python。

在仓库根目录运行下列命令。`C:\analysis` 和 Python 路径是示例，
应替换为本机明确选择的独立目录和解释器：

```powershell
.\setup\register_codex.ps1 -Name microscopy-images -Backend images `
  -ImageWorkspace 'C:\analysis\images' `
  -ImagePython 'C:\analysis\env\Scripts\python.exe' `
  -ContextWorkspace 'C:\analysis\contexts' -CheckOnly
```

预检查成功后去掉 `-CheckOnly` 执行注册。脚本核对独立依赖、绝对路径和
Codex 现有名称；同名时拒绝修改。原有 `digitalmicrograph`、其他 MCP、
已有 Skill 和科学数据不受影响。`-StructureWorkspace` 与
`-StructurePython` 可成对显式添加；`-ExecutionObservability` 可选。
注册不会启动 DM，也不会自动创建科学结果。

三个现有科研 Skills 可另行显式安装：

```powershell
.\setup\install_codex_skills.ps1 -CheckOnly
.\setup\install_codex_skills.ps1
```

默认目标为 `$CODEX_HOME/skills`（未设置时为 `~/.codex/skills`）。
可用 `-SkillsDirectory` 指定客户端实际发现的目录。它们作为同级目录复制，
相互的相对链接保留；任何同名目录存在时整批预检查拒绝，不覆盖。
然后刷新客户端 MCP/Skills 发现，确认工具目录；文件复制不代表模型已使用 Skill。

## 日常使用

告诉 Codex“打开这份 TIFF，在面板里让我选区”。Agent 调用 `image_open`、
`image_panel_open` 并打开返回的私有 loopback URL。你框选/点选后说“继续，
做局部 FFT / 测这个峰”；Agent 读 `image_panel_current` 并通过
`image_panel_show` 将结果送回同一面板。当前客户端不自动唤醒模型，
选好后仍需说一次“继续”。

修改标尺或点位后，重测及新渲染复用已有复数 FFT。Agent 保留原请求 ID、
命名分析及 Context 修订；停止等待后查询 `image_result`，不重发未知副作用。
导出到新目录，重连时读取已保存分析；原 TIFF 保持只读。

## 客户端审批限制

Codex 的工具审批与本仓库数值校验是两层机制。非交互 `never` 模式下，
需要审批的 MCP 调用可能在执行前被拒绝；这不代表科学 worker 失败。
可以使用支持交互审批的会话。明确授权的无交互验收也可仅对这个独立
Provider 的具体工具配置审批，不改变全局沙箱或其他 Provider。例如：

```toml
[mcp_servers.microscopy-images]
# 保留注册脚本写入的 command / args / env 等字段
default_tools_approval_mode = "prompt"

[mcp_servers.microscopy-images.tools.image_info]
approval_mode = "approve"
```

其他工具按该次任务的实际授权逐项决定，不要把读取配置示例理解成
所有文件操作都已获准。以上 standalone 字段在本轮安装版本通过了严格
配置解析检查；真正模型调用、MCP 图片返回、模型看见图片、浏览器拖动和
DM 实机应分别记录，不能由配置检查代替。
