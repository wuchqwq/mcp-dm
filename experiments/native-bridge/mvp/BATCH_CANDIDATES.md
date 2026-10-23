# DM 原生操作：批量离线候选与续接清单

后续科学计算由 **DM 自己的算子**执行。MCP/C++ 负责显式数据身份、参数、
宿主调用、状态及结果交接；独立数学参考只用于验收。

**本批不是新增的可用 MCP 功能。** 公开原生目录仍为六个工具。下面的 C++
候选只连接合成回调，不加载厂商 DLL、不进入产品 DLL，也没有加入 NB1 操作
或工具 schema。所有候选均为 **NOT_QUALIFIED / 真实 DM NOT_TESTED**。

## 已准备的调用层

[candidate_calls.hpp](candidate_calls.hpp) 和
[candidate_calls.cpp](candidate_calls.cpp) 提供三种明确 POD 调用形状：
单图返回新图、双图返回新图、单图返回 double。目录包含精确导出名和证据限制，
不接受任意符号或脚本，不含像素处理、FFT、滤波或统计算法。

| 分组 | 合成可调用的候选项 | 仍须独立确认 |
|---|---|---|
| FFT / 逆 FFT | FFT、Real_FFT、Packed_FFT、IFFT、Real_IFFT、Packed_IFFT | 实/复/packed 输入限制、输出布局、归一化、频谱中心、相位、频率轴、工作区和生命周期 |
| 标量图像运算 | Abs、Negate、Square、Sqrt、Log、Log10、Exp | 输入域、非有限结果、输出 dtype、强度标定及源保护 |
| 复数分量与派生图 | Real、Imag、Arg、Conj、Norm | complex/packing、幅值/平方幅值/相位的准确含义；不靠名字猜单位 |
| 双图算术 | 加、减、乘、除 | 尺寸/类型兼容、单位与标定政策、除零、独立输出和源保护 |
| 内置滤波 | SmoothFilter、SobelFilter、LaplaceFilter、SharpenFilter | DM 实际核、边界处理、输出类型与标定；不宣称为 Gaussian/median 或带任意参数 |
| 相位相关 | PhaseCrossCorrelation | 原生数值含义、归一化、坐标及峰位解释；不冒充普通互相关或已经完成对齐 |
| 基础标量统计 | GetMinimum、GetMaximum、GetMean、GetSum、GetVariance、GetStdDev、GetMedian | 支持类型、raw/物理强度、非有限值、精度和方差/标准差/偶数样本中位数约定 |

共 **34 个合成回调候选项**；其中有多个同类变体，不等于 34 个已迁移工具。
薄包装的静态证据只支持调用形状和原生委派路径，不证明上述科学行为。
当前已有限实机验收的 `dm_native_mean` 仍使用原来的独立实现和约定。

候选调用层拒绝错误签名、缺少绑定、空输入、错误 sret 返回地址、空/别名输出
及非有限 double；它管理返回的新 owned 引用并在异常时清理。输入是借用引用，
输出按约定转交一份新 owned 引用。即使错误地返回源对象，也只释放新返回的
那份引用。这里的 release callback 必须是正确的引用释放，而非直接最终 delete。
这些合成检查不能证明厂商回调满足相同契约，不能提供原生异常隔离。

## 已识别但没有硬套进调用层的项目

| 项目 | 当前边界 |
|---|---|
| GetPixelCount | 原生返回 uint64，不冒充 double reduction，也不丢失整数精度 |
| GetMeanAndVariance / GetMinimumMaximum | 原生双输出参数形状，未适配为上述三类签名 |
| 几何变换 / rebin / stack 投影 | 部分原生导出已知；参数、枚举、轴和标定尚未形成接入契约 |
| 剖面 / 直方图 | 未准备完整的有界结果、坐标、类型及原生调用契约 |
| 打开文件 / 完整元数据 | 当前候选不提供；不能借此宣称原生已支持旧目录全部能力 |
| 科学保存 | SaveAs 的字符串/格式、禁止覆盖、失败和重新打开验证仍未闭合 |
| 预览 / 有界数值读取 | 没有合格的通用读法；不猜像素结构或把 packed 数据强转为实数组 |

目录另保留六个明确阻塞项：三个不同返回形状，以及 geometry/save/preview
三个类别。类别占位不是函数实现，不得计入已迁移功能。EDS/EELS、4D-STEM、
重构及硬件控制不属于本批候选。

## 离线构建与检查

按 [INSTALL.md](INSTALL.md) 使用指定的本地工具链和新输出目录：

```powershell
$candidateBuildDirectory = Join-Path $env:TEMP ('dm-native-offline-' + [guid]::NewGuid().ToString('N'))
& .\experiments\native-bridge\mvp\build.ps1 -Cxx clang++.exe -OutputDirectory $candidateBuildDirectory -OfflineOnly
& (Join-Path $candidateBuildDirectory 'candidate_calls_tests.exe')
```

[candidate_calls_tests.cpp](candidate_calls_tests.cpp) 验证精确目录/签名、全部
候选的合成参数传递、拒绝时不调用、输出/异常清理，以及 move/reset/不同
release context 的所有权。它不加载 Gatan，也不替代任何真实数值验收。
`build.ps1` 的产品插件链接源列表没有候选模块；旧协议、六工具和 v0.6 不变。
编译产物不是安装指令，也不能覆盖加载中的 DLL。

## 解锁后的续接顺序

1. **先核对并收尾原会话。** 使用 [UNLOCK_CHECKLIST.md](UNLOCK_CHECKLIST.md)，
   保留旧证据；核对实际宿主和显示文档，再检查 STOP 后持有、关闭本次结果后
   的最终释放、正常退出和 manifest 归属清理。缺历史 STOP 原始请求始终
   UNVERIFIED。不要在旧 stopped IPC 上重发或探索新算子。
2. **再选新空闲测试会话和一个候选。** 先闭合它的输入类型/packing、参数、
   预算、源保护和原生错误边界；使用当前精确构建门与正确的引用释放。
   将明确的结果接到既有宿主线程和 retained-record 路径，不增加第二套调度器。
3. **独立验收后再登记能力。** 保留请求前的 ID/session/参数及原回执；小合成图
   对照完整结果、标定、源不变、同 ID 查询和冲突。未闭合契约不公开为工具。
   FFT 用例另见 [FFT_READINESS.md](FFT_READINESS.md)。
4. **单独验收交付。** 现有 SHOW 仅接受 retained crop；新的处理结果不能冒充
   crop。明确结果持有、真实文档、STOP 后文档持有和最后释放；文件保存必须
   另验证重新打开，不用窗口或回执代替永久保存。

某个算子受阻时记录具体缺口，继续其它独立候选。不得用离线通过、另一个
算子的实机记录或旧 Python 结果填补本算子的资格。每项分别记录
STATIC_PARTIAL / OFFLINE_PASS / FAIL / NOT_TESTED / NOT_QUALIFIED。
