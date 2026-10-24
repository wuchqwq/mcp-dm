# 原生操作与显式数据交接

DigitalMicrograph 执行科研处理，MCP 适配显式图像 ID、参数、原生调用和结果。
Python/NumPy 参考只用于独立验收；下面的外部均值示例是用户单独运行的后处理，
不参与插件处理，也不在缺少原生算子时自动启动。

先看 [操作验收范围](OPERATIONS_ACCEPTANCE.md) 和 [版本兼容矩阵](ADAPTERS.md)。
目录有工具不代表当前宿主获准执行该能力：检查 `dm_status` 的构建、兼容状态、
能力和原因。当前仅有一个固定 Windows x64 GMS 构建适配器；其它版本明确拒绝。
第一宿主的处理、预览和结果生命周期已通过限定合成验收并正常退出。第二宿主
已独立通过公开 MCP → READ → NPY → 显式外部均值链路，含 signed zero、subnormal、
Fourier v2 和四种 filter。第二宿主的同 PID STOP 释放 oracle、正常 exit 0 和
manifest 清理也已通过。当前五组 profile 资格不依赖 preparation 环境开关；
最终 production DLL 又在第三宿主独立通过同一公开 MCP 工作流和同 PID oracle，
记为 **LIMITED_SYNTHETIC_REAL_HOST_PASS**。第三宿主自身也通过原始 STOP 身份、
九个未显示输出释放、九源/文档/capture 保持的独立核对，正常 exit 0 后完成
manifest 移除。退出后另一次显式外部运行仍能重开保存的 NPY 并得到同一均值，
原 capture 未变；这些是最终二进制自己的证据。

## 十四个原生工具

使用显式 `DM_MCP_BACKEND=native` 和用户启动宿主时记录的 session。
默认 v0.6 后端是另一条路径，不会作为原生失败的回退。

| 工具 | 用途 |
| --- | --- |
| `dm_status` | 构建、适配器、能力、宿主状态 |
| `dm_datasets` | 有界原生图像枚举及元数据 |
| `dm_native_mean` | 指定二维 float32 / uint32 图像的原始强度均值；各有像素预算 |
| `dm_native_summary` | 原生 minimum、maximum、sum、mean 四值 |
| `dm_native_result` | 同 session、同 request_id 查询原 NB2 记录 |
| `dm_crop` | 半开像素矩形的独立原生副本 |
| `dm_native_show` | 插件持有的合格结果交给可见 DM 文档 |
| `dm_native_unary` | `negate`、`abs`、`square` |
| `dm_native_binary` | `add`、`subtract`、`multiply` |
| `dm_native_fft` | `forward` 或受限的配对 `inverse` |
| `dm_native_complex` | `real`、`imaginary`、`phase`、`power` |
| `dm_native_filter` | `smooth`、`sobel`、`laplace`、`sharpen` |
| `dm_native_preview` | 最大 128×128 的显示用灰度 PNG |
| `dm_native_read` | 明确 ROI 的 float32 / uint32 原始数值与标定快照 |

宿主空闲且不编辑源图时串行调用。先保存 session、request_id 和原参数，再提交
创建结果或显示文档的操作。超时、取消或断连后只用 `dm_native_result` 查询原 ID；
不重新提交来猜测是否完成。`queued`、`running`、`unknown` 和错误均不是成功。
NB2 保留原操作、规范参数、结果类型及版本；Fourier 新提交使用 v2，旧 v1 QUERY
只用于恢复其原始记录。STOP、退出或新 session 不保证旧记录可恢复。

float32 的一个短工作流是：枚举得到源 ID → 明确 ROI 做 crop → 对返回的新 ID 做 square
或其它支持的原生处理 → preview 查看显示内容 → 按需 show 或 read。二元操作
要求同形状、同空间标定，不广播。复数预览或 READ 前先请求明确的实数分量，
不要把 complex 图像当作两列 float32。

uint32 的工作流是：明确源 ID → preview 核对 → crop → 原生 mean / summary
→ READ → 无损 NPY 交接。统计最多 2,097,152 像素；crop 源最多 4,194,304 像素、
输出最多 4 MiB。2048×2048 整图超过统计预算，需先明确选取较小区域。
不能把 float32 的 square、FFT、滤波或 show 直接用于 uint32；这些会明确拒绝。
具体资格与合成验收入口见 [uint32 专项](UINT32_ACCEPTANCE.md)。

`show` 不保存文件，也不等于模型已理解图像。插件正常 STOP 释放其强引用；
已显示文档可继续持有结果，直至用户正常关闭该文档。不要关闭无关文档，
不要强制结束 DM 或替换仍加载的插件。

