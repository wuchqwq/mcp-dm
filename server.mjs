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
 * DM operations go through dm_bridge.py over loopback TCP. Optional preview
 * and report helpers run outside GMS; reports are not required for core tools.
 * Reason: DigitalMicrograph.pyd only loads inside the DM process, so an
 * external interpreter cannot import the host module directly.
 */

import net from "node:net";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import process from "node:process";
import { NativeBridge, NativeBridgeError, validRequestId } from "./lib/native_bridge.mjs";
import { nativePreviewImage } from "./lib/native_preview.mjs";

const BACKEND = process.env.DM_MCP_BACKEND === undefined ? "python" : process.env.DM_MCP_BACKEND;
if (!["python", "native"].includes(BACKEND)) throw new Error("DM_MCP_BACKEND must be python or native; no implicit backend fallback");
const BRIDGE_HOST = process.env.DM_BRIDGE_HOST || "127.0.0.1";
const BRIDGE_PORT = Number(process.env.DM_BRIDGE_PORT || 8765);
const TIMEOUT_MS = Number(process.env.DM_MCP_TIMEOUT_MS || 30000);
const ANALYSIS_PYTHON = process.env.DM_ANALYSIS_PYTHON || "python";
const ANALYSIS_WORKER_TIMEOUT_MS = Number(process.env.DM_ANALYSIS_TIMEOUT_MS || 1200000);
const ANALYSIS_WORKER = path.join(path.dirname(fileURLToPath(import.meta.url)), "tools", "analysis_worker.py");
const SERVER_NAME = "digitalmicrograph";
const SERVER_VERSION = "0.6.0";
const PROTOCOL_VERSION = "2024-11-05";
if (BACKEND === "python" && !["127.0.0.1", "localhost"].includes(BRIDGE_HOST)) throw new Error("DM bridge must use IPv4 loopback");
if (BACKEND === "python" && (!Number.isInteger(BRIDGE_PORT) || BRIDGE_PORT < 1 || BRIDGE_PORT > 65535)) throw new Error("Invalid bridge port");
if (!Number.isFinite(TIMEOUT_MS) || TIMEOUT_MS < 100 || TIMEOUT_MS > 600000) throw new Error("Invalid timeout (100..600000 ms)");
if (BACKEND === "python" && (!Number.isFinite(ANALYSIS_WORKER_TIMEOUT_MS) || ANALYSIS_WORKER_TIMEOUT_MS < 1000 || ANALYSIS_WORKER_TIMEOUT_MS > 3600000)) throw new Error("Invalid analysis timeout (1000..3600000 ms)");

