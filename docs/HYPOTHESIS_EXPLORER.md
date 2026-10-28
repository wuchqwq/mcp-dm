# Hypothesis Explorer MVP

给 Agent 一组已保存的实验反射和 1–3 个候选 CIF/XYZ，它可以试探少量晶带轴、
面内旋转和 HKL 对应，显示哪些反射匹配、哪些冲突，并保留多种解释。
入口是独立 Python 命令，复用既有科学工具，不新增聊天 UI、Runtime 或模拟内核。
研究者指出孪晶后继续修订的已执行闭环见 [双域反馈示例](TWIN_FEEDBACK_LOOP.md)。
它尚不是新的 MCP 工具；Agent 可在本地运行命令，也可按同一方法直接编排既有 MCP 工具。

## 运行可查看的合成实验

使用已安装 `requirements-structure-tools.txt` 的独立环境，不能使用 GMS Python。
以下 PowerShell 命令从仓库根目录执行；两个输出目录必须是新的绝对路径：

```powershell
$demoRoot = Join-Path (Get-Location) ("outputs/hypothesis-" + [guid]::NewGuid().ToString("N"))
python examples/hypothesis_explorer_demo.py --output $demoRoot
$searchRoot = $demoRoot + "-search"
python tools/hypothesis_explorer.py --config (Join-Path $demoRoot "config.json") --output $searchRoot
Invoke-Item (Join-Path $searchRoot "index.html")
```

`index.html` 是嵌入叠加图的独立页面，可离线查看；`overlay.png` 可单独分享。
页面包含所有候选／区轴的比较表、编号测量表、假设 HKL、残差与未匹配项、下一观察建议。
图中的模拟点逆变换回原实验坐标，纵轴向上只是明确标注的绘图约定。
`report.json` 保留全部试探角度、参数和对应；`structure/` 保存原工具的不可变科学证据，
`calls/` 在每次写入前保存请求 ID。结果目录已存在时拒绝执行，不覆盖或自动重放。
若中断，先使用保存请求及原工作区查询 `structure_result`；新目录代表一次明确的新实验。

生成器先用 ASE 创建理想周期 CIF，再经 `structure_open/orient/simulate` 生成 diffsims
定量 raster，将其显式量化为 uint16 TIFF 并重新读取。峰位从 TIFF 像素的局部极大值获取，
通过 `image_open/frame/calibrate/center/measure` 提交真实测量记录；没有手写测量 manifest。
`fixture.json` 保留真值、数值数组／TIFF／CIF 哈希、量化误差、标定和软件来源。
搜索配置不提供真值候选标记、真值取向或 HKL。生成和比较使用同一模拟器，
这验证的是无真值输入的恢复流程，不是独立模拟器验证、盲法人类实验或真实实验验收。

## 已实际执行的首个实验

2026-10-28，从 main `097de96` 开始，实际运行上述生成器和搜索入口。
三个固定模型为 ASE 常规立方胞：Al FCC `a=4.05 Å`、Fe BCC `a=2.86 Å`、
Cu FCC `a=3.615 Å`。这些是显式理想模型参数，不是实验测得晶格常数或 MP 数据。
真值为 Al `[001]`、正向面内 roll `17°`。

条件为 200 kV、倒空间半径 `0.9 Å⁻¹`、激发误差界 `0.02 Å⁻¹`、无直射束、
Lobato 散射参数、零进动的运动学模型。真值 raster 为 512×512、Gaussian sigma=1 px；
候选 raster 为 128×128，只使用其未栅格化反射比较。
TIFF 标定为 `0.003515625 Å⁻¹/px`，DC 为 `[256,256]`，列对应 +labX、行对应 +labY，
因此 `flip_y=false` 有生成器来源。尺度不从候选拟合，平移固定为零。
容差在搜索前固定为 `sqrt(2)×pixel_scale = 0.00497184456 Å⁻¹`，
依据是已记录的 diffsims 每轴小于 1 px 的栅格中心截断界；不是为候选调大的阈值。

从重读 TIFF 得到 8 个反射；每个候选只试 `[001]`、`[110]`、`[111]`，
旋转范围 `[-180°,180°)`。以下是每个结构的最佳试探：

