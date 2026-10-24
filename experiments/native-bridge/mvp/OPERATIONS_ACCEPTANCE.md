# 原生操作验收范围

本页区分真实小型合成宿主证据、当前代码接入和待验功能。处理全部由指定构建
的 DM 原生接口执行；离线 reference 不进入运行时。真实实验数据、其它版本、
并发编辑及任意大图都不能由这些结果推定通过。

## 已完成的第一宿主验收

2026-10-24 的独立新合成会话已通过以下限定检查，并正常退出，exit code 0：

| 范围 | 结果与限制 |
| --- | --- |
| 三个 unary、三个 binary | 6 个结果逐像素吻合独立 raw 参考，复制标定；未测试 division |
| 四个原生 filter | 8×8 非对称整数图的固定核、边界和 Sobel 合成参考逐像素吻合 |
| Fourier 与分量 | 常数、矩形冲激、单频及非对称输入，共 22 个输出，固定参考逐值吻合 |
| 源保护与独立内存 | 同宿主 oracle 核对全部源像素、空间/强度标定、文档数与输出不共享内存 |
| 记录与恢复 | 预存请求记录、42 个提交检查、32 个结果及 34 个新客户端查询相关联 |
| Preview | 原生采样、灰度映射和 PNG 字节吻合固定显示参考；不等于模型视觉理解 |
| 生命周期 | 选定 arithmetic 结果只形成一个对应文档；STOP 后它由文档持有，其它 31 个未显示结果失效；关闭该文档后最后结果失效，源仍不变，普通一次性 Python 可继续使用 |
| 宿主结束 | 正常退出成功；没有将强制结束当作清理证据 |

数学报告自身不证明 UI 或 STOP；可见性、原始 STOP 请求/回执、文档关联及
before/after-STOP/after-close 是分开核对的证据。SHOW 的本次目标是一个明确
arithmetic 结果，不代表逐个显示了所有 Fourier/filter 输出。更早缺原始 STOP
请求的历史会话仍为 UNVERIFIED，不因本次通过而补成 PASS。

第一宿主使用 prepared 原生调用及 Fourier v1 观察记录。当前公开 Fourier v2
把已证实语义写入合同并收紧来源、尺寸和标定门；第二宿主已单独通过以下 MCP
链路。旧记录不改成新 schema，也不作为最终 production 二进制的实测证据。
非 ASCII 旧 Python/native 名称对照仍为 NOT_QUALIFIED，未作猜编码修复。

## 当前输入与结果边界

| 操作 | 当前代码边界 |
| --- | --- |
| mean / summary | float32 2D 最多 4,194,304 像素；普通 packing uint32 2D 最多 2,097,152 像素，限制最坏整数总和在 binary64 精确范围；raw intensity，仅 min/max/sum/mean |
| crop | float32 / uint32 2D，明确非空半开 ROI、不越界；输出最多 4 MiB；uint32 源最多 4,194,304 像素；完整空间标定，偏移须可精确表示，输出保持源 dtype |
| negate / abs / square | float32 或 uint32 2D、普通 packing、完整空间标定；独立 float32 输出最多 4 MiB；uint32 由 DM 以 binary64 计算后舍入 |
| add / subtract / multiply | 同 unary；两源同形状和空间标定，不广播，不支持 divide |
| FFT | float32 或 uint32 2D，普通 packing，完整有效空间标定；每轴为 4–256 的二次幂，最多 65,536 像素；uint32 先由 DM 舍入 binary32，输出 complex64 |
| IFFT | 仅本插件仍持有的 FFT full-complex 结果；不接受任意外部非 Hermitian 复数源 |
| real / imaginary / phase / power | 仅本插件仍持有的 FFT/IFFT full-complex 结果；产生独立 float32 图 |
| smooth / sobel / laplace / sharpen | float32 或 uint32 2D、普通 packing、完整空间标定；每轴 5–256；uint32 Smooth/Sharpen 输出饱和/截断的 uint32，Sobel/Laplace 输出 float32 |
| preview | float32 / uint32 2D、普通 packing，源最多 4,194,304 像素；输出每轴最多 128，不放大；非有限或无效 dtype 数值采样拒绝 |
| READ | float32 / uint32 2D、普通 packing，源最多 4,194,304 像素；明确 ROI 最多 16,384 样本／64 KiB；缺失标定明确保留问题，不编造单位；uint32 原字节交接不经 float32 |

