# GMS 兼容性工程：证据、工具与边界

本文说明 MCP-DM 现有原生 Adapter 的实际状态、哪些 ABI 信息可以被确定性工具自动提取、
哪些只能算静态候选、哪些必须由真实宿主验收，以及本轮新增的离线兼容基础设施
（`tools/gms_compat/`）如何在不放松任何门禁的前提下支持跨版本研究。

范围声明：本工具不加载厂商 DLL、不启动 DM、不执行目标文件中的代码、不解析任意地址，
也不会把任何候选提升为可用能力。它输出的是**可复核的差异与缺口**，不是兼容性结论。

---

## 1. 当前 Native Adapter 架构与已验证范围

### 1.1 分层

| 层 | 位置 | 是否含厂商信息 |
| --- | --- | --- |
| Node MCP facade | `server.mjs` | 否 |
| NB2 传输、请求记录、结果生命周期 | `lib/native_bridge.mjs`, `experiments/native-bridge/mvp/core.cpp` | 否 |
| 版本选择与兼容状态 | `adapter_profile.hpp`, `adapter_identity_win.hpp` | 否 |
| 通用分派 | `adapter_dispatch.inc` | 否 |
| 版本专用实现 | `adapters/gms_3_53_4137/` | 是（指纹、POD、入口 RVA、签名） |

选择的唯一入口是 `select_adapter`：先比较可执行文件名、文件版本与 PE 架构，再逐个核对
五个模块的 SHA-256（`mfc140.dll` 只校验哈希不校验版本），随后解析显式列出的导出符号。
任何一步不满足即返回 `UNSUPPORTED_BUILD` 或 `ABI_MISMATCH`，并且**在触碰任何厂商调用之前返回**。
未知构建只读取 Windows 元数据，不探测导出表以外的内容，不扫描入口。

### 1.2 能力门禁

能力以独立组声明（`native_crop`、`native_read`、`native_fft`、`native_line_profile`、
`native_histogram` 等）。一个组的可用性需要同时满足：

1. 适配器整体 `SUPPORTED`；
2. 该组的 `qualified` 声明为真；
3. 该组**全部**必需导出（以及非导出的 `entry_contract`）在该构建上可用。

`adapter_dispatch.inc` 在进入版本实现之前把请求映射到组名，缺组直接抛
`native_capability_unavailable`。catalog 条目本身不等于能力准入。

### 1.3 已验证范围（必须逐字理解）

- 仅 `Windows x64 GMS 3.53.4137.0`，且五个模块指纹全部匹配。
- 证据来自**有界合成真实宿主**验收：合成图像、合成 GUI fixture、独立的同 PID oracle。
- 覆盖：核心元数据、mean/SUMMARY、crop、READ、PREVIEW、SHOW、uint16 FRAME、
  float32/uint32 算术与滤波、Fourier v2、GUI 矩形 ROI、真一维 line profile、histogram、
  有界数值导入。
- **不覆盖**：其他构建或其他架构、真实实验数据、并发编辑、模型侧视觉确认、
  任意 dtype/layout、SaveAs/OpenImage、workspace 激活、注释写回。

历史失败不被后续成功覆盖，例如同栈销毁 document 持有引用、非 ASCII 名称比较、
binary64 表达式幂 oracle 的 FAIL，均单独保留。

---

## 2. 现有 ABI 信息中哪些可以自动提取

`gms-compat inspect` 的自动提取范围，全部来自 PE 文件本身，不依赖厂商文档：

| 项目 | 来源 | 可靠性 |
| --- | --- | --- |
| 文件 SHA-256 | 逐块读取 | 确定性事实 |
| 架构（x86/x64/arm64） | COFF `Machine` | 确定性事实 |
| PE 形态（pe32/pe32+）、节表、`SizeOfImage` | 可选头 + 节表 | 确定性事实 |
| 文件版本 `a.b.c.d` | `RT_VERSION` → `VS_FIXEDFILEINFO` | 确定性事实（缺失则显式 `absent`） |
| 导出：名称、序号、RVA、所在节、是否可执行、是否转发 | 导出目录 | 确定性事实 |
| 导入模块关系与 thunk 数量 | 导入/延迟导入目录 | 确定性事实 |

