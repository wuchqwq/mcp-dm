#!/usr/bin/env node
/**
 * server.mjs -- DigitalMicrograph MCP server (stdio, zero dependencies).
 *
 * SCOPE: post-acquisition analysis only. This server does not drive the
 * column, the stage, or detectors. It exists so an agent can use what
 * DigitalMicrograph is uniquely good at: dm3/dm4 files carry full
 * acquisition metadata and spatial calibration, and DM's own processing
 * (DM-Script, EELS/EDS/SI plugins) operates on that metadata.
 *
 * The process is a thin MCP facade; all work happens inside the running
 * DigitalMicrograph instance via dm_bridge.py over loopback TCP.
 * Reason: DigitalMicrograph.pyd only loads inside the DM process, so an
 * external interpreter cannot import the host module directly.
 */

import net from "node:net";
import process from "node:process";

const BRIDGE_HOST = process.env.DM_BRIDGE_HOST || "127.0.0.1";
const BRIDGE_PORT = Number(process.env.DM_BRIDGE_PORT || 8765);
const TIMEOUT_MS = Number(process.env.DM_MCP_TIMEOUT_MS || 30000);
const SERVER_NAME = "digitalmicrograph";
const SERVER_VERSION = "0.6.0";
const PROTOCOL_VERSION = "2024-11-05";
if (!["127.0.0.1", "localhost"].includes(BRIDGE_HOST)) throw new Error("DM bridge must use IPv4 loopback");
if (!Number.isInteger(BRIDGE_PORT) || BRIDGE_PORT < 1 || BRIDGE_PORT > 65535) throw new Error("Invalid bridge port");
if (!Number.isFinite(TIMEOUT_MS) || TIMEOUT_MS < 100 || TIMEOUT_MS > 600000) throw new Error("Invalid timeout (100..600000 ms)");

const INSTRUCTIONS = [
  "DigitalMicrograph 分析用 MCP（仅分析，不控制电镜）。",
  "推荐顺序：dm_status 确认真实后端 → dm_open → dm_datasets 检查数据集、轴序与标定 → dm_metadata 检查 path_status/complete/issues → dm_stats / dm_profile / dm_fft → dm_export。",
  "dm_run_script 调用返回不代表分析成功；必须检查输出和后置条件。超时或取消仅停止等待，已经发送的 DM 操作可能仍在运行，不要自动重试。导出禁止覆盖已有文件。",
  "实验性光谱工具只接受明确指定的 NumPy 能量轴（eV/keV 标定），不自动判断 EDS/EELS；真实 EDS/EELS/SI 为 NOT_TESTED，仅合成数据覆盖。四维衍射与 nm 空间轴不适用。",
  "离线参考手册：Scripting_DigitalMicrograph.pdf（DM-Script）、PythonReference.pdf（Python API），位于 C:\\ProgramData\\Gatan\\Documentation。",
].join("\n");

/* ------------------------------------------------------------------ */
/* Bridge client                                                       */
/* ------------------------------------------------------------------ */

class Bridge {
  constructor() {
    this.socket = null;
    this.connecting = null;
    this.pending = new Map();
    this.nextId = 1;
    this.queue = Promise.resolve();
  }

