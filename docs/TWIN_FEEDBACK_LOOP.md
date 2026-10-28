# 从研究者纠正到双域孪晶解释

这是 Hypothesis Explorer 的窄交互闭环：**单域初算 → 研究者指出孪晶 → 提出双域假设 → 重新比较并返回同一 Image Panel**。
既有图像、标定、测量和结构模拟工具仍是科学记录的来源，不新增聊天 UI 或通用 Runtime。
当前双域提议限定常规轴对齐、满占位、单元素四原子 FCC 胞；不把任意两个取向称作孪晶。

## 研究者如何使用

Agent 先把单域解释以已有 `image_annotate` 标到测量图中，再调用 `image_panel_open`。
研究者可以在同一 Panel 的“修订解释：这里有孪晶”中输入实际说明并提交，也可以在 Codex 对话中说明，
由 Agent 用既有 `image_context` 保存同形状的有来源声明。研究者不需要填写内部 ID 或 JSON。

新声明只含：

```json
{"research_observation":{"kind":"twinning_present","source_text":"这里存在孪晶；请继续检验具体关系。","authority":"user_confirmed"}}
```

`image_context` 在原有工作区保存不可变 context，provider 计算 `research_observation_scope`，
绑定精确图像／帧／ROI／数组网格。`confirmation_scope` 固定为 `twinning_present_only`。
`user_confirmed` 是调用者转述研究者声明，不是工具认证的身份或科学证明；它不确认孪晶面、具体取向或 HKL。
自动化演示必须选择 `synthetic_fixture`，Panel 会明确显示“合成演示（非真人确认）”。

提交声明不替换当前图、不消耗已选峰、不丢弃未保存显示或标记草稿。Agent 在研究者说“继续”后调用
`image_panel_current`，读取 `view.research_observation.object_id`，再运行下面的修订入口。
没有自动唤醒模型。声明、原图与旧 context 即使换了显示也仍保留；换视图后 Panel 提示复核原观察范围。
图像／标定更改后不能拿旧测量直接续算，沿用原有当前几何检查和重测要求。

结果通过已有 `image_panel_show` 送回同一个 panel_id，并绑定刚读到的当前图和草稿版本。
有未保存草稿时结果排队，研究者显式接受；不能为了展示成功覆盖草稿。

## 复现合成闭环

使用已装 `requirements-structure-tools.txt` 的独立 Python 环境，以及本分支的 MCP server。不能使用 GMS Python。
从仓库根目录运行以下命令，所有目录须为新的绝对路径：

```powershell
$fixtureRoot = Join-Path (Get-Location) ("outputs/twin-" + [guid]::NewGuid().ToString("N"))
python examples/twin_feedback_demo.py --output $fixtureRoot
$singleRoot = $fixtureRoot + "-single"
python tools/hypothesis_explorer.py --config (Join-Path $fixtureRoot "config.json") --output $singleRoot
$initialRoot = $fixtureRoot + "-initial"
python tools/twin_feedback.py initial --report (Join-Path $singleRoot "report.json") --output $initialRoot
```

Agent 保留返回的 `display_object_id`，在生成器的 `image-workspace` 中用 `image_panel_open` 打开它。
在 Panel 输入说明并选择“合成演示（非真人确认）”，提交后让 Agent 继续。
Agent 从 `image_panel_current` 得到已提交的 observation ID，再调用：

```powershell
python tools/twin_feedback.py revise --initial <initialRoot>/initial.json --observation <saved-observation-id> --output <new-absolute-revision-directory>
```

返回的 `display_object_id` 交给同一面板的 `image_panel_show`；原单域图像仍可按原 ID 查看。
`index.html` 是含前后叠加图、声明来源、八个试探、逐峰域／HKL／残差表和未解释项的独立页面。
`before-after.png` 可单独查看；`revision.json` 链接旧结果及其哈希、反馈 manifest、全部原工具证据。
写调用前保存并 fsync 请求；所有输出目录拒绝覆盖。中断后查询原 `image_result/structure_result`，不自动重放。

## 已实际执行的结果

2026-10-28，基于 #41 实际运行了科学 worker、真实 stdio MCP、现有 Panel 和浏览器表单：

