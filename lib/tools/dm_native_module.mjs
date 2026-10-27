// Explicit NB2 adapter. Exact ABI/capability validation remains in the
// existing native bridge and pinned host, never in registry discovery.
import {NativeBridge,NativeBridgeError,validRequestId} from '../native_bridge.mjs';
import {nativePreviewImage} from '../native_preview.mjs';
import {nativeImportTool,callNativeImport} from '../native_import.mjs';
import {tool,validate,RpcError} from '../runtime/schema.mjs';
import {nativeContract} from './dm_contracts.mjs';
const NATIVE_INSTRUCTIONS = [
  "实验性 DigitalMicrograph C++ NB2 bridge，仅用于明确启动的指定构建；只在宿主空闲且不编辑源图时调用。源图保持只读，不控制硬件。",
  "提供有限原生工具：dm_status、dm_datasets、dm_native_mean、dm_native_summary、dm_native_result、dm_crop、dm_native_show、dm_native_unary、dm_native_binary、dm_native_fft、dm_native_complex、dm_native_filter、dm_native_preview、dm_native_read、dm_native_frame、dm_native_result_info、dm_native_release、dm_native_rois、dm_native_profile、dm_native_histogram；rois 仅在对应能力已合格时只读枚举明确图像的显示对象和选区，不自动挑选或裁剪；GUI 选区是非原子执行时快照，旧 ID 的 QUERY 不会刷新当前选区，不把小数或越界选区舍入为分析区域；结果释放只释放插件引用，必须提供创建回执的 token 和预先保存的 request_id；未实现工具明确拒绝，绝不回退到 Python。图像 ID 跨工作区；SHOW 不保证激活结果所在标签页，不能据回执声称当前页或模型已看到图像。mean 只返回原生均值；summary 仅返回 minimum/maximum/sum/mean 四个原生摘要值，均不代表完整 stats，不应用强度标定。已识别的不可用空间标定通过元数据报告，不妨碍 raw intensity 摘要。DM 执行有限算术、Fourier 与滤波；复数 power 为平方模，不是幅值。preview 仅作显示适配，不是科研导出；read 仅交接明确 ROI 的有界原始数值和标定，不写文件或创建图像。dm_native_show 仅为本插件仍持有的已合格结果创建或复用包含该明确 image_id 的可见 DM 文档，不保存文件，不代表模型已看图。正常 STOP/cleanup 释放插件持有的结果引用，不关闭已显示的文档。",
  "每次提交返回 native_receipt 含 session/request_id 和 NB2 原操作身份。frame、crop、show、unary、binary、fft、complex、filter、profile、histogram 等副作用工具必须使用客户端在提交前保存的 request_id；只读 status/datasets/mean/summary/preview/read 可省略并生成 UUID。超时、取消、断连均不代表操作终止，使用 dm_native_result 在原 session 查询同一 ID，不自动重发；STOP 或新 session 不承诺恢复旧结果。",
  "queued/running/unknown 均不是成功。backend 必须检查宿主实际返回值；mock-native 只代表合成测试。",
  "dm_native_import 受独立资格门禁限制：匹配当前精确构建与可用能力后，仅接收有限二维 float32 科学 NPY 和来源 JSON，实空间单位 nm 或倒空间单位 1/nm；其它单位和未知域不在普通构建资格内。它在 DM 新建独立图像，不覆盖源图、不执行脚本、不隐式转换、不自动 SHOW。必须在提交前保存 request_id；恢复只查询原记录。外部计算来源与 DM 原生创建/读取分别记录；合成子范围验收不代表所有数据或 GMS 构建均受支持。",
].join("\n");

const RECT = {
  type: "array",
  items: { type: "integer", minimum: 0 },
  minItems: 4,
  maxItems: 4,
  description: "像素矩形 [x0, y0, x1, y1]，右下边界不包含；必须完整位于图内，不舍入或裁夹；省略则整幅",
};