  connect(timeoutMs) {
    if (this.socket && !this.socket.destroyed) return Promise.resolve();
    if (this.connecting) return this.connecting;
    const attempt = new Promise((resolve, reject) => {
      const socket = net.createConnection({ host: "127.0.0.1", port: BRIDGE_PORT });
      let buffer = "";
      const timer = setTimeout(() => onError(new Error("连接超时")), timeoutMs);
      const onError = (err) => {
        clearTimeout(timer);
        socket.destroy();
        reject(
          new Error(
            `无法连接 DigitalMicrograph 桥接端口 ${BRIDGE_HOST}:${BRIDGE_PORT} (${err.code || err.message})。` +
              `请在 DigitalMicrograph 的 Python 工作区运行 dm_bridge.py 后重试。`
          )
        );
      };
      socket.once("error", onError);
      socket.once("connect", () => {
        clearTimeout(timer);
        socket.off("error", onError);
        socket.setNoDelay(true);
        socket.setEncoding("utf8");
        socket.on("data", (chunk) => {
          if (this.socket !== socket) return;
          buffer += chunk;
          if (Buffer.byteLength(buffer, "utf8") > 16 * 1024 * 1024) {
            this._failAll(socket, "桥接响应超过 16 MiB");
            socket.destroy();
            return;
          }
          let idx;
          while ((idx = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 1);
            if (!line) continue;
            try { this._onMessage(JSON.parse(line)); }
            catch { this._failAll(socket, "桥接返回无效 JSON，操作状态未知，请检查 DM"); socket.destroy(); return; }
          }
        });
        socket.on("close", () => this._failAll(socket, "bridge connection closed；已发送操作的执行状态未知"));
        socket.on("error", () => {});
        this.socket = socket;
        resolve();
      });
    });
    this.connecting = attempt;
    attempt.then(() => { if (this.connecting === attempt) this.connecting = null; }, () => { if (this.connecting === attempt) this.connecting = null; });
    return attempt;
  }

  _onMessage(msg) {
    const waiter = this.pending.get(msg.id);
    if (!waiter) return;
    waiter.finish();
    if (msg.ok) waiter.resolve(msg.result);
    else waiter.reject(new Error(msg.error || "bridge error"));
  }

  _failAll(socket, reason) {
    if (this.socket !== socket) return;
    for (const waiter of [...this.pending.values()]) {
      waiter.finish();
      waiter.reject(new Error(reason));
    }
    this.socket = null;
  }

  call(op, args = {}, timeoutMs = TIMEOUT_MS, signal) {
    const deadline = Date.now() + timeoutMs;
    const run = () => this._call(op, args, deadline, signal);
    const result = this.queue.then(run, run);
    this.queue = result.catch(() => {});
    return result;
  }

  async _call(op, args, deadline, signal) {
    if (signal?.aborted) throw new Error("请求已取消，尚未发送到 DM");
    if (deadline <= Date.now()) throw new Error("请求在排队时超时，尚未发送到 DM");
    await this.connect(deadline - Date.now());
    if (signal?.aborted) throw new Error("请求已取消，尚未发送到 DM");
    if (deadline <= Date.now()) throw new Error("请求在连接时超时，尚未发送到 DM");
    const id = this.nextId++;
    const payload = JSON.stringify({ id, op, args }) + "\n";
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        finish();
        reject(new Error(`桥接请求超时: ${op}；操作可能仍在 DM 中执行，状态未知，不要自动重试`));
      }, Math.max(1, deadline - Date.now()));
      const onAbort = () => { finish(); reject(new Error("等待已取消；操作可能仍在 DM 中执行，状态未知，不要自动重试")); };
      const finish = () => { clearTimeout(timer); this.pending.delete(id); signal?.removeEventListener("abort", onAbort); };
      this.pending.set(id, { resolve, reject, finish });
      signal?.addEventListener("abort", onAbort, { once: true });
      this.socket.write(payload, (err) => {
        if (err) {
          finish();
          reject(new Error(`${err.message}；发送状态未知，请检查 DM`));
        }
      });
    });
  }

  close() {
    const socket = this.socket;
    if (socket) { this._failAll(socket, "MCP client closed"); socket.destroy(); }
  }
}

const bridge = new Bridge();

/* ------------------------------------------------------------------ */
/* Tool catalog                                                        */
/* ------------------------------------------------------------------ */

const IMAGE_ID = {
  type: ["integer", "string"],
  description: '图像 id（来自 dm_datasets），或 "front" 表示前台窗口',
};

const RECT = {
  type: "array",
  items: { type: "integer", minimum: 0 },
  minItems: 4,
  maxItems: 4,
  description: "像素矩形 [x0, y0, x1, y1]，右下边界不包含；必须完整位于图内，不舍入或裁夹；省略则整幅",
};

