# VASP 与现有 ASE 工具的衔接评估

核对日期：2026-10-26。本文件是接口调查与合成文件实验，**没有新增
VASP MCP 工具、安装或运行 VASP，也没有访问 PAW/POTCAR 或实验数据**。

建议将 VASP 作为独立的第一性原理计算来源：ASE 管理候选结构与文件，
VASP 在有授权的计算环境中求能量、力和弛豫结构；已有显微工具负责
观察、几何测量和显式的衍射/图像模拟交接。VASP 计算本身需要单独
配置可执行程序及势数据，安装 ASE 或 py4vasp 不会提供这些资源。
依据：[ASE VASP 接口](https://docs.ase-lib.org/ase/calculators/vasp.html)、
[VASP 官方许可说明](https://vasp.at/info/faq/)。

## 当前能力和建议顺序

下表的成本是实现判断，不是工期或数值精度承诺。

| 顺序 | 可形成的用户任务 | 当前状态 | 最小增量与成本 |
|---|---|---|---|
| 已有 | 打开 CIF/XYZ，查看通用晶胞和原子，量距离、晶面间距、晶向/晶面关系；显式运行运动学衍射 | `structure_*` 已实现；不是 VASP 能量计算 | 复用固定结构 ID、来源哈希、3Dmol 视图、ASE 度量及已准入的 diffsims 路径；偏斜晶胞模拟仍有明确门禁 |
| P0 | “打开我的 POSCAR/CONTCAR，对比弛豫前后的结构” | ASE 库有读写接口；当前 `structure_open` **只接 CIF/XYZ** | 扩展一个受限、定格式的结构入口，保留原子顺序、晶胞、Selective dynamics、原文件哈希及明确步号；低到中成本，无需 VASP 可执行程序 |
| P1 | “这次计算收敛了吗？晶格、能量和力改变了多少？” | 尚无 VASP 结果 MCP 入口 | 只读接入既有 OUTCAR/vasprun.xml；有 HDF5 时评估 py4vasp；区分电子收敛、离子收敛、正常结束和仅有最后一步；中成本，需要合法、可分享的测试夹具 |
| P2 | “为这个候选结构准备一份可审查的弛豫输入” | 未实现 | 用成熟 ASE VASP writer/calculator 准备显式参数和新输出目录，保留约束、初始磁矩、原子顺序及势版本/哈希；中成本；先只生成，不默认提交计算 |
| 后续 | 比较结构弛豫、缺陷/层错模型与碳候选模型的相对能量，再比较显微信号 | 未实现 VASP 执行或 abTEM 接口 | 用户已授权的 VASP/HPC 环境、计算参数收敛和参考态；其后独立调用成熟衍射或 multislice 引擎；科学验证成本最高 |

POSCAR 与 CONTCAR 的结构格式相容，但 CONTCAR 的存在不证明弛豫已收敛，
它可能只是最后一个离子步。ASE 还提供 OUTCAR 和 vasprun.xml 的结构、
能量与力读取接口；读取成功本身也不是收敛证明。
依据：[POSCAR](https://vasp.at/wiki/POSCAR)、
[CONTCAR](https://vasp.at/wiki/CONTCAR)、
[ASE 格式接口](https://docs.ase-lib.org/ase/io/formatoptions.html#vasp)。

## 最值得先做的三个接点

1. **保真结构导入。** 将 POSCAR/CONTCAR 作为已有 `structure_open` 的
   显式格式扩展，复用同一对象/视图/测量系统。先支持带明确元素的
   VASP 5/6 结构，不从邻近 POTCAR/OUTCAR 猜元素，不静默排序或标准化
   晶胞。若只支持几何快照，必须明确不等价于完整 MD 重启文件。
2. **已有结果的只读检查。** 先取用户指定计算的固定结果和明确离子步，
   返回能量、力、应力及各自单位、版本和收敛证据。解析不完整文件时
   标为部分/未知，不把最后一帧标为“优化成功”。电子 `EDIFF` 与离子
   `EDIFFG` 分开判断，正常退出也不替代它们。
   依据：[EDIFF](https://vasp.at/wiki/EDIFF)、
   [EDIFFG](https://vasp.at/wiki/EDIFFG)。
3. **弛豫结构接回显微比较。** 固定输入模型与弛豫输出的身份、计算设置
   和假设，再接已有 ASE 度量/diffsims；需要 HRTEM、ADF 或厚度效应时
   另接成熟 multislice。先做“原始模型→已有 VASP 结果→结构/信号对照”，
   比先造远程作业平台更快产生可审查的科研收益。此项是建议，尚未验收。

## 保真问题：不能只加一个文件后缀

私有合成实验使用 ASE 3.29.0，非正交晶胞和 C/Si/C 的原始原子顺序，
包含全固定及分方向固定约束。写出 POSCAR、同格式 CONTCAR 并重读：
晶胞和分数坐标在预设绝对容差 `2e-15` 内相同，Selective dynamics
掩码一致，文件哈希不变。结果为 **PASS_SYNTHETIC_ASE_IO_ONLY**，
不是 MCP 导入验收、真实 VASP 结果或计算验收。

同时确认两个必须处理的缺口：当前结构快照只序列化几何/占据信息，
不保留 ASE constraints 或初始磁矩；POSCAR 本身也不保存 INCAR 的
MAGMOM。将文件直接塞进现有快照会丢失计算语义。因此后续须显式保存
这些字段或明确拒绝保真导出；不能用归零磁矩冒充成功恢复。ASE 的
CONTCAR reader 对部分晶格速度信息也有已注明的限制，不能承诺完整
MD restart。依据：[ASE VASP reader/writer 源码](https://docs.ase-lib.org/_modules/ase/io/vasp.html)、
[ASE 自旋设置](https://docs.ase-lib.org/ase/calculators/vasp.html#spin-polarized-calculation)。

## 结果解析、许可与科学含义

py4vasp 面向已有 VASP HDF5 结果；官方当前提供只依赖 NumPy/h5py 的
`py4vasp-core`，可在独立环境中评估，不需要把完整绘图栈加入默认后端。
其官方许可证是 **Apache-2.0（不是 MIT）**，不等于取得 VASP 计算授权。
HDF5 兼容性仍须按实际 VASP/py4vasp 版本和文件验证。
依据：[py4vasp 官方说明](https://vasp.at/py4vasp/latest/)、
[官方许可证](https://github.com/vasp-dev/py4vasp/blob/master/LICENSE.txt)。

`vaspout.h5` 可能含完整 POTCAR 内容，不能把原始文件当公共测试夹具或
上传给不具授权的第三方；应优先保留在用户计算环境，并导出获准的
最小结构/数值及来源清单。[VASP 官方文件说明](https://vasp.at/wiki/Vaspout.h5)

VASP 能量可帮助检验候选模型的稳定性、缺陷和层错，但需一致的收敛
条件、组成/参考态、超胞与边界条件。碳的立方/六方金刚石与石墨要保留
实际基元、键合和堆垛；“FCC/HCP”标签不能代替完整原子模型，也不能
仅凭最低能量证明实验区域的唯一物相。这是后续工作流的科学要求。

CHGCAR 是电荷密度及 PAW 占据信息，LOCPOT 是由输出设置决定的局域势，
二者都不是 ADF/HRTEM 强度。要连接显微成像，仍须验证势的定义、PAW/core
处理、符号/单位/轴序以及束流、厚度、取向和探测/传递函数。abTEM 官方
提供 GPAW 直接接口及通用电荷密度路线，这不是已经完成的 VASP 适配。
依据：[CHGCAR](https://vasp.at/wiki/CHGCAR)、
[LOCPOT](https://vasp.at/wiki/LOCPOT)、
[abTEM DFT 势教程](https://abtem.github.io/doc/user_guide/tutorials/charge_density.html)。

## 本次验证范围

| 项目 | 状态 |
|---|---|
| 官方 ASE/VASP/py4vasp/abTEM 接口与许可资料 | 已调查 |
| 独立环境中的合成 POSCAR/CONTCAR 几何和约束读写 | PASS，有限文件 I/O 范围 |
| 新 VASP MCP 工具、真实 OUTCAR/XML/HDF5 导入、py4vasp 实际解析 | NOT_TESTED / 未实现 |
| VASP 可执行程序、PAW、DFT/弛豫/缺陷计算、HPC 提交 | NOT_TESTED，未执行 |
| VASP→显微模拟→DM 的完整链 | NOT_TESTED，建议方向 |
