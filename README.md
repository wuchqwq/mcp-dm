# DigitalMicrograph MCP

[English](README.en.md) · [给编程代理的说明](AGENTS.md)

**让通用 Agent 能够了解 DigitalMicrograph 中的数据、查看指定图像、正确调用常用的采集后分析操作，并取得带标定、可继续处理的结果。**

`mcp-dm` 是本机 Gatan DigitalMicrograph（DM）的工具接口，不是新的聊天产品或自动科研分析平台。Agent 负责理解目标、组合工具、选择方法和组织解释；本项目负责正确的数据对象、坐标、单位、操作结果和失败状态。只处理**采集后分析**，不控制相机、束流、样品台或光路。

## 项目边界

| 层次 | 本项目提供 | 不强制做的事 |
|---|---|---|
| 核心 MCP | 连接与状态、数据集、元数据、常用数值操作、裁剪和保标定导出 | 不要求捕获包、报告、Skill 或外部绘图库 |
| 图像与数据交接 | 有界二维副本、显示预览、源坐标映射 | 预览不参与数值计算；当前预览使用 `capture → preview` 两步 |
| 可选工作流示例 | 既有二维报告、结果查询与复跑脚本 | 不替用户决定科学方法，不是使用核心工具的前置条件 |

不追求封装所有 DM API，不承诺自动物相识别、应变、光谱定量或重构。4D-STEM 既有接口按已声明范围保留，近期不扩展。新功能先判断是否为可靠访问 DM 所必需，优先复用通用 Agent 与外部科学计算工具。

## 从一个具体操作开始

可以让 Agent：“列出已打开图像并读取这张图的标定”“对我指定的区域取剖面”“计算该区域 FFT 并返回频率”“导出一个不覆盖原图的新文件”。它应先确认真实后端与明确的 `image_id`，然后只调用需要的工具。显式 ID 固定对象，不冻结内容；多步分析需要固定像素时再捕获独立副本。

**不需要每次执行“捕获 → 统计 → 剖面 → FFT → 报告”。** 成功标准是连接可用、操作正确、结果可继续使用，而不是能否生成一篇报告。

```text
MCP 客户端 → Node stdio server.mjs → 127.0.0.1 TCP → DM 内嵌 Python
```

Node 服务无 npm 运行依赖；DM 桥仅用 Python 标准库和 NumPy。DM/GMS、Python 运行时、Gatan 插件、参考手册和真实实验数据均不随仓库分发。MIT 许可只覆盖本仓库代码，不改变 Gatan 软件的许可。

## 当前验证范围

| 功能 | 已有证据与限制 |
|---|---|
| 二维 STEM 图像 | 小型真实 DM 合成图已验证 ROI、标定、捕获、预览与任务 A 数值/复跑；真实样本覆盖仍有限 |
| EDS/EELS 基础接口 | 合成数值、假 DM API、mock MCP 链已测；**真实 EDS、EELS、光谱 SI 均为 `NOT_TESTED`** |
| 4D-STEM | 有界 uint8 原生流读取与虚拟探测器分析验证通过，支持范围有限 |
| 硬件、采集、插件定量、相位重建 | 未提供或未验证 |

仓库分发的是合成数据测试与显式运行的宿主验收脚本，不含实验数据。上述真实宿主记录属于既有版本；本次范围/预览修改不继承其实机通过结论。新机器需验证自己的 DM 版本、数据类型、轴序和标定；默认使用本地测试；常规 Actions 保持手动触发；隔离验证只证明合成行为，不证明真实 DM 可用。

## 1. 准备环境

需要 Windows x64、已启用内嵌 Python 的 Gatan DigitalMicrograph/GMS，以及 Node.js **18 或更新版本**。桥代码兼容 Python 3.7 和 NumPy 1.18 API；请使用 Gatan 随 GMS 提供的 Python 环境。Node 必须在 MCP 客户端可见的 `PATH`，也可以在配置中填写其绝对路径。