const SPECTRUM_IMAGE_ID = {
  type: "integer", minimum: 0,
  description: "dm_datasets 返回的明确图像 id；不接受 front，避免窗口切换改变数据集",
};
const SPECTRUM_ENERGY_AXIS = {
  type: "integer", minimum: 0, maximum: 2,
  description: "NumPy 轴序中的能量轴，0 起始（不是 DM 维号）；必须具有 eV 或 keV 标定。支持 1D/2D/3D，拒绝 4D 衍射",
};
const SPECTRUM_BOUNDS = {
  type: "array", minItems: 0, maxItems: 2,
  items: { type: "array", minItems: 2, maxItems: 2, items: { type: "integer", minimum: 0 } },
  description: "其余空间轴按 NumPy 原始顺序的 [start,stop) 边界；显式提供时必须覆盖所有空间轴。每对 start<stop，不裁夹越界值；省略则全部空间范围",
};
const SPECTRUM_WINDOW = {
  type: "array", minItems: 2, maxItems: 2, items: { type: "number" },
  description: "以 eV 表示的半开区间 [low,high)，按原始通道中心 low<=E<high 选择，不插值或背景扣除",
};
const SPECTRUM_BASE = {
  image_id: SPECTRUM_IMAGE_ID,
  energy_axis: SPECTRUM_ENERGY_AXIS,
  spatial_bounds: SPECTRUM_BOUNDS,
};
const SPECTRUM_EXTRACT = {
  ...SPECTRUM_BASE,
  reduction: { type: "string", enum: ["sum", "mean"], description: "所选空间范围的逐通道 sum 或 mean；默认 sum；float64 运算，不假定强度单位为 counts" },
  energy_window_eV: SPECTRUM_WINDOW,
};
const SPECTRUM_SCOPE = "实验性基础接口；真实 EDS/EELS/SI 为 NOT_TESTED（未验证），仅合成数据覆盖。不自动识别谱种，不作背景扣除或元素/化学定量，不假定强度单位；拒绝 4D 衍射或 nm 标定能量轴。";

const FOUR_AXES = {type:"array",minItems:2,maxItems:2,items:{type:"integer",minimum:0,maximum:3}};
const FOUR_BOUNDS = {type:"array",minItems:2,maxItems:2,items:{type:"array",minItems:2,maxItems:2,items:{type:"integer",minimum:0}},description:"[[scan_y0,scan_y1],[scan_x0,scan_x1]]，原始NumPy坐标，右端排除"};
const FOUR_SOURCE = {dataset_id:{type:"string",description:"dm_4dstem_open返回的有界文件索引id"},scan_bounds:FOUR_BOUNDS};
const FOUR_DETECTORS = {type:"array",minItems:1,maxItems:8,items:{type:"object",properties:{
  label:{type:"string"},center_q:{type:"array",minItems:2,maxItems:2,items:{type:"number"}},
  r_inner:{type:"number",minimum:0},r_outer:{type:"number",minimum:0}
},required:["label","center_q","r_inner","r_outer"],additionalProperties:false},description:"物理倒空间[qx,qy]中心与半开半径r_inner<=r<r_outer；单位来自显式轴标定，不推断mrad或HAADF"};

function tool(name, description, properties, required = []) {
  return {
    name,
    description,
    inputSchema: { type: "object", properties, required, additionalProperties: false },
  };
}