不可自动提取、本工具也不猜测的内容：

- 调用形状（sret、参数顺序、寄存器分配、`this` 位置）；
- 对象布局、对齐、所有权与销毁配对；
- 非导出入口的地址（必须逐构建重新定位，见 §6）；
- 数值约定（归一化、centering、饱和/截断）；
- 任何“两个同名导出 ABI 相同”的结论。

`compare` 只在上述事实层面比较。它不会读机器码，因此**相似机器码不可能被它当成证据**。

---

## 3. 哪些证据仅为静态候选

`docs/GMS_COMPAT_ABI_EVIDENCE.md` 中 `STATIC_CANDIDATE` / `UNRESOLVED` / `BLOCKED` 三类
即“没有真实宿主执行证据”的集合，当前包括：

| 条目 | 状态 | 原因 |
| --- | --- | --- |
| `processing.fourier_packed_candidates`（`FFT`、`Packed_FFT`） | STATIC_CANDIDATE | 只闭合了 one-pointer reference 骨架；复数存储、归一化、centering、workspace 边界未定 |
| `presentation.plot_style` | STATIC_CANDIDATE | 一个字节的 setter/getter 已静态闭合，但发货禁用，重绘行为无法验收 |
| `processing.other_signatures` | BLOCKED | `GetPixelCount`/`GetMeanAndVariance`/`GetMinimumMaximum` 签名不匹配已绑定的三种回调形状 |
| `blocked.save`（SaveAs） | BLOCKED | 字符串构造只是部分证据；格式保持、独占写、源名突变、错误/所有权未定 |
| `blocked.whole_file_open` | BLOCKED | 任意文件读取的语义与所有权从未闭合 |
| `unresolved.workspace_activation` | UNRESOLVED | 候选对象族与 `GMS::Image` 引用契约不同构 |
| `superseded.probe_lookup` | BLOCKED | 对象地址令牌不是稳定 ID，旧 PE resolver 已退役 |

这些条目在 `compare` 输出里可以出现（作为高风险项），但它们的 `qualification` 不会被工具改写。
工具没有任何写路径可以修改证据文件里的资格字段。

---

## 4. 哪些调用必须依赖真实宿主验证

以下事项无论如何都无法由静态工具证明，必须在目标构建的真实宿主上单独验收：

1. **调用形状**：sret 指针位置、参数顺序、返回值寄存器。静态可推断，但只有执行才能确认。
2. **对象布局与对齐**：`NativeImageRef`、`NativeDataSlice`(176B)、`DataSize353`(48B)、
   `CharRange353`(16B)、MSVC `std::wstring`(32B)、document holder(16B)、引用计数前缀。
3. **所有权与销毁配对**：引用计数递减、`ref_ptr_delete` 仅在计数归零时调用、
   `mfc140.dll` ordinal 1487 与厂商分配器配对。
4. **数值语义**：Fourier 符号/归一化/centering、滤波边界、uint32 饱和与截断、
   histogram 计数完整性。
5. **GUI 身份与几何**：display/ROI 身份链、`slice_ids`、直接 `ImageSource_Simple` 布局。
6. **文档生命周期**：SHOW 后的可见性、STOP 后引用失效时机（同栈销毁已 FAIL，空闲后观测才 PASS）。
7. **dtype 映射**：type code 2/11/12 与真实存储的一致性。

对应地，证据清单中每条 `QUALIFIED_LIMITED` 都带 `verification.real_host` 记录；
校验器会拒绝没有 `PASS*` 记录却被标为 `QUALIFIED_LIMITED` 的条目。

---

## 5. 现有架构与跨版本适配之间的最小缺口

按“最小必要”排序：

1. **证据不可机器校验**（本轮 P0 已补）：ABI 知识原先散落在 Markdown 与 C++ 常量里，
   无法回答“这条结论依据是什么、是否已验收、换构建后哪些必须重推”。
2. **没有构建间结构对照**（本轮 P1 已补）：面对新构建只能人工比对导出表。
3. **非导出入口无法静态推导**（P2）：`GMS.dll` 中文档工厂、SHOW、ROI、line extract 的入口
   只有固定构建的 RVA。任何构建变化都必须重新定位，当前只能手工完成。
