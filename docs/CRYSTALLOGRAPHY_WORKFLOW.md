# 从 DM 数据到 FCC / BCC / HCP 候选

这是显式的**外部 Python 伴随工具**，不是新增的 DM 原生算子或自动判相服务。
现有 MCP 保持默认配置和接口，负责选对图像、原生处理和科学数据交接；Agent
在独立环境调用 `python -m crystallography`，取得可核对的测量和候选。

首版可以自动检测有界衍射图中的斑点，通过至少三组不共线 Friedel 对估计中心，
计算倒空间矢量、d、长度比和夹角，联合比较 FCC、BCC、HCP，并保留 P 歧义对照。
可读取指定 CIF，固定其中的常规晶胞参数检验候选。输出包括点位叠加 SVG、CSV、
完整 JSON、请求、程序副本、依赖版本和输入哈希。没有中心/点位统计误差时明确未知。

## 一次安装，常规任务尽量自动继续

在独立 Python 3.10+ 环境、仓库根目录运行。新版本依赖可能要求更新的 Python，
pip 会选择满足当前解释器的版本；每次分析记录实际版本。不要修改 GMS Python。

```powershell
python -m venv C:\analysis\crystal-env
C:\analysis\crystal-env\Scripts\python -m pip install -r requirements-crystallography.txt
```

NumPy/SciPy 提供数值、图像定位与分配；ASE 提供成熟的倒易晶胞与 CIF 解析。
许可、维护状态和其它方案的比较见[依赖调查](CRYSTALLOGRAPHY_DEPENDENCIES.md)。
无需 pymatgen、spglib 或 diffsims 才能完成首个流程；没有复制它们的结构/模拟算法。

## Agent 操作顺序

1. 使用现有 `dm_status` 核对真实后端、ready 和构建门禁；用明确图像 ID 选定数据。
   不按名字猜最新窗口。询问的重点是图像身份或缺失标定，而非逐步请求批准。
2. 对已授权的小区域调用原生 READ 或完整区域交接，保存原始请求和 NPY/schema-1
   包。大图只交接所需区域；首版伴随工具 NPY 上限 16 MiB。`dm_native_preview`
   用于看图，不能代替数值数据。若先裁剪/FFT，副作用请求 ID 必须提前保存。
3. 保存下面的请求。默认 `spots:"auto"`，衍射中心 `mode:"auto"`。已有正确单位
   和明确频率约定时直接分析；不反复让用户点击每个斑点。自动定位不能确定时保留
   候选证据和叠加图，才请用户提供中心或点表。
4. 外部命令运行并验证结果。文件均写入新目录，拒绝覆盖；已有结果使用 `verify`。
   缺完成标记表示未完成，不能把残留文件当成功，也不能借此自动重发任何 DM 操作。
5. 解释多个模型的共同拟合、残差、未匹配点及缺失证据。候选不等于化学物相结论。
   交接已保存后按原 MCP 生命周期释放插件结果，不关闭无关文档。

```json
{
  "schema_version": 1,
  "coordinate_frame": "source_pixel_centers_xy",
  "source": {"kind": "diffraction", "capture_directory": "capture"},
  "center": {"mode": "auto"},
  "spots": "auto",
  "calibration": {"mode": "capture_axes", "convention": "cycles_per_length"},
  "indexing": {"models": ["FCC", "BCC", "HCP", "P"], "max_index": 3}
}
```

`capture_directory` 和 CIF 相对路径均相对请求文件。`diffraction` 接受已有原生
单 READ 或完整分块包；`fft` 要求有完整且未再处理的原生频率来源。
`synthetic_diffraction` 只接受现有 mock capture2d 包，明确记录 `actual_dm:false`。
普通 Python 后端的真实 capture2d 包尚未接入这个加载器；不要将它改标为 synthetic。
这是 checkout 内的命令，不是新增 MCP 工具；Agent 需要文件和进程执行能力。