const NATIVE_REQUEST_ID = {type: "string", minLength: 1, maxLength: 64, pattern: "^[A-Za-z0-9_-]{1,64}$", description: "可选客户端请求 ID；省略时生成 UUID。取消前预先保存此 ID，之后只用 dm_native_result 查询，不自动重发"};
const NATIVE_COORDINATE_MODE = {type:'string',enum:['physical','pixel'],description:'默认 physical 保持原契约。显式 pixel 使用独立 *_PIXEL 请求身份；仅当前宿主单独资格通过时可用。像素网格不是物理标尺，不改变 dtype/尺寸/ABI 门禁。'};
const NATIVE_IMAGE_ID = {type: "integer", minimum: 0, maximum: 4294967295, description: "dm_datasets 返回的显式 uint32 图像 ID；不接受 front 或数字字符串"};
// Read-only tools may generate an ID; side-effect tools require a saved ID.
const NATIVE_OPTIONAL_REQUEST_ID_TOOLS = new Set(["dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary", "dm_native_preview", "dm_native_read", "dm_native_rois"]);
NATIVE_OPTIONAL_REQUEST_ID_TOOLS.add('dm_native_result_info');
const NATIVE_SAVED_REQUEST_ID = {...NATIVE_REQUEST_ID, description: "必填：客户端在提交前保存的 [A-Za-z0-9_-]{1,64} 请求 ID；超时/取消/断连后在同一 session 只查询此 ID，不自动重发"};
const NATIVE_UNARY = {negate: 1, abs: 2, square: 3};
const NATIVE_BINARY = {add: 1, subtract: 2, multiply: 3};
const NATIVE_FILTER = {smooth: 1, sobel: 2, laplace: 3, sharpen: 4};
const NATIVE_COMPLEX = {real: "REAL", imaginary: "IMAG", phase: "VENDOR_ARG", power: "VENDOR_NORM"};
const nativeTools = [
  tool("dm_status", "实验性指定构建的 C++ NB2 桥状态及宿主真实 backend；只在 DM 空闲且不编辑源图时调用，源图只读，不回退 Python。", {request_id: NATIVE_REQUEST_ID}),
  tool("dm_datasets", "实验性指定构建：枚举宿主当前图像；只在 DM 空闲且不编辑源图时调用，源图只读。请固定数字 image_id，不回退 Python。", {request_id: NATIVE_REQUEST_ID}),
  tool("dm_native_mean", "实验性指定构建的 DM 原生均值，仅 mean，不提供完整 stats；必须显式数字 image_id。只在 DM 空闲且不编辑源图时调用，源图只读。超时/取消后同 ID 查询，不自动重发，不回退 Python。", {
    image_id: NATIVE_IMAGE_ID,
    request_id: NATIVE_REQUEST_ID,
  }, ["image_id"]),
  tool("dm_native_summary", "实验性指定构建的 DM 原生二维 float32/uint32 摘要，仅 minimum、maximum、sum、mean 四值，不提供完整 stats、stddev 或 variance；显式数字 image_id；float32 最多 4194304 像素，uint32 最多 2097152 像素以保持最坏整数和小于 2^53。不应用强度标定；已识别的缺失/无效空间标定通过 calibration_complete 和每轴 issue 报告，仍可计算 raw pixel intensity。只在 DM 空闲且不编辑源图时调用，源图只读；超时/取消后同 ID 查询，不自动重发，不回退 Python。", {
    image_id: NATIVE_IMAGE_ID,
    request_id: NATIVE_REQUEST_ID,
  }, ["image_id"]),
  tool("dm_native_result", "实验性指定构建：用已保存 request_id 查询 NB2 记录，只发送 QUERY，不重执行原操作。queued/running/unknown 不当作成功；只在 DM 空闲且不编辑源图时调用。", {
    request_id: {...NATIVE_REQUEST_ID, description: "原操作已保存的 request_id，必须属于当前 DM_NATIVE_SESSION"},
  }, ["request_id"]),
  tool("dm_crop", "实验性指定构建的原生二维独立副本裁剪；显式数字 image_id、非空半开 rect=[x0,y0,x1,y1] 和提交前已保存的 request_id 必填，不舍入/裁夹。插件持有新图像至正常 native STOP/cleanup 释放，不创建可见 DM 文档。只在 DM 空闲且不编辑源图时调用，源图不改；超时/取消/断连后在原 session 只查询同 ID，不自动重发，不回退 Python。", {
    image_id: NATIVE_IMAGE_ID,
    coordinate_mode:NATIVE_COORDINATE_MODE,
    rect: {...RECT, items: {type: "integer", minimum: 0, maximum: 4294967295}},
    request_id: {...NATIVE_REQUEST_ID, description: "必填：客户端在提交前保存的 [A-Za-z0-9_-]{1,64} 请求 ID；超时/取消/断连后在同一 session 用 dm_native_result 查询。STOP 或新 session 不承诺恢复"},
  }, ["image_id", "rect", "request_id"]),
  tool("dm_native_show", "实验性指定构建：仅为本插件仍持有的已合格原生结果创建或复用包含明确 image_id 的可见 DM 文档；显式 image_id 和提交前保存的 request_id 必填，不选择最新/前台窗口。接受已合格二维结果、PROFILE 的真一维 float64 和 HISTOGRAM 的真一维 uint32；保留真实 [N] 和单条原生轴，不伪装成 [1,N] 光栅。直方图轴须与冻结的创建上下文一致。柱状样式为独立可选能力：原生类型核对及 setter/getter 读回通过才报告 display_style=histogram；未应用时保留默认显示并报告原因，样式不构成科学声明。首次创建在当前工作区；复用文档不保证激活其标签页。源图不改，不保存文件，不代表模型已看图。STOP/cleanup 只释放插件引用，不关闭已显示的文档；超时/取消后只查询同 ID，不重发或回退 Python。", {
    image_id: {...NATIVE_IMAGE_ID, description: "本插件仍持有的已合格原生结果 image_id（显式 uint32）；不接受任意源图、front 或数字字符串"},
    request_id: {...NATIVE_REQUEST_ID, description: "必填：客户端在提交前保存的 [A-Za-z0-9_-]{1,64} 请求 ID；超时/取消/断连后在同一 session 用 dm_native_result 查询。STOP 或新 session 不承诺恢复"},
  }, ["image_id", "request_id"]),
  tool("dm_native_unary", "DM 原生逐像素 negate/abs/square，显式二维 float32 或经宿主逐项获准的 uint32 image_id；uint32 的原生结果为 float32，dtype_semantics 明示并非任意整数的无损运算。产生插件持有的独立结果，源图不改。宿主空闲时串行调用，不回退或重发。", {
    image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_UNARY)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "operation", "request_id"]),
  tool("dm_native_binary", "DM 原生逐像素 add/subtract/multiply，显式且兼容的两个二维 float32 图像或经宿主逐项获准的 uint32 输入；uint32 原生二元结果为 float32，按 dtype_semantics 报告精度限制，不是任意整数的无损运算。产生独立结果，源图不改，不支持 divide。宿主空闲时串行调用，不回退或重发。", {
    left_image_id: NATIVE_IMAGE_ID, right_image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_BINARY)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["left_image_id", "right_image_id", "operation", "request_id"]),
  tool("dm_native_fft", "有限 DM 原生二维 Fourier：forward 接受 float32 或经宿主 dtype 能力获准的 uint32，原生 complex64 输出不是无损整数表示；按 dtype_semantics 报告单精度限制。forward 为正指数、未归一化并 fftshift 的 full complex；inverse 为负指数且除以像素数。仅显式 ID；经宿主对应操作和 dtype 的大尺寸能力获准时，二次幂轴 4..1024、最多1048576像素；未获准尺寸拒绝。当前大尺寸 uint32 谱系的 inverse 未资格；1024×1024 inverse 的已知驻留及校验图超过16MiB预算，也会拒绝。16MiB插件结果池还约束已有结果与校验临时图，不保证最大尺寸的整条链同时驻留；不是旧 dm_fft。数学频率使用 frequency_grid，勿将 DM 半 bin 标定偏移当作 DC。产生独立结果，源图不改。", {
    image_id: NATIVE_IMAGE_ID, direction: {type: "string", enum: ["forward", "inverse"]}, coordinate_mode:NATIVE_COORDINATE_MODE, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "direction", "request_id"]),
  tool("dm_native_complex", "DM 原生 full complex 分量：real、imaginary、phase（弧度）、power（平方模，不是幅值）；产生独立实数结果，源图不改；经宿主对应分量的大尺寸能力获准时，二次幂轴4..1024、最多1048576像素；未获准或结果池容量不足则拒绝。", {
    image_id: NATIVE_IMAGE_ID, component: {type: "string", enum: Object.keys(NATIVE_COMPLEX)}, coordinate_mode:NATIVE_COORDINATE_MODE, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "component", "request_id"]),
  tool("dm_native_filter", "DM 原生二维 float32 或经宿主逐项获准的 uint32 smooth/sobel/laplace/sharpen，处理明确 image_id 的完整输入图像；当前资格仅覆盖每轴5..256，更大整图尚未资格。uint32 的 smooth/sharpen 原生输出 uint32，sobel/laplace 原生输出 float32；实际存储和精度限制由 dtype_semantics 明示，桥端不做像素 cast。产生独立结果且保留空间标定，源图不改；算法及边缘语义以回执为准。宿主空闲时串行调用，不回退或重发。", {
    image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_FILTER)}, coordinate_mode:NATIVE_COORDINATE_MODE, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "operation", "request_id"]),
  tool("dm_native_preview", "显式二维 float32/uint32 图像的有界灰度 PNG 显示：原生点读取、最近邻采样，最大 128×128，不放大。仅显示适配，不是定量分析或科研文件导出，不修改源图；不代表模型已经看见。", {
    image_id: NATIVE_IMAGE_ID, max_width: {type: "integer", minimum: 1, maximum: 128, default: 128},
    max_height: {type: "integer", minimum: 1, maximum: 128, default: 128}, request_id: NATIVE_REQUEST_ID,
  }, ["image_id"]),
  tool("dm_native_read", "DM 原生读取显式二维 float32/uint32 图像的半开 ROI，最多 16384 样本/65536 原始字节；返回保留源 dtype 的 little-endian 4 字节标量 base64、行优先 shape/轴序和 ROI 标定。源图只读，源图最多 4194304 像素；不裁夹、不生成图片、不保存文件，不是 DM SaveAs。只在宿主空闲且不编辑源图时调用，snapshot_atomic:false；用于调用方显式数值交接，不回退 Python。", {
    image_id: NATIVE_IMAGE_ID, rect: {...RECT, items: {type: "integer", minimum: 0, maximum: 4294967295}}, request_id: NATIVE_REQUEST_ID,
  }, ["image_id", "rect"]),
  tool('dm_native_frame', '按明确三维 uint16 序列 image_id 和零基 frame_index 提取独立二维工作副本：DM 原生切片后显式转换为 float32，uint16 数值精确保留，原序列及文件不改。仅 DM dimension2/NumPy axis0 的明确帧，最多1048576输出像素；保留原序列、帧号、三轴标定和转换来源，不猜当前显示帧或求和图。缺少空间单位不阻止复制，也不产生nm或相位解释。使用 dm_native_preview/read/mean 等已支持的二维工具继续；FFT仍有尺寸和标定限制。必须提前保存 request_id，超时或取消查询原ID，不重发、不回退Python。仅能力已合格时开放调用。', {
    image_id: {...NATIVE_IMAGE_ID, minimum: 1},
    frame_index: {type: 'integer', minimum: 0, maximum: 4294967295, description: '零基序列帧索引；DM dimension2 / NumPy axis0，不代表空间Z或时间'},
    request_id: NATIVE_SAVED_REQUEST_ID,
  }, ['image_id','frame_index','request_id']),
  tool('dm_native_result_info', '查询明确结果的当前插件引用状态。必须同时提供创建回执中的 image_id 和 retention.token；这是该次查询执行时的快照；刷新状态用新查询 ID，旧 ID 的 QUERY 保持历史。已释放结果可能仍由用户文档持有，但不能继续作为插件处理输入。', {
    image_id: {...NATIVE_IMAGE_ID, minimum: 1}, retention_token: {type: 'integer', minimum: 1, maximum: 4294967295}, request_id: NATIVE_REQUEST_ID,
  }, ['image_id', 'retention_token']),
  tool('dm_native_release', '只释放本 session 插件自己持有的明确结果引用，要求 image_id、创建回执中的 retention.token 及预先保存的 request_id；不关闭文档、不销毁源图、不自动清理祖先，不篡改旧 completed 回执。超时只查询原请求 ID。', {
    image_id: {...NATIVE_IMAGE_ID, minimum: 1}, retention_token: {type: 'integer', minimum: 1, maximum: 4294967295}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ['image_id', 'retention_token', 'request_id']),
  tool('dm_native_rois', '只读枚举明确 image_id 的原生显示对象与 GUI 选区；不选择前台/最新窗口，不切换工作区，不自动选中某个 ROI。只把 rotation_degrees 严格为零、source_layout 为 direct_image_canonical_xy、slice_ids 为 [0] 且 coordinate_mapping.source_pixel_aligned 为真的明确、有限、范围内整数矩形标为可用于半开像素分析；原生线剖面能力另行合格时，也报告宽度1、非零轴对齐整数像素中心线端点及 line 资格；PROFILE 仍须显式提交完整 GUI 身份和 expected_line。旋转、不支持的图像来源/映射、小数、越界、退化和其它类型保留诊断，不舍入、不裁夹、不当作全图。结果是执行时快照，新的查询 ID 才读取当前 GUI，旧 ID 的 QUERY 保持原快照。能力未合格或原生读取失败时明确拒绝，不回退 Python/GUI 点击。', {
    image_id: NATIVE_IMAGE_ID, request_id: NATIVE_REQUEST_ID,
  }, ['image_id']),
  tool('dm_native_profile', '按完整 GUI 线选区身份和预先保存的 expected_line 执行有限 DM 原生剖面；重新核对图像/文档/显示/ROI 和原始端点，变化即拒绝。不选择当前窗口。仅 width=1、非零轴对齐整数像素中心端点，最多4096点；源为普通二维 float32/uint32，两轴完整、同单位、相同非零 signed scale。结果是真一维 float64 原生图像及已冻结的 f64 数值快照，保留 native_profile_axis 的原始 signed 标定，不伪称任意整数无损或强度已校准。必须提前保存 request_id；取消/超时只查询同 ID，不重发或回退 Python。', {
    image_id: NATIVE_IMAGE_ID,
    document_id: {type: 'integer', minimum: 0, maximum: 2147483647},
    display_id: {type: 'integer', minimum: 0, maximum: 2147483647},
    roi_id: {type: 'integer', minimum: 0, maximum: 2147483647},
    expected_line: {type: 'array', minItems: 4, maxItems: 4, items: {type: 'integer', minimum: 0, maximum: 4294967295},
      description: '从明确 GUI line 快照保存的 [x0,y0,x1,y1] 像素中心，端点包含；不是半开矩形边缘'},
    width: {type: 'integer', enum: [1]}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ['image_id', 'document_id', 'display_id', 'roi_id', 'expected_line', 'width', 'request_id']),
  tool('dm_native_histogram', '用 DM 自带 GMSImageProcessing::CalcHistogram 计算明确 image_id 的原始强度直方图，不写自己的分箱内核、不用 NumPy 顶替。源为普通二维 float32、最多4194304像素；bins 2..4096，可多于源像素数；min/max 为 binary32 原始强度边界，必须覆盖源的原生 minimum/maximum，否则拒绝。逐 bin 计数为精确非负整数且总和等于源像素数。原生存储为 uint32，数值快照以精确 binary64 传输。不应用源强度标定：仅源强度 origin=0、scale=1 且单位非空时，允许原生一维强度轴，回执保留请求/观测/往返误差及固定校验界；其它情况保持 bin_index 并另报原始强度分箱边界。产生插件持有的独立一维结果，源图不改；显示用 dm_native_show，保存数值用显式 NPY 交接。必须提前保存 request_id；超时/取消只查询同 ID。', {
    image_id: NATIVE_IMAGE_ID,
    bins: {type: 'integer', minimum: 2, maximum: 4096, description: '原生一维计数图的 bin 数（目的图维度）'},
    min: {type: 'number', description: 'binary32 原始强度下界；必须 <= 源原生 minimum'},
    max: {type: 'number', description: 'binary32 原始强度上界；必须 >= 源原生 maximum'},
    request_id: NATIVE_SAVED_REQUEST_ID,
  }, ['image_id', 'bins', 'min', 'max', 'request_id']),
  nativeImportTool,
];

function nativeFloatBits(value) {
  const buffer = new ArrayBuffer(4);
  new Float32Array(buffer)[0] = value;
  return new Uint32Array(buffer)[0];
}

function nativeInvocation(name, args) {
  if (args.coordinate_mode === 'pixel') {
    if(name==='dm_crop')return ['CROP_PIXEL',[args.image_id,...args.rect]];
    if(name==='dm_native_filter')return ['FILTER_PIXEL',[args.image_id,NATIVE_FILTER[args.operation]]];
    if(name==='dm_native_fft')return [args.direction==='forward'?'FFT_PIXEL':'IFFT_PIXEL',[args.image_id]];
    if(name==='dm_native_complex')return [NATIVE_COMPLEX[args.component]+'_PIXEL',[args.image_id]];
  }
  if (name === 'dm_native_frame') return ['FRAME', [args.image_id, args.frame_index]];
  if (name === 'dm_native_profile') return ['PROFILE', [args.image_id, args.document_id, args.display_id, args.roi_id, ...args.expected_line, args.width]];
  if (name === 'dm_native_histogram') return ['HISTOGRAM', [args.image_id, args.bins, nativeFloatBits(args.min), nativeFloatBits(args.max)]];
  if (name === 'dm_native_rois') return ['ROIS', [args.image_id]];
  if (name === 'dm_native_release' || name === 'dm_native_result_info') return [name === 'dm_native_release' ? 'RELEASE' : 'RESULT_INFO', [args.image_id, args.retention_token]];
  if (name === "dm_native_unary") return ["UNARY", [args.image_id, NATIVE_UNARY[args.operation]]];
  if (name === "dm_native_binary") return ["BINARY", [args.left_image_id, args.right_image_id, NATIVE_BINARY[args.operation]]];
  if (name === "dm_native_fft") return [args.direction === "forward" ? "FFT" : "IFFT", [args.image_id]];
  if (name === "dm_native_complex") return [NATIVE_COMPLEX[args.component], [args.image_id]];
  if (name === "dm_native_filter") return ["FILTER", [args.image_id, NATIVE_FILTER[args.operation]]];
  if (name === "dm_native_preview") return ["PREVIEW", [args.image_id, args.max_width ?? 128, args.max_height ?? 128]];
  if (name === "dm_native_read") return ["READ", [args.image_id, ...args.rect]];
  return [{dm_status: "STATUS", dm_datasets: "DATASETS", dm_native_mean: "MEAN", dm_native_summary: "SUMMARY", dm_crop: "CROP", dm_native_show: "SHOW"}[name],
    ["dm_native_mean", "dm_native_summary", "dm_native_show"].includes(name) ? [args.image_id] : name === "dm_crop" ? [args.image_id, ...args.rect] : []];
}


export function createDMNativeModule({env=process.env,bridge:providedBridge}={}){
const bridge=providedBridge??new NativeBridge({session:env.DM_NATIVE_SESSION,timeoutMs:Number(env.DM_MCP_TIMEOUT_MS||30000)});
async function callNativeTool(name, args, signal) {
  const catalog = nativeTools.find(entry => entry.name === name);
  if (!catalog) throw new RpcError(-32602, `native backend 不支持工具: ${name}；不会回退 Python`);
  args = args === undefined ? {} : args;
  validate(args, catalog.inputSchema);
  if (!NATIVE_OPTIONAL_REQUEST_ID_TOOLS.has(name) && !validRequestId(args.request_id)) throw new RpcError(-32602, "request_id 必须由客户端在提交前保存，并匹配 [A-Za-z0-9_-]{1,64}");
  if (args.request_id !== undefined && !validRequestId(args.request_id)) throw new RpcError(-32602, "request_id 必须匹配 [A-Za-z0-9_-]{1,64}");
  if (name === 'dm_native_profile') {
    const [x0, y0, x1, y1] = args.expected_line;
    if ((x0 === x1 && y0 === y1) || (x0 !== x1 && y0 !== y1) || Math.max(Math.abs(x1-x0), Math.abs(y1-y0)) + 1 > 4096)
      throw new RpcError(-32602, 'PROFILE 只接受非零轴对齐整数线，最多4096个端点包含的样本');
  }
  if (["dm_crop", "dm_native_read"].includes(name) && (args.rect[2] <= args.rect[0] || args.rect[3] <= args.rect[1])) throw new RpcError(-32602, "rect 必须为正面积，右下边界不包含");
  if (name === "dm_native_read" && (args.rect[2] - args.rect[0]) * (args.rect[3] - args.rect[1]) > 16384) throw new RpcError(-32602, "READ ROI 超出 16384 样本预算");
  try {
    const options = {requestId: args.request_id, signal};
    const reply = name === "dm_native_import" ? await callNativeImport(bridge,args,options)
      : name === "dm_native_result" ? await bridge.query(args.request_id, options)
      : await bridge.execute(...nativeInvocation(name, args), options);
    const {result, import_handoff, ...receipt} = reply;
    const native_receipt = {...receipt, request_id: receipt.id};
    if (reply.state === "completed" && name === "dm_native_mean" && (typeof result.mean !== "number" || !Number.isFinite(result.mean))) {
      throw new NativeBridgeError("Native MEAN completed without a finite numeric mean", {session: bridge.session, requestId: reply.id, code: "NATIVE_PROTOCOL", sent: true});
    }
    if (reply.state === "completed" && name === "dm_crop") {
      const matches = rect => Array.isArray(rect) && rect.length === 4 && rect.every((value, index) => value === args.rect[index]);
      const hasEffective = Object.hasOwn(result, "effective_rect"), hasRect = Object.hasOwn(result, "rect");
      if (!Number.isInteger(result.image_id) || result.image_id < 0 || result.image_id > 4294967295 || result.image_id === args.image_id ||
          result.source_image_id !== args.image_id || !(hasEffective || hasRect) ||
          (hasEffective && !matches(result.effective_rect)) || (hasRect && !matches(result.rect)) ||
          (Object.hasOwn(result, "requested_rect") && !matches(result.requested_rect))) {
        throw new NativeBridgeError("Native CROP completed with invalid new/source image identity or effective rectangle", {session: bridge.session, requestId: reply.id, code: "NATIVE_PROTOCOL", sent: true});
      }
    }
    if (reply.state === "completed" && name === "dm_native_show" &&
        (result.image_id !== args.image_id || result.delivery !== "visible_dm_document" || result.document_visible !== true)) {
      throw new NativeBridgeError("Native SHOW completed without the requested image identity and visible DM document delivery", {session: bridge.session, requestId: reply.id, code: "NATIVE_PROTOCOL", sent: true});
    }
    const output = reply.state === "completed" ? {...result, ...(import_handoff?{import_handoff}:{}), native_receipt} : {native_receipt, error: reply.error || `Native request is ${reply.state}; only completed is success`};
    // SHOW confirms document delivery, not the active workspace or GUI focus.
    // Also annotate recovered historical SHOWs; this is adapter policy, not
    // a fresh visibility probe or a rewrite of the stored native receipt.
    if (reply.state === "completed" && reply.original_operation === "SHOW") {
      output.display_context = {
        scope: "document_delivery_only",
        active_workspace_visibility: "unknown",
        workspace_activation_requested: false,
        model_visual_verification: false,
        observation: "not_performed_by_mcp",
      };
    }
    const content = [{type: "text", text: JSON.stringify(output, null, 2)}];
    if (reply.state === "completed" && reply.original_operation === "PREVIEW") content.push(nativePreviewImage(result));
    return {content, ...(reply.state !== "completed" ? {isError: true} : {})};
  } catch (error) {
    // Let the existing MCP cancellation path suppress the response; returning a
    // tool result here would fall through after handle() sees an aborted signal.
    if (signal?.aborted) throw error;
    if (!(error instanceof NativeBridgeError)) throw error;
    return {content: [{type: "text", text: JSON.stringify(error.details, null, 2)}], isError: true};
  }
}

return {id:'dm-native',enabled:true,instructions:NATIVE_INSTRUCTIONS,
  tools:nativeTools.map(definition=>({definition,contract:nativeContract(definition),execute:(args,{signal}={})=>callNativeTool(definition.name,args,signal)})),
  close:()=>bridge.close()};
}