4. **资格仍是手工编辑 C++ 常量**（P2）：`profile.hpp` 的 `qualified` 是人工审阅后写入的，
   没有模板化的候选产物与验收计划生成。
5. **没有“候选 → 验收 → 提级”的固定流程**（P2）：缺一套默认禁用、可 diff、可审查的
   候选 Adapter 骨架。

本轮不触碰第 1、2 项之外的任何东西：正式 C++ Adapter、已验证 SHA、能力门禁、
运行时分派、`server.mjs`、MCP Schema、默认 Python v0.6 后端、安装机制均未修改。

---

## 6. 本轮交付

### 6.1 `tools/gms_compat/` 结构

```text
tools/gms_compat/
  cli.py                     inspect / compare / audit / evidence 子命令
  pe.py                      只读 PE 解析（mmap + 界限检查，不加载、不执行）
  manifest.py                模块清单模型、规范化、路径脱敏、稳定序列化
  compare.py                 结构对照与能力影响映射
  audit.py                   单清单 vs 证据清单的一致性核对
  evidence.py                证据清单校验、查询、Markdown 渲染
  evidence/abi_evidence.json 机器可读 ABI 证据（唯一事实源）
  schema/*.schema.json       供非 Python 消费者使用的契约
```

### 6.2 `inspect`

- 输入：显式指定的本地 PE 文件或目录（目录默认 `*.dll`/`*.exe`，非递归，模块数有预算）。
- 输出：`schema: mcp-dm/gms-compat/module-manifest`，模块按名称排序，导出按 `(ordinal, name)` 排序，
  JSON 键排序、固定缩进、以 `\n` 结尾 → 同输入两次运行逐字节一致。
- 明确错误码（节选）：`pe_file_missing`、`pe_file_empty`、`pe_file_too_large`、
  `pe_dos_header_truncated`、`pe_dos_magic`、`pe_lfanew_out_of_range`、`pe_nt_signature`、
  `pe_optional_header_truncated`、`pe_optional_magic_unsupported`、`pe_section_table_too_many`、
  `pe_rva_unmapped`、`pe_export_table_too_large`、`pe_export_name_ordinal_mismatch`、
  `pe_resource_directory_invalid`、`pe_version_resource_invalid`。
- 路径脱敏：`--disclosure none|basename|relative|full`，默认 `basename`；
  `relative` 必须配 `--redact-root`，否则拒绝。报告中同时声明 `read_only: true`、
  `loaded_any_module: false`、`executed_any_target_code: false`。

### 6.3 `compare`

输入两份清单，输出 `schema: mcp-dm/gms-compat/comparison`：

- `modules[].status`：`IDENTICAL` / `CHANGED` / `MISSING_IN_CANDIDATE` / `ADDED_IN_CANDIDATE`；
  `IDENTICAL` 需要哈希、架构与命名导出面同时一致。
- 每个模块的 `exports.detail` 分桶：`identical`、`rva_changed`、`forwarder_changed`、
  `section_changed`、`removed`、`added`，另有 `rename_candidates`。
- `abi_unknown`：模块二进制变化后，同名（甚至同 RVA）导出依然列入未知，理由字段写明
  “name/RVA 不构成调用形状证据”。
- `high_risk`：变化导出若在证据清单中有绑定，给出 `evidence_entry` 与需重推的项目。
- `manual_review`：变化模块上的非导出入口契约，理由固定为
  “RVA 不能跨构建转移，必须在候选构建上重新定位并记录新的静态证据”。
- `affected_operations`：受影响的既有能力组（来自证据清单的 `scope.operations`）。
- `qualification.state` **恒为 `REFUSED`**，`may_authorize_calls` 恒为 `false`。

`rename_candidates` 仅由“同一 RVA、一删一增”产生，`confidence: low`，
并显式带 `establishes_equivalent_abi: false`。

### 6.4 `audit`

`compare` 回答“两份构建之间变了什么”，`audit` 回答另一个更窄的问题：
**针对这一份构建，哪些已记录的 ABI 绑定存在、哪些缺失、哪些永远无法离线确认。**

输出 `schema: mcp-dm/gms-compat/audit`：