基础 uint32 读取、统计和裁剪有[独立记录](UINT32_ACCEPTANCE.md)；新增算术、
Fourier、filter 和指定保留结果 SHOW 有[另一份逐项验收](UINT32_OPERATIONS_ACCEPTANCE.md)。
原有 float32 实机记录不作为新 dtype 的证据；准备版与最终生产构建分别记录。
整数运算和 Fourier 的输出精度不能据输入 dtype 被标成无损整数结果。

crop、算术、Fourier 和 filter 共用最多 32 个强引用、累计 16 MiB、单结果
4 MiB 的保留池。Fourier 分量验证和 Sobel 的已知临时图也在入场预算中；厂商
FFT/convolution 内部工作区没有完整上界，不能宣称整个进程工作集有界。
达到容量会明确拒绝，不通过遗忘旧结果 ID 来静默腾空间。

源描述符复核不是原子像素锁。只在空闲宿主串行运行，源图不被本操作请求写入；
实际源不变和独立内存来自限定合成 oracle，不是任意并发情形的保证。

## Fourier v2 的固定含义

DM forward 为正指数、未归一化、数据本身居中的 full complex；不去均值、不加窗、
不填充。配对 inverse 为负指数并除以 width×height，返回空间数据。实虚分量
直接来自 DM；phase 为 `atan2(imag,real)` 弧度，power 为 `real²+imag²`，不是幅值。
IFFT 的数值证据是四个 real-input FFT 所得 Hermitian 频谱的配对逆变换。

每轴输入带符号间距为 d、长度为 N 时，频率步长为 float32 的 `1/(N*d)`。
厂商 raw origin 为 `(N+1)/2`，物理零点保留实际读回值；DC 数组索引是 N/2，
厂商标定在该点有半 bin 偏移。v2 的 `frequency_grid` 另列数学坐标
`f(i)=(i-N/2)*frequency_step` 及实际 native zero/DC 值，不改 DM 标定来掩盖差异。
IFFT 恢复 signed scale 和空间单位，但 raw origin 与物理零点为 0，不恢复源偏移。
Fourier 输出强度标定重置为 origin 0、scale 1、空单位；分量继承父结果标定。

本次数值参考限定在 4×4 和 4×8 的可手算输入，不能据此承诺所有尺寸、其它
dtype/packing/单位或任意复杂输入的误差界。运行时只调用 DM，不加入科学像素
计算来修正结果。

## 四种滤波的已验参考

- Smooth：3×3 二项式核 `[1,2,1;2,4,2;1,2,1]/16`。
- Laplace：3×3 中心 8、其余 -1。
- Sharpen：3×3 中心 9、其余 -1。
- Sobel：两标准 3×3 方向核后取平方和开根号；不是绝对值之和。

在本次有限 float32 小图路径，Smooth/Sharpen 保留源的一像素外边框，
Laplace/Sobel 外边框为 0。报告的原生 kernel/edge 标签仍是 vendor_defined，
上述数学证据限定于已测构建和小图路径，不扩展成自写滤波实现。

## 第二宿主：有界交接及正常清理通过

第二个真实合成宿主的独立同 PID oracle 已返回
`PASS_BOUNDED_SYNTHETIC_HANDOFF`，原始请求、truth、实际活图和保存文件逐项绑定：

