# 研究者数据检查器与测量结果工作区

研究者可以直接打开本地图像、选区、做 FFT、测量和导出；不需要启动 Codex
模型会话。GUI 使用已有 `image_*` stdio MCP 服务和独立 Python 科学后端，
Agent 仍可选用同一工具和不可变结果。这里没有另一个计算引擎，也不连接 DM。

## 直接打开与重开

先准备 Node.js 18+，以及安装了 `requirements-images.txt` 的独立 Python 3.10+
环境。不要在 GMS Python 内安装依赖。第一次运行：

```powershell
node tools/researcher_inspector.mjs `
  --source 'C:\data\sequence.tiff' `
  --workspace 'C:\analysis\my-sequence' `
  --python 'C:\analysis\image-env\Scripts\python.exe' `
  --frame 1
```

用本地浏览器打开终端打印的 `http://127.0.0.1:.../#...` 地址。
保留终端进程；不需要模型、API Key 或 Agent 配置。URL 的 fragment 是本地访问
令牌，不要公开它。工具不上传图像，不开放任意文件读取或脚本执行接口。

支持范围沿用[像素图像工具](PIXEL_IMAGE_WORKFLOW.md)：普通灰度 `uint16` TIFF
页，每次有界读取明确帧；这不是任意 TIFF 或 DM3/DM4 导入器。`--frame` 是人类
从 1 开始的帧号，后端仍记录从 0 开始的 `frame_index`。

完成后在终端按 Ctrl+C 正常退出。保留整个工作区，之后运行：

```powershell
node tools/researcher_inspector.mjs `
  --workspace 'C:\analysis\my-sequence' `
  --python 'C:\analysis\image-env\Scripts\python.exe'
```

重开的是上次**保存的科学对象**及可恢复测量，不是重新执行 FFT。启动器只读取
其绑定工作区内的已知记录。不能把同一个工作区换绑到另一份 TIFF；另一份数据
用新的工作区。若上次还有未保存草稿，原 journal 保留，并提示本轮只恢复已保存
对象；不宣称把未保存编辑自动合入新视图。

启动和 GUI 的有副作用调用均先保存原请求 ID。启动响应丢失后，重开只查询原 ID，
不重发未知状态写入。失效、损坏或未完成记录明确报错。不要删除原请求记录后
以新 ID 冒充恢复。

## 从图像到结果表

1. 查看“当前科学数据”：文件来源、帧、ROI、科学数组形状和 dtype、坐标域、
   标定及来源。PNG 尺寸不是科学数组尺寸；未知标尺、强度单位和误差继续显示未知。
2. 框选 ROI，点 **FFT**；Hann/无窗、去均值在设置里可见并可改。
3. 在频谱上点一个峰，再点 **测量**。继续点其它峰并测量，多条结果同时保留。
   也可画线测量两点差矢量。点峰测量明确使用数学 DC；任意两峰差矢量不自动
   命名为晶面间距。
4. 点击结果行选择其对应标记；点画布上的测量标记定位相应行。属于其它帧或
   当前视野外的结果先提示，需显式跳转，不能把旧结果强画在当前图上。
5. 移动峰位后，只修订关联测量并保留旧版。拖文字、改字号、Gamma 或灰度范围
   只改显示，不改变科学数值。结果表的查看、排序和选择也不重算。
6. 有可靠尺度时在设置里填写 XY 数值、单位、作用范围和来源，再保存。修改尺度
   让受影响的旧结果显示待重测；选中结果后点 **更新选中测量**，保留旧版。

无标定仍可选区、FFT 和测像素/`cycles/pixel`。不会从 TIFF 灰度推断相位弧度，
从帧号推断深度，或从 FFT 几何吻合直接宣布物相。XY 尺度、中心、点位和标定版本
与数值一起保存；新标定不修改原图文件或已保存的复数 FFT。

结果表来自工作区已有 provider 的不可变测量记录，非标签文本、浏览器
`localStorage` 或仅 `last_operation`。折叠或拖动结果区上沿调整高度，画布继续占
主要空间。历史版本按需显示；详情包含端点/频率坐标、来源帧/ROI、标定与结果引用。

