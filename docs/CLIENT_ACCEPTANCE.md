# 本机普通 Agent 验收 / Local general-agent acceptance

目的：测通用 Agent 能否仅凭 MCP 工具说明正确使用 DM，而不是测它会不会读源码、临时写 Python 或生成报告。此文件是测试说明，不是已通过的兼容认证。WorkBuddy、其它客户端和真实 DM 的本轮状态均为 `NOT_TESTED`，由本机测试更新。

## 1. 固定候选版本，准备环境

记录 `git rev-parse HEAD`、客户端版本和实际选择的模型。使用本轮候选分支 `release/d0-client-candidate-20261022`，不要把旧 `main` 当成同一版本。已有工作区先保存自己的修改；不执行 reset --hard，不盲目覆盖配置。

核心工具不需外部绘图库。需要预览时，在 Windows 的独立 Python 3.10+ 环境安装 `requirements-preview.txt`；不要在 GMS 管理环境安装这些依赖。使用 `mcp.preview.json.example`，替换：

| 占位符 | 填写内容 |
|---|---|
| `__ABS_NODE_EXE__` | 本机 Node 可执行文件绝对路径 |
| `__ABS_REPO_PATH__` | 此候选版本仓库的绝对路径 |
| `__ABS_PREVIEW_PYTHON_EXE__` | 已安装预览依赖的外部 Python 绝对路径 |

JSON 中可用 Windows 正斜线路径，例如 `C:/tools/node.exe`；不要把路径和参数合并成一条 shell 命令。将一个服务器条目合并到现有配置，保留其它服务器。无需复制 Codex 的 TOML、`disabled_tools` 或 `tool_timeout_sec` 到其它客户端。