const INSTRUCTIONS = [
  "DigitalMicrograph 分析用 MCP（仅分析，不控制电镜）。",
  "定位：可靠的 DM 工具接口，不是固定分析流水线。先用 dm_status/dm_datasets 识别数据，再按目标选择 metadata/stats/profile/fft/crop/export；简单操作无需捕获包或报告。多步调用应固定显式 image_id。",
  "需要看图或固定多步输入时，可用 dm_2d_capture + dm_2d_preview；显示 PNG 不参与计算。dm_2d_analyze 是可选的完整报告示例，只在用户需要这种组合时调用。dm_2d_result 可独立查询状态。",
  "dm_run_script 调用返回不代表分析成功；必须检查输出和后置条件。超时或取消仅停止等待，已经发送的 DM 操作可能仍在运行，不要自动重试。导出禁止覆盖已有文件。",
  "实验性光谱工具只接受明确指定的 NumPy 能量轴（eV/keV 标定），不自动判断 EDS/EELS；真实 EDS/EELS/SI 为 NOT_TESTED，仅合成数据覆盖。四维衍射与 nm 空间轴不适用。",
  "离线参考手册：Scripting_DigitalMicrograph.pdf（DM-Script）、PythonReference.pdf（Python API），位于 C:\\ProgramData\\Gatan\\Documentation。",
].join("\n");
const NATIVE_INSTRUCTIONS = [
  "实验性 DigitalMicrograph C++ NB2 bridge，仅用于明确启动的指定构建；只在宿主空闲且不编辑源图时调用。源图保持只读，不控制硬件。",
  "提供有限原生工具：dm_status、dm_datasets、dm_native_mean、dm_native_summary、dm_native_result、dm_crop、dm_native_show、dm_native_unary、dm_native_binary、dm_native_fft、dm_native_complex、dm_native_filter、dm_native_preview、dm_native_read、dm_native_result_info、dm_native_release；结果释放只释放插件引用，必须提供创建回执的 token 和预先保存的 request_id；未实现工具明确拒绝，绝不回退到 Python。图像 ID 跨工作区；SHOW 不保证激活结果所在标签页，不能据回执声称当前页或模型已看到图像。mean 只返回原生均值；summary 仅返回 minimum/maximum/sum/mean 四个原生摘要值，均不代表完整 stats，不应用强度标定。已识别的不可用空间标定通过元数据报告，不妨碍 raw intensity 摘要。DM 执行有限算术、Fourier 与滤波；复数 power 为平方模，不是幅值。preview 仅作显示适配，不是科研导出；read 仅交接明确 ROI 的有界原始数值和标定，不写文件或创建图像。dm_native_show 仅为本插件仍持有的已合格结果创建或复用包含该明确 image_id 的可见 DM 文档，不保存文件，不代表模型已看图。正常 STOP/cleanup 释放插件持有的结果引用，不关闭已显示的文档。",
  "每次提交返回 native_receipt 含 session/request_id 和 NB2 原操作身份。crop、show、unary、binary、fft、complex、filter 等副作用工具必须使用客户端在提交前保存的 request_id；只读 status/datasets/mean/summary/preview/read 可省略并生成 UUID。超时、取消、断连均不代表操作终止，使用 dm_native_result 在原 session 查询同一 ID，不自动重发；STOP 或新 session 不承诺恢复旧结果。",
  "queued/running/unknown 均不是成功。backend 必须检查宿主实际返回值；mock-native 只代表合成测试。",
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

const bridge = BACKEND === "native" ? new NativeBridge({session: process.env.DM_NATIVE_SESSION, timeoutMs: TIMEOUT_MS}) : new Bridge();

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
    "链路自检：桥接后端（digitalmicrograph/mock）、DM 版本、宿主 Python 与 numpy 版本、官方离线手册路径。DM 连接或原生操作出错时检查它；本地预览/报告依赖错误应检查 DM_ANALYSIS_PYTHON，不要因此重启 DM。",
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
    "沿两点取强度剖面：直接传 x0/y0/x1/y1 原图像素中心坐标（不是 start/end；只有 dm_2d_preview 的 profile 对象用 start/end）。可指定 width，按标定返回距离。",
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
    "二维 FFT：返回去均值后的 DC、频谱格点坐标与按两个方向标定换算的空间频率/间距。d_pix 仅为频谱格点半径，不能当作 1/pixel 或晶格间距。",
    {
      image_id: IMAGE_ID,
      rect: RECT,
      top_n: { type: "integer", minimum: 1, maximum: 200, description: "返回最强频谱格点数，默认 12；不等同独立衍射斑点识别" },
    }
  ),
  tool(
    "dm_2d_capture",
    "一次解析图像（默认 front），在新目录保存有界二维像素副本与标定；后续二维预览和分析固定读取该包。捕获期间请勿编辑源图；DM API 不提供像素与标定的原子快照。",
    { image_id: IMAGE_ID, rect: RECT,
      output_dir: { type: "string", description: "必须是尚不存在的新 Windows 绝对目录；仅保存捕获的二维 ROI、标定与哈希" } },
    ["output_dir"]
  ),
  tool(
    "dm_2d_preview",
    "从 dm_2d_capture 包生成线性显示 PNG 和准确源坐标映射；可叠加 ROI 与剖面条带。显示拉伸不用于计算，返回 MCP image block、本地 PNG 路径及捕获时的标定。只看图无需调用 dm_2d_analyze；不能显示图片时明确说明，不假装看见。",
    { capture_dir: { type: "string", description: "dm_2d_capture 返回的目录" },
      roi: { ...RECT, description: "原图 source pixel 的半开边界 [x0,y0,x1,y1]，须在捕获区域内" },
      profile: { type: "object", properties: {
        start: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" }, description: "原图 source pixel 中心 [x,y]" },
        end: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" }, description: "原图 source pixel 中心 [x,y]" },
        width: { type: "integer", minimum: 1, maximum: 1024, description: "剖面宽度（像素），默认 1" },
      }, required: ["start", "end"], additionalProperties: false },
      max_side: { type: "integer", minimum: 32, maximum: 4096, description: "最长预览边像素，默认 1024" } },
    ["capture_dir"]
  ),
  tool(
    "dm_2d_analyze",
    "可选报告示例，不是使用 DM 的必经步骤。对捕获包组合统计、剖面和完整 FFT，在新目录保存数值、图、报告及复跑脚本。需要独立报告环境；简单测量优先用单独工具。operation_id + result_dir 用于查询，不自动重跑不确定任务。",
    { capture_dir: { type: "string" }, result_dir: { type: "string", description: "必须是尚不存在的新 Windows 绝对目录" },
      operation_id: { type: "string", minLength: 1, maxLength: 128 }, roi: { ...RECT, description: "原图 source pixel 半开边界；省略表示整个捕获区域" },
      profile: { type: "object", properties: {
        start: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" }, description: "原图 source pixel 中心 [x,y]" },
        end: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" }, description: "原图 source pixel 中心 [x,y]" },
        width: { type: "integer", minimum: 1, maximum: 1024 },
      }, required: ["start", "end"], additionalProperties: false },
      top_n: { type: "integer", minimum: 1, maximum: 200, description: "FFT 峰值摘要数量；完整频谱同时写入 NPY，默认 12" } },
    ["capture_dir", "result_dir", "operation_id"]
  ),
  tool(
    "dm_2d_result",
    "只查询捕获或分析目录中的状态与输出哈希。running 返回 unknown，不判断计算已停止；不自动重发捕获或分析。两种目录参数恰选其一。",
    { result_dir: { type: "string", description: "dm_2d_analyze 使用的结果目录" },
      capture_dir: { type: "string", description: "dm_2d_capture 使用的捕获目录" } }
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

const NATIVE_REQUEST_ID = {type: "string", minLength: 1, maxLength: 64, pattern: "^[A-Za-z0-9_-]{1,64}$", description: "可选客户端请求 ID；省略时生成 UUID。取消前预先保存此 ID，之后只用 dm_native_result 查询，不自动重发"};
const NATIVE_IMAGE_ID = {type: "integer", minimum: 0, maximum: 4294967295, description: "dm_datasets 返回的显式 uint32 图像 ID；不接受 front 或数字字符串"};
// Read-only tools may generate an ID; side-effect tools require a saved ID.
const NATIVE_OPTIONAL_REQUEST_ID_TOOLS = new Set(["dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary", "dm_native_preview", "dm_native_read"]);
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
    rect: {...RECT, items: {type: "integer", minimum: 0, maximum: 4294967295}},
    request_id: {...NATIVE_REQUEST_ID, description: "必填：客户端在提交前保存的 [A-Za-z0-9_-]{1,64} 请求 ID；超时/取消/断连后在同一 session 用 dm_native_result 查询。STOP 或新 session 不承诺恢复"},
  }, ["image_id", "rect", "request_id"]),
  tool("dm_native_show", "实验性指定构建：仅为本插件仍持有的已合格原生结果（该 dtype 的交付能力也必须已合格）创建或复用包含该明确 image_id 的可见 DM 文档；显式数字 image_id 和提交前已保存的 request_id 必填，不选择最新/前台窗口。首次创建在当前工作区；复用已有文档不保证激活其工作区标签页。只在 DM 空闲且不编辑源图时调用，源图不改，不保存文件，不代表模型已看图。正常 native STOP/cleanup 只释放插件的结果引用，不关闭已显示的文档；超时/取消/断连后在原 session 只查询同 ID，不自动重发，不回退 Python。", {
    image_id: {...NATIVE_IMAGE_ID, description: "本插件仍持有的已合格原生结果 image_id（显式 uint32）；不接受任意源图、front 或数字字符串"},
    request_id: {...NATIVE_REQUEST_ID, description: "必填：客户端在提交前保存的 [A-Za-z0-9_-]{1,64} 请求 ID；超时/取消/断连后在同一 session 用 dm_native_result 查询。STOP 或新 session 不承诺恢复"},
  }, ["image_id", "request_id"]),
  tool("dm_native_unary", "DM 原生逐像素 negate/abs/square，显式二维 float32 或经宿主逐项获准的 uint32 image_id；uint32 的原生结果为 float32，dtype_semantics 明示并非任意整数的无损运算。产生插件持有的独立结果，源图不改。宿主空闲时串行调用，不回退或重发。", {
    image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_UNARY)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "operation", "request_id"]),
  tool("dm_native_binary", "DM 原生逐像素 add/subtract/multiply，显式且兼容的两个二维 float32 图像或经宿主逐项获准的 uint32 输入；uint32 原生二元结果为 float32，按 dtype_semantics 报告精度限制，不是任意整数的无损运算。产生独立结果，源图不改，不支持 divide。宿主空闲时串行调用，不回退或重发。", {
    left_image_id: NATIVE_IMAGE_ID, right_image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_BINARY)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["left_image_id", "right_image_id", "operation", "request_id"]),
  tool("dm_native_fft", "有限 DM 原生二维 Fourier：forward 接受 float32 或经宿主 dtype 能力获准的 uint32，原生 complex64 输出不是无损整数表示；按 dtype_semantics 报告单精度限制。forward 为正指数、未归一化并 fftshift 的 full complex；inverse 为负指数且除以像素数。仅显式 ID，最多每轴 256/65536 像素；不是旧 dm_fft。数学频率使用 frequency_grid，勿将 DM 半 bin 标定偏移当作 DC。产生独立结果，源图不改。", {
    image_id: NATIVE_IMAGE_ID, direction: {type: "string", enum: ["forward", "inverse"]}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "direction", "request_id"]),
  tool("dm_native_complex", "DM 原生 full complex 分量：real、imaginary、phase（弧度）、power（平方模，不是幅值）；产生独立实数结果，源图不改，最多每轴 256/65536 像素。", {
    image_id: NATIVE_IMAGE_ID, component: {type: "string", enum: Object.keys(NATIVE_COMPLEX)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "component", "request_id"]),
  tool("dm_native_filter", "DM 原生二维 float32 或经宿主逐项获准的 uint32 smooth/sobel/laplace/sharpen。uint32 的 smooth/sharpen 原生输出 uint32，sobel/laplace 原生输出 float32；实际存储和精度限制由 dtype_semantics 明示，桥端不做像素 cast。产生独立结果且保留空间标定，源图不改；算法及边缘语义以回执为准。宿主空闲时串行调用，不回退或重发。", {
    image_id: NATIVE_IMAGE_ID, operation: {type: "string", enum: Object.keys(NATIVE_FILTER)}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ["image_id", "operation", "request_id"]),
  tool("dm_native_preview", "显式二维 float32/uint32 图像的有界灰度 PNG 显示：原生点读取、最近邻采样，最大 128×128，不放大。仅显示适配，不是定量分析或科研文件导出，不修改源图；不代表模型已经看见。", {
    image_id: NATIVE_IMAGE_ID, max_width: {type: "integer", minimum: 1, maximum: 128, default: 128},
    max_height: {type: "integer", minimum: 1, maximum: 128, default: 128}, request_id: NATIVE_REQUEST_ID,
  }, ["image_id"]),
  tool("dm_native_read", "DM 原生读取显式二维 float32/uint32 图像的半开 ROI，最多 16384 样本/65536 原始字节；返回保留源 dtype 的 little-endian 4 字节标量 base64、行优先 shape/轴序和 ROI 标定。源图只读，源图最多 4194304 像素；不裁夹、不生成图片、不保存文件，不是 DM SaveAs。只在宿主空闲且不编辑源图时调用，snapshot_atomic:false；用于调用方显式数值交接，不回退 Python。", {
    image_id: NATIVE_IMAGE_ID, rect: {...RECT, items: {type: "integer", minimum: 0, maximum: 4294967295}}, request_id: NATIVE_REQUEST_ID,
  }, ["image_id", "rect"]),
  tool('dm_native_result_info', '查询明确结果的当前插件引用状态。必须同时提供创建回执中的 image_id 和 retention.token；这是该次查询执行时的快照；刷新状态用新查询 ID，旧 ID 的 QUERY 保持历史。已释放结果可能仍由用户文档持有，但不能继续作为插件处理输入。', {
    image_id: {...NATIVE_IMAGE_ID, minimum: 1}, retention_token: {type: 'integer', minimum: 1, maximum: 4294967295}, request_id: NATIVE_REQUEST_ID,
  }, ['image_id', 'retention_token']),
  tool('dm_native_release', '只释放本 session 插件自己持有的明确结果引用，要求 image_id、创建回执中的 retention.token 及预先保存的 request_id；不关闭文档、不销毁源图、不自动清理祖先，不篡改旧 completed 回执。超时只查询原请求 ID。', {
    image_id: {...NATIVE_IMAGE_ID, minimum: 1}, retention_token: {type: 'integer', minimum: 1, maximum: 4294967295}, request_id: NATIVE_SAVED_REQUEST_ID,
  }, ['image_id', 'retention_token', 'request_id']),
];

function nativeInvocation(name, args) {
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

async function callNativeTool(name, args, signal) {
  const catalog = nativeTools.find(entry => entry.name === name);
  if (!catalog) throw new RpcError(-32602, `native backend 不支持工具: ${name}；不会回退 Python`);
  args = args === undefined ? {} : args;
  validate(args, catalog.inputSchema);
  if (!NATIVE_OPTIONAL_REQUEST_ID_TOOLS.has(name) && !validRequestId(args.request_id)) throw new RpcError(-32602, "request_id 必须由客户端在提交前保存，并匹配 [A-Za-z0-9_-]{1,64}");
  if (args.request_id !== undefined && !validRequestId(args.request_id)) throw new RpcError(-32602, "request_id 必须匹配 [A-Za-z0-9_-]{1,64}");
  if (["dm_crop", "dm_native_read"].includes(name) && (args.rect[2] <= args.rect[0] || args.rect[3] <= args.rect[1])) throw new RpcError(-32602, "rect 必须为正面积，右下边界不包含");
  if (name === "dm_native_read" && (args.rect[2] - args.rect[0]) * (args.rect[3] - args.rect[1]) > 16384) throw new RpcError(-32602, "READ ROI 超出 16384 样本预算");
  try {
    const options = {requestId: args.request_id, signal};
    const reply = name === "dm_native_result" ? await bridge.query(args.request_id, options)
      : await bridge.execute(...nativeInvocation(name, args), options);
    const {result, ...receipt} = reply;
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
    const output = reply.state === "completed" ? {...result, native_receipt} : {native_receipt, error: reply.error || `Native request is ${reply.state}; only completed is success`};
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
  dm_2d_capture: ["capture2d", (a) => ({ image_id: a.image_id, rect: a.rect, output_dir: a.output_dir })],
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

const LOCAL_ACTIONS = {
  dm_2d_preview: "preview",
  dm_2d_analyze: "analyze",
  dm_2d_result: "result",
};

function runAnalysisWorker(payload, signal) {
  if (signal?.aborted) return Promise.reject(new Error("请求已取消，尚未启动本地分析进程"));
  const body = JSON.stringify(payload);
  if (Buffer.byteLength(body, "utf8") > 1024 * 1024) {
    return Promise.reject(new Error("分析请求超过 1 MiB；未启动进程"));
  }
  const child = spawn(ANALYSIS_PYTHON, [ANALYSIS_WORKER], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  return new Promise((resolve, reject) => {
    let chunks = [], bytes = 0, stderr = "", settled = false, discardOutput = false;
    const queryHint = "结果状态未知；使用 dm_2d_result 查询对应 capture_dir/result_dir，勿自动重试。";
    // Settling a client wait is not the end of the child process lifetime.
    const settle = (fn, value) => {
      if (!settled) { settled = true; signal?.removeEventListener("abort", onAbort); fn(value); }
    };
    const killChild = () => { try { child.kill(); } catch {} };
    const discard = () => { discardOutput = true; chunks = []; };
    const onAbort = () => {
      discard();
      settle(reject, new Error("已停止等待；本地计算可能仍在执行。" + queryHint));
    };
    // This deadline survives cancellation. Termination is requested, never
    // represented as proof that all side effects were rolled back.
    const timer = setTimeout(() => {
      discard(); killChild();
      settle(reject, new Error("本地分析达到运行时限，已请求终止进程；" + queryHint));
    }, ANALYSIS_WORKER_TIMEOUT_MS);
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", onAbort); };
    signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout.on("data", chunk => {
      if (discardOutput) return;
      bytes += chunk.length;
      if (bytes > 4 * 1024 * 1024) {
        discard(); killChild();
        settle(reject, new Error("本地分析响应超过 4 MiB；" + queryHint));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.on("data", chunk => { if (stderr.length < 8192) stderr += chunk.toString("utf8").slice(0, 8192 - stderr.length); });
    child.once("error", err => {
      cleanup(); discard();
      settle(reject, new Error("无法启动独立分析 Python（DM_ANALYSIS_PYTHON）: " + err.message));
    });
    const inputError = err => {
      discard(); killChild();
      settle(reject, new Error("本地分析输入管道失败: " + err.message + "；" + queryHint));
    };
    // EPIPE must be a tool error, not an unhandled EventEmitter error that
    // terminates the MCP server and all of the client's other tool calls.
    child.stdin.on("error", inputError);
    child.once("close", code => {
      cleanup();
      if (settled) return;
      try {
        let reply;
        try { reply = JSON.parse(Buffer.concat(chunks, bytes).toString("utf8")); }
        catch { throw new Error("本地分析进程没有返回有效 JSON" + (stderr ? ": " + stderr : "")); }
        if (!reply || typeof reply !== "object" || Array.isArray(reply)) throw new Error("本地分析返回无效响应对象");
        if (code !== 0 || reply.ok !== true) throw new Error(reply.error || stderr || "本地分析进程失败");
        const result = reply.result;
        if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("本地分析返回无效 result 对象");
        const content = [{ type: "text", text: JSON.stringify(result, null, 2) }];
        if (payload.action === "preview") {
          if (!Number.isSafeInteger(result.preview_bytes) || result.preview_bytes < 0 || typeof result.preview_path !== "string") {
            throw new Error("本地预览缺少有效 PNG 路径或字节数");
          }
          if (result.preview_bytes <= 2 * 1024 * 1024) {
            const image = requireFile(result.preview_path);
            content.push({ type: "image", data: image.toString("base64"), mimeType: "image/png" });
          } else {
            result.inline_image = "omitted: PNG exceeds 2 MiB; open preview_path locally";
            content[0].text = JSON.stringify(result, null, 2);
          }
        }
        settle(resolve, { content });
      } catch (err) { settle(reject, err); }
    });
    try { child.stdin.end(body); } catch (err) { inputError(err); }
    if (signal?.aborted) onAbort();
  });
}

function requireFile(file) {
  const bytes = readFileSync(file);
  if (bytes.length > 2 * 1024 * 1024) throw new Error("preview PNG exceeds inline image limit");
  return bytes;
}

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
  if (BACKEND === "native") return callNativeTool(name, args, signal);
  const entry = OPS[name];
  if (!Object.hasOwn(OPS, name) && !Object.hasOwn(LOCAL_ACTIONS, name)) throw new RpcError(-32602, `未知工具: ${name}`);
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
  if (args.image_id !== undefined && args.image_id !== "front") {
    const numericId = typeof args.image_id === "string" && /^[0-9]+$/.test(args.image_id) ? Number(args.image_id) : args.image_id;
    if (!Number.isSafeInteger(numericId) || numericId < 0) throw new RpcError(-32602, 'image_id 必须是非负安全整数或 "front"，请使用 dm_datasets 返回的 ID');
  }
  if (args.roi && (args.roi[2] <= args.roi[0] || args.roi[3] <= args.roi[1])) throw new RpcError(-32602, "roi 必须是正面积的原图坐标区域，右下边界不包含");
  if (args.profile && args.profile.start.every((v, i) => v === args.profile.end[i])) throw new RpcError(-32602, "profile 两个端点不能重合；请使用原图像素中心坐标");
  if (args.spatial_bounds?.some(([start, stop]) => stop <= start)) throw new RpcError(-32602, "spatial_bounds 每对必须 start<stop，stop 不包含");
  if (args.energy_window_eV && args.energy_window_eV[1] <= args.energy_window_eV[0]) throw new RpcError(-32602, "energy_window_eV 必须 low<high，high 不包含");
  if (args.path !== undefined && (!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(args.path) || args.path.includes("\0"))) throw new RpcError(-32602, "path 必须是 Windows 绝对路径");
  for (const key of ["output_dir", "capture_dir", "result_dir"]) {
    if (args[key] !== undefined && (!/^(?:[A-Za-z]:[\\/]|\\\\)/.test(args[key]) || args[key].includes("\0"))) {
      throw new RpcError(-32602, `${key} 必须是 Windows 绝对路径`);
    }
  }
  if (name === "dm_spectrum_export" && !/\.csv$/i.test(args.path)) throw new RpcError(-32602, "dm_spectrum_export 只支持 .csv 文件");
  if (args.script !== undefined && (!args.script.trim() || Buffer.byteLength(args.script, "utf8") > 1024 * 1024)) throw new RpcError(-32602, "script 不能为空或超过 1 MiB");
  if (name === "dm_2d_analyze" && (typeof args.operation_id !== "string" || !args.operation_id.trim() || args.operation_id.length > 128)) {
    throw new RpcError(-32602, "operation_id 必须是 1 到 128 字符的非空字符串");
  }
  if (name === "dm_2d_result" && (Boolean(args.result_dir) === Boolean(args.capture_dir))) {
    throw new RpcError(-32602, "dm_2d_result 需要且只接受 result_dir 或 capture_dir 其中一个");
  }
  if (Object.hasOwn(LOCAL_ACTIONS, name)) {
    return runAnalysisWorker({ action: LOCAL_ACTIONS[name], ...args }, signal);
  }
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
      instructions: BACKEND === "native" ? NATIVE_INSTRUCTIONS : INSTRUCTIONS,
    });
  }
  if (method === "ping") return ok(id, {});
  if (method === "tools/list") return ok(id, { tools: BACKEND === "native" ? nativeTools : tools });
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