```powershell
# 调用前保存 request-id、请求文件和输出路径。
C:\analysis\crystal-env\Scripts\python -m crystallography run --request C:\analysis\request.json --output C:\analysis\result-01 --request-id crystal-01
C:\analysis\crystal-env\Scripts\python -m crystallography verify --output C:\analysis\result-01
```

退出码：0 表示计算/文件验证完成；2 表示 `NEEDS_REVIEW`，可用的定位或测量证据仍保留；
1 表示错误。`COMPLETE` 不表示已唯一识别物相。原捕获目录应保留，`verify` 会重新
检查其身份与全部已消费文件；哈希是保存证据的一致性检查，不是新的实机观测。

## 手动输入是补充，不是每次都要确认

自动模式复用 SciPy 局部极值、连通域、质心和稳健拟合。中心必须得到至少三组
不共线相反点支持、配对覆盖至少 70%、达到预设中点残差且无竞争中心。
这些是有限适用条件，不是统计置信概率。无中心亮斑也能工作；最亮点不直接等同直射束。
重叠晶粒、缺斑、束挡、饱和/环状或畸变图可能返回需要复核，不能强制成功。

对已明确给出中心的情况，包括原生 FFT 的数学 DC，`detection.exclude_radius`
在归一化、平滑和峰定位之前作用于独立工作副本。排除圆盘使用未排除像素的中位数
填充，亮 DC 不再通过平滑晕或强度尺度压住邻近反射；记录中的
`prelocalization_center_exclusion` 保留范围和处理依据。该步骤不修改科学输入，
不把最亮点认作中心，也不将显示用对数图用于测量。

手动模式使用 `center:{"mode":"user_confirmed","xy":[x,y],"sigma_px":[sx,sy]}` 和
`spots:[{"id":"s1","xy":[x,y],"sigma_px":[sx,sy]}, ...]`。
点坐标是**源图像像素中心**，不是缩小 PNG 或窗口坐标；区域偏移自动换算，不裁边、不取整。
索引需要 3..12 个非共线反射，单纯测量最多 128 点，使用 `indexing.enabled:false`。
自动索引的 `detection.max_spots` 为 3..12。自动定位的误差目前未知，不用拟合残差冒充误差。

有效测量点共线、无法约束二维索引时，返回 `NEEDS_REVIEW`（退出码 2），保留
已完成的间距/夹角表、标定、叠加图及具体原因，不丢弃仍可用的测量结果。
这只处理已识别的几何不可辨识性；身份错误、非有限数值、损坏输入和预算超限
仍是错误，不能被降为复核状态。可预先声明的搜索条件与安全边界见
[限制与分析设置](CRYSTALLOGRAPHY_GATES.md)。

## 标定和 FFT

- `capture_axes` 使用记录的 XY signed scale 和物理零点；nm 与 angstrom 显式换算。
  `cycles_per_length` 使用 `d=1/|g|`；`radians_per_length` 先除以 `2*pi`。
  例如 `1/nm` 不能单靠文字证明是哪种约定，调用方须声明；未知单位不生成 d。
- 已知标准可显式提供 `mode:"explicit"`、`scale_xy`、`unit`、`convention` 和 `basis`。
  这一步独立于物相匹配，不通过拟合候选反向修改标定。若另给 `zero_xy`，还须声明
  `zero_frame:"source_pixel_zero"` 或 `"capture_pixel_zero"`，避免 ROI 偏移造成歧义。
- 缺绝对标定可用 `mode:"relative", isotropic_pixel_geometry_confirmed:true`，只输出
  几何比值/角度与相对候选，不输出 d 或绝对晶格常数。不确认各向同性则不索引物理几何。
- `sigma_px` 和 `scale_sigma_xy` 是调用方给出的 1σ 标准差；缺任一项均标未知。
  当前线性误差传播考虑共享中心和轴尺度引入的角度相关性，不建畸变或自动估计噪声模型。