## 保存一份 READ 数值快照

READ 是只读调用，不创建结果图，不写文件。它返回原始 little-endian float32 或 uint32
base64、`shape:[y,x]`、C 行序、源元数据、逻辑 ROI 标定和原生回执。上限为
16,384 样本／65,536 原始字节；矩形为 `[x0,y0,x1,y1]`，右下界不包含，不裁夹。
源图上限 4,194,304 像素。它不是原子快照，不能在并发编辑下保证一致性。

调用方保存成功 MCP text JSON 或单个 text content 的 MCP 结果。预览 PNG
不能作为这个数值输入。下面命令从仓库根目录运行，路径由用户显式指定；
`$workspace` 必须是已有的独立工作目录，输出子目录必须尚不存在。

```powershell
node tools/native_snapshot_handoff.mjs `
  --workspace $workspace --output capture-processed `
  --request-id handoff-processed-001 --snapshot .\saved-native-read.json
```

工具只验证和编码保存的响应，不连接 DM。产物复用已有 schema 1：

- `input.npy`：float32 使用 `<f4` 并保留负零；uint32 使用 `<u4`，保留全部高位整数原字节。
- `input.json`：源/ROI、轴角色、原始 origin、物理零点、带符号 scale、单位、
  来源、NB2 回执和字节／像素／文件哈希。
- `capture.json`：`capturing` 后经写入、flush/fsync 和读回验证成为 `captured`；
  失败保留为 `failed`。

强度 getter 未被读取，`intensity_calibration` 的 origin、scale、unit 均为 null，
状态为 `NOT_READ`，`intensity_calibration_applied:false`。不把未知单位写成 counts。
源 ID 仍可变；不可变身份针对存储的数值字节及其哈希，不针对之后的活图像。
保留的 creation provenance 只描述创建记录，不证明结果之后从未被用户编辑。

写输出前，`handoff-requests/<request-id>.json` 先独占记录并 fsync 固定参数。
同 ID 同参数只核验原 captured 文件并返回原结果；改快照或路径拒绝。
没有完成回执的半写请求返回 `UNKNOWN_INCOMPLETE`，不会自动修补或重新请求 DM。
工具不覆盖、清理或删除用户文件。

## 用户显式运行外部示例

```powershell
python examples/native_handoff_mean.py `
  --workspace $workspace --capture "$workspace\capture-processed" `
  --output external-mean
```

这个独立示例对 float32 使用 NumPy float64 累加；对 uint32 使用精确 Python
整数求和并交叉核对 NumPy uint64，再除以样本数取得 binary64 raw mean。
它核对 capture、原始 READ
身份、文件和像素哈希，并在结束前复核输入文件。输出到新的目录，保存当前
脚本副本、`parameters.json`、`results.json`、`run.json`，记录 Python/NumPy
版本及脚本、参数和输入哈希。它不调用 DM、不改 capture、不把结果回传 DM。
需要 DM 原生均值时直接使用 `dm_native_mean`；外部示例是显式用户工作流。

这份 NPY 是有界原始数值交接，不是 DM SaveAs，也不是完整科学文档保存。
原生 SaveAs/Open 的路径、格式、禁止覆盖及错误语义仍未资格确认。

## 复现当前 production 链路

下面仅用于新建的合成验收宿主，不操作实验文件。按 [安装步骤](INSTALL.md)
记录待测 DLL 的构建、加载哈希和实际 PID；正常关闭旧宿主后才安装，禁止替换
加载中的文件。`$fixture` 是已有的独立绝对目录，`$acceptance` 是尚不存在的
绝对输出目录，`$session` 是为本次宿主生成并保留的 32 位小写十六进制 session。

启动本次宿主前设置：

```powershell
$env:DM_NATIVE_SESSION = $session
$env:DM_NATIVE_EVIDENCE_DIR = $fixture
$env:DM_NATIVE_INCLUDE_READ_BITS = "1"
```

不设置 `DM_NATIVE_QUALIFY_OPERATIONS`；production 准入不读取它。然后只在这个
宿主的一次性 Python 编辑器内运行 `create_operations_fixture.py`。脚本需要其
所在 MVP 目录可导入，可使用如下固定脚本入口；`mvp_dir` 由用户填入仓库内的
绝对 MVP 目录：

```python
import os, runpy, sys
mvp_dir = r"<absolute repository directory>\experiments\native-bridge\mvp"
assert os.path.isabs(mvp_dir)
if mvp_dir not in sys.path:
    sys.path.insert(0, mvp_dir)
runpy.run_path(os.path.join(mvp_dir, "create_operations_fixture.py"), run_name="__main__")
```