| 字段 | 含义 |
| --- | --- |
| `modules[].pinned_sha256_match` | 与固定 profile 的哈希是否一致（未知模块为 `null`） |
| `modules[].missing_exports` | 缺失的导出/序号绑定，附带绑定它的证据条目 |
| `modules[].non_export_contracts` | 该模块上依赖非导出入口的契约名 |
| `capabilities[].state` | 见下表 |
| `summary.non_export_contracts` | 无法离线核验的入口总数 |

能力状态：

| 状态 | 含义 |
| --- | --- |
| `EVIDENCE_COMPLETE` | 全部导出绑定存在、全部证据条目为 `QUALIFIED_LIMITED`、无非导出依赖 |
| `CONTRACT_UNVERIFIABLE` | 绑定存在且已验收，但功能依赖非导出入口，文件层面无法确认 |
| `SYMBOL_MISSING` | 至少一个必需导出/序号缺失 → 该能力在该构建上必然不可用 |
| `EVIDENCE_INCOMPLETE` | 绑定存在，但支撑条目本身不是 `QUALIFIED_LIMITED` |
| `REFUSED_BY_EVIDENCE` | 该操作的全部证据条目都是 `BLOCKED`（如 SaveAs） |

`audit` 的 `qualification.state` 同样恒为 `REFUSED`，并显式声明能力覆盖由
“证据条目的操作范围并集”推导，而非版本 profile 的逐能力符号表，因此可能低估
某个能力额外需要的符号。

### 6.5 对真实安装的只读核对

对一台已安装 GMS 的机器（只读、仅本机、未上传任何厂商文件）执行：

```text
$ gms-compat inspect <install>/{DigitalMicrograph.exe,GMSImage.dll,GMSImageProcessing.dll,GMS.dll} \
                     %SystemRoot%/System32/mfc140.dll -o installed.json
$ gms-compat audit installed.json
modules present 5/5   hash matched 5/5   export bindings 46/46 present   missing 0
non-export contracts 27
capability states: EVIDENCE_COMPLETE 35 | CONTRACT_UNVERIFIABLE 7
                   EVIDENCE_INCOMPLETE 1 | REFUSED_BY_EVIDENCE 1
```

由此得到三个此前未记录的结构性事实：

1. **固定指纹可复现**：五个模块（含 `mfc140.dll` 14.51.36247.0 的 ordinal 1487）
   与 profile 逐一匹配，说明证据清单描述的就是这套安装，而不是历史推测。
2. **已用 ABI 面极窄**：`GMSImage.dll` 有 1033 个命名导出，证据只绑定 18 个（1.7%）；
   `GMSImageProcessing.dll` 328 个中绑定 27 个（8.2%）。其余导出全部处于“存在但未验证”状态，
   `audit` 不会因为它们存在就提高任何资格。
3. **`GMS.dll` 的导出表几乎不携带信息**：它只有 64 个导出，而适配器在其中绑定 27 条
   **非导出**入口（文档工厂、SHOW、ROI、line extract、plot style）。这直接说明：
   对 `GMS.dll` 而言，导出表对照基本无效——`compare` 只能通过模块哈希变化提示风险，
   27 条契约必须逐条人工重新定位。这正是 `compare` 输出 `manual_review` 的原因，
   也是 P2 必须引入静态反汇编辅助的核心理由。

### 6.6 入口重定位结构分析（只读静态筛查）

为回答“换构建后这 27 条非导出入口要怎么找回来”，对同一安装做了三项互不依赖的静态筛查。
全部为只读、本机执行，结论只保留聚合数字，不记录任何地址或偏移。

**（1）导出与地址层面：没有捷径。** 27 条入口全部位于 `.text`、16 字节对齐，
且**没有一条**与任何导出同址，即不可能通过导出名解析到它们。

**（2）调用图层面：从导出出发不可达。** 由 PE 异常表（`.pdata`）恢复 49,615 个函数区间，
再扫描直接调用指令得到 88,254 条被调用者→调用者边（0 个调用点落在函数区间之外，
可作为扫描完整性的交叉校验）。结果：

- 27 条入口中只有 **1 条**能在 6 跳内到达任何导出函数；
- **17 条**在整份 `.text` 中没有任何直接调用者——它们只经间接调用（虚表）、
  窗口过程或脚本层注册到达。