- HRTEM/ADF 路径先执行已有且符合类型/尺寸条件的 **DM 原生 FFT → 标量频谱 → READ/NPY**。
  请求用 `source.kind:"fft"`、`center.mode:"frequency_grid_dc"`。中心和坐标采用已有数学
  `frequency_grid`，保留 crop+READ 偏移与区域外 DC；不使用原生显示半格偏移代替数学频率。
  不新增外部 FFT fallback，不放宽原生尺寸限制；历史 ADF FFT 精度 FAIL 原样保留。

这条交接路径已有有限的真实宿主验收：新合成图经过 DM 原生正号、居中 FFT 与
power、实际 MCP READ、NPY/sidecar，再由独立 ASE/SciPy 环境自动测量；同时核对
signed 轴、ROI 偏移、原生半格标定与数学频率网格分别保留。有界的授权 ADF 区域
也完成相同的数据交接与外部测量，原图像素、标定和源文件另行只读核对。
这仅资格确认已执行的正向频谱与交接步骤，不包含新的 IFFT 精度保证、隐藏的外部
FFT 替代或普通 MCP 客户端验收。有限 ROI 的频率格距不能当成统计误差；相近 d
与六方度量匹配也不能独自证明金刚石多型或其它碳相，具体基底须按参考结构另行检查。

## 候选比较能说明什么

FCC/F、BCC/I 使用立方度量与中心化条件；HCP 使用 ASE 常规六方晶胞（γ=120°），
分别保留 a、c、`c/a`、反射 `(hkil)`、三/四指数晶带轴。多个反射共享同一取向和尺度，
用 SciPy 一对一分配后联合检查残差，不能逐点拼接不同晶体答案。

无参考 HCP 默认在预先记录的有限 `c/a` 网格 1.50..1.90 中比较，包括理想值；这不是
通用 HCP 范围或连续拟合结果。可用 `c_over_a` 或 `c_over_a_candidates` 覆盖，最多13值。
基面反射不能确定 `c/a`，结果会保留这个歧义。反射指数上限 1..4，最多 50,000 搜索种子；
超预算明确拒绝，局部噪声精化不承诺穷尽所有解。显示数量限制不会抹掉已发现的模型歧义。

指定参考时增加 `references:[{"label":"candidate-A","model":"HCP","cif":"candidate.cif"}]`。
支持 FCC/BCC/P 常规立方或 HCP 常规六方 CIF1 单结构；拒绝需要猜测转换的菱方/原始设置。
由 ASE 读取，保留原始字节、解析警告和单位，固定参数不会为匹配暗中重拟合。
解析晶胞不验证化学、占位、空间群或实际 HCP 堆垛。HCP 理想双原子消光仅作诊断，
电子动力学/多重散射可能使运动学禁反射出现。所有模型都不是单张图的唯一化学物相证明。

## 可运行演示及证据边界

```powershell
python -m examples.crystallography_demo --workspace C:\analysis\demo-fcc --model FCC
python -m crystallography run --request C:\analysis\demo-fcc\request.json --output C:\analysis\demo-fcc\result --request-id demo-fcc-01
python -m examples.crystallography_demo --workspace C:\analysis\demo-hcp --model HCP
```

使用上面独立环境的解释器运行。演示生成的是**外部合成高斯点位**，不是 DM 计算或
电子衍射强度模拟。请求不含中心/斑点数值答案；独立答案在 `answer-record.json`，运行时不读取。
实测/模型/文件结果应分别报告。上述有限实机交接不替代标准样品的晶体学标定、
物相判断或普通 MCP 客户端验收；保存回执一致不等于重新读取了真实宿主。
实际范围见[验收记录](CRYSTALLOGRAPHY_VALIDATION.md)，后续进展见 [Issue #11](https://github.com/wuchqwq/mcp-dm/issues/11)。

给 Agent 的短提示：

> 读取指定捕获的身份和标定，用独立环境中的晶体学伴随工具自动分析中心和斑点，同时比较
> FCC、BCC、HCP 并保留 P 对照。先保存请求 ID 和参数；输出点位图、间距/夹角与联合索引候选。
> 缺单位或中心有多解时说明具体缺口，不猜答案、不改源数据，不把几何候选说成唯一物相。