const tools = [
  tool(
    "dm_status",
    "链路自检：桥接后端（digitalmicrograph/mock）、DM 版本、宿主 Python 与 numpy 版本、官方离线手册路径。任何工具报错时先调它。",
    {}
  ),
  tool(
    "dm_open",
    "在 DigitalMicrograph 中打开本地数据文件（dm3/dm4 及其它 DM 支持的格式），返回该文档内的图像 id 列表。dm3/dm4 的采集元数据与标定会随文件一起载入。",
    {
      path: { type: "string", description: "绝对路径" },
      show: { type: "boolean", description: "是否显示窗口，默认 true" },
    },
    ["path"]
  ),
  tool(
    "dm_datasets",
    "枚举当前 DM 中所有图像数据集：id、名称、形状、维度、dtype、类型提示（image / stack / spectrum image）、每维标定（scale/unit/origin）。分析前必查。",
    {}
  ),
  tool(
    "dm_metadata",
    "读取指定元数据子树。先检查 path_status（found/not_found/unavailable），再检查 complete 和 issues；先定位 prefix 再按子树预算读取，不把截断或读取失败当作标签缺失。",
    {
      image_id: IMAGE_ID,
      max_depth: { type: "integer", minimum: 0, maximum: 32, description: "所选子树的递归深度上限，默认 8；不限制 prefix 的路径深度" },
      prefix: { type: "string", description: 'JSON Pointer，如 "/Acquisition/Instrument"；也接受无首斜线形式；~1 表示斜线，~0 表示波浪号；列表用零基索引；省略或空字符串表示根' },
    }
  ),
  tool(
    "dm_stats",
    "区域统计：min/max/mean/stddev/分位数。可限定矩形区域。",
    { image_id: IMAGE_ID, rect: RECT }
  ),
  tool(
    "dm_profile",
    "沿任意两点取线条剖面，支持剖面宽度平均。横轴按图像标定自动换算成物理距离。",
    {
      image_id: IMAGE_ID,
      x0: { type: "number" },
      y0: { type: "number" },
      x1: { type: "number" },
      y1: { type: "number" },
      width: { type: "integer", minimum: 1, maximum: 255, description: "沿线垂直方向的剖面宽度（像素），默认 1；算法与边界策略随结果返回" },
    },
    ["x0", "y0", "x1", "y1"]
  ),
  tool(
    "dm_fft",
    "二维 FFT：返回去均值前后的 DC、频谱格点坐标与按两个方向标定换算的空间频率/间距。d_pix 仅为频谱格点半径，不能当作 1/pixel 或晶格间距。",
    {
      image_id: IMAGE_ID,
      rect: RECT,
      top_n: { type: "integer", minimum: 1, maximum: 200, description: "返回最强频谱格点数，默认 12；不等同独立衍射斑点识别" },
    }
  ),
  tool(
    "dm_export",
    "导出到新文件，禁止覆盖。dm3/dm4 使用明确 DM writer；TIFF 使用保留原始 dtype 的无压缩科学数据 writer，附嵌入标定；所有格式附标定侧文件。支持 npy/csv/txt/tif/dm3/dm4，拒绝未经定义的 PNG 强度映射。",
    {
      image_id: IMAGE_ID,
      path: { type: "string", description: "绝对路径，目录不存在会自动创建" },
      format: { type: "string", description: "dm3 / dm4 / tif / npy / csv / txt；省略时按扩展名推断，PNG 尚不支持" },
    },
    ["path"]
  ),
  tool(
    "dm_crop",
    "在 DM 内原生裁出二维独立子图，返回新图像 id、标定与 NumPy 轴序 shape[y,x]；右下边界不包含。原图保持不变；不支持三维/四维直接裁剪。",
    {
      image_id: IMAGE_ID,
      rect: { ...RECT, description: "像素矩形 [x0, y0, x1, y1]，必须完整位于图内，不舍入或裁夹" },
      name: { type: "string", description: "新图像名称，省略则自动命名" },
    },
    ["rect"]
  ),
  tool(
    "dm_spectrum_info",
    "读取明确指定数据集的光谱轴、空间选择及能量标定信息。" + SPECTRUM_SCOPE,
    SPECTRUM_BASE,
    ["image_id", "energy_axis"]
  ),
  tool(
    "dm_spectrum",
    "提取原始通道中心与 float64 强度，按空间范围作 sum/mean；能量窗采用 low<=E<high。" + SPECTRUM_SCOPE,
    SPECTRUM_EXTRACT,
    ["image_id", "energy_axis"]
  ),
  tool(
    "dm_spectrum_integrate",
    "对指定能量窗内原始通道作逐空间位置求和，保留其余空间轴。无 bin-width 或梯形权重；结果不能直接认定为元素/化学分布图。" + SPECTRUM_SCOPE,
    { ...SPECTRUM_BASE, energy_window_eV: SPECTRUM_WINDOW },
    ["image_id", "energy_axis", "energy_window_eV"]
  ),
  tool(
    "dm_spectrum_export",
    "按 dm_spectrum 的空间归约与能量选择导出新 CSV（energy_eV,intensity；强度为 float64）和元数据侧文件，禁止覆盖或写回原始数据。" + SPECTRUM_SCOPE,
    { ...SPECTRUM_EXTRACT, path: { type: "string", description: "新 CSV 文件的 Windows 绝对路径，扩展名必须为 .csv；禁止覆盖" } },
    ["image_id", "energy_axis", "path"]
  ),
  tool(
    "dm_4dstem_open",
    "只读索引未压缩uint8 DM4中的唯一4D数据集。仅解析有界header，不整文件OpenImage；后续由Gatan原生只读binary stream按小块读取。显式NumPy轴scan_axes=[0,1]和detector_axes=[2,3]。",
    {path:{type:"string"},scan_axes:FOUR_AXES,detector_axes:FOUR_AXES},["path","scan_axes","detector_axes"]
  ),
  tool(
    "dm_4dstem_read",
    "用Gatan原生只读流读取最多256个扫描位置且不超过16MiB的小4D块，创建独立DM图像并复制四轴物理标定；不修改原文件。",
    FOUR_SOURCE,["dataset_id","scan_bounds"]
  ),
  tool(
    "dm_4dstem_virtual",
    "分块计算虚拟圆形BF/环形ADF、全探测器总强度与平均/总衍射图，发布独立DM图像。每次最多8192扫描位置，分批覆盖全scan；整数uint64求和，原生发布仅允许精确dtype转换；不是硬件角度标定或HAADF认定。",
    {...FOUR_SOURCE,detectors:FOUR_DETECTORS,chunk_patterns:{type:"integer",minimum:1,maximum:128}},["dataset_id","scan_bounds","detectors"]
  ),
  tool(
    "dm_run_script",
    "在 DM 内执行 DM-Script（等价于脚本窗口）。用于调用 DM 原生算法：滤波、漂移校正、EELS/EDS 定量、SI 处理、批量宏等。执行后会自动比对图像集合，报告新产生/被删除的图像 id，便于接着用其它工具量化。默认关闭，需环境变量 DM_MCP_ALLOW_DMSCRIPT=1。",
    {
      script: { type: "string", description: "完整 DM-Script 源码" },
      expect_new_image: {
        type: "boolean",
        description: "声明该脚本应当产生新图像；若没有则返回 warning",
      },
    },
    ["script"]
  ),
];