```powershell
git clone https://github.com/wuchqwq/mcp-dm.git
Set-Location .\mcp-dm
node --version
# 无 npm 运行依赖，不需要 npm install
```

核心连接、元数据、统计、剖面、FFT、裁剪、导出和捕获不需要以下外部环境。**仅在需要图像预览时**，另建 Python 3.10+ 环境；不要改 GMS 管理的 Python/NumPy：

```powershell
python -m venv .analysis-env
.\.analysis-env\Scripts\python.exe -m pip install -r requirements-preview.txt
$analysisPython = (Resolve-Path .\.analysis-env\Scripts\python.exe).Path
```
预览环境只需 NumPy 和 Pillow。可选报告的 Matplotlib 在调用报告时才加载；状态查询与数值验证不依赖 Pillow/Matplotlib。预览用有界分块统计显示范围，只在目标分辨率上分配显示缓冲；缩略图可能遗漏细节，需要时显式提高分辨率或缩小捕获区域。


DM 内嵌 Python 不是普通系统 Python。不要在外部 Python 中尝试 `import DigitalMicrograph`，也不要用较新的 NumPy 替换 GMS 管理的 NumPy。

如果 GMS 已安装但 Python 组件缺失，先检查 Gatan 已提供的离线安装包：

```powershell
Test-Path 'C:\ProgramData\Gatan\Python\Miniconda3.exe'
Test-Path 'C:\ProgramData\Gatan\Python\installGMSvenv.bat'
# 确认这些是本机 Gatan 提供的安装包后执行；系统目录写入可能需要管理员权限
cmd /c .\setup\install_gms_python.bat
```

该脚本使用 Gatan 的离线包，不下载替代运行时。默认安装位置是 `C:\ProgramData\Miniconda3\envs\GMS_VENV_PYTHON`。如果本机采用其它 GMS 布局，按 Gatan 安装说明配置 Python；不要全盘搜索或混入其它项目的环境。

```powershell
$gmsPython = 'C:\ProgramData\Miniconda3\envs\GMS_VENV_PYTHON\python.exe'
& $gmsPython -c "import sys,numpy; print(sys.version); print(numpy.__version__)"
```

## 2. 启动真实 DM 桥

在仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\start_bridge.ps1
```

启动器先等待 DM 初始化，再在其内嵌 Python 中启动后台桥。默认 DM 程序为 `%ProgramFiles%\Gatan\DigitalMicrograph.exe`；自定义安装可以传参，或设置 `DM_GMS_EXE`。日志默认保存在仓库的 `runtime/bridge.log`。

```powershell
.\setup\start_bridge.ps1 -DmExecutable 'D:\Gatan\DigitalMicrograph.exe' -Port 8765
# 自定义 Gatan 日志目录时增加 -GatanLogDirectory 'D:\GatanLogs'
# 停止前先断开 MCP 客户端，随后：
.\setup\start_bridge.ps1 -Stop
```

端口仅绑定 IPv4 loopback。已运行时启动器返回状态；端口监听但不回答时报告 busy/unknown，拒绝重复注入。启动器分两阶段初始化 DM 与桥。桥占用一个 DM Python 后台执行槽；默认空闲一小时退出，退出后重跑启动器。

## 3. 接入 Codex 或其它 MCP 客户端

安装并登录 Codex 后，可用仓库脚本注册当前绝对路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\register_codex.ps1
codex mcp list
codex mcp get digitalmicrograph --json
```

脚本仅注册 MCP，不启动 DM。已有同名配置时先检查，不要盲目覆盖。等价的手动命令如下：

```powershell
$nodeExe = (Get-Command node).Source
$serverFile = (Resolve-Path .\server.mjs).Path
codex mcp add digitalmicrograph --env DM_BRIDGE_HOST=127.0.0.1 --env DM_BRIDGE_PORT=8765 --env DM_MCP_TIMEOUT_MS=600000 --env DM_MCP_ALLOW_DMSCRIPT=0 -- $nodeExe $serverFile
```