结论：**“顺着导出往下追”不能作为跨构建重定位策略**。

**（3）函数边界层面：`.pdata` 会漏掉叶函数。** 27 条中有 6 条完全不落在任何
`.pdata` 区间内。逐字节检查显示它们是被 `INT3` 填充包围的叶函数，典型形态为
单条取字段指令后 `ret`、常量返回、或对另一函数的一条尾跳转。
因此新构建的函数边界恢复不能只依赖 `.pdata`，必须同时识别叶函数岛。

**（4）引用形态层面：三条重定位通道。** 统计入口地址在只读数据段/数据段中
作为 8 字节对齐指针出现的次数，并按 RTTI（完整对象定位器 → 类型描述符）判定其是否
落在某张虚表内：

| 形态 | 条数 | 含义 |
| --- | --- | --- |
| `vtable_slot` | 8 | 位于具名类的虚表中（两类：显示对象族、直接图像源族） |
| `data_pointer` | 5 | 在数据段出现一次，形态接近注册表条目，非虚表 |
| `code_only` | 14 | 无任何对齐数据指针，只能从代码引用 |

其中 2 条（`roi_raster_mapping`、`roi_raster_slice_id`）在 7 张继承自同一基类的
虚表中占据**相同槽位**，说明它们是基类实现、派生类未覆盖——这对重定位是强信号：
槽位号比地址稳定得多。

这两处结论同时构成了对既有 profile 的独立复核：`docs`/`ABI_NOTES` 中“RasterImageDisplay
vtable”与“直接 ImageSource_Simple 布局”的判断，在本轮通过类型描述符名称被独立复现，
而不是引用原文。

### 6.7 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 完成（`compare` 发现差异也算完成） |
| 1 | 策略性失败：证据校验不通过、`--fail-on-change` 检出变化 |
| 2 | 输入失败：不可解析/缺失/超限的 PE、非法清单、未知条目 |
| 3 | `evidence render --check` 检出文档与 JSON 漂移 |

### 6.8 实际执行结果

环境：Windows，Python 3.13，仓库内 `python -B`。fixture 为自制合成 PE（无任何厂商代码）。

```text
$ python tools/gms_compat/cli.py evidence validate
evidence valid: 34 entries

$ python tools/gms_compat/cli.py evidence render --check
evidence render up to date: docs/GMS_COMPAT_ABI_EVIDENCE.md
```

两套合成构建（A=3.53.4137.0，B=3.54.1.0；B 中 `GetMean` 移位、`GetSubSliceAsImage` 改名、
`GMS.dll` 变化）的对照结果：

```text
$ python tools/gms_compat/cli.py compare A.json B.json
summary: changed_modules=2  exports_rva_changed=2  exports_removed=1
         exports_added=1   high_risk=3  affected_operations=19
qualification: {"state": "REFUSED", "may_authorize_calls": false}
high_risk: GMSImage.dll ?FindByID...        -> image.lookup
           GMSImage.dll ?GetSubSliceAsImage -> image.sub_slice
           GMSImageProcessing.dll ?GetMean  -> processing.reductions
```

当候选构建的 `GMS.dll` 发生变化时，`manual_review` 会列出 6 条非导出契约
（`document.factory_show`、`document.holders`、`presentation.plot_style`、
`roi.display_resolution`、`roi.geometry`、`roi.line_profile`），要求逐条重新定位。

### 6.9 测试

新增 `tests/gms_compat_pe_fixture.py`（合成 PE 生成器）与四个测试模块，共 **83 个用例**：

| 文件 | 覆盖 |
| --- | --- |
| `test_gms_compat_inspect.py`（16） | 版本/架构/哈希、转发导出、导入关系、缺失版本资源、截断/非 PE/空/超限输入、逐字节可复现、路径脱敏、目录预算 |
| `test_gms_compat_compare.py`（19） | 完全一致但不授予资格、哈希变化、同名不同 RVA、同名同 RVA 仍未知、架构变化 CRITICAL、改名候选、转发变化、模块缺失/新增、证据映射、非导出契约、可复现性、CLI 退出码与非法清单 |
| `test_gms_compat_audit.py`（14） | 完整构建全覆盖、序号绑定、缺失导出导致能力缺符号、模块缺失、哈希/架构不符、纯契约能力不可确认、BLOCKED 操作被拒、可复现性、CLI 退出码 |
| `test_gms_compat_evidence.py`（34） | 清单自校验、指纹与 C++ profile 交叉核对、资格门禁的 16 项篡改/覆盖拒绝用例、schema 契约一致、渲染幂等 |

