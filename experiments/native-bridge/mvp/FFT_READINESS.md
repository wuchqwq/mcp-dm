# DM 原生 Fourier：已验范围与剩余边界

原生 Fourier 已接入指定构建适配器，科学计算由 DM 的 Real_FFT、IFFT、Real、
Imag、Arg 和 Norm 完成。MCP/C++ 不另写 FFT、幅值、功率或滤波算法，也不回退
到旧 Python FFT。当前十四工具目录和显式使用方法见
[原生工作流](NATIVE_WORKFLOW.md)，逐项证据见 [操作验收](OPERATIONS_ACCEPTANCE.md)。

第一新合成宿主的 prepared 调用、独立数学、源保护、输出独立性、预览及
SHOW/STOP/最终关闭生命周期已限定通过，并正常退出，exit code 0。数学证明
使用常数、4×8 单点冲激、单频与 4×4 非对称图，共 22 个 Fourier/分量输出，
不是从预览亮度或旧 Python 输出猜约定。该批记录是 v1。第二合成宿主另外通过
当前公开 MCP 的 v2 FFT/IFFT/REAL 与固定参考、四种 filter、READ/NPY 逐 bit
交接及显式外部均值；其独立源保护、内存核对、同 PID STOP 释放、正常 exit 0
和 manifest 清理也通过。最终 production DLL 随后在第三宿主独立通过当前
MCP 链和 `qualification_mode:production` 的同 PID oracle，功能链记为
LIMITED_SYNTHETIC_REAL_HOST_PASS；加载产物身份已单独绑定。第三宿主自己的
原始 STOP、九个未显示输出释放、九源/文档/capture 保持已独立通过，随后正常
exit 0 并完成 manifest 移除；退出后的新外部运行仍可核验原 NPY 并重现均值。
当前 profile 已提升五组限定资格，production 不再读取 preparation 环境开关，
也不以目录名称或环境变量绕过能力检查。

## 目前的窄门

- FFT：显式 float32 2D、ordinary packing、finite、完整有效空间标定；每轴
  为 4–256 的二次幂，最多 65,536 像素。Real_FFT 的返回路径由 DM 自身转换为
  full complex，结果按 complex64 元数据处理，不把 packed 数据猜成普通数组。
- IFFT：只接受本插件仍持有的 FFT 结果；当前数学证据是 real-input 的
  Hermitian 频谱配对，不接受任意外部复数图或声称测完所有非 Hermitian 输入。
- 分量：只接受本插件仍持有的 FFT/IFFT 结果，生成独立 float32；phase 为弧度，
  power 为平方幅值。ID 和 immutable creation record 决定来源，不解析名字或前台图。
- 共享结果池最多 32 项／16 MiB，单结果最多 4 MiB；已知验证临时图计入入场预算。
  厂商内部 FFT 工作区未完全界定，小输入限制不是整个宿主工作集的上界。

正常失败会释放尚未提交的 owned reference；成功提交的结果由插件持有至
正常 STOP/cleanup。客户端取消不等于厂商计算取消；有副作用的提交前先保存
session、request_id 和参数，状态不确定时只 QUERY 同 ID，不自动重发。

## v2 明确的数值与坐标

Forward 使用正指数、未归一化，DC 数据位于居中数组索引；没有去均值、加窗或
padding。配对 inverse 使用负指数并除以 width×height。REAL/IMAG 为原生实虚部，
Arg 为 `atan2(imag,real)` 弧度（含 signed-zero 分支），Norm 为 `real²+imag²`，
不是幅值。不能把旧默认后端 `dm_fft` 的历史语义套在此处。

对长度 N、源带符号间距 d，native 频率 scale 为 float32 `1/(N*d)`，保留方向。
原生 raw origin 是 `(N+1)/2`，其物理零点保留实际读回值；DC 索引是 N/2，
因此 native 校准坐标有半 bin 偏移。v2 同时返回：

- 实际 DM 元数据和 native DC 值，不改标定。
- `frequency_grid` 的数学 bin 坐标 `f(i)=(i-dc_index)*physical_frequency_step`。

不可把 native raw origin、物理零点与数学 DC 混为一谈。IFFT 恢复 signed scale
和空间单位，但将原点设为 0，不恢复源偏移；`inverse_restores_source_origin:false`。
Fourier 输出强度标定为 origin 0、scale 1、空单位，分量复制其父结果标定，
不应用源 intensity calibration。首批输入的非平凡强度标定用于独立区分 raw 处理。

数学 reference 是验收工具，不进入插件。首批所有对照值准确吻合，仍只证明
4×4／4×8 的固定合成矩阵，未给任意尺寸、其它单位/packing/dtype 或大图精度
背书。缺失或无效空间标定在进入 Fourier 前拒绝，不猜 nm 或倒易 nm。

## 交付与待验事项

SHOW 可交付本插件持有的合格结果；本次独立可见性和文档持有试验选择了一个
arithmetic 结果，未逐一显示所有 Fourier 输出。STOP 后显示文档可保留其结果，
关闭该文档才释放最后引用；其余未显示结果在正常 STOP 后失效。旧缺原始 STOP
记录的历史试验仍为 UNVERIFIED。

Preview 已实现有界显示采样及 PNG content；它不等于定量导出或模型理解图像。
复数图需先明确选择 real、imaginary、phase 或 power 再预览。READ 和显式 NPY
编码针对有界实数数值，第二宿主已通过独立 bitwise 验收；不是 full-complex
文件保存或 native SaveAs。当前 v2 复现入口是工作流中的
`accept_handoff_mcp.py --qualification-mode production` 加同 PID oracle，
不是第一宿主历史 prepared v1 harness。
原生 SaveAs/Open 的路径、格式、禁止覆盖和失败语义仍未资格确认。

其它 GMS 版本、Unicode、任意复数输入和大尺寸不得自动继承 PASS。增加版本
必须独立绑定 ABI、模块身份、数值、标定及生命周期，见 [版本步骤](ADAPTERS.md)。