| 范围 | 已观察结果 |
| --- | --- |
| MCP | 十四工具目录与当前公开工具链；成功 READ 的同 ID QUERY 保持原响应，缺少副作用 request_id 明确拒绝 |
| READ → NPY | 源与 crop/square 结果的明确 ROI；原始 float32、shape/轴、signed zero 与 subnormal 逐 bit 一致；NPY/schema-1 文件及原生回执的 hash/身份链一致 |
| 源和归属 | 九个合成源前后像素、名称、空间/强度标定不变，文档数不变；结果独立内存，Python wrapper/view 已释放 |
| 原生处理 | crop、square 的独立固定参考；Fourier v2 FFT/IFFT/REAL 三个结果与四个 filter 的固定合成参考及标定一致 |
| 显示适配 | PNG 解码后的灰度采样/映射吻合独立参考；没有模型视觉理解声明 |
| 显式外部计算 | NumPy float64 raw mean、当前脚本和参数/软件版本/输入 hash 可追溯；capture 未改变，不调用或回传 DM |
| STOP | 原始请求已预存且获得同 session 回执；同 PID oracle 确认所有 11 个明确归属输出失效、九源与文档数不变、两份 capture 各三文件 hash 保持；先前失败前缀的结果仅核归属释放，不补成数学 PASS |
| 正常清理 | 宿主正常 exit code 0，manifest-owned 插件移除完成；未删除加载中的文件 |

第二宿主使用 prepared DLL。当前源码已把 arithmetic、Fourier、filter、preview、
READ 五组 profile 声明提升为限定真实宿主资格，生产准入依赖完整符号组，
不读取 `DM_NATIVE_QUALIFY_OPERATIONS`。缺少能力在版本实现和图像 lookup 前拒绝。
缺少符号不能借另一能力或环境变量回退。第二宿主的 loaded hash 不替换最终
production 二进制的单独加载证据。

## 最终 production 二进制：功能链与正常清理限定通过

第三个新合成宿主已核对实际加载 DLL 与最终离线构建产物一致，启动时没有
`DM_NATIVE_QUALIFY_OPERATIONS`。STATUS 为 SUPPORTED，五组新能力可用，SaveAs
仍禁用，没有 candidate 字段或绕过资格的环境门。真实 Node MCP 工作流记录
后，同 PID oracle 以 `qualification_mode:production` 返回
`PASS_BOUNDED_SYNTHETIC_HANDOFF`；本轮功能链记为
**LIMITED_SYNTHETIC_REAL_HOST_PASS**。

该最终二进制独立通过：两个 READ/NPY 的 float32 逐 bit 核对（含 ±0 和
subnormal）、源与 ROI 空间标定、九源前后像素/两种标定保护、独立内存、PNG、
Fourier v2 FFT/IFFT/REAL、四种 filter 及显式外部均值。十四工具目录已核对；
不是声称每个目录工具的所有输入都在本轮重新验完。

另有七项实际 MCP 安全拒绝通过：uint16、NaN、无效 ID、越界 ROI、4×4 filter、
3×3 FFT、非本插件 FFT 的任意 IFFT；这些失败的同 ID QUERY 保持原记录，未知
工具被拒绝。它们证明列出的拒绝场景，不构成厂商异常/并发崩溃隔离。

第三宿主原始 STOP 请求身份验证通过，同 PID 的
`PASS_UNSHOWN_HANDOFF_STOPPED` 核对九个明确生成的未显示输出全部失效，九源
像素/名称/空间与强度标定及文档数不变，两份 capture 各三文件原 hash 保持。
随后该宿主正常 exit code 0，manifest 为 removed，项目持有的插件文件已移除。
这次生命周期 PASS 来自最终二进制自己的证据，不继承第一、第二宿主结果。

正常退出后，在新的外部输出目录再次显式运行示例，成功重开原 captured NPY、
验证同一输入链并得到相同 raw mean，原 capture 保持不变。它证明已保存有界数据
可脱离 DM 继续使用，不是 DM SaveAs、永久文档或自动回传接口。

离线编码测试另覆盖同 ID 重复/冲突、已有目标、receipt 身份矛盾和短写/半写
失败；这些故障注入的范围与实际宿主成功链分开记录。流程见
[原生工作流](NATIVE_WORKFLOW.md)。

NPY 编码不等于 native SaveAs；文件保存、模型视觉理解、其它 GMS 构建和
Unicode 资格都保留各自的未验范围。新的宿主证据须绑定实际 PID/session、
加载二进制、预存请求、完整像素及生命周期后再更新此表。