/* ------------------------------------------------------------------ */
/* MCP plumbing                                                        */
/* ------------------------------------------------------------------ */

function send(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

function ok(id, result) {
  send({ jsonrpc: "2.0", id, result });
}

function fail(id, code, message) {
  send({ jsonrpc: "2.0", id, error: { code, message } });
}

const OPS = {
  dm_4dstem_open: ["fourdstem_open", a=>({...a})],
  dm_4dstem_read: ["fourdstem_read", a=>({...a})],
  dm_4dstem_virtual: ["fourdstem_virtual", a=>({...a})],
  dm_status: ["ping", () => ({})],
  dm_open: ["open_file", (a) => ({ path: a.path, show: a.show })],
  dm_datasets: ["list_datasets", () => ({})],
  dm_metadata: ["metadata", (a) => ({ image_id: a.image_id, max_depth: a.max_depth, prefix: a.prefix })],
  dm_stats: ["stats", (a) => ({ image_id: a.image_id, rect: a.rect })],
  dm_profile: ["profile", (a) => ({ ...a })],
  dm_fft: ["fft", (a) => ({ image_id: a.image_id, rect: a.rect, top_n: a.top_n })],
  dm_export: ["export", (a) => ({ image_id: a.image_id, path: a.path, format: a.format })],
  dm_crop: ["crop", (a) => ({ image_id: a.image_id, rect: a.rect, name: a.name })],
  dm_spectrum_info: ["spectrum_info", (a) => ({ ...a })],
  dm_spectrum: ["spectrum", (a) => ({ ...a })],
  dm_spectrum_integrate: ["spectrum_integrate", (a) => ({ ...a })],
  dm_spectrum_export: ["spectrum_export", (a) => ({ ...a })],
  dm_run_script: ["run_script", (a) => ({ script: a.script, expect_new_image: a.expect_new_image })],
};

class RpcError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

function validate(value, schema, label = "arguments") {
  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  const matches = types.some(t => t === "object" ? value !== null && typeof value === "object" && !Array.isArray(value)
    : t === "array" ? Array.isArray(value)
    : t === "integer" ? Number.isSafeInteger(value)
    : t === "number" ? typeof value === "number" && Number.isFinite(value)
    : typeof value === t);
  if (!matches) throw new RpcError(-32602, `${label}: 类型应为 ${types.join("/")}`);
  if (schema.enum && !schema.enum.includes(value)) throw new RpcError(-32602, `${label}: 不是允许的取值`);
  if (typeof value === "number" && ((schema.minimum !== undefined && value < schema.minimum) || (schema.maximum !== undefined && value > schema.maximum))) {
    throw new RpcError(-32602, `${label}: 超出允许范围`);
  }
  if (Array.isArray(value)) {
    if (value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) throw new RpcError(-32602, `${label}: 元素数量错误`);
    value.forEach((v, i) => validate(v, schema.items, `${label}[${i}]`));
  } else if (types.includes("object")) {
    for (const key of schema.required || []) if (!Object.hasOwn(value, key)) throw new RpcError(-32602, `${label}.${key}: 缺少必填参数`);
    for (const key of Object.keys(value)) {
      if (!Object.hasOwn(schema.properties, key)) throw new RpcError(-32602, `${label}.${key}: 未知参数`);
      validate(value[key], schema.properties[key], `${label}.${key}`);
    }
  }
}

async function callTool(name, args, signal) {
  const entry = OPS[name];
  if (!Object.hasOwn(OPS, name)) throw new RpcError(-32602, `未知工具: ${name}`);
  const catalog = tools.find(t => t.name === name);
  args = args === undefined ? {} : args;
  validate(args, catalog.inputSchema);
  if (name.startsWith("dm_4dstem_")) {
    if (args.dataset_id !== undefined && !/^4d-[1-9][0-9]*$/.test(args.dataset_id)) throw new RpcError(-32602,"invalid 4D dataset_id");
    if (args.scan_axes && (JSON.stringify(args.scan_axes)!=="[0,1]" || JSON.stringify(args.detector_axes)!=="[2,3]")) throw new RpcError(-32602,"native file route requires scan_axes=[0,1], detector_axes=[2,3]");
    if (args.scan_bounds && args.scan_bounds.some(pair=>pair[1]<=pair[0])) throw new RpcError(-32602,"scan bounds must be nonempty half-open intervals");
    if (args.detectors) {
      const labels=new Set();
      for (const d of args.detectors) {
        if (!/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(d.label) || ["total","sum_dp","mean_dp","mean_diffraction","sum_diffraction"].includes(d.label) || labels.has(d.label)) throw new RpcError(-32602,"detector labels must be unique, safe and not reserved");
        labels.add(d.label);
        if (d.r_outer<=d.r_inner) throw new RpcError(-32602,"detector radii require 0<=inner<outer");
      }
    }
  }
  if (args.rect && (args.rect[2] <= args.rect[0] || args.rect[3] <= args.rect[1])) throw new RpcError(-32602, "rect 必须为正面积，右下边界不包含");
  if (args.image_id !== undefined && !(Number.isSafeInteger(args.image_id) || /^(front|[0-9]+)$/.test(args.image_id))) throw new RpcError(-32602, 'image_id 必须是整数或 "front"');
  if (args.spatial_bounds?.some(([start, stop]) => stop <= start)) throw new RpcError(-32602, "spatial_bounds 每对必须 start<stop，stop 不包含");
  if (args.energy_window_eV && args.energy_window_eV[1] <= args.energy_window_eV[0]) throw new RpcError(-32602, "energy_window_eV 必须 low<high，high 不包含");
  if (args.path !== undefined && (!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(args.path) || args.path.includes("\0"))) throw new RpcError(-32602, "path 必须是 Windows 绝对路径");
  if (name === "dm_spectrum_export" && !/\.csv$/i.test(args.path)) throw new RpcError(-32602, "dm_spectrum_export 只支持 .csv 文件");
  if (args.script !== undefined && (!args.script.trim() || Buffer.byteLength(args.script, "utf8") > 1024 * 1024)) throw new RpcError(-32602, "script 不能为空或超过 1 MiB");
  const [op, mapArgs] = entry;
  if (name === "dm_run_script" && process.env.DM_MCP_ALLOW_DMSCRIPT !== "1") {
    throw new Error(
      "dm_run_script 默认关闭（等同任意代码执行）。确认允许后，在 MCP 配置的 env 里设置 DM_MCP_ALLOW_DMSCRIPT=1。"
    );
  }
  const result = await bridge.call(op, mapArgs(args), TIMEOUT_MS, signal);
  return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
}

const running = new Map();
async function handle(msg) {
  if (!msg || typeof msg !== "object" || Array.isArray(msg) || msg.jsonrpc !== "2.0" || typeof msg.method !== "string"
      || (Object.hasOwn(msg, "id") && !(typeof msg.id === "string" || Number.isSafeInteger(msg.id)))) {
    return fail(null, -32600, "Invalid Request");
  }
  const { id, method, params } = msg;
  if (id === undefined) {
    if (method === "notifications/cancelled") running.get(params?.requestId)?.abort();
    return;
  }
  if (params !== undefined && (params === null || typeof params !== "object" || Array.isArray(params))) return fail(id, -32602, "params 必须是对象");
  if (method === "initialize") {
    return ok(id, {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      instructions: INSTRUCTIONS,
    });
  }
  if (method === "ping") return ok(id, {});
  if (method === "tools/list") return ok(id, { tools });
  if (method === "tools/call") {
    if (!params || typeof params.name !== "string") return fail(id, -32602, "需要工具名称");
    if (running.has(id)) return fail(id, -32600, "Duplicate in-flight request id");
    const controller = new AbortController();
    running.set(id, controller);
    try {
      const result = await callTool(params.name, params.arguments, controller.signal);
      if (!controller.signal.aborted) return ok(id, result);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof RpcError) return fail(id, err.code, err.message);
      return ok(id, {
        content: [{ type: "text", text: `错误: ${err.message}` }],
        isError: true,
      });
    } finally {
      running.delete(id);
    }
  }
  if (method === "resources/list") return ok(id, { resources: [] });
  if (method === "prompts/list") return ok(id, { prompts: [] });
  return fail(id, -32601, `Method not found: ${method}`);
}

let stdinBuffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  stdinBuffer += chunk;
  if (Buffer.byteLength(stdinBuffer, "utf8") > 2 * 1024 * 1024) {
    stdinBuffer = "";
    fail(null, -32600, "Request exceeds 2 MiB");
    return;
  }
  let idx;
  while ((idx = stdinBuffer.indexOf("\n")) >= 0) {
    const line = stdinBuffer.slice(0, idx).trim();
    stdinBuffer = stdinBuffer.slice(idx + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      fail(null, -32700, "Parse error");
      continue;
    }
    handle(msg).catch((err) => {
      if (msg && msg.id !== undefined) fail(msg.id, -32603, err.message);
    });
  }
});
process.stdin.on("end", () => {
  bridge.close();
  process.exit(0);
});
process.on("SIGINT", () => {
  bridge.close();
  process.exit(0);
});