WorkBuddy 官方文档提供用户级 `~/.workbuddy/mcp.json` 和项目级 `<项目目录>/.workbuddy/mcp.json`，使用 `mcpServers` 下的 `command/args/env` 配置。参考：[官方 MCP 指南](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)、[官方连接器说明](https://open.workbuddy.cn/docs/connector)（本地进程可使用 stdio；参考日期 2026-10-22）。此项目不自动写入这些配置，也不假定特定客户端已经接受了当前协议协商或图像内容。

**一次只连接一个客户端。** 当前 Bridge 服务一个持续 TCP 连接；测试 WorkBuddy 前，断开 Codex 和其它连接此 Bridge 的 MCP 会话。不要启动第二份 Bridge，不要因为 busy/unknown 强杀或重启 DM。按 README 启动或正常重新加载本项目 Bridge，并核对 `dm_status` 的真实后端与加载代码身份；磁盘 git 更新不等于运行代码已经更新。

## 2. 只用合成图开始

在 DM 的 Python 工作区手动运行 `examples/create_2d_client_fixture.py`。该脚本仅创建两个新的小图，不读取实验文件、不修改现有图、不控制显微镜、不启用任意脚本 MCP。先保留自己的工作；运行完保留脚本工作区与两张图，记录打印出的名称和 ID。名称含随机后缀，重跑时不要混淆不同轮次。

第一张为 `MCP_D0_RAMP_<后缀>`，第二张为 `MCP_D0_OTHER_<后缀>`。把下面 `<RAMP>`、`<OTHER>` 替换为本轮真实名称。提前选一个新的本地输出父目录；后续每次捕获和导出使用不同子路径。

脚本的 fake-DM/数值测试不等于在你的 DM 版本上通过。如创建失败，记录失败，不要让 Agent 修改源代码绕过。

## 3. 第一轮：不安装 Skill，不给长开发提示词

新建对话，仅告知：使用 DigitalMicrograph MCP；不要改源图；输出到选定目录。不要先提供本文件的数值答案。先尝试以下独立任务，可以一条一条发。需要授权时正常确认，不要为了减少确认关闭安全控制。

| 场景 | 发给 Agent 的短任务 | 验收者检查 |
|---|---|---|
| 数据与标定 | 列出 DM 中的图像，告诉我 `<RAMP>` 的形状、类型和两轴标定，不修改数据。 | 真后端、ID、轴序和单位正确；不能只输出工具名或编造结果 |
| 查看图像 | 看一下 `<OTHER>`，告诉我较亮的矩形在哪个方位，给我一张预览，不要生成报告。 | 真的显示/查看图像；不能只凭文件名或文本声称已经看见 |
| 看图选区 | 用叠加框标出刚才较亮的矩形，坐标按原图给出，不写替代分析脚本。 | 对照原图核对框；缩略图坐标不能直接当源坐标；允许记录小定位误差，不伪造精确性 |
| 指定区域统计 | 对 `<RAMP>` 的 `[10,8,30,18]` 区域计算像素数、最小值、最大值和均值；右下不包含。 | 必须来自指定数据与区域的工具结果 |
| 剖面 | 在 `<RAMP>` 上从 `[10,12]` 到 `[29,12]` 取宽度 1 像素的剖面，说明距离单位和总长度。 | 数值、方向、单位正确；不是沿线方向平滑 |
| 原生裁剪与导出 | 把 `<RAMP>` 的 `[10,8,30,18]` 裁成独立新图，导出到指定的新 NPY 路径，不覆盖任何文件。 | 图像归属、shape、标定和新文件/sidecar 对应；源图不变 |

可补充让 Agent 对指定 ROI 调用 FFT 并解释输出，但不要求自动识别晶面或生成报告。首轮不要临时安装库、读仓库源码或者写新算法替代工具；确需这些才能成功时，应记录 MCP/客户端能力缺口，而不是把绕行结果算成首轮通过。正常打开返回的预览文件作为图像回退不算算法绕行。

### 数值与视觉真值（仅供验收者，不提前发给模型）

两图均为 NumPy `[48,64]`、float32。X 物理像素零点 1.25 nm、scale -0.25 nm/pixel；Y 零点 -2.5 nm、scale 0.5 nm/pixel。RAMP 像素值为 `100*y+x`。

- ROI `[10,8,30,18]`：200 像素，min=810，max=1729，mean=1269.5。
- 剖面：20 个点，原始强度 1210 到 1229，总长度 4.75 nm；负 X scale 不代表负的路径长度。
- 裁剪 NumPy shape `[10,20]`；新图物理零点 X=-1.25 nm，Y=1.5 nm；scale 不变。
- OTHER 的亮矩形源边界 `[40,8,54,18]`，位于显示图右上；暗矩形 `[8,28,22,40]` 位于左下。视觉定位允许小误差，但 Agent 应承认定位精度，且叠加与声明一致。
- 强度是原始像素值，不因带有强度单位字段就自动成为标定物理强度。

## 4. 失败与数据保护检查

一次只做一个小检查。请求一个明确越界的 ROI，观察是否拒绝，而不是裁夹；把相同导出路径再用一次，观察是否拒绝覆盖且原文件仍在；完成捕获后切换到另一张前台图，再请求该捕获包预览，确认输入不变。若出现超时，查询相应包状态，不自动重跑。**不要通过强杀 DM、人为制造原生崩溃或修改实验文件来测失败。**

图片传输、用户看到图片、模型实际看图是三项独立结果。客户端不能显示且不能读取本地图片时，标记该场景 blocked/NOT_TESTED，不能把语言描述算通过。不能据此直接认定是模型能力问题；分别检查配置、协议、依赖、图像传输、选工具与数值契约。

第二轮可以明确安装/提供可选 Skill 再试，但保存首轮失败和用户干预次数，分开记为 assisted。不要用新的长提示词覆盖原始测试结论。

## 5. 反馈模板（保存在本地，分享前脱敏）

| 项目 | 记录 |
|---|---|
| 候选 commit、客户端版本、模型 |  |
| DM/Bridge 代码身份与版本 |  |
| 场景与原始短任务 |  |
| 无 Skill / Skill 辅助 |  |
| 实际调用的工具、参数和关键返回值 |  |
| PNG 传输 / 用户显示 / 模型看图 | PASS / FAIL / NOT_TESTED |
| 对象、坐标、数值、标定、源保护 | PASS / FAIL / NOT_TESTED |
| 用户纠正次数与失败原因 |  |

不要公开上传完整日志、配置文件、绝对私人路径、凭据或实验数据。合成通过后，再自行选择一张熟悉且允许交给所选模型服务的真实二维图。发布或合并前据本机结果判断，不因为 D0 合成回归通过就写“WorkBuddy 已兼容”。

## English summary

Use the fixed candidate, merge the generic JSON config without overwriting settings, and connect only one MCP client at a time. Manually run the small synthetic fixture inside DM. In a fresh conversation without the optional Skill or substitute scripts, test listing/calibration, actual image viewing, a visually selected overlay, explicit statistics/profile and crop/export. Keep the oracle above private from the model until after testing. Record transport, visible rendering, model vision and numerical correctness separately. Skill-assisted retries are a second run, not a replacement for the first outcome. D0 is engineering readiness; local DM/client acceptance (P0) remains pending.