| 假设 | 区轴 | 实验→模拟旋转 | 匹配 | 未匹配实验 | 未分配模拟 | 匹配 RMS / Å⁻¹ |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Fe BCC | [001] | 117.987453° | 8/8 | 0 | 0 | 0.00268585336 |
| Al FCC | [001] | -17.012547° | 8/8 | 0 | 0 | 0.00281077704 |
| Cu FCC | [001] | -180°（区间起点，无可行径向对应） | 0/8 | 8 | 8 | 无匹配，不定义 RMS |

Al 和 Fe 的 `[110]`／`[111]` 均只匹配 2/8，其余 6 个实验反射不支持这些已试解释；
Cu 三个已试区轴均为 0/8。这些结论仅覆盖本次候选和有限取向。
Al 真值已回到兼容集合，旋转约为真值的负值，也保留四重对称解。
Fe 残差略小，**不能据此决定 Fe 正确**：其 `[110]` 反射长度 `sqrt(2)/2.86`
与 Al `[200]` 的 `2/4.05` 只相差约 `0.000653 Å⁻¹`，二维网经 45° 旋转近似重合。

追加半径 `1.25 Å⁻¹` 的前瞻模拟，在全部保留的竞争结构／区轴／试探旋转中找
尚未搜索过的外侧位置，使用最小候选间距选择目标。Al `{420}` 附近的新反射
模长约 `1.104 Å⁻¹`，与 Fe 的最近预测只相差约 `0.00146039 Å⁻¹`。
当前精度仍不足；若要用该新反射区分这两个固定模型，位置、标定及模型的相关误差界
须小于约 `0.000730195 Å⁻¹`，否则应获取有标定倾转或独立成分证据。
报告给出目标 XY、假设 HKL、旋转及最近竞争预测。目标邻域通过 Ewald 激发界检查，
保证不会仅因竞争反射落在全三维枚举截断外而夸大位置差异。
这是未来观察建议，没有实际测到该新反射；也不保证其可见性，单凭未见峰不能排除模型。

## 用自己的已保存反射

由 Agent 准备与演示 `config.json` 同形状的配置：

- `measurement_paths`：1–32 个原 `image_measure/image_remeasure` 返回的绝对 manifest 路径。
- `current_image_object_id`：明确选定的当前图像／FFT／标定 wrapper；调用原校验拒绝旧标定或别源网格。
- `experimental_kind`、固定 `screen_axes:{flip_y,basis}`、预先给定的物理容差和旋转区间。
- `candidates`：1–3 个 `{label,source_path,zone_axes}`；每个区轴是三指数、非零互素且 `|index|<=3`。
  不默认把一般晶体约化为立方对称；显式列出值得试探的正负方向。
- `simulation`：同演示的显式物理参数；最多 24 组结构／区轴，每组最多 256 个旋转提议，超限拒绝而不截断。
- 可选 `followup_radius_inv_angstrom`：追加外侧目标预测；未指定时不声称完成跨结构的下一位置比较。

面内角只从径向长度在容差内的实验／模拟矢量对的极角差提出，加上区间起点；
这不是连续角度全局最优搜索。每次评分直接复用现有 `reflection_compare.compare`，
每个区轴的最佳完整比较通过原 `structure_compare` 提交并再次校验当前几何。
自动一对一 HKL 分配仍由既有匹配器执行。没有改动 `structure_register` 的确认门槛。
排序先看匹配数量，再看总残差；模拟未分配点数只展示，不作为未见实验峰的惩罚。

全部解释和对应均为 `hypothesized`，不会写成 `user_confirmed`。全部测量点参与了搜索，
独立留出验证为 **NOT_TESTED**。不比较运动学强度与 SAED 计数或 HRTEM FFT 对比，
不优化实验尺度、晶格、应变、平移、中心或镜像。无 MP 连接时不阻塞本地 CIF，
真实 MP 候选仍按 [materials-project-reference Skill](../skills/materials-project-reference/SKILL.md) 获取。

## 本轮验证范围

PASS：真实独立科学 worker 的合成 TIFF→提交测量→9 组取向比较→外侧预测→静态 PNG/HTML；
已目视检查 PNG。定点测试覆盖角度符号、边界、预算、零匹配、不可覆盖和已有反射／当前几何契约。
NOT_TESTED：真实实验数据、真实 DM/GMS、MP 服务、普通 MCP 客户端对新批处理的自动触发、
HTML 浏览器交互和完整 Windows/Python/C++ 回归。现有 MCP 科学工具未改变。
下一项实用改进是基于研究者修订或实测误差的更精细角度提议，而非扩大运行框架。