关键负向断言（防止“候选自动变成 QUALIFIED”）：

- `compare` 输出中不允许出现 `"QUALIFIED_LIMITED"` 或 `"state": "QUALIFIED`；
- 去掉某条的 `real_host` 记录后校验器必须报 `qualified_without_real_host_pass`；
- 把 `derivation` 改成 `name_only`/`similarity_only` 后必须报 `qualification_exceeds_derivation`；
- 伪造标题锚点、伪造源文件、伪造布局出处、重复绑定符号、重复写入 RVA、未声明的操作名，
  全部必须报错。

合成 PE 覆盖 x86 与 x64、有/无版本资源、转发导出、导入模块，以及损坏/截断/空/超限输入。
测试不加载任何厂商 DLL，不需要 DM 许可、真实数据或固定盘符。

---

## 7. P2 设计建议（本轮不实现）

目标：把“人工比对 + 人工移植”变成“可复核的候选生成 + 明确验收清单”，
但**任何候选默认 `CANDIDATE_DISABLED`**，且 P2 在没有真实目标构建时不得宣称跨版本兼容。

### 7.1 输入与产物

```text
gms-compat evidence extract   --build-dir <授权安装> --out build_b.json     # 复用 inspect
gms-compat evidence derive    --base abi_evidence.json --candidate build_b.json \
                              --out candidate_evidence.json                 # 默认全 UNRESOLVED
gms-compat adapter scaffold   --evidence candidate_evidence.json \
                              --out adapters/gms_<ver>/                    # 模板，默认禁用
gms-compat plan acceptance    --evidence candidate_evidence.json \
                              --out plan.json                              # 实机验收清单
```

### 7.2 每个不确定项必须给出具体验证方法

候选证据条目强制带 `verification_plan`，字段固定：

```json
{
  "unknown": "call_shape.hidden_sret",
  "method": "real_host_probe",
  "preconditions": ["module hash pinned", "idle host", "synthetic source image"],
  "observation": "result slot written exactly once; returned pointer equals slot address",
  "oracle": "independent same-PID read of the created image",
  "pass_criterion": "one owned reference, matching numeric ID, source pixels unchanged",
  "artifact": "experiments/native-bridge/results/<build>/probe_<id>.json"
}
```

方法枚举：`static_disassembly`、`offline_synthetic`、`real_host_probe`、
`real_host_numerical_oracle`、`real_host_lifecycle`、`manual_review`。
静态方法**不得**单独产出 `QUALIFIED_LIMITED`。

### 7.3 Adapter 候选模板

- 目录结构对齐 `adapters/gms_3_53_4137/`：`profile.hpp`、`<group>_contract.hpp`、
  `<group>_adapter.inc`。
- 模板生成时把每个 `qualified` 置为 `false`，所有 RVA 占位为 `null` 并带
  `#error` 或 `static_assert` 的显式填充要求，避免“复制旧 RVA 就能编译通过”。
- 生成的候选不进入 `implementations()`，不进入 MCP catalog，不改变现有 SHA 门禁。

### 7.4 合成测试与实机验收计划生成

- 合成测试：按能力组生成 `*_adapter_tests.cpp` 骨架，覆盖 dtype/维度/校准/所有权拒绝路径；
  不含任何数值实现，只测门禁。
- 实机验收计划：按 `AGENTS.md` 的必选顺序生成步骤与观测项
  （身份 → 符号 → 回调就绪 → 数值 → 源不变 → 生命周期 → 正常退出），
  每步绑定预期的 PASS/FAIL 判定与产物路径。

### 7.5 关于 Ghidra 等本地反汇编工具

可评估，但必须遵守：

