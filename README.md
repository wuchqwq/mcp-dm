# DigitalMicrograph MCP

[English](README.en.md) · [给编程代理的说明](AGENTS.md)

让 Codex 等 MCP 客户端调用本机 Gatan DigitalMicrograph（DM），读取已采集数据的标定与元数据，进行图像、基础光谱和虚拟探测器计算。只处理**采集后分析**，没有相机、束流、样品台或光路控制工具。

```text
MCP 客户端 → Node stdio server.mjs → 127.0.0.1 TCP → DM 内嵌 Python
```

Node 服务无 npm 运行依赖；DM 桥仅用 Python 标准库和 NumPy。DM/GMS、Python 运行时、Gatan 插件、参考手册和真实实验数据均不随仓库分发。MIT 许可只覆盖本仓库代码，不改变 Gatan 软件的许可。

## 当前验证范围

| 功能 | 已有证据与限制 |
|---|---|
| 二维 STEM 图像 | 真实 DM 标定、数值与导出验证通过，支持范围有限 |
| EDS/EELS 基础接口 | 合成数值、假 DM API、mock MCP 链已测；**真实 EDS、EELS、光谱 SI 均为 `NOT_TESTED`** |
| 4D-STEM | 有界 uint8 原生流读取与虚拟探测器分析验证通过，支持范围有限 |
| 硬件、采集、插件定量、相位重建 | 未提供或未验证 |

仓库只含合成测试。新机器需验证自己的 DM 版本、数据类型、轴序和标定；默认使用本地测试；Actions 仅手动触发，未将 CI 计入验证结论。

## 1. 准备环境

需要 Windows x64、已启用内嵌 Python 的 Gatan DigitalMicrograph/GMS，以及 Node.js **18 或更新版本**。桥代码兼容 Python 3.7 和 NumPy 1.18 API；请使用 Gatan 随 GMS 提供的 Python 环境。Node 必须在 MCP 客户端可见的 `PATH`，也可以在配置中填写其绝对路径。

```powershell
git clone https://github.com/wuchqwq/mcp-dm.git
Set-Location .\mcp-dm
node --version
# 无 npm 运行依赖，不需要 npm install
```

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

长时间 4D 分析需要 MCP 客户端等待时间大于桥的等待时间。在 Codex 的现有 `[mcp_servers.digitalmicrograph]` 表内增加以下设置，不要重复建立同名 TOML 表；已有 `disabled_tools` 时把 `dm_run_script` 合并进去，保留其它禁用项：

```toml
startup_timeout_sec = 20
tool_timeout_sec = 660
disabled_tools = ["dm_run_script"]
```

注册脚本拒绝覆盖已存在的同名服务器；它不自动编辑上述超时或工具禁用配置。服务目录包含 17 个工具，配置该禁用项后 Codex 可用 16 个；未隐藏时自由脚本仍被 Node/桥两层执行门禁拒绝。桌面客户端已打开的聊天需要刷新 MCP；官方入口为 Settings → MCP servers → Restart。[Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

其它客户端可参考 [mcp.json.example](mcp.json.example)，将 `__ABS_REPO_PATH__` 替换成仓库绝对路径，例如 `D:/code/mcp-dm`。不要把 JSON 样例原样粘贴到 Codex 的 TOML 配置。

**配置存在、工具能发现、真实 DM 能执行是三项独立检查。** 在客户端调用 `dm_status`，只有 `backend="digitalmicrograph"` 才是实际 DM；`backend="mock"` 是合成后端。记录 PID、版本、源码哈希和结果后置条件。超时或取消只停止客户端等待，已经发送的操作可能继续执行，不要自动重试导出等有副作用操作。

## 4. 工具与数值约定

| 工具 | 用途 |
|---|---|
| `dm_status`、`dm_datasets` | 查看后端和已打开数据集的 shape、dtype、每轴标定 |
| `dm_open`、`dm_metadata` | 打开二维数据副本/视图、读取 typed metadata；检查 `complete` 和错误列表 |
| `dm_stats`、`dm_profile`、`dm_fft` | 二维统计、物理距离剖面、标定频率 FFT |
| `dm_crop`、`dm_export` | 独立裁剪与新路径导出，保留标定和 provenance |
| `dm_spectrum_info`、`dm_spectrum` | 显式能量轴检查及区域抽谱；真实光谱未验证 |
| `dm_spectrum_integrate`、`dm_spectrum_export` | 原始通道能窗求和、CSV；不代表元素定量 |
| `dm_4dstem_open` | 只读索引唯一未压缩 uint8 4D DM4 数据集；显式 canonical 轴，未整文件 OpenImage |
| `dm_4dstem_read` | 有界 Gatan 原生流读取小 4D 块，发布独立 DM 图像并复制四轴标定 |
| `dm_4dstem_virtual` | 分块 BF/ADF、总强度、总/平均衍射图，发布独立 DM 图像 |
| `dm_run_script` | 自由脚本入口，Node 与桥两层默认禁用 |

- 二维矩形为零基 `[x0,y0,x1,y1]`，右下端排除；NumPy 图像 shape 为 `[y,x]`。DM 维度 0 变化最快，NumPy C-order 最末轴变化最快。
- 标定采用 `coordinate[i] = calibrated_value_at_pixel_zero + i * scale`。原始 DM `Origin` 可能是物理零点的像素索引，不能直接当作物理起点；裁剪起点按 `old_zero + start * scale` 平移。
- 统计使用有限值、float64、总体标准差 `ddof=0`；零值参与统计。未完成扫描的全零区域必须显式标记与处理。
- FFT 去均值、无窗、无 padding。报告频率分量不等于确认晶面、物相或原子间距。
- 光谱必须显式选择 NumPy 能量轴，单位必须是 eV/keV；能窗按通道中心 `low <= E < high`，原始积分是通道值求和，不乘能宽。整数累积受 `2**53` 精度保护；无背景扣除、谱漂移/厚度/元素定量承诺。
- 4D 核心要求显式 `[scan_y,scan_x]` 和 `[q_y,q_x]` 轴。虚拟圆盘/圆环按像素中心 `r_inner <= r < r_outer` 选择，使用匹配的倒易单位，默认拒绝被探测器 FOV 裁切的圆。不会由亮度或文件名猜 HAADF，也不擅自换算 mrad。
- `dm_open` 拒绝超过 512 MiB 的整文档打开。大型 4D 数据应走独立 4D 接口：先 seek-only header 索引，再由 Gatan 原生只读流读取，不整块载入；内存预算先于分配和读取。

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

DM3、其它 GMS/探测器类型与新格式组合须分别验收。CSV/TXT 保留整数十进制或浮点 17 位有效数字。PNG 展示映射尚未定义。导出与 sidecar 必须写全新路径，附来源、处理历史、writer 和 SHA-256。

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