显式 flag 在原有八张合成图之外增加 `READ_BITS`，其固定首行包含正负零和正负
最小 float32 subnormal；默认原八图流程保持不变。truth/NPY 必须是本次新文件，
记录的 PID 来自该宿主自己的 `os.getpid()`。fixture 的 `RECORDED` 只证明建图记录。

从仓库根目录的外部 PowerShell 运行当前 v2 公开 MCP 链路：

```powershell
python experiments/native-bridge/mvp/accept_handoff_mcp.py `
  --directory $fixture --output-directory $acceptance `
  --qualification-mode production
```

该程序保存原请求 ledger 后才提交，核对十四工具目录，执行预览、crop/square、
源与结果 READ、同 ID QUERY、Fourier v2 FFT/IFFT/REAL、四种 filter、NPY 和外部
示例。`RECORDED` 不是源保护、数学或释放的独立 PASS。`qualify_operations.mjs`
及第一宿主的 prepared v1 记录属于历史验收路径，不是当前 v2 的复现命令。

接着回到**同一 PID、同一 session** 的一次性 Python 编辑器。保留上面的
`mvp_dir`，将 `acceptance_dir` 填为刚才 `$acceptance` 的绝对路径；为 report、
原 ledger 和每次新的输出显式指定绝对路径：

```python
acceptance_dir = r"<absolute acceptance directory>"
assert os.path.isabs(acceptance_dir)
os.environ["DM_NATIVE_HANDOFF_TRUTH"] = os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"], "operations-truth.json")
os.environ["DM_NATIVE_HANDOFF_REPORT"] = os.path.join(acceptance_dir, "mcp-handoff-report.json")
os.environ["DM_NATIVE_HANDOFF_LEDGER"] = os.path.join(acceptance_dir, "mcp-handoff-requests.jsonl")
os.environ["DM_NATIVE_HANDOFF_OUTPUT"] = os.path.join(acceptance_dir, "independent-handoff-01.json")
runpy.run_path(os.path.join(mvp_dir, "verify_handoff.py"), run_name="__main__")
```

独立 oracle 重新读取原文件与活图像，逐 bit 核对 READ/NPY、源保护和独立内存，
核对带符号标定、PNG、固定数学参考及外部结果，并释放 Python wrapper/view。
只有完整通过才返回 `PASS_BOUNDED_SYNTHETIC_HANDOFF`。该脚本不证明文档可见性、
模型看图、STOP 或正常退出；输出已存在、任何矛盾或异常都不能形成 PASS。

最后在外部终端用 `stop_native.py` 预存新的原始 STOP 请求后发送：

```powershell
python experiments/native-bridge/mvp/stop_native.py `
  --session $session --request-id $stopRequestId --expected-host-pid $hostPid `
  --request-record "$acceptance\stop-request.json" `
  --evidence "$acceptance\stop-receipt.json"
```

回执之后等待正常 host cleanup，另核管道和插件窗口已消失。仍在同一 DM 宿主的
一次性 Python 编辑器设置以下新证据路径，再运行只读释放 oracle：

```python
os.environ["DM_NATIVE_HANDOFF_INDEPENDENT"] = os.path.join(acceptance_dir, "independent-handoff-01.json")
os.environ["DM_NATIVE_HANDOFF_STOP_REQUEST"] = os.path.join(acceptance_dir, "stop-request.json")
os.environ["DM_NATIVE_HANDOFF_STOP_RECEIPT"] = os.path.join(acceptance_dir, "stop-receipt.json")
os.environ["DM_NATIVE_HANDOFF_STOPPED_OUTPUT"] = os.path.join(acceptance_dir, "independent-handoff-stopped.json")
runpy.run_path(os.path.join(mvp_dir, "verify_handoff_stopped.py"), run_name="__main__")
```

这条未 SHOW 的交接流程应得到 `PASS_UNSHOWN_HANDOFF_STOPPED`：只查原记录中明确
生成的输出 ID 已失效，源和文档数不变、capture 文件仍在；它不发送 IPC、不关图。
若同次会话有先前失败且已生成输出的尝试，必须显式保留其报告并用该 oracle 的
`DM_NATIVE_HANDOFF_PRIOR_REPORTS` 绝对路径 JSON 列表核对所有归属，不能把失败前缀
改写成数学 PASS。完成后由用户正常退出 DM，另记录退出码和 manifest 清理。
STOP 本身不关闭 DM，未退出前不得移除加载中的插件。