- 只在**用户有权分析的本地安装**上运行，产物不入库（只入库结构化结论与锚点）；
- 反汇编结论只能记为 `derivation: static_inspection`，不能记为真实宿主例外；
- 任何“看起来一样”的签名或常量都不构成调用约定证明；
- 非导出入口的定位结果必须记录为“候选 RVA + 证据锚点”，并强制 `manual_review`。

### 7.6 入口重定位分道（基于 §6.6 的静态筛查）

P2 不应把“把旧 RVA 抄过来再试试”当作定位方法。按引用形态分三条通道，成本递增：

| 通道 | 适用 | 方法 | 必须复核 |
| --- | --- | --- | --- |
| L1 RTTI 槽位 | 8 条虚表槽位形态 | 按类型描述符名称定位虚表起点，读取同一槽位号 | 该槽位的实际行为与参数形态；槽位号跨构建可漂移 |
| L2 注册表条目 | 5 条单一数据指针形态 | 按注册条目结构（条目内函数指针 + 名称字符串）定位 | 条目字段顺序；名称是否随构建变化 |
| L3 纯代码引用 | 14 条无数据引用形态 | 反汇编 + 惯用式匹配（叶 getter 通常 1–3 条指令，包装器是一条尾跳转） | 每条都必须重推调用形状与所有权 |

三条通道的共同前提：**入口身份必须由行为复核确认，而不是由“找到了一个看起来对的函数”
确认**。L1 的槽位号与 L2 的条目结构都只是搜索线索，不是 ABI 证据。

对应的工具化建议：`gms-compat` 在 P2 增加一个只读的 `scaffold` 子命令，输出
“待重定位清单 + 每条通道的搜索线索 + 各自的复核判定标准”，仍然不产出任何可调用绑定。

### 7.7 提级路径（不可跳过）

`CANDIDATE_DISABLED` → 离线合成测试通过 → 真实目标构建上的分组验收
（数值 + 源不变 + 生命周期 + 正常退出）→ 独立人工审查 → 才允许修改
`profile.hpp` 的 `qualified` 与模块指纹。

---

## 8. 未解决问题

1. **x86 构建**：现有适配器只有 x64 调用形状；x86 需要 `__stdcall`/`__cdecl`/`__thiscall`
   独立建模，且 `mfc140` 分配器配对可能不同。
2. **非导出入口的自动定位**：§6.6 已给出三条重定位通道（RTTI 槽位 / 注册表条目 /
   纯代码惯用式），但每条都仍是“线索”而非“映射规则”：槽位号可能漂移，
   注册表结构未闭合，纯代码引用需要逐条惯用式匹配。目前没有可离线判定
   “找到的就是同一个函数”的判据，只能靠行为复核。
3. **MSVC STL 版本差异**：`std::wstring` 32B 布局在别的 MSVC 运行时上可能变化，
   需要按 `mfc140` 版本的独立证据条目。
4. **Fourier 复数表示**：`FFT`/`Packed_FFT` 的复数存储与 packing 仍未闭合。
5. **manifest 覆盖面**：`compare` 不解释节区属性差异的业务含义，也不检查重定位信息；
   对加壳或自修改镜像无意义（也不会被误判为兼容）。
6. **compare 的能力映射依赖证据清单**：清单未覆盖的导出只会进 `high_risk` 且标
   `evidence_entry: null`，这是刻意的——宁缺勿猜。
7. **槽位与条目结构只在单一构建上成立**：§6.6 的通道分类来自同一台安装，
   尚无第二个构建可用于验证“槽位号/条目结构在版本间稳定”这一假设。
   在拿到授权第二构建之前，该分类只能作为搜索线索，不能作为结论。
8. **入口身份判定**：本轮只能证明“某个地址被某种结构引用”，无法证明
   “该地址在另一构建上仍是同一语义的入口”。这是 P2 最需要补齐的一环。

---

## 9. 与既有文档的关系

- `AGENTS.md`：产品边界与科学契约，未修改，仅新增一段指向本工具的说明。
- `experiments/native-bridge/ABI_NOTES.md`：静态 ABI 叙述的原始出处，本清单逐条引用其标题锚点。
- `experiments/native-bridge/mvp/ADAPTERS.md`：能力/资格语义的原始出处。
- 本工具不取代上述文档的规范地位：证据清单只做索引与校验，结论仍以原始记录为准。