1. ASE 生成 Cu FCC，`a=3.615 Å`。真值为两个周期域：A `[1 -1 0]`、B `[0 -1 1]`，
   面内参考均为 `[111]`、共同 roll `13°`。两次原 `structure_orient` 给出 `R_B=R_A T`，
   `T=(1/3)[[2,-1,2],[2,2,-1],[-1,2,2]]`，是绕 `[111]` 的正向 60° 关系。
   FCC Σ3 的 60°/⟨111⟩ 表述及立方对称等价关系见 [IUCr 原始论文](https://doi.org/10.1107/S1600576715004896)。
2. 两域均用原 `structure_simulate`：200 kV、半径 `0.9 Å⁻¹`、激发误差 `0.02 Å⁻¹`、无直射束，
   真值 raster 512²、sigma=1 px。两个库输出 raster 明确叠加，亮度权重为合成显示参数，不代表孪晶体积分数。
   加入一个有单独来源记录的非 Bragg 合成探测器伪点 `[335,322]`，用于检验是否仍保留未解释项。
3. 生成 uint16 TIFF 后重新读取，局部极大值取峰，再由原 `image_open/frame/calibrate/center/measure`
   提交 15 条真实测量记录。标定固定 `0.003515625 Å⁻¹/px`，DC `[256,256]`；
   容差搜索前固定 `sqrt(2)×pixel_scale = 0.00497184456 Å⁻¹`，不拟合尺度、中心、平移或镜像。
   初算配置没有真值 HKL、孪晶关系、域分组或反馈信息。
4. 单域搜索实际返回 8/15。通过浏览器在同一个 Image Panel 提交 `synthetic_fixture` 声明，
   再用 `image_panel_current` 取回原 context 引用。此次没有声称真人操作或真人确认。
5. 修订入口保留最佳单域取向和同一个实验→模拟变换，提议四个 ⟨111⟩ 轴、各 ±60°，共八个孪晶关系。
   `beam_B=Tᵀ beam_A`、`reference_B=Tᵀ reference_A` 转成互素三指数，交给原 `structure_orient`；
   独立核对 `R_B=R_A T` 后才模拟。具体孪晶关系、取向、域归属和 HKL 一直是 `hypothesized`。

| 阶段 | 已解释测量 | 域 A 独有 | 域 B 独有 | 重合 | 未解释 | 匹配 RMS / Å⁻¹ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 单域初算 | 8/15 | 8 | — | — | 7 | 0.00278604 |
| 反馈后的双域假设 | 14/15 | 6 | 6 | 2 | 1 | 0.00286017 |

RMS 只针对各阶段匹配的点，点集不同，不能把两个 RMS 直接当成优劣比较。
±60° 的 `[111]` 试探均达到 14/15；其他三轴的已试关系为 8/15。保留全部替代解释，不声称唯一孪晶关系。
第 9 个测量（零基 index 8）仍未解释，对应生成器注入的伪点；搜索和修订都没有读取这个真值标签。
同一 Panel 已实际显示 A、B、shared、unexplained 的新标记，旧单域结果和原声明仍可独立读取。

## 联合匹配和下一观察

不能把两个单域得分直接相加：共同反射会被计数两次，竞争对应也可能冲突。
这里读取两个原 `structure_compare` 的完整可行候选图，用带域名的真实 HKL 身份联合分配。
最大匹配数量／最小残差的原 SciPy 分配步骤只做了函数提取供复用，旧单域算法未改变。
数值上重合的投影只占一个列，每个实验峰最多计数一次；每个域的边仍须单独满足原容差。
`2e-12 Å⁻¹` 的投影重合界是数值识别界，不是把相邻反射按实验容差强行合并。
未分配模拟组、竞争对应及未解释实验点都保留。

下一观察建议为**分别获取拟议孪晶界两侧的局部图像 FFT 或局部衍射**，
检查 A 独有和 B 独有峰是否分别随区域出现，共同峰是否保留。单张叠加图和增加模型自由度后匹配增多，仍不足以证明孪晶。
当前样例没有生成原子级界面实空间图，因此该空间检验是建议，尚未实际执行。

Agent 生成的 `hyp-*` 域分类标记可随假设修订；不同 ID 的研究者标记保留。
若研究者将某个生成峰位标为 `user_confirmed`，原确认标记保留，新的域归属另加为 `hypothesized`，不会覆盖确认。
本入口只处理“存在孪晶”的纠正；移动峰位后须先重测，再建立对应的新初算，不暗中让旧测量跟随显示标记。

验证范围：PASS 为实际合成闭环和同 Panel 浏览器展示、定点数值／上下文／Panel 测试。
NOT_TESTED 为真人输入验收、真实实验、GMS、MP、原子级孪晶界、相干干涉、双衍射／动力学散射和独立留出验证。
数据生成与比较使用同一运动学模拟器；全部峰都参与搜索。没有用强度比估算域比例，没有放宽 `structure_register` 的确认门槛。