## 导出

选中结果行后可复制；**CSV / TSV** 默认下载当前可见行，勾选行则只导出勾选项。
表中保留单位、有效状态及
来源；未知值留空，不写成 0，历史或待重测值保留状态，不能冒充当前测量。
文本字段转义以防电子表格公式注入，真正数值仍作为数值列导出。

顶部 **导出** 仍将科学 NPY、可用 PNG、参数和来源保存到工作区内新目录。
既有[论文标注、SVG/PNG 与图面配方](PUBLICATION_ANNOTATIONS.md)继续可用。
显示 PNG 和标记不是原始科学数值，放大 PNG 不增加频谱分辨率。

## 本轮实际验证范围

Windows 的实际 Chrome 中，独立启动器连接真实 stdio MCP 与 Python worker，
完成了选 ROI、一次 FFT、三条测量、图表双向选择、单峰拖动、Gamma 修订、
标定修订后逐条重测、标签单独移动、刷新恢复及浏览器 CSV 下载。
手势由自动化执行，没有启动模型会话，也不是人类可用性评分。
数值、版本及文件哈希与原始 provider 记录独立核对。
另一个无标定浏览器实例返回 `40 px`，没有生成物理单位。

- [实际画布与结果表截图](examples/researcher-inspector/canvas-results.png)
- [浏览器实际导出的 CSV](examples/researcher-inspector/measurements.csv)

示例中的三个点来自公开合成纹理；为测试修订，尺度从合成 `0.02 nm/px`
显式改成 `0.025 nm/px`。这是人为测试条件，不是实验尺度或物相证据。
CSV 中的结果引用属于原验证工作区，样例文件本身不替代完整工作区。
实际 DM、Mac、真实实验物相及模型客户端视觉验收均为 **NOT_TESTED**。
原数组探针、ROI 统计及强度剖面通过独立 B2 增量接入，详见
[数值检查范围与用法](IMAGE_NUMERIC_INSPECTION.md)，不读取显示 PNG 灰度冒充原值。

## 公开合成例子与定点检查

以下命令创建新目录，拒绝覆盖已有数据：

```powershell
C:\analysis\image-env\Scripts\python.exe examples/make_microscopy_trial.py C:\analysis\inspector-fixture
node tools/researcher_inspector.mjs `
  --source 'C:\analysis\inspector-fixture\periodic-sequence.tiff' `
  --workspace 'C:\analysis\inspector-fixture-workspace' `
  --python 'C:\analysis\image-env\Scripts\python.exe'
```

这是三帧 `uint16` 周期合成纹理，不是实验或某种材料。独立已知频率为
`(1/8,0)` 和 `(0,1/16)` cycles/pixel；完整整数周期 ROI 可选
`[16,16,112,80)`。仅在这个合成例子中，按 `fixture-specification.json` 声明整组
XY = `0.02 nm/px`，对应理想周期 `0.16 nm` 和 `0.32 nm`。
用于第三条反射的负频率伙伴不是第三个独立结构证据。禁用窗口可检查理想精确
频点；使用 Hann 时保留实际设置，不混用不同处理的强度解释。

启动器自身相关测试：

```powershell
node --test tests/researcher-inspector-launch.test.mjs
$env:DM_RESEARCHER_ENTRY_REAL_TEST='1'
$env:DM_IMAGE_PYTHON='C:\analysis\image-env\Scripts\python.exe'
node --test tests/researcher-inspector-launch.test.mjs
$env:DM_INSPECTOR_PANEL_REAL_TEST='1'
node --test tests/image-panel-data-inspector.test.mjs
```

默认测试检查入口、来源隔离、请求持久化与恢复；显式开启的测试实际运行 stdio
MCP/Python，验证打开、PNG 返回和重开不产生新科学对象。结果区端点测试另检查
三条反射、独立修订、显示不重算、尺度失效/重测、响应丢失恢复和 CSV 重开数值。
**这些自动化测试没有运行浏览器**，
不能替代本轮 B1 实际浏览器逐步验收和截图。Mac、真实 DM 和模型视觉分别验收，
不由这些检查推出。