二维捕获和分析可能超过客户端默认等待时间。在 Codex 的现有 `[mcp_servers.digitalmicrograph]` 表内按需增加以下设置，不要重复建立同名 TOML 表；已有 `disabled_tools` 时把 `dm_run_script` 合并进去，保留其它禁用项：

```toml
startup_timeout_sec = 20
tool_timeout_sec = 660
disabled_tools = ["dm_run_script"]
```

注册脚本拒绝覆盖已存在的同名服务器；它不自动编辑上述超时或工具禁用配置。服务目录包含 21 个工具，配置该禁用项后 Codex 可用 20 个；未隐藏时自由脚本仍被 Node/桥两层执行门禁拒绝。桌面客户端已打开的聊天需要刷新 MCP；官方入口为 Settings → MCP servers → Restart。[Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

其它客户端可参考 [mcp.json.example](mcp.json.example)，将 `__ABS_REPO_PATH__` 替换成仓库绝对路径，例如 `D:/code/mcp-dm`。不要把 JSON 样例原样粘贴到 Codex 的 TOML 配置。

**配置存在、工具能发现、真实 DM 能执行是三项独立检查。** 在客户端调用 `dm_status`，只有 `backend="digitalmicrograph"` 才是实际 DM；`backend="mock"` 是合成后端。记录 PID、版本、源码哈希和结果后置条件。超时或取消只停止客户端等待，已经发送的操作可能继续执行，不要自动重试导出等有副作用操作。

## 4. 工具与数值约定

| 工具 | 用途 |
|---|---|
| `dm_status`、`dm_datasets` | 查看后端和已打开数据集的 shape、dtype、每轴标定 |
| `dm_2d_capture`、`dm_2d_preview` | 固定捕获二维工作输入；预览并返回 image block、PNG 路径和源坐标映射 |
| `dm_2d_analyze`、`dm_2d_result` | 可选组合报告／独立状态查询；不作为其他工具的前置条件 |
| `dm_open`、`dm_metadata` | 打开二维数据副本/视图、读取 typed metadata；检查 `complete` 和错误列表 |
| `dm_stats`、`dm_profile`、`dm_fft` | 二维统计、物理距离剖面、标定频率 FFT |
| `dm_crop`、`dm_export` | 独立裁剪与新路径导出，保留标定和 provenance |
| `dm_spectrum_info`、`dm_spectrum` | 显式能量轴检查及区域抽谱；真实光谱未验证 |
| `dm_spectrum_integrate`、`dm_spectrum_export` | 原始通道能窗求和、CSV；不代表元素定量 |
| `dm_4dstem_open` | 只读索引唯一未压缩 uint8 4D DM4 数据集；显式 canonical 轴，未整文件 OpenImage |
| `dm_4dstem_read` | 有界 Gatan 原生流读取小 4D 块，发布独立 DM 图像并复制四轴标定 |
| `dm_4dstem_virtual` | 分块 BF/ADF、总强度、总/平均衍射图，发布独立 DM 图像 |
| `dm_run_script` | 自由脚本入口，Node 与桥两层默认禁用 |

- **二维 ROI 契约变化**：统计、FFT 和裁剪严格拒绝越界、空区域及非整数坐标，不再舍入或自动裁夹。省略 `rect` 仅对统计/FFT 表示整幅；裁剪仍要求显式选区。`requested_rect` 保留请求（省略时为 null），`effective_rect` 给出实际区域；旧 `rect` 字段继续保留。
- 裁剪继续使用原生 `ImageClone`，通过每次操作独有的内部令牌和新图像 ID 认领结果；不再按用户显示名称或“最新窗口”回退。缺失或重复令牌时明确失败，不修改无关图像标定。该固定合成路径已在当前 DM 主机复验；不代表任意版本或样本均通过，也不构成像素原子快照或安全沙箱。
- 二维矩形为零基 `[x0,y0,x1,y1]`，右下端排除；NumPy 图像 shape 为 `[y,x]`。DM 维度 0 变化最快，NumPy C-order 最末轴变化最快。
- 标定采用 `coordinate[i] = calibrated_value_at_pixel_zero + i * scale`。原始 DM `Origin` 可能是物理零点的像素索引，不能直接当作物理起点；裁剪起点按 `old_zero + start * scale` 平移。
- 统计使用有限值、float64、总体标准差 `ddof=0`；零值参与统计。未完成扫描的全零区域必须显式标记与处理。
- FFT 去均值、无窗、无 padding。报告频率分量不等于确认晶面、物相或原子间距。
- 光谱必须显式选择 NumPy 能量轴，单位必须是 eV/keV；能窗按通道中心 `low <= E < high`，原始积分是通道值求和，不乘能宽。整数累积受 `2**53` 精度保护；无背景扣除、谱漂移/厚度/元素定量承诺。
- 4D 核心要求显式 `[scan_y,scan_x]` 和 `[q_y,q_x]` 轴。虚拟圆盘/圆环按像素中心 `r_inner <= r < r_outer` 选择，使用匹配的倒易单位，默认拒绝被探测器 FOV 裁切的圆。不会由亮度或文件名猜 HAADF，也不擅自换算 mrad。
- `dm_open` 拒绝超过 512 MiB 的整文档打开。大型 4D 数据应走独立 4D 接口：先 seek-only header 索引，再由 Gatan 原生只读流读取，不整块载入；内存预算先于分配和读取。

## 元数据子树读取

`dm_metadata(prefix=...)` 先定位标签，再以该子树为深度零点读取；不读取无关 sibling 的值。支持 `/Acquisition/Instrument` 及原有无首斜线写法，列表用零基索引；标签里的 `/`、`~` 分别写作 `~1`、`~0`。省略/空字符串表示根；`/` 表示空名称标签，不再把前后空白或斜线悄悄删去。

检查 `path_status`：`found` 只说明路径存在，值是否完整仍看 `complete` 和 `issues`；`not_found` 表示已确认不存在；`unavailable` 表示查找预算不足、标签读取失败或路径不唯一，不能据此认定不存在。`complete` 仅描述所选子树。查找和子树遍历各有独立节点预算，路径最多 64 段；失败不会丢失诊断信息。类型描述或大小读取失败时停止，不猜测原生 getter。

此改动有合成、fake-DM 与当前 DM 主机固定标签验收覆盖；原生 getter 故障/崩溃注入仍为 **NOT_TESTED**。后续范围见 [ROADMAP.md](ROADMAP.md)。

## 可选示例：二维分析报告与复跑

以下是已有组合示例，不是核心 MCP 的默认工作流。只想看图时，到 `dm_2d_preview` 即可；只想取剖面或 FFT，也可直接使用单独工具。生成完整报告才需要额外安装：

```powershell
.\.analysis-env\Scripts\python.exe -m pip install -r requirements-analysis.txt
```

新注册 MCP 时可将外部分析解释器交给注册脚本：

```powershell
.\setup\register_codex.ps1 -AnalysisPython $analysisPython
```

`dm_2d_capture` 省略 `image_id` 时只在调用开始解析一次 DM 前台图像，也可明确传图像 ID；可选 `rect` 使用原图坐标 `[x0,y0,x1,y1)`。输出目录必须是新目录。捕获前检查二维 shape、dtype 和内存预算；复制像素与标定后，后续工具都固定使用该 NPY，不再跟随前台窗口。DM API 不能保证像素与标定的原子快照，**捕获期间不要编辑源图**。预算不够时明确失败，不自动缩小 ROI。

`dm_2d_preview` 可显示捕获图并叠加候选 ROI、剖面线/条带。返回内容包含 PNG image block、本地 PNG 路径、显示范围，以及 preview↔source 像素/边界坐标映射。显示采用有限值线性 min-max；常数图显示中灰，NaN/Inf 显示洋红。缩略图按最近源像素中心采样，仅供查看，可能遗漏细节。PNG 只用于核对，**不参与统计、剖面或 FFT，也不是科学数据导出**。需确认客户端实际显示了 image block；否则用本地路径打开图片。选择坐标仍须用原图 source pixel，矩形右/下边界不包含，剖面端点是像素中心。

最小调用示例（路径需替换为新建目录）：

```json
{"output_dir":"C:/analysis/capture-001","image_id":1234}
{"capture_dir":"C:/analysis/capture-001","roi":[20,30,180,150],"profile":{"start":[20,90],"end":[179,90],"width":1}}
{"capture_dir":"C:/analysis/capture-001","result_dir":"C:/analysis/result-001","operation_id":"analysis-001","roi":[20,30,180,150],"profile":{"start":[20,90],"end":[179,90],"width":1}}
```

依次调用 `dm_2d_capture`、`dm_2d_preview`、`dm_2d_analyze`；任务参数中的 ROI 与剖面坐标均为**原图坐标**。分析结果目录包含捕获 NPY 与标定、统计/剖面 JSON、剖面 CSV、完整 FFT 幅值 NPY 与频率/峰值 JSON、结果图、参数、manifest、Markdown 报告和 `replay.py`。用 `python replay.py --verify` 独立重算并按 manifest 容差核对；用 `python replay.py --output NEW_EMPTY_DIRECTORY` 重新生成结果包。超时后先调用 `dm_2d_result` 查状态；`unknown` 不表示计算已停止，不要自动重试。

物理单位、缺失标定或异常值必须按结果报告处理；FFT 要求有限输入，不补 NaN/Inf。频谱格点不能直接当作已确认的衍射斑点、晶面或物相。Skill 流程见 [skills/dm-2d-analysis/SKILL.md](skills/dm-2d-analysis/SKILL.md)。MCP 本身不上传捕获文件，但客户端可能把图像预览、选区、标定和数值发送给所选模型服务；提交数据前应确认客户端/服务的数据处理方式。

## 4D-STEM 调用示例与限制

文件路径与 `image_id` 不等价。先通过 `dm_4dstem_open` 获得 `dataset_id`，此入口仅支持 NumPy 布局 `[scan_y,scan_x,q_y,q_x]`，必须传 `scan_axes=[0,1]`、`detector_axes=[2,3]`。文件必须含唯一 4D 标量数据集，当前 native 路径仅接受未压缩 uint8。

下面是 MCP 工具参数示例；把路径和返回的 `dataset_id` 替换为本机值：

```json
{"path":"C:/data/example.dm4","scan_axes":[0,1],"detector_axes":[2,3]}
```

调用 `dm_4dstem_read` 读取小块，参数为：

```json
{"dataset_id":"4d-1","scan_bounds":[[0,2],[0,3]]}
```

调用 `dm_4dstem_virtual` 的示例参数如下。中心与半径必须依据返回的倒易标定和实际衍射图选择；以下数值只是用法示例，假设单位为 `1/nm`、该圆完全位于 FOV 内，不构成推荐硬件收集角：

```json
{"dataset_id":"4d-1","scan_bounds":[[0,16],[0,16]],"chunk_patterns":128,"detectors":[{"label":"BF","center_q":[0,0],"r_inner":0,"r_outer":0.5},{"label":"ADF","center_q":[0,0],"r_inner":1,"r_outer":4}]}
```

单次读取最多 256 个扫描位置且不超过 16 MiB；单次虚拟探测器计算最多 8,192 个扫描位置，每次原生读取最多 128 张衍射图。大扫描需分不重叠批次，并按返回的原始坐标与标定拼接；保存总衍射图和样本数后再求全局平均，不直接等权平均不同大小的批次平均图。图像通过 `images` 返回，可用 `dm_export` 导出新文件。

已验证有界原生读取、轴标定及虚拟探测器结果导出的基础链路。

**未验证**：大型 DM4 的原生 `OpenImage` 整文档加载、DM 内置 BF/ADF 插件、其它压缩/打包/dtype/轴布局、实验探测器角度与 HAADF 对应关系、COM/DPC 和相位重建。真实 EDS/EELS/光谱 SI 仍为 `NOT_TESTED`。

## 导出与源数据保护

源数据只读，禁止原位覆盖。NPY 保留 dtype/shape，标定在 sidecar；科学 TIFF 为无压缩单通道 classic TIFF，保持 dtype，标定写入 description、Gatan 轴标签和 sidecar。导出后应检查数值和标定。超过 classic TIFF 格式容量上限、未知类型或不兼容单位应明确拒绝。

DM3、其它 GMS/探测器类型与新格式组合须分别验收。CSV/TXT 保留整数十进制或浮点 17 位有效数字。科学 PNG 强度导出未定义；`dm_2d_preview` 的 PNG 仅为显示图。科学导出与 sidecar 必须写全新路径，附来源、处理历史、writer 和 SHA-256。

自由脚本开关不构成硬件沙箱；保持 `DM_MCP_ALLOW_DMSCRIPT=0`。本项目不提供远程开放端口和采集工具。

## 5. 合成测试：不启动 DM、不需要真实数据

推荐使用外部 Python 3.10+ 虚拟环境运行完整合成测试。此环境与 DM 内嵌 Python 分开：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
node --test
$env:DM_TEST_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
node selftest.mjs
```

mock 自测使用临时 loopback 端口和合成数组，不连接正在运行的 DM。`DM_TEST_PYTHON` 可指定已有 Python；省略时使用 `PATH` 中的 `python`。核心 Python 代码保持 3.7/NumPy 1.18 兼容；独立 TIFF 测试需 `tifffile`，不要为此升级 GMS 环境。可选工作流只包含合成检查，不能证明真实 DM、真实光谱或新机器安装通过。

## 贡献

阅读 [AGENTS.md](AGENTS.md)，给修改增加独立数值 oracle 或必要的协议测试。区分 `PASS`、`FAIL`、`NOT_TESTED`，不要以 mock 结果扩大真实仪器支持范围。提交前检查 `git diff --check`、运行相关测试，并检查暂存区未包含实验数据、图像输出、绝对个人路径、日志或凭据。不要上传 Gatan 手册、二进制或其它许可不兼容的 reader。

## 可选 Skill 与兼容性

`skills/dm-2d-analysis/SKILL.md` 是可选使用指南。注册 MCP 不会自动安装它；可直接要求 Agent 阅读该文件。Codex 本地发现时，可将整个 `dm-2d-analysis` 目录复制到工作目录的 `.agents/skills/`，已有同名目录先检查，不覆盖。[官方 Skill 文档](https://developers.openai.com/codex/skills/)

工具名称与 21 项目录保持兼容，没有新增模式开关。可选报告的剖面 `sampled_coordinates` 现为原图坐标，副本坐标在 `sampled_coordinates_local`；强度明确为原始像素值，强度标定只保留为元数据；`replay.py --verify` 失败或状态未知时非零退出。旧结果包保留自己的复跑代码，不原位改写。新变更的真实 DM/客户端验收仍须分别执行。范围决策与剩余限制见 [ROADMAP.md](ROADMAP.md) 和 [审计记录](docs/SCOPE_AUDIT.md)。

## 普通客户端测试版本（D0 → 本机 P0）

核心 MCP 不依赖 Codex。需要预览的通用 stdio 配置见 [mcp.preview.json.example](mcp.preview.json.example)，核心工具配置仍使用 [mcp.json.example](mcp.json.example)。必须替换所有绝对路径占位符，不自动覆盖客户端配置。

[本机客户端验收](docs/CLIENT_ACCEPTANCE.md) 包含 WorkBuddy 官方配置参考、手动创建的两张合成图和短任务。先在新会话不用 Skill、不读源码、不临时写替代分析脚本，检查模型能否凭工具说明完成基本操作；失败后再单独记录带 Skill 的辅助测试。

D0 只表示代码、合成回归和交付准备完成；本次真实 DM、WorkBuddy 图像显示、模型看图及操作正确性仍须本机 P0 验收。当前桥一次服务一个持续连接：测试前断开其它 MCP 客户端，不要因 busy/unknown 重启 DM 或重复注入桥。详见 [D0 交接边界](docs/D0_HANDOFF.md)。
