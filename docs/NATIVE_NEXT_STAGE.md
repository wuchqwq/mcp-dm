# 下一阶段：按研究者的 DM 工作流补能力

核对日期：2026-10-24。对照对象是本仓库原生后端，而不是默认 Python 后端。
本表是官方功能线索与工程优先级，**不是新增能力或跨版本资格声明**。

## 官方功能与当前缺口

| 优先级 | 研究者要做的事 | Gatan 官方依据 | 当前原生缺口与接入要求 |
|---|---|---|---|
| P0 | 用刚刚在 GUI 画好的选区继续分析 | [官方 ROI 示例](https://www.gatan.com/Software/Scripts/Python-Library/Live-FFT-color-map) 使用 ImageDisplay 的 CountROIs/GetROI、ROI ID 和 GetRectangle | 当前工具要求手填像素坐标；应绑定 image_id/display_id/roi_id，先只读矩形/线，复制一次坐标并返回。不得静默采用最新窗口或找不到 ROI 就改成全图；不恢复示例里的 Python listener。 |
| P0 | 沿线/条带测强度、看分布 | [应用说明](https://www.gatan.com/Resources/Applications-Library/Application-Notes/Frame-Control-mode-for-optimized-imaging-and-diffraction-with-ClearView-camera) 描述内置 profile/histogram；[直方图官方脚本](https://www.gatan.com/Software/Scripts/DigitalMicrograph-Library/Interactive-histogram) 展示 ImageCalculateHistogram | 默认 Python 有 profile，但原生没有。先确定原生 ABI、采样/宽度/端点、距离标定、bin 边界、计数与非有限值政策；方差/标准差/中位数候选需各自验收，不手写替代核冒充 DM。 |
| P1 | 标出本次测量区域和结果 | [ImageDisplay annotation 示例](https://www.gatan.com/Software/Scripts/Python-Library/Adding-annotations-to-an-image-display) 展示线、箭头、框、椭圆 | 有 PNG 和 Show 但没有明确的原生注释管理；对受控结果文档添加命名/标识注释，不烘焙到科学像素，不清除用户原有注释，重复请求不重复创建。 |
| P1 | 比较 FFT/衍射斑点、晶格间距和角度 | [DIFPack 模块](https://www.gatan.com/Products/TEM-Software/Digital-Imaging-Modules/DIFPack-Module) 介绍峰定位、间距/夹角、中心与标定转移 | 本项目只有小尺寸 FFT/分量；没有掩膜→逆变换测量流程或峰测量。DIFPack 是单列模块：需要检查安装/许可/API，不能认作每个 DM 的基础功能，也不绕过许可。先做通用标定和明确点/线测量，不直接输出物相。 |
| P2 | 做径向/角向分析 | [Rotational average 官方脚本](https://www.gatan.com/ja/Software/Scripts/DigitalMicrograph-Library/Rotational-average) 使用 warp、极坐标和投影 | 属于官方脚本组合示例，不证明存在同名稳定 C++ 算子。明确中心、采样、插值、环边界、单位后再研究已验证原生操作的组合；不从脚本名猜 ABI。 |
| P2 | 对已采集堆栈做漂移校正、叠加与分箱 | [GMS 3.4 漂移演示](https://www.gatan.com/resources/media-library/situ-data-processing-gms-34-drift-correctionfull-frame) 和 [In-situ 技术说明](https://www.gatan.com/Technologies/In-Situ) | 现有 native 只做二维；需先声明 stack 轴/帧范围，再验证相关位移正负、插值、边界、sum/mean 和空间/时间标定。只做采集后数据，不接采集或硬件控制；检查所需模块。 |

官方 GUI、Python 或 DM-Script 示例是**功能线索**，不是当前 GMS 3.53 的原生
二进制调用契约。尤其有外部依赖的官方 Python 示例不能证明运算由 DM 内部执行。
不抄入监听循环、不猜函数签名，不因页面列出某功能就宣布 MCP 支持它。

## 在新增算子之前，先补三个实际瓶颈

1. **确定性的分块数据交接。** 当前 READ 最多 16,384 样本，FFT/滤波最多每轴
   256，无法直接满足完整日常图像交接。用代码规划不重叠批次，保存源身份、区域、
   参与数、dtype、科学语义和完成状态；缺块/重复块/源变化必须检测。保持有界
   内存，不让 Agent 手写随意拼接，也不冒称并发编辑下的原子快照。
2. **显式释放中间结果。** 当前最多保留 32 个结果/16 MiB。设计只释放插件自己
   对指定结果的引用，不关闭用户文档、不改变旧请求已完成的历史事实。查询应
   区分“操作曾完成”与“结果现在已释放”；处理 IFFT/来源依赖，不自动淘汰未知结果。
3. **数据进出与必要元数据。** 明确的打开/保存、强度标定与标签子树仍缺原生能力。
   保留已有 NPY 精确交接，不把它叫 SaveAs。原生保存应验证字符串 ABI、独占发布、
   失败恢复及重开；外部计算返回 DM 要有明确的新图创建和标定接口，不能靠任意脚本。

这些是工程缺口与优先级建议，不是从官网推断出来的稳定 API。
尺寸上限应按代表性输入逐步验证性能/内存后提高，不直接删掉保护。

## 下一轮推荐交付

先完成一个研究者能直接用的场景：

**GUI 选择矩形/剖面线 → 原生读取明确 ROI → 原生剖面或直方图 →
带单位的结果与选区注释 → 可重复的完整数值交接。**

同时补分块交接和结果释放，复用现有 NB2、版本适配和对象管理，不建新平台。
等这些能力稳定，再推进 FFT 掩膜/峰值测量、stack 配准和文件回传。
普通模型客户端测试可后置，但必须保留真实 DM、独立真值、源保护和生命周期验收。

## 给后续开发者的约束

- 先读取当前 capability 和具体 dtype/尺寸限制；默认后端有的功能不等于 native 有。
- 当前 scientific handoff 修复保留数学频率坐标与 DM 标定两套描述；后续工具不得再次丢失。
- 只处理用户授权的数据；界面 ROI 读取不得顺手修改用户选区或像素。
- 原生能力不足明确报不支持；显式外部工作流可用但不是隐式 fallback。
- 新算子调用和文件副作用单独验收；通用恢复/停止机制只做针对性回归，不反复造框架。
- 不合并兼容生成器 Draft RFC，不扩展 4D/EELS 定量和硬件控制来填充工具数量。

## 当前 feature 的收尾进展

结果引用释放和确定性有界分块交接已实现，并有独立合成实机证据；原始 READ 及算子尺寸限制保持不变。GUI 选区/剖面/直方图仍缺少完整 ABI 与一维输出契约，原生工作区枚举/切换也未通过资格确认。手动切换工作区已用于验证显式 image_id 和 SHOW 的行为；SHOW 不保证激活结果所在标签页。参见[具体契约、阻塞与证据边界](NATIVE_LIFECYCLE_HANDOFF.md)。
