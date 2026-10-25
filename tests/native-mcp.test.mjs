// Real Node stdio MCP with synthetic named-pipe hosts only; no DM acceptance.
import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import {spawn} from "node:child_process";
import {once} from "node:events";
import {randomUUID} from "node:crypto";
import {fileURLToPath} from "node:url";
import {inflateSync} from "node:zlib";
import {NativeBridge} from "../lib/native_bridge.mjs";
import {operationFixture, readFixture, imageMetadata, uint32BinaryFixture, uint32OperationFixture} from "./fixtures/native-operations.mjs";
import {guiRoisFixture} from './fixtures/native-rois.mjs';
import {profileFixture,profileArgs} from './fixtures/native-profile.mjs';
import {frameHandoffFixture} from './fixtures/native-frame-handoff.mjs';
import {pixelCropFixture,pixelFilterFixture,pixelFourierFixture} from './fixtures/native-pixel.mjs';
import {histogramFixture,histogramArgs,histogramIntensityFixture,histogramIndexAxisFixture,histogramShowFixture} from './fixtures/native-histogram.mjs';

const serverPath = fileURLToPath(new URL("../server.mjs", import.meta.url));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const resultTypes = {FRAME: "native_frame_copy", STATUS: "status", DATASETS: "datasets", INFO: "image_info", MEAN: "native_mean", SUMMARY: "native_summary", CROP: "image_crop", SHOW: "image_delivery", STOP: "ipc_stop", RELEASE: "native_result_release", RESULT_INFO: "native_result_availability", ROIS: "native_gui_rois", PROFILE:"native_line_profile"};
Object.assign(resultTypes, {UNARY: "native_image_operation", BINARY: "native_image_operation", FILTER: "native_image_operation", PREVIEW: "native_preview", READ: "native_data_snapshot",
  FFT: "native_fourier_operation", HISTOGRAM: "native_histogram", IFFT: "native_fourier_operation", REAL: "native_fourier_operation", IMAG: "native_fourier_operation", VENDOR_ARG: "native_fourier_operation", VENDOR_NORM: "native_fourier_operation"});
for (const base of ['CROP','FILTER','FFT','IFFT','REAL','IMAG','VENDOR_ARG','VENDOR_NORM'])resultTypes[base+'_PIXEL']=resultTypes[base];
const nativeCatalog = ["dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary", "dm_native_result", "dm_crop", "dm_native_show",
  "dm_native_unary", "dm_native_binary", "dm_native_fft", "dm_native_complex", "dm_native_filter", "dm_native_preview", "dm_native_read", "dm_native_frame", "dm_native_result_info", "dm_native_release", "dm_native_rois", "dm_native_profile", "dm_native_histogram"];

// Contract emulation only: no DM process/vendor computation is used here.
function summaryFixture(imageId = 77) {
  return {backend: "digitalmicrograph-native", image_id: imageId,
    image: {id: imageId, name: "synthetic", ndim: 2, data_type_code: 2, dtype: "float32", packing_style: 1, shape: [3, 4], dm_dimensions: [4, 3],
      shape_order: "numpy (last axis is X)", pixels: 12,
      calibration: [
        {dm_dimension: 0, numpy_axis: 1, size: 4, origin: 2, calibrated_value_at_pixel_zero: 0.5, scale: -0.25, unit: "nm", usable: true, issue: null},
        {dm_dimension: 1, numpy_axis: 0, size: 3, origin: -1, calibrated_value_at_pixel_zero: 0.5, scale: 0.5, unit: "nm", usable: true, issue: null},
      ], calibration_complete: true, native_mean_supported: true, native_summary_supported: true,
      coordinate_rule: "physical(i)=calibrated_value_at_pixel_zero+i*scale"},
    minimum: -3.25, maximum: 8.5, sum: -0.75, mean: -0.0625,
    operators: ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum", "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"],
    computation: "DM native", intensity_calibration_applied: false, intensity_semantics: "raw pixel intensity",
    source_write_requested: false, snapshot_atomic: false};
}

function mcpClient(extraEnv = {}, defaultBackend = false) {
  const env = {...process.env, DM_MCP_TIMEOUT_MS: "150", ...extraEnv};
  if (defaultBackend) delete env.DM_MCP_BACKEND;
  const child = spawn(process.execPath, [serverPath], {env, stdio: ["pipe", "pipe", "pipe"]});
  child.stdin.on("error", () => {});
  let buffer = "", stderr = "", next = 1;
  const pending = new Map(), messages = [];
  child.stderr.on("data", chunk => {stderr += chunk;});
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", chunk => {
    buffer += chunk; let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const message = JSON.parse(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1);
      assert.equal(message.jsonrpc, "2.0", "stdout contains only MCP JSON-RPC");
      assert.notEqual(Object.hasOwn(message, "result"), Object.hasOwn(message, "error"), "strict response envelope");
      messages.push(message);
      const waiter = pending.get(message.id); if (waiter) {pending.delete(message.id); waiter(message);}
    }
  });
  const send = message => child.stdin.write(JSON.stringify({jsonrpc: "2.0", ...message}) + "\n");
  const rpc = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++;
    const timer = setTimeout(() => {pending.delete(id); reject(new Error(`MCP timeout ${method}: ${stderr}`));}, 4000);
    pending.set(id, message => {clearTimeout(timer); resolve(message);});
    send({id, method, params});
  });
  const tool = (name, args = {}) => rpc("tools/call", {name, arguments: args});
  return {child, messages, rpc, tool, send, async init() {
    const response = await rpc("initialize", {protocolVersion: "2024-11-05", capabilities: {}, clientInfo: {name: "strict-synthetic-native", version: "1"}});
    assert.equal(response.error, undefined); assert.equal(response.result.protocolVersion, "2024-11-05");
    send({method: "notifications/initialized"}); return response.result;
  }, async close() {
    if (child.exitCode === null && child.signalCode === null) {const done = once(child, "exit"); child.kill(); await done;}
  }};
}

function toolOutput(message, expectedError = false) {
  assert.equal(message.error, undefined, "RPC envelope must be successful before tool result is inspected");
  assert.equal(Boolean(message.result.isError), expectedError, "MCP tool isError must be inspected separately");
  assert.equal(message.result.content[0].type, "text");
  return JSON.parse(message.result.content[0].text);
}

test('explicit MCP pixel mode has separate wire identity and original-ID QUERY, never a physical fallback',async()=>{
  const saved=new Map();
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.operation!=='QUERY'){
      const output=request.operation==='CROP_PIXEL'?pixelCropFixture():request.operation==='FILTER_PIXEL'?pixelFilterFixture(Number(request.args[1])):pixelFourierFixture(request.operation);
      saved.set(request.id,output);
    }
    socket.end(JSON.stringify(reply('completed',saved.get(request.id)))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_ANALYSIS_PYTHON:'must-never-run.exe'});
  try {
    await client.init();
    const cases=[['dm_crop',{rect:[1,2,5,6]},'CROP_PIXEL'],['dm_native_filter',{operation:'smooth'},'FILTER_PIXEL'],
      ['dm_native_fft',{direction:'forward'},'FFT_PIXEL'],['dm_native_fft',{direction:'inverse'},'IFFT_PIXEL'],
      ...[['real','REAL_PIXEL'],['imaginary','IMAG_PIXEL'],['phase','VENDOR_ARG_PIXEL'],['power','VENDOR_NORM_PIXEL']].map(([component,op])=>['dm_native_complex',{component},op])];
    for(let index=0;index<cases.length;index++){
      const [name,args,op]=cases[index],request_id='pixel-mcp-'+index;
      const response=await client.tool(name,{image_id:77,...args,coordinate_mode:'pixel',request_id});assert.notEqual(response.result?.isError,true,JSON.stringify(response));const output=toolOutput(response);
      assert.equal(output.coordinate_mode,'pixel');assert.equal(output.native_receipt.original_operation,op);
      assert.deepEqual((await client.tool('dm_native_result',{request_id})).result.content,response.result.content);
    }
    const before=host.requests.length;
    assert.equal((await client.tool('dm_native_fft',{image_id:77,direction:'forward',coordinate_mode:'guess',request_id:'badmode'})).error.code,-32602);
    assert.equal(host.requests.length,before);
  }finally{await client.close();await host.close();}
});

test("existing native MCP tools carry uint32 statistics/crop/preview/READ without changing either catalog", async () => {
  const source = imageMetadata(77, {unsigned: true}), rect = [1, 1, 4, 3];
  const summary = {...summaryFixture(), image: source, minimum: 0, maximum: 4294967295, sum: 4294967295, mean: 4294967295 / source.pixels};
  const mean = {...summary, operator: "GMSImageProcessing::GetMean"}; delete mean.operators;
  const crop = {backend: "digitalmicrograph-native", source_image_id: 77, image_id: 99, source,
    image: imageMetadata(99, {unsigned: true, shape: [2, 3]}), requested_rect: rect, effective_rect: rect,
    output_bytes: 24, operator: "GMS::Image::GetSubSliceAsImage", computation: "DM native independent pixel copy",
    visible_dm_document: false, source_write_requested: false, snapshot_atomic: false};
  const preview = {...operationFixture("PREVIEW", [77, 2, 2]), source, sampled_minimum: 0, sampled_maximum: 4294967295};
  const results = {MEAN: mean, SUMMARY: summary, CROP: crop, PREVIEW: preview, READ: readFixture([77, ...rect], {source})}, saved = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") saved.set(request.id, results[request.operation]);
    socket.end(JSON.stringify(reply("completed", saved.get(request.id))) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init(); assert.equal((await client.rpc("tools/list")).result.tools.length, nativeCatalog.length);
    const calls = [["dm_native_mean", {}], ["dm_native_summary", {}], ["dm_crop", {rect}],
      ["dm_native_preview", {max_width: 2, max_height: 2}], ["dm_native_read", {rect}]];
    for (let index = 0; index < calls.length; ++index) {
      const [name, args] = calls[index], request_id = "uint32-mcp-" + index;
      const response = await client.tool(name, {image_id: 77, ...args, request_id}), output = toolOutput(response);
      assert.equal(Object.hasOwn(output, "display_context"), false, "non-SHOW outputs do not claim delivery");
      assert.equal(output.native_receipt.request_id, request_id);
      assert.equal((output.source || output.image).dtype, "uint32");
      const queried = await client.tool("dm_native_result", {request_id}); assert.deepEqual(queried.result.content, response.result.content);
      assert.equal(response.result.content.length, name === "dm_native_preview" ? 2 : 1);
      if (name === "dm_native_read") {
        const bytes = Buffer.from(output.values_base64, "base64");
        assert.deepEqual(Array.from({length: 6}, (_, i) => bytes.readUInt32LE(i * 4)), [0, 16777215, 16777217, 2147483648, 4294967295, 1]);
      }
    }
  } finally {await client.close(); await host.close();}
});

test("typed uint32 binary and described SHOW preserve actual output metadata through MCP QUERY", async () => {
  const binary = uint32BinaryFixture(), show = {backend: "digitalmicrograph-native", image_id: 99,
    image: imageMetadata(99, {unsigned: true}), delivery: "visible_dm_document", document_visible: true,
    operator: "ImageGetOrCreateImageDocument + ImageDocumentShow", ownership: "synthetic only; no visible document exists",
    source_write_requested: false, snapshot_atomic: false, file_saved: false, model_visual_verification: false};
  const saved = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") saved.set(request.id, request.operation === "BINARY" ? binary : show);
    socket.end(JSON.stringify(reply("completed", saved.get(request.id))) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init(); assert.equal((await client.rpc("tools/list")).result.tools.length, nativeCatalog.length);
    const result = toolOutput(await client.tool("dm_native_binary", {left_image_id: 77, right_image_id: 78, operation: "add", request_id: "candidate-binary"}));
    assert.equal(result.image.dtype, "float32"); assert.deepEqual(result.sources.map(source => source.dtype), ["uint32", "uint32"]);
    assert.match(result.dtype_semantics.precision, /not lossless/);
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: "candidate-binary"})), result);
    const shown = await client.tool("dm_native_show", {image_id: 99, request_id: "candidate-show"});
    assert.equal(shown.result.content.length, 1, "a DM document receipt never creates an MCP image block");
    const text = toolOutput(shown); assert.equal(text.image.dtype, "uint32"); assert.equal(text.file_saved, false);
    assert.equal(text.display_context.active_workspace_visibility, "unknown");
    assert.equal(text.display_context.workspace_activation_requested, false);
    assert.equal(text.model_visual_verification, false);
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: "candidate-show"})), text);
  } finally {await client.close(); await host.close();}
});

test("MCP maps uint32 unary/filter/forward FFT enums to their actual native result dtype without changing the catalog", async () => {
  const results = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") results.set(request.id, uint32OperationFixture(request.operation, request.args.map(Number)));
    socket.end(JSON.stringify(reply("completed", results.get(request.id))) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init(); assert.equal((await client.rpc("tools/list")).result.tools.length, nativeCatalog.length);
    const calls = [["dm_native_unary", {operation: "negate"}, "float32"], ["dm_native_unary", {operation: "abs"}, "float32"],
      ["dm_native_unary", {operation: "square"}, "float32"], ["dm_native_filter", {operation: "smooth"}, "uint32"],
      ["dm_native_filter", {operation: "sobel"}, "float32"], ["dm_native_filter", {operation: "laplace"}, "float32"],
      ["dm_native_filter", {operation: "sharpen"}, "uint32"], ["dm_native_fft", {direction: "forward"}, "complex64"]];
    for (let i = 0; i < calls.length; ++i) {
      const [tool, args, expected] = calls[i], request_id = "native-u32-matrix-" + i;
      const actual = toolOutput(await client.tool(tool, {image_id: 77, ...args, request_id}));
      assert.equal(actual.image.dtype, expected); assert.equal(actual.dtype_semantics.output_dtype, expected);
      assert.deepEqual(actual.dtype_semantics.input_dtypes, ["uint32"]);
      assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id})), actual);
    }
  } finally {await client.close(); await host.close();}
});

test("unqualified prepared operation receipts never become successful MCP science or preview output", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    const result = uint32BinaryFixture();
    if (request.id === "candidate-flag") result.candidate_probe = true;
    else if (request.id === "candidate-qualification") result.qualification = "NOT_QUALIFIED";
    else result.computation = "DM native unqualified probe";
    socket.end(JSON.stringify(reply("completed", result, {original_operation: "BINARY", normalized_args: [77, 78, 1], result_type: "native_image_operation", result_version: 1})) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const request_id of ["candidate-flag", "candidate-qualification", "candidate-computation"]) {
      const response = await client.tool("dm_native_binary", {left_image_id: 77, right_image_id: 78, operation: "add", request_id});
      const error = toolOutput(response, true); assert.equal(error.code, "NATIVE_PROTOCOL"); assert.equal(error.state, "unknown");
      assert.equal(response.result.content.length, 1); assert.equal(Object.hasOwn(error, "image"), false);
      assert.equal(toolOutput(await client.tool("dm_native_result", {request_id}), true).code, "NATIVE_PROTOCOL");
    }
    assert.equal(host.requests.filter(request => request.operation === "BINARY").length, 3);
  } finally {await client.close(); await host.close();}
});

async function nativeHost(handler) {
  const session = randomUUID().replaceAll("-", ""), bridge = new NativeBridge({session});
  const requests = [], sockets = new Set(), records = new Map();
  const server = net.createServer(socket => {
    sockets.add(socket); socket.on("error", () => {}); socket.on("close", () => sockets.delete(socket));
    let input = "";
    socket.on("data", chunk => {
      input += chunk.toString("ascii"); const newline = input.indexOf("\n"); if (newline < 0) return;
      const [protocol, requestSession, id, operation, ...args] = input.slice(0, newline).split(" ");
      assert.equal(protocol, "NB2"); assert.equal(requestSession, session);
      const request = {id, operation, args}; requests.push(request);
      if (operation !== "QUERY" && !records.has(id)) records.set(id, request);
      const original = records.get(id) || {operation: "STATUS", args: []};
      const reply = (state, result, extra = {}) => ({protocol: "NB2", session, id, state, host_pid: 301, worker_tid: 302,
        exec_tid: state === "completed" || state === "running" ? 303 : 0, timings_us: {queue: 4, execute: 5},
        ...(state === "unknown" ? {original_operation: null, normalized_args: null, result_type: null, result_version: null} :
          {original_operation: original.operation, normalized_args: original.args.map(Number), result_type: resultTypes[original.operation],
            result_version: ["native_fourier_operation","native_gui_rois"].includes(resultTypes[original.operation]) ? 2 : 1}),
        ...(state === "completed" ? {result} : {}), ...extra});
      handler({socket, request, requests, reply}); input = "";
    });
  });
  await new Promise((resolve, reject) => {server.once("error", reject); server.listen(bridge.pipePath, resolve);});
  return {session, requests, async close() {for (const socket of sockets) socket.destroy(); await new Promise(resolve => server.close(resolve));}};
}

const profileToolArgs = (request_id = 'saved-profile') => ({image_id:77,document_id:31,display_id:9,roi_id:4,
  expected_line:[2,1,5,1],width:1,request_id});

test('FRAME requires caller-saved identity and exact zero-based selection before connecting to a host',async()=>{
  const host=await nativeHost(()=>assert.fail('Invalid FRAME must not connect to the native pipe'));
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});
  try {
    await client.init();const tool=(await client.rpc('tools/list')).result.tools.find(t=>t.name==='dm_native_frame');
    assert.deepEqual(tool.inputSchema.required,['image_id','frame_index','request_id']);
    const valid={image_id:31,frame_index:0,request_id:'pre-saved-frame'};
    for(const args of [{image_id:31,frame_index:0},{...valid,request_id:''},{...valid,image_id:0},
      {...valid,image_id:'front'},{...valid,frame_index:-1},{...valid,frame_index:1.5},
      {image_id:31,request_id:'missing-index'},{...valid,frame_index:2**32},{...valid,script:'arbitrary'}])
      assert.equal((await client.tool('dm_native_frame',args)).error.code,-32602);
    assert.equal(host.requests.length,0);
  } finally {await client.close();await host.close();}
});

test('FRAME accepted then cancelled is recovered by a fresh MCP client without creating a second object',async()=>{
  const id='pre-saved-frame-cancellation',fixture=frameHandoffFixture({index:1,unknownUnits:true});
  const result={...fixture.result,retention:{token:8,creation_request_id:id,state_at_creation:'plugin_retained',
    identity_scope:'bridge token in this native session, not a host image ID'}};
  let accepted,completed=false,created=0;const observed=new Promise(resolve=>accepted=resolve);
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.operation==='FRAME') {
      if(JSON.stringify(request.args.map(Number))!=='[31,1]') {
        socket.end(JSON.stringify(reply('failed',undefined,{code:'id_conflict',error:'same ID changed source or frame'}))+'\n');return;
      }
      assert.equal(created,0);created++;socket.end(JSON.stringify(reply('queued'))+'\n');accepted();
    } else socket.end(JSON.stringify(completed?reply('completed',result):reply('running'))+'\n');
  });
  const env={DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_MCP_TIMEOUT_MS:'1000',DM_ANALYSIS_PYTHON:'must-not-start.exe'};
  const first=mcpClient(env);let second;
  try {
    await first.init();first.send({id:902,method:'tools/call',params:{name:'dm_native_frame',arguments:{image_id:31,frame_index:1,request_id:id}}});
    await observed;first.send({method:'notifications/cancelled',params:{requestId:902}});await first.rpc('ping');
    assert.equal(first.messages.some(message=>message.id===902),false);await first.close();completed=true;
    second=mcpClient(env);await second.init();const recovered=toolOutput(await second.tool('dm_native_result',{request_id:id}));
    assert.equal(recovered.image_id,result.image_id);assert.equal(recovered.frame_index,1);
    assert.equal(recovered.source.dtype,'uint16');assert.equal(recovered.image.dtype,'float32');
    assert.equal(recovered.image.calibration_complete,false);
    assert.equal(toolOutput(await second.tool('dm_native_frame',{image_id:31,frame_index:2,request_id:id}),true).native_receipt.code,'id_conflict');
    assert.deepEqual(toolOutput(await second.tool('dm_native_result',{request_id:id})),recovered);
    assert.equal(created,1);
  } finally {await first.close();if(second)await second.close();await host.close();}
});

test('HISTOGRAM MCP publishes bin-index semantics and rejects missing saved IDs before dispatch',async()=>{
  const host=await nativeHost(()=>assert.fail('invalid histogram reached host'));
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});
  try {
    await client.init();const tool=(await client.rpc('tools/list')).result.tools.find(t=>t.name==='dm_native_histogram');
    assert.deepEqual(tool.inputSchema.required,['image_id','bins','min','max','request_id']);
    assert.match(tool.description,/bin_index/);assert.match(tool.description,/uint32.*binary64/);
    assert.doesNotMatch(tool.description,/则原生一维轴按/);
    const args={image_id:77,bins:8,min:-4,max:4,request_id:'histogram-saved'};
    const missing={...args};delete missing.request_id;
    for(const invalid of [missing,{...args,request_id:''},{...args,bins:1},{...args,bins:4097},{...args,bins:2.5},
      {...args,image_id:'front'},{...args,script:'noop'}]) assert.equal((await client.tool('dm_native_histogram',invalid)).error.code,-32602);
    assert.equal(host.requests.length,0);
  } finally {await client.close();await host.close();}
});

test('accepted sparse HISTOGRAM cancellation recovers original uint32/f64 receipt in a fresh MCP client',async()=>{
  const savedId='saved-before-histogram-cancel',result=histogramFixture(histogramArgs,savedId);
  let accepted,completed=false,creations=0;const observed=new Promise(resolve=>accepted=resolve);
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.operation==='HISTOGRAM') {
      if(JSON.stringify(request.args.map(Number))!==JSON.stringify(histogramArgs)) {
        socket.end(JSON.stringify(reply('failed',undefined,{code:'id_conflict',error:'saved ID has different original parameters'}))+'\n');return;
      }
      assert.equal(creations,0);creations++;socket.end(JSON.stringify(reply('queued'))+'\n');accepted();
    } else socket.end(JSON.stringify(completed?reply('completed',result):reply('running'))+'\n');
  });
  const env={DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_MCP_TIMEOUT_MS:'1000',DM_ANALYSIS_PYTHON:'must-not-start.exe'};
  const first=mcpClient(env);let recovered;
  try {
    await first.init();first.send({id:901,method:'tools/call',params:{name:'dm_native_histogram',arguments:{image_id:77,bins:8,min:-4,max:4,request_id:savedId}}});
    await observed;first.send({method:'notifications/cancelled',params:{requestId:901}});await first.rpc('ping');
    assert.equal(first.messages.some(message=>message.id===901),false);await first.close();completed=true;
    recovered=mcpClient(env);await recovered.init();
    const original=toolOutput(await recovered.tool('dm_native_result',{request_id:savedId}));
    assert.equal(original.dtype,'uint32');assert.equal(original.raw_bytes,64);assert.equal(original.output_bytes,32);
    assert.equal(original.bins>original.source_pixels,true);assert.equal(original.axis_mode,'bin_index');
    const conflict=toolOutput(await recovered.tool('dm_native_histogram',{image_id:77,bins:16,min:-4,max:4,request_id:savedId}),true);
    assert.equal(conflict.native_receipt.code,'id_conflict');
    assert.deepEqual(toolOutput(await recovered.tool('dm_native_result',{request_id:savedId})),original);
    assert.equal(creations,1);assert.equal(host.requests.filter(r=>r.operation==='HISTOGRAM'&&JSON.stringify(r.args.map(Number))===JSON.stringify(histogramArgs)).length,1);
  } finally {await first.close();if(recovered)await recovered.close();await host.close();}
});

test('malformed histogram creation and original QUERY never turn native counts into a false success',async()=>{
  const records=new Map();
  const host=await nativeHost(({socket,request,reply})=>{
    if(!records.has(request.id)) {
      const result=histogramFixture(histogramArgs,request.id);
      if(request.id==='zero-image') result.image_id=result.image.id=0;
      if(request.id==='wrong-wire') result.counts_encoding='uint32 little-endian';
      if(request.id==='fake-axis') result.axis_mode='source_intensity_units';
      if(request.id==='source-size') result.source_pixels++;
      if(request.id==='foreign-creation') result.retention.creation_request_id='another-id';
      records.set(request.id,result);
    }
    socket.end(JSON.stringify(reply('completed',records.get(request.id)))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_ANALYSIS_PYTHON:'must-not-start.exe'});
  try {
    await client.init();for(const request_id of ['zero-image','wrong-wire','fake-axis','source-size','foreign-creation']) {
      assert.equal(toolOutput(await client.tool('dm_native_histogram',{image_id:77,bins:8,min:-4,max:4,request_id}),true).code,'NATIVE_PROTOCOL');
      assert.equal(toolOutput(await client.tool('dm_native_result',{request_id}),true).code,'NATIVE_PROTOCOL');
    }
  } finally {await client.close();await host.close();}
});

test('HISTOGRAM creation, original QUERY and SHOW share exact native axis evidence while old bin-index QUERY remains usable',async()=>{
  const records=new Map();
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.id==='legacy-index-query') {
      socket.end(JSON.stringify(reply('completed',histogramFixture(histogramArgs,request.id),{
        original_operation:'HISTOGRAM',normalized_args:histogramArgs,result_type:'native_histogram',result_version:1}))+'\n');return;
    }
    if(!records.has(request.id)) {
      let result;
      if(request.id.startsWith('show-')) {
        result=histogramShowFixture(histogramIntensityFixture('axis-good'));
        Object.assign(result,{display_style:'default',display_style_reason:'style_not_qualified',
          display_style_scope:'host line-plot presentation only; no scientific claim; reversible in the DM UI'});
        if(request.id==='show-no-context')delete result.histogram_axis_context;
        if(request.id==='show-fake-axis')result.histogram_axis_context.axis_roundtrip_bound=1;
        if(request.id==='show-fake-style')result.display_style='histogram',result.display_style_reason='style_not_qualified';
      } else if(request.id==='axis-index')result=histogramIndexAxisFixture(histogramArgs,request.id);
      else {
        result=histogramIntensityFixture(request.id);
        if(request.id==='axis-nonidentity')result.source_intensity_calibration.scale=-2;
        if(request.id==='axis-offset') {
          result.image.calibration[0].calibrated_value_at_pixel_zero+=2**-22;
          result.axis_zero_observed=result.image.calibration[0].calibrated_value_at_pixel_zero;result.axis_roundtrip_error=2**-22;
        }
        if(request.id==='axis-large-tolerance')result.axis_tolerance='binary32 1000 ulp';
      }
      records.set(request.id,result);
    }
    socket.end(JSON.stringify(reply('completed',records.get(request.id)))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_ANALYSIS_PYTHON:'must-not-start.exe'});
  try {
    await client.init();const args={image_id:77,bins:8,min:-4,max:4};
    for(const request_id of ['axis-good','axis-index']) {
      const result=toolOutput(await client.tool('dm_native_histogram',{...args,request_id}));
      assert.deepEqual(toolOutput(await client.tool('dm_native_result',{request_id})),result);
      assert.equal(result.dtype,'uint32');assert.equal(result.raw_bytes,64);assert.equal(result.output_bytes,32);
    }
    const historical=toolOutput(await client.tool('dm_native_result',{request_id:'legacy-index-query'}));
    assert.equal(historical.axis_mode,'bin_index');assert.equal(Object.hasOwn(historical,'axis_tolerance'),false);
    const shown=toolOutput(await client.tool('dm_native_show',{image_id:99,request_id:'show-good'}));
    assert.equal(shown.display_style,'default');assert.equal(shown.display_style_reason,'style_not_qualified');
    assert.deepEqual(toolOutput(await client.tool('dm_native_result',{request_id:'show-good'})),shown);
    for(const request_id of ['axis-nonidentity','axis-offset','axis-large-tolerance']) {
      assert.equal(toolOutput(await client.tool('dm_native_histogram',{...args,request_id}),true).code,'NATIVE_PROTOCOL');
      assert.equal(toolOutput(await client.tool('dm_native_result',{request_id}),true).code,'NATIVE_PROTOCOL');
    }
    for(const request_id of ['show-no-context','show-fake-axis','show-fake-style']) {
      assert.equal(toolOutput(await client.tool('dm_native_show',{image_id:99,request_id}),true).code,'NATIVE_PROTOCOL');
      assert.equal(toolOutput(await client.tool('dm_native_result',{request_id}),true).code,'NATIVE_PROTOCOL');
    }
  } finally {await client.close();await host.close();}
});

test('PROFILE validates saved ID, full explicit GUI identity and finite bounded line before dispatch',async()=>{
  const host=await nativeHost(()=>assert.fail('invalid parameters reached host'));
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});
  try {
    await client.init();const catalog=(await client.rpc('tools/list')).result.tools,tool=catalog.find(t=>t.name==='dm_native_profile');
    assert.deepEqual(tool.inputSchema.required,['image_id','document_id','display_id','roi_id','expected_line','width','request_id']);
    const missing=profileToolArgs();delete missing.request_id;
    for(const args of [missing,{...profileToolArgs(),request_id:''},{...profileToolArgs(),document_id:0x80000000},
      {...profileToolArgs(),expected_line:[2,1,5,2]},{...profileToolArgs(),expected_line:[2,1,2,1]},
      {...profileToolArgs(),expected_line:[0,0,4096,0]},{...profileToolArgs(),width:2},{...profileToolArgs(),expected_line:[2.5,1,5,1]},
      {...profileToolArgs(),line:[2,1,5,1]}]) assert.equal((await client.tool('dm_native_profile',args)).error.code,-32602);
    assert.equal(host.requests.length,0);
  } finally {await client.close();await host.close();}
});

test('accepted PROFILE cancellation recovers same f64 image/snapshot in fresh MCP client and conflicting args never replay it',async()=>{
  const savedId='saved-before-profile-cancel',result=profileFixture(profileArgs,savedId);
  let accepted,completed=false,creations=0;const observed=new Promise(resolve=>accepted=resolve);
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.operation==='PROFILE') {
      if(JSON.stringify(request.args.map(Number))!==JSON.stringify(profileArgs)) {
        socket.end(JSON.stringify(reply('failed',undefined,{code:'id_conflict',error:'saved ID has different original parameters'}))+'\n');return;
      }
      assert.equal(creations,0);socket.end(JSON.stringify(reply('queued'))+'\n');accepted();
    } else socket.end(JSON.stringify(completed?reply('completed',result):reply('running'))+'\n');
  });
  const env={DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_MCP_TIMEOUT_MS:'1000',DM_ANALYSIS_PYTHON:'must-not-start.exe'};
  const first=mcpClient(env);let recovered;
  try {
    await first.init();first.send({id:900,method:'tools/call',params:{name:'dm_native_profile',arguments:profileToolArgs(savedId)}});
    await observed;first.send({method:'notifications/cancelled',params:{requestId:900}});await first.rpc('ping');
    assert.equal(first.messages.some(message=>message.id===900),false);await first.close();
    completed=true;creations++;
    recovered=mcpClient(env);await recovered.init();
    const a=toolOutput(await recovered.tool('dm_native_result',{request_id:savedId}));
    assert.equal(a.image_id,99);assert.equal(a.dtype,'float64');assert.deepEqual(a.shape,[4]);
    const conflict=toolOutput(await recovered.tool('dm_native_profile',{...profileToolArgs(savedId),expected_line:[2,1,6,1]}),true);
    assert.equal(conflict.native_receipt.code,'id_conflict');
    assert.deepEqual(toolOutput(await recovered.tool('dm_native_result',{request_id:savedId})),a);
    assert.equal(creations,1);assert.equal(host.requests.filter(r=>r.operation==='PROFILE'&&JSON.stringify(r.args.map(Number))===JSON.stringify(profileArgs)).length,1);
  } finally {await first.close();if(recovered)await recovered.close();await host.close();}
});

test('PROFILE fresh and recovered malformed data, native geometry conflict and unqualified capability never claim success',async()=>{
  const records=new Map();
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.id==='geometry-changed'||request.id==='not-qualified') {
      socket.end(JSON.stringify(reply('failed',undefined,{code:'native_error',error:request.id==='geometry-changed'?'native_profile_gui_line_conflict':'native_line_profile_not_qualified'}))+'\n');return;
    }
    if(!records.has(request.id)) {
      const result=profileFixture(profileArgs,request.id);
      if(request.id==='rank') result.image.ndim=2;
      if(request.id==='dtype') result.dtype='float32';
      if(request.id==='identity') result.source_gui_line.roi_id++;
      if(request.id==='zero-image') result.image_id=result.image.id=0;
      if(request.id==='cal') result.image.calibration[0].scale*=-1;
      if(request.id==='bytes') result.values_base64='AAAA';
      if(request.id==='candidate') result.candidate_probe=true;
      records.set(request.id,result);
    }
    socket.end(JSON.stringify(reply('completed',records.get(request.id)))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_ANALYSIS_PYTHON:'must-not-start.exe'});
  try {
    await client.init();
    for(const request_id of ['rank','dtype','identity','zero-image','cal','bytes','candidate']) {
      assert.equal(toolOutput(await client.tool('dm_native_profile',profileToolArgs(request_id)),true).code,'NATIVE_PROTOCOL');
      assert.equal(toolOutput(await client.tool('dm_native_result',{request_id}),true).code,'NATIVE_PROTOCOL');
    }
    for(const request_id of ['geometry-changed','not-qualified']) {
      const output=toolOutput(await client.tool('dm_native_profile',profileToolArgs(request_id)),true);
      assert.equal(output.native_receipt.state,'failed');assert.equal(Object.hasOwn(output,'image'),false);
    }
    assert.equal(host.requests.filter(r=>r.operation==='PROFILE').length,9);
  } finally {await client.close();await host.close();}
});

test('ROIS preserves exact historical v1 QUERY but fresh calls require v2 and never infer a selected line',async()=>{
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.id==='historical-rois') socket.end(JSON.stringify(reply('completed',guiRoisFixture(77,1),{
      original_operation:'ROIS',normalized_args:[77],result_type:'native_gui_rois',result_version:1}))+'\n');
    else socket.end(JSON.stringify(reply('completed',guiRoisFixture(77,1),{result_version:1}))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});
  try {
    await client.init();
    const old=toolOutput(await client.tool('dm_native_result',{request_id:'historical-rois'}));
    assert.equal(old.native_receipt.result_version,1);assert.equal(Object.hasOwn(old.displays[0].rois[0],'line'),false);
    assert.equal(toolOutput(await client.tool('dm_native_rois',{image_id:77,request_id:'new-v1-invalid'}),true).code,'NATIVE_PROTOCOL');
    assert.equal(host.requests.filter(r=>r.operation==='ROIS').length,1);
    assert.equal(host.requests.filter(r=>r.operation==='PROFILE').length,0);
  } finally {await client.close();await host.close();}
});

test('readonly GUI ROI MCP requires explicit image and returns an immutable display/ROI snapshot', async () => {
  const records = new Map(); let current = guiRoisFixture();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === 'ROIS') {
      assert.deepEqual(request.args, ['77']);
      if (!records.has(request.id)) records.set(request.id, structuredClone(current));
    }
    socket.end(JSON.stringify(reply('completed', records.get(request.id))) + '\n');
  });
  const client = mcpClient({DM_MCP_BACKEND: 'native', DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: 'must-never-start.exe'});
  try {
    const initialized = await client.init();
    assert.match(initialized.instructions, /只读枚举明确图像/);
    assert.match(initialized.instructions, /不自动挑选或裁剪/);
    assert.match(initialized.instructions, /非原子执行时快照/);
    assert.match(initialized.instructions, /旧 ID 的 QUERY 不会刷新当前选区/);
    const catalog = (await client.rpc('tools/list')).result.tools;
    const tool = catalog.find(entry => entry.name === 'dm_native_rois');
    assert.deepEqual(tool.inputSchema.required, ['image_id']);
    assert.match(tool.description, /不选择前台\/最新窗口/);
    for (const args of [{}, {image_id: 'front'}, {image_id: '77'}, {image_id: true}, {image_id: -1},
      {image_id: 1.5}, {image_id: 4294967296}, {image_id: 77, display_id: 9}, {image_id: 77, roi_id: 4},
      {image_id: 77, request_id: 'bad id'}]) assert.equal((await client.tool('dm_native_rois', args)).error.code, -32602);
    assert.equal(host.requests.length, 0, 'invalid GUI identity arguments never enter the plugin');
    const initial = toolOutput(await client.tool('dm_native_rois', {image_id: 77, request_id: 'gui-snapshot'}));
    assert.deepEqual(initial.displays[0].display_identity, {document_id: 31, display_id: 9});
    assert.deepEqual(initial.displays[0].rois[0].rect, [2, 1, 10, 6]);
    assert.equal(initial.native_receipt.original_operation, 'ROIS');
    assert.equal(initial.native_receipt.result_type, 'native_gui_rois');
    assert.equal(initial.native_receipt.result_version, 2);
    current.displays[0].roi_count = 0; current.displays[0].rois = [];
    assert.deepEqual(toolOutput(await client.tool('dm_native_result', {request_id: 'gui-snapshot'})), initial,
      'changing GUI state does not rewrite an accepted snapshot');
    const fresh = toolOutput(await client.tool('dm_native_rois', {image_id: 77}));
    assert.match(fresh.native_receipt.request_id, /^[0-9a-f-]{36}$/);
    assert.deepEqual(fresh.displays[0].rois, []);
    assert.equal(fresh.displays[0].roi_count, 0);
    assert.deepEqual(host.requests.map(request => request.operation), ['ROIS', 'QUERY', 'ROIS']);
  } finally {await client.close(); await host.close();}
});

test('GUI ROI unsupported/error and corrupt direct or recovered records never impersonate empty or whole-image success', async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.id === 'not-qualified') return socket.end(JSON.stringify(reply('failed', undefined,
      {code: 'native_error', error: 'native_capability_unavailable:native_gui_rois'})) + '\n');
    if (request.id === 'getter-error') return socket.end(JSON.stringify(reply('failed', undefined,
      {code: 'native_error', error: 'native_roi_getter_failed'})) + '\n');
    const result = guiRoisFixture();
    if (request.id === 'wrong-image') result.image_id = 78;
    if (request.id === 'wrong-display') result.displays[0].display_identity.document_id = 99;
    if (request.id === 'rounded') result.displays[0].rois[0].raw_rectangle.left = 2.5;
    if (request.id === 'fake-empty') result.displays[0].issue = 'native_getter_failed';
    if (request.id === 'candidate') result.qualification = 'NOT_QUALIFIED';
    socket.end(JSON.stringify(reply('completed', result)) + '\n');
  });
  const client = mcpClient({DM_MCP_BACKEND: 'native', DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: 'must-never-start.exe'});
  try {
    await client.init();
    for (const request_id of ['not-qualified', 'getter-error']) {
      const output = toolOutput(await client.tool('dm_native_rois', {image_id: 77, request_id}), true);
      assert.equal(output.native_receipt.state, 'failed');
      assert.equal(Object.hasOwn(output, 'displays'), false);
    }
    for (const request_id of ['wrong-image', 'wrong-display', 'rounded', 'fake-empty', 'candidate']) {
      const output = toolOutput(await client.tool('dm_native_rois', {image_id: 77, request_id}), true);
      assert.equal(output.code, 'NATIVE_PROTOCOL'); assert.equal(Object.hasOwn(output, 'displays'), false);
      assert.equal(toolOutput(await client.tool('dm_native_result', {request_id}), true).code, 'NATIVE_PROTOCOL');
    }
    assert.equal(host.requests.filter(request => request.operation === 'ROIS').length, 7, 'no fallback/replay follows failed native reads');
  } finally {await client.close(); await host.close();}
});

test('release requires pre-saved ID and token before pipe dispatch; readonly availability preserves identity', async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    socket.end(JSON.stringify(reply('completed', {backend:'digitalmicrograph-native',image_id:88,retention_token:3,
      creation_request_id:'created',plugin_retained:request.operation==='RESULT_INFO',available_for_native_processing:request.operation==='RESULT_INFO',
      released:request.operation==='RELEASE',released_now:request.operation==='RELEASE',result_bytes:24,
      retained_result_count:request.operation==='RESULT_INFO'?1:0,retained_result_bytes:request.operation==='RESULT_INFO'?24:0,
      document_closed:false,source_write_requested:false,native_object_existence:'not_probed',
      scope:'plugin reference only; shown document may still hold the image; old creation receipt is unchanged'}))+'\n');
  });
  const client=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});
  try {
    await client.init();
    for(const args of [{image_id:88,retention_token:3},{image_id:88,retention_token:0,request_id:'saved'},
      {image_id:0,retention_token:3,request_id:'saved'},{image_id:88,retention_token:3,request_id:'invalid id'},
      {image_id:88,request_id:'saved'}]) assert.equal((await client.tool('dm_native_release',args)).error.code,-32602);
    assert.equal(host.requests.length,0);
    const info=toolOutput(await client.tool('dm_native_result_info',{image_id:88,retention_token:3}));
    assert.equal(info.plugin_retained,true);assert.equal(info.native_receipt.original_operation,'RESULT_INFO');
    const released=toolOutput(await client.tool('dm_native_release',{image_id:88,retention_token:3,request_id:'release-saved'}));
    assert.equal(released.released,true);assert.equal(released.native_receipt.request_id,'release-saved');
    assert.deepEqual(host.requests.map(r=>[r.operation,r.args]),[['RESULT_INFO',['88','3']],['RELEASE',['88','3']]]);
  } finally {await client.close();await host.close();}
});

test('cancelled release is recovered by a fresh MCP client using original identity; corrupt late result is rejected', async () => {
  let releases=0;
  const result={backend:'digitalmicrograph-native',image_id:88,retention_token:3,creation_request_id:'created',
    plugin_retained:false,available_for_native_processing:false,released:true,released_now:true,result_bytes:24,
    retained_result_count:0,retained_result_bytes:0,document_closed:false,source_write_requested:false,native_object_existence:'not_probed',
    scope:'plugin reference only; shown document may still hold the image; old creation receipt is unchanged'};
  const host=await nativeHost(({socket,request,reply})=>{
    if(request.operation==='RELEASE') {++releases;socket.end(JSON.stringify(reply('running',null))+'\n');}
    else socket.end(JSON.stringify(reply('completed',request.id==='release-wrong-token'?{...result,retention_token:4}:result))+'\n');
  });
  const first=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session,DM_MCP_TIMEOUT_MS:'2000'});
  let second;
  try {
    await first.init();
    first.send({id:701,method:'tools/call',params:{name:'dm_native_release',arguments:{image_id:88,retention_token:3,request_id:'release-cancel'}}});
    for(let i=0;i<100&&!releases;++i)await sleep(5);
    assert.equal(releases,1);first.send({method:'notifications/cancelled',params:{requestId:701,reason:'cancel waiting'}});
    await first.close();second=mcpClient({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:host.session});await second.init();
    const recovered=toolOutput(await second.tool('dm_native_result',{request_id:'release-cancel'}));
    assert.equal(recovered.native_receipt.original_operation,'RELEASE');assert.equal(recovered.retention_token,3);assert.equal(releases,1);
    // A different stored result cannot cross the ID/token boundary, including QUERY.
    toolOutput(await second.tool('dm_native_release',{image_id:88,retention_token:3,request_id:'release-wrong-token'}),true);
    toolOutput(await second.tool('dm_native_result',{request_id:'release-wrong-token'}),true);
    assert.equal(releases,2);
  } finally {await first.close();if(second)await second.close();await host.close();}
});

test("default backend retains v0.6 and all original 21 tool schemas", async () => {
  const client = mcpClient({}, true);
  try {
    const init = await client.init(); assert.equal(init.serverInfo.version, "0.6.0");
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.equal(catalog.length, 21);
    assert.deepEqual(catalog.map(entry => entry.name), ["dm_status", "dm_open", "dm_datasets", "dm_metadata", "dm_stats", "dm_profile", "dm_fft", "dm_2d_capture", "dm_2d_preview", "dm_2d_analyze", "dm_2d_result", "dm_export", "dm_crop", "dm_spectrum_info", "dm_spectrum", "dm_spectrum_integrate", "dm_spectrum_export", "dm_4dstem_open", "dm_4dstem_read", "dm_4dstem_virtual", "dm_run_script"]);
    assert.deepEqual(catalog[0].inputSchema.properties, {});
    assert.equal((await client.tool("dm_native_mean", {image_id: 1})).error.code, -32602);
    assert.equal((await client.tool("dm_native_summary", {image_id: 1})).error.code, -32602);
    for (const name of nativeCatalog.slice(7)) assert.equal((await client.tool(name, {image_id: 1, request_id: "saved"})).error.code, -32602);
  } finally {await client.close();}
});

test("unknown backend and malformed native session refuse startup without fallback", async () => {
  for (const extraEnv of [{DM_MCP_BACKEND: ""}, {DM_MCP_BACKEND: "tcp-typo"}, {DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: "bad"}]) {
    const child = spawn(process.execPath, [serverPath], {env: {...process.env, ...extraEnv}, stdio: ["pipe", "pipe", "pipe"]});
    let stdout = "", stderr = ""; child.stdout.on("data", chunk => {stdout += chunk;}); child.stderr.on("data", chunk => {stderr += chunk;});
    const [code] = await once(child, "exit");
    assert.notEqual(code, 0); assert.equal(stdout, ""); assert.match(stderr, /DM_MCP_BACKEND|DM_NATIVE_SESSION/);
  }
});

test("native MCP exposes only implemented tools, strict IDs and real host fields", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    const result = request.operation === "STATUS" ? {backend: "mock-native", build: "synthetic-only"}
      : request.operation === "DATASETS" ? {backend: "mock-native", datasets: [{image_id: 77, name: "合成图"}]}
      : {backend: "mock-native", image_id: 77, mean: -3.25};
    socket.write(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_BRIDGE_HOST: "invalid-unused", DM_BRIDGE_PORT: "invalid-unused", DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    const init = await client.init(); assert.match(init.instructions, /空闲/); assert.match(init.instructions, /不回退/);
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.deepEqual(catalog.map(entry => entry.name), nativeCatalog);
    for (const name of ["dm_stats", "dm_run_script", "dm_2d_preview", "dm_open", "no_such_tool"]) {
      const response = await client.tool(name); assert.equal(response.error.code, -32602); assert.match(response.error.message, /不支持工具/);
    }
    for (const image_id of ["front", "77", -1, 1.5, 4294967296]) assert.equal((await client.tool("dm_native_mean", {image_id})).error.code, -32602);
    for (const request_id of ["", "x\n", "x y", "x".repeat(65)]) assert.equal((await client.tool("dm_status", {request_id})).error.code, -32602);
    assert.equal((await client.tool("dm_native_mean", {})).error.code, -32602);
    assert.equal((await client.tool("dm_native_result", {})).error.code, -32602);
    assert.equal(host.requests.length, 0, "unimplemented tools/invalid IDs never reach any bridge");
    assert.equal(toolOutput(await client.tool("dm_status")).backend, "mock-native");
    assert.equal(toolOutput(await client.tool("dm_datasets", {request_id: "datasets-fixed"})).datasets[0].name, "合成图");
    const output = toolOutput(await client.tool("dm_native_mean", {image_id: 77, request_id: "mean-fixed"}));
    assert.equal(output.mean, -3.25); assert.equal(output.backend, "mock-native");
    assert.deepEqual(Object.keys(output).sort(), ["backend", "image_id", "mean", "native_receipt"]);
    assert.equal(output.native_receipt.session, host.session); assert.equal(output.native_receipt.request_id, "mean-fixed");
    assert.equal(output.native_receipt.host_pid, 301); assert.equal(output.native_receipt.exec_tid, 303);
    assert.deepEqual(host.requests.map(request => request.operation), ["STATUS", "DATASETS", "MEAN"]);
  } finally {await client.close(); await host.close();}
});

test("native MCP marks failed/unknown/queued/running and malformed mean as tool errors", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    let message;
    if (request.id === "failed") message = reply("failed", undefined, {code: "INVALID_IMAGE", error: "missing image"});
    else if (request.id === "unknown") message = reply("unknown");
    else if (["queued", "running"].includes(request.id)) message = reply(request.id);
    else message = reply("completed", {backend: "mock-native", mean: "not a number"});
    socket.end(JSON.stringify(message) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (const request_id of ["failed", "unknown", "queued", "running"]) {
      const output = toolOutput(await client.tool("dm_native_result", {request_id}), true);
      assert.equal(output.native_receipt.state, request_id);
    }
    const invalid = toolOutput(await client.tool("dm_native_mean", {image_id: 77, request_id: "bad-mean"}), true);
    assert.equal(invalid.code, "NATIVE_PROTOCOL"); assert.equal(invalid.request_id, "bad-mean");
  } finally {await client.close(); await host.close();}
});

test("native MCP timeout and cancellation are recovered by QUERY without re-execution", async () => {
  const done = new Set();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "MEAN") {
      done.add(request.id); // A silent reply does not prevent execution.
      return;
    }
    socket.write(JSON.stringify(reply(done.has(request.id) ? "completed" : "unknown", {backend: "mock-native", mean: 2.75})) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const timeout = toolOutput(await client.tool("dm_native_mean", {image_id: 3, request_id: "timeout-known"}), true);
    assert.equal(timeout.code, "NATIVE_TIMEOUT"); assert.equal(timeout.request_id, "timeout-known"); assert.equal(timeout.session, host.session);
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: timeout.request_id})).mean, 2.75);
    client.send({id: 900, method: "tools/call", params: {name: "dm_native_mean", arguments: {image_id: 3, request_id: "cancel-known"}}});
    await sleep(30);
    client.send({method: "notifications/cancelled", params: {requestId: 900}});
    await sleep(180);
    assert.equal(client.messages.some(message => message.id === 900), false, "standard MCP cancellation suppresses response: " + JSON.stringify(client.messages.find(message => message.id === 900)));
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: "cancel-known"})).mean, 2.75);
    assert.equal(host.requests.filter(request => request.operation === "MEAN").length, 2);
    assert.equal(host.requests.filter(request => request.id === "timeout-known" && request.operation === "MEAN").length, 1);
    assert.equal(host.requests.filter(request => request.id === "cancel-known" && request.operation === "MEAN").length, 1);
  } finally {await client.close(); await host.close();}
});

test("native dm_crop validates explicit half-open bounds and preserves the host's independent-image metadata", async () => {
  const rect = [1, 2, 4, 6];
  const source = {id: 77, shape: [7, 11], calibration: [{dm_dimension: 0, scale: -0.25, calibrated_value_at_pixel_zero: 1.25, unit: "nm"}]};
  const image = {id: 88, shape: [4, 3], calibration: [{dm_dimension: 0, scale: -0.25, calibrated_value_at_pixel_zero: 1, unit: "nm"}]};
  const result = {backend: "mock-native", source_image_id: 77, image_id: 88, requested_rect: rect, effective_rect: rect,
    source, image, operator: "GMS::Image::GetSubSliceAsImage", source_write_requested: false,
    ownership: "plugin-retained until normal native STOP/cleanup; no visible DM document"};
  const records = new Map(); let executions = 0;
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "CROP") {
      const previous = records.get(request.id);
      if (previous && JSON.stringify(previous.args) !== JSON.stringify(request.args)) {
        socket.end(JSON.stringify(reply("failed", undefined, {code: "id_conflict", error: "request ID already bound"})) + "\n"); return;
      }
      if (!previous) {records.set(request.id, {args: request.args, complete: false}); executions++;}
      socket.end(JSON.stringify(records.get(request.id).complete ? reply("completed", result) : reply("queued")) + "\n");
    } else {
      records.get(request.id).complete = true;
      socket.end(JSON.stringify(reply("completed", result)) + "\n");
    }
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const crop = (await client.rpc("tools/list")).result.tools.find(tool => tool.name === "dm_crop");
    assert.match(crop.description, /不创建可见 DM 文档/);
    assert.deepEqual(crop.inputSchema.required, ["image_id", "rect", "request_id"]);
    for (const request_id of [undefined, "", "bad id", "x".repeat(65), 123]) {
      const args = {image_id: 77, rect};
      if (request_id !== undefined) args.request_id = request_id;
      assert.equal((await client.tool("dm_crop", args)).error?.code, -32602);
    }
    assert.equal(host.requests.length, 0, "missing/invalid recovery IDs never dispatch");
    for (const args of [
      {}, {image_id: 77}, {rect}, {image_id: "front", rect}, {image_id: "77", rect}, {image_id: -1, rect},
      {image_id: 77, rect: null}, {image_id: 77, rect: []}, {image_id: 77, rect: [1, 2, 1, 6]},
      {image_id: 77, rect: [4, 2, 1, 6]}, {image_id: 77, rect: [1, 6, 4, 2]},
      {image_id: 77, rect: [-1, 2, 4, 6]}, {image_id: 77, rect: [1, 2, 4.5, 6]},
      {image_id: 77, rect: [1, 2, "4", 6]}, {image_id: 77, rect: [1, 2, 4294967296, 6]},
      {image_id: 77, rect, name: "unsupported custom name"},
    ]) assert.equal((await client.tool("dm_crop", {...args, request_id: "invalid-arguments"})).error?.code, -32602, JSON.stringify(args));
    assert.equal(host.requests.length, 0, "invalid crops must fail before any native dispatch");
    const first = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "crop-id"}));
    const {native_receipt, ...original} = first;
    assert.deepEqual(original, result, "return host metadata exactly without fabricated fields");
    assert.equal(native_receipt.request_id, "crop-id"); assert.equal(native_receipt.session, host.session);
    assert.deepEqual(host.requests.map(request => request.operation), ["CROP", "QUERY"]);
    assert.deepEqual(host.requests[0].args, ["77", "1", "2", "4", "6"]);
    const repeated = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "crop-id"}));
    assert.equal(repeated.image_id, 88); assert.equal(executions, 1, "an explicit repeated ID returns the same host record");
    const conflict = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [2, 2, 4, 6], request_id: "crop-id"}), true);
    assert.equal(conflict.native_receipt.code, "id_conflict"); assert.equal(executions, 1);
  } finally {await client.close(); await host.close();}
});

test("native dm_crop rejects wrong new/source identities or inconsistent reported rectangles", async () => {
  const rect = [1, 2, 4, 6];
  const mutations = [
    {image_id: 77}, {image_id: -1}, {image_id: 4294967296}, {image_id: 1.5}, {image_id: "88"}, {image_id: true},
    {source_image_id: 78}, {source_image_id: "77"}, {effective_rect: undefined}, {effective_rect: [1, 2, 3, 6]},
    {effective_rect: [1, 2, 4, 6, 8]}, {effective_rect: ["1", 2, 4, 6]}, {rect: [2, 2, 4, 6]}, {requested_rect: [1, 3, 4, 6]},
  ];
  const host = await nativeHost(({socket, request, reply}) => {
    const mutation = mutations[Number(request.id.slice(4))];
    socket.end(JSON.stringify(reply("completed", {backend: "mock-native", source_image_id: 77, image_id: 88, effective_rect: rect, ...mutation})) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (let index = 0; index < mutations.length; index++) {
      const output = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: "bad-" + index}), true);
      assert.equal(output.code, "NATIVE_PROTOCOL"); assert.equal(output.sent, true);
      assert.equal(output.request_id, "bad-" + index); assert.equal(output.session, host.session);
    }
    assert.equal(host.requests.length, mutations.length, "a malformed completed crop is never automatically resubmitted");
  } finally {await client.close(); await host.close();}
});

test("native dm_crop accepts the rect alias and propagates host ROI failures without retry", async () => {
  const host = await nativeHost(({socket, request, reply}) => {
    const response = request.id === "rect-alias" ? reply("completed", {backend: "mock-native", source_image_id: 77, image_id: 88, rect: [1, 2, 4, 6]})
      : reply("failed", undefined, {code: "roi_out_of_bounds", error: "rectangle is outside source"});
    socket.end(JSON.stringify(response) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const aliased = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [1, 2, 4, 6], request_id: "rect-alias"}));
    assert.deepEqual(aliased.rect, [1, 2, 4, 6]); assert.equal(Object.hasOwn(aliased, "effective_rect"), false);
    const failure = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [1, 2, 400, 600], request_id: "outside"}), true);
    assert.equal(failure.native_receipt.code, "roi_out_of_bounds");
    assert.deepEqual(host.requests.map(request => request.operation), ["CROP", "CROP"]);
  } finally {await client.close(); await host.close();}
});

test("native dm_crop requires a caller-saved request ID before any native call", async () => {
  const host = await nativeHost(() => assert.fail("invalid or missing crop ID must never reach the plugin"));
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const crop = (await client.rpc("tools/list")).result.tools.find(tool => tool.name === "dm_crop");
    assert.deepEqual(crop.inputSchema.required, ["image_id", "rect", "request_id"]);
    assert.match(crop.inputSchema.properties.request_id.description, /必填/);
    const argumentsWithoutId = {image_id: 77, rect: [1, 2, 4, 6]};
    const missing = await client.tool("dm_crop", argumentsWithoutId);
    assert.equal(missing.error?.code, -32602); assert.match(missing.error.message, /request_id/);
    for (const request_id of [null, 7, false, [], {}, "", "bad id", "bad\n", "bad\r", "图", "x".repeat(65)]) {
      const response = await client.tool("dm_crop", {...argumentsWithoutId, request_id});
      assert.equal(response.error?.code, -32602, JSON.stringify(request_id));
      assert.match(response.error.message, /request_id/);
    }
    assert.equal(host.requests.length, 0);
  } finally {await client.close(); await host.close();}
});

test("accepted crop cancellation recovers the same object through a new client in the same host session", async () => {
  const savedId = "caller-saved-before-cancel", rect = [1, 2, 4, 6];
  const result = {backend: "mock-native", source_image_id: 77, image_id: 88, effective_rect: rect};
  let accepted, completed = false, creations = 0;
  const observed = new Promise(resolve => {accepted = resolve;});
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "CROP") {
      assert.equal(request.id, savedId); assert.deepEqual(request.args, ["77", "1", "2", "4", "6"]);
      socket.end(JSON.stringify(reply("queued")) + "\n"); accepted();
    } else socket.end(JSON.stringify(completed ? reply("completed", result) : reply("running")) + "\n");
  });
  const env = {DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_MCP_TIMEOUT_MS: "1000"};
  const first = mcpClient(env); let recovered;
  try {
    await first.init();
    first.send({id: 900, method: "tools/call", params: {name: "dm_crop", arguments: {image_id: 77, rect, request_id: savedId}}});
    await observed;
    first.send({method: "notifications/cancelled", params: {requestId: 900}});
    await first.rpc("ping");
    assert.equal(first.messages.some(message => message.id === 900), false, "cancelled MCP response stays suppressed");
    assert.equal(creations, 0, "the accepted operation can still execute after the local wait ends");
    await first.close();
    completed = true; creations++;
    // Recovery belongs to the native host session, not the first Node process.
    recovered = mcpClient(env); await recovered.init();
    const a = toolOutput(await recovered.tool("dm_native_result", {request_id: savedId}));
    const b = toolOutput(await recovered.tool("dm_native_result", {request_id: savedId}));
    assert.equal(a.image_id, 88); assert.deepEqual(a, b);
    assert.equal(a.native_receipt.request_id, savedId); assert.equal(a.native_receipt.session, host.session);
    assert.equal(creations, 1); assert.equal(host.requests.filter(request => request.operation === "CROP").length, 1);
    assert.ok(host.requests.every(request => request.id === savedId));
  } finally {await first.close(); if (recovered) await recovered.close(); await host.close();}
});

test("crop disconnect, busy rejection and conflicting parameters cannot consume or overwrite the accepted record", async () => {
  const rect = [1, 2, 4, 6], savedId = "crop-accepted-before-disconnect";
  const result = {backend: "mock-native", source_image_id: 77, image_id: 88, effective_rect: rect};
  let acceptedArgs, complete = false, creations = 0;
  const host = await nativeHost(({socket, request, reply}) => {
    let response;
    if (request.operation === "CROP" && request.id === savedId) {
      if (!acceptedArgs) {acceptedArgs = request.args; socket.destroy(); return;}
      response = JSON.stringify(request.args) !== JSON.stringify(acceptedArgs)
        ? reply("failed", undefined, {code: "id_conflict", error: "ID is already bound to different parameters"})
        : complete ? reply("completed", result) : reply("running");
    } else if (request.operation === "CROP") {
      response = reply("failed", undefined, {code: "busy", error: "the original operation is still running"});
    } else response = request.id !== savedId ? reply("unknown") : complete ? reply("completed", result) : reply("running");
    socket.end(JSON.stringify(response) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const lost = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: savedId}), true);
    assert.equal(lost.request_id, savedId); assert.equal(lost.session, host.session); assert.equal(lost.sent, true);
    const busy = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [0, 0, 1, 1], request_id: "different-crop"}), true);
    assert.equal(busy.native_receipt.code, "busy"); assert.equal(busy.native_receipt.request_id, "different-crop");
    const running = toolOutput(await client.tool("dm_native_result", {request_id: savedId}), true);
    assert.equal(running.native_receipt.state, "running");
    complete = true; creations++;
    const original = toolOutput(await client.tool("dm_native_result", {request_id: savedId}));
    assert.equal(original.image_id, 88); assert.deepEqual(original.effective_rect, rect);
    const conflict = toolOutput(await client.tool("dm_crop", {image_id: 77, rect: [2, 2, 4, 6], request_id: savedId}), true);
    assert.equal(conflict.native_receipt.code, "id_conflict");
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: savedId})), original);
    const other = toolOutput(await client.tool("dm_native_result", {request_id: "different-crop"}), true);
    assert.equal(other.native_receipt.state, "unknown");
    assert.deepEqual(acceptedArgs, ["77", "1", "2", "4", "6"]);
    assert.equal(creations, 1);
    assert.equal(host.requests.filter(request => request.operation === "CROP" && JSON.stringify(request.args) === JSON.stringify(acceptedArgs)).length, 1,
      "the originally sent operation must never be resent automatically after disconnect");
  } finally {await client.close(); await host.close();}
});

test("a late crop completion after timeout remains bound to its saved ID while a later crop has a different ID", async () => {
  const rect = [1, 2, 4, 6], savedId = "late-crop-original", otherId = "later-crop";
  const firstResult = {backend: "mock-native", source_image_id: 77, image_id: 88, effective_rect: rect};
  const otherResult = {...firstResult, image_id: 99};
  let complete = false, originalReply, originalSocket, observedQuery, creations = 0;
  const queried = new Promise(resolve => {observedQuery = resolve;});
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation === "CROP" && request.id === savedId) {
      socket.end(JSON.stringify(reply("queued")) + "\n"); return;
    }
    if (request.operation === "QUERY" && request.id === savedId && !complete) {
      originalSocket = socket; originalReply = reply; observedQuery(); return;
    }
    if (request.operation === "CROP") creations++;
    socket.end(JSON.stringify(reply("completed", request.id === savedId ? firstResult : otherResult)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_MCP_TIMEOUT_MS: "150"});
  try {
    await client.init();
    const submitted = client.tool("dm_crop", {image_id: 77, rect, request_id: savedId});
    await Promise.race([queried, submitted.then(response => {throw new Error("expected an in-flight QUERY before completion: " + JSON.stringify(response));})]);
    const timeout = toolOutput(await submitted, true);
    assert.equal(timeout.code, "NATIVE_TIMEOUT"); assert.equal(timeout.request_id, savedId); assert.equal(timeout.sent, true);
    complete = true; creations++;
    // The old response can arrive after its socket/waiter has been destroyed.
    originalSocket.end(JSON.stringify(originalReply("completed", firstResult)) + "\n");
    const later = toolOutput(await client.tool("dm_crop", {image_id: 77, rect, request_id: otherId}));
    assert.equal(later.image_id, 99); assert.equal(later.native_receipt.request_id, otherId);
    const recovered = toolOutput(await client.tool("dm_native_result", {request_id: savedId}));
    assert.equal(recovered.image_id, 88); assert.equal(recovered.native_receipt.request_id, savedId);
    assert.equal(creations, 2);
    assert.deepEqual(host.requests.filter(request => request.operation === "CROP").map(request => request.id), [savedId, otherId]);
  } finally {await client.close(); await host.close();}
});

test("native dm_native_show requires both saved request ID and explicit uint32 image ID before any host call", async () => {
  const host = await nativeHost(() => assert.fail("invalid SHOW must not reach a plugin"));
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    const init = await client.init();
    assert.match(init.instructions, /dm_native_show/);
    const show = (await client.rpc("tools/list")).result.tools.find(tool => tool.name === "dm_native_show");
    assert.deepEqual(show.inputSchema.required, ["image_id", "request_id"]);
    assert.equal(show.inputSchema.properties.image_id.type, "integer");
    assert.match(show.description, /本插件仍持有的已合格原生结果/);
    assert.match(show.description, /不保存文件/);
    assert.match(show.description, /不代表模型已看图/);
    assert.match(show.description, /不关闭已显示的文档/);
    for (const args of [{}, {image_id: 88}, {request_id: "saved-show"}, {image_id: 88, request_id: "saved-show", front: true}]) {
      assert.equal((await client.tool("dm_native_show", args)).error.code, -32602);
    }
    for (const image_id of [null, "front", "88", true, [], {}, -1, 0.25, 4294967296]) {
      assert.equal((await client.tool("dm_native_show", {image_id, request_id: "saved-show"})).error.code, -32602);
    }
    for (const request_id of [null, 7, false, [], {}, "", "bad id", "bad\n", "bad\r", "图", "x".repeat(65)]) {
      assert.equal((await client.tool("dm_native_show", {image_id: 88, request_id})).error.code, -32602);
    }
    assert.equal(host.requests.length, 0);
  } finally {await client.close(); await host.close();}
});

test("native SHOW polls same ID once submitted and reuses a completed record without another document creation", async () => {
  const result = {backend: "mock-native", image_id: 88, delivery: "visible_dm_document", document_visible: true,
    operator: "synthetic-explicit-image-document", ownership: "document owns image; native STOP releases plugin crop reference only",
    source_write_requested: false, snapshot_atomic: false};
  const records = new Map(); let creations = 0;
  const host = await nativeHost(({socket, request, reply}) => {
    let response;
    const previous = records.get(request.id);
    if (request.operation === "SHOW") {
      if (previous && JSON.stringify(previous.args) !== JSON.stringify(request.args)) {
        response = reply("failed", undefined, {code: "id_conflict", error: "request ID already bound to another image"});
      } else {
        if (!previous) {records.set(request.id, {args: request.args, complete: false}); creations++;}
        response = records.get(request.id).complete ? reply("completed", result) : reply("queued");
      }
    } else {
      assert.equal(request.operation, "QUERY");
      if (previous) {previous.complete = true; response = reply("completed", result);}
      else response = reply("unknown");
    }
    socket.end(JSON.stringify(response) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    const args = {image_id: 88, request_id: "show-saved"};
    const first = toolOutput(await client.tool("dm_native_show", args));
    assert.deepEqual(host.requests, [
      {id: "show-saved", operation: "SHOW", args: ["88"]},
      {id: "show-saved", operation: "QUERY", args: []},
    ], "the facade must only QUERY after the initial SHOW is accepted");
    const {display_context, ...nativeFields} = first;
    assert.deepEqual({...nativeFields, native_receipt: undefined}, {...result, native_receipt: undefined}, "host fields stay unchanged without invented delivery claims");
    assert.deepEqual(display_context, {scope: "document_delivery_only", active_workspace_visibility: "unknown",
      workspace_activation_requested: false, model_visual_verification: false, observation: "not_performed_by_mcp"});
    assert.equal(Object.hasOwn(result, "display_context"), false, "stored host result is not rewritten");
    assert.equal(first.native_receipt.request_id, args.request_id); assert.equal(first.native_receipt.session, host.session);
    assert.deepEqual(toolOutput(await client.tool("dm_native_show", args)), first);
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: args.request_id})), first);
    const conflict = toolOutput(await client.tool("dm_native_show", {...args, image_id: 89}), true);
    assert.equal(conflict.native_receipt.code, "id_conflict");
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: args.request_id})), first);
    assert.equal(creations, 1, "an explicit repeat of a completed ID reuses the host record");
    assert.equal(host.requests.filter(request => request.operation === "SHOW" && request.args[0] === "88").length, 2,
      "there are exactly two explicitly requested SHOW submissions and no automatic resend");
  } finally {await client.close(); await host.close();}
});

test("native SHOW rejects completed results without the same image and visible document delivery", async () => {
  const valid = {backend: "mock-native", image_id: 88, delivery: "visible_dm_document", document_visible: true};
  const cases = [
    {...valid, image_id: 89}, {...valid, image_id: "88"}, {...valid, image_id: undefined},
    {...valid, delivery: "file"}, {...valid, delivery: "latest_window"}, {...valid, delivery: undefined},
    {...valid, document_visible: false}, {...valid, document_visible: "true"}, {...valid, document_visible: undefined},
  ];
  const host = await nativeHost(({socket, request, reply}) => {
    assert.equal(request.operation, "SHOW");
    socket.end(JSON.stringify(reply("completed", cases[Number(request.id.split("-").at(-1))])) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (let index = 0; index < cases.length; index++) {
      const request_id = "bad-show-" + index;
      const output = toolOutput(await client.tool("dm_native_show", {image_id: 88, request_id}), true);
      assert.equal(output.code, "NATIVE_PROTOCOL"); assert.equal(output.state, "unknown");
      assert.equal(output.request_id, request_id); assert.equal(output.session, host.session); assert.equal(output.sent, true);
      assert.equal(Object.hasOwn(output, "delivery"), false);
    }
    assert.equal(host.requests.length, cases.length, "malformed success receipts must not trigger a replay");
  } finally {await client.close(); await host.close();}
});

test("native SHOW failures and unknown do not succeed or fall back; timeout recovers using only QUERY", async () => {
  const savedId = "show-late";
  const result = {backend: "mock-native", image_id: 88, delivery: "visible_dm_document", document_visible: true};
  let displays = 0;
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.id === "not-retained") socket.end(JSON.stringify(reply("failed", undefined,
      {code: "not_retained_crop", error: "SHOW only accepts this plugin's retained crops"})) + "\n");
    else if (request.id === "unknown-show") socket.end(JSON.stringify(reply("unknown")) + "\n");
    else if (request.operation === "SHOW") {displays++; /* Operation completed, response lost. */}
    else socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    const failed = toolOutput(await client.tool("dm_native_show", {image_id: 77, request_id: "not-retained"}), true);
    assert.equal(failed.native_receipt.state, "failed"); assert.equal(failed.native_receipt.code, "not_retained_crop");
    const unknown = toolOutput(await client.tool("dm_native_show", {image_id: 88, request_id: "unknown-show"}), true);
    assert.equal(unknown.native_receipt.state, "unknown");
    const timeout = toolOutput(await client.tool("dm_native_show", {image_id: 88, request_id: savedId}), true);
    assert.equal(timeout.code, "NATIVE_TIMEOUT"); assert.equal(timeout.sent, true);
    assert.equal(timeout.request_id, savedId); assert.equal(timeout.session, host.session);
    const recovered = toolOutput(await client.tool("dm_native_result", {request_id: savedId}));
    assert.equal(recovered.image_id, 88); assert.equal(recovered.delivery, "visible_dm_document");
    assert.equal(recovered.native_receipt.request_id, savedId); assert.equal(displays, 1);
    assert.deepEqual(host.requests.filter(request => request.id === savedId).map(request => request.operation), ["SHOW", "QUERY"]);
  } finally {await client.close(); await host.close();}
});

test("native SUMMARY exposes only four raw reductions with explicit image ID and optional read-only request ID", async () => {
  const expected = summaryFixture();
  const host = await nativeHost(({socket, request, reply}) => {
    assert.equal(request.operation, "SUMMARY"); assert.deepEqual(request.args, ["77"]);
    socket.end(JSON.stringify(reply("completed", expected)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    const init = await client.init(); assert.match(init.instructions, /dm_native_summary/); assert.match(init.instructions, /四个原生摘要/);
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.equal(catalog.length, nativeCatalog.length);
    const summary = catalog.find(tool => tool.name === "dm_native_summary");
    assert.deepEqual(summary.inputSchema.required, ["image_id"]);
    assert.equal(summary.inputSchema.properties.image_id.type, "integer");
    assert.match(summary.description, /minimum.*maximum.*sum.*mean/);
    assert.match(summary.description, /不提供完整 stats/); assert.match(summary.description, /不应用强度标定/);
    for (const args of [{}, {image_id: "front"}, {image_id: "77"}, {image_id: true}, {image_id: -1}, {image_id: 1.5},
      {image_id: 4294967296}, {image_id: 77, rect: [0, 0, 1, 1]}, {image_id: 77, request_id: "bad id"}]) {
      assert.equal((await client.tool("dm_native_summary", args)).error.code, -32602, JSON.stringify(args));
    }
    assert.equal(host.requests.length, 0);
    for (const request_id of [undefined, "summary-saved"]) {
      const output = toolOutput(await client.tool("dm_native_summary", {image_id: 77, ...(request_id ? {request_id} : {})}));
      const {native_receipt, ...actual} = output;
      assert.deepEqual(actual, expected, "metadata and raw signed fractions remain as returned by host");
      assert.equal(native_receipt.state, "completed"); assert.equal(native_receipt.session, host.session);
      assert.equal(native_receipt.host_pid, 301); assert.equal(native_receipt.exec_tid, 303);
      if (request_id) assert.equal(native_receipt.request_id, request_id);
      else assert.match(native_receipt.request_id, /^[0-9a-f-]{36}$/);
      for (const unsupported of ["stddev", "variance", "preview", "path"]) assert.equal(Object.hasOwn(output, unsupported), false);
    }
    assert.deepEqual(host.requests.map(request => request.operation), ["SUMMARY", "SUMMARY"]);
  } finally {await client.close(); await host.close();}
});

test("native SUMMARY keeps missing spatial units explicit and polls the same request without resubmission", async () => {
  const expected = summaryFixture();
  for (const axis of expected.image.calibration) {axis.unit = null; axis.usable = false; axis.issue = "unknown_units";}
  expected.image.calibration_complete = false;
  const host = await nativeHost(({socket, request, reply}) => socket.end(JSON.stringify(
    request.operation === "SUMMARY" ? reply("queued") : reply("completed", expected)) + "\n"));
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const output = toolOutput(await client.tool("dm_native_summary", {image_id: 77, request_id: "summary-unmarked"}));
    assert.equal(output.image.calibration_complete, false); assert.equal(output.image.calibration[0].unit, null);
    assert.equal(output.image.calibration[0].issue, "unknown_units"); assert.equal(output.mean, -0.0625);
    assert.equal(output.intensity_calibration_applied, false);
    assert.deepEqual(host.requests, [
      {operation: "SUMMARY", args: ["77"], id: "summary-unmarked"},
      {operation: "QUERY", args: [], id: "summary-unmarked"},
    ]);
    assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id: "summary-unmarked"})), output);
    assert.equal(host.requests.filter(request => request.operation === "SUMMARY").length, 1);
  } finally {await client.close(); await host.close();}
});

test("native SUMMARY malformed completion is a protocol tool error, including recovered queries", async () => {
  const cases = [
    ...["minimum", "maximum", "sum", "mean"].map(key => r => {r[key] = "1.25";}),
    r => {r.image_id = 78;}, r => {r.image.id = 78;}, r => {r.image.dtype = "uint16";},
    r => {r.image.shape = [4, 3];}, r => {r.image.pixels = 13;},
    r => {r.operators = ["Python::statistics"];}, r => {r.intensity_calibration_applied = true;},
    r => {r.intensity_semantics = "calibrated";}, r => {r.source_write_requested = true;},
    r => {r.image.calibration_complete = false;}, r => {r.image.native_summary_supported = false;},
  ];
  const host = await nativeHost(({socket, request, reply}) => {
    const result = summaryFixture(); cases[Number(request.id.split("-").at(-1))](result);
    socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (let index = 0; index < cases.length; index++) {
      const output = toolOutput(await client.tool("dm_native_summary", {image_id: 77, request_id: "malformed-summary-" + index}), true);
      assert.equal(output.code, "NATIVE_PROTOCOL"); assert.equal(output.sent, true); assert.equal(output.state, "unknown");
      assert.equal(output.request_id, "malformed-summary-" + index);
    }
    const recovered = toolOutput(await client.tool("dm_native_result", {request_id: "malformed-summary-0"}), true);
    assert.equal(recovered.code, "NATIVE_PROTOCOL"); assert.equal(recovered.request_id, "malformed-summary-0");
    assert.equal(host.requests.length, cases.length + 1, "invalid results do not cause resubmission or fallback");
  } finally {await client.close(); await host.close();}
});

test("native SUMMARY errors and unknown do not fall back; timeout and cancellation recover through QUERY", async () => {
  const completed = new Set();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.id === "summary-failed") return socket.end(JSON.stringify(reply("failed", undefined,
      {code: "native_summary_nonfinite_result", error: "nonfinite native result"})) + "\n");
    if (request.id === "summary-unknown") return socket.end(JSON.stringify(reply("unknown")) + "\n");
    if (request.operation === "SUMMARY") {completed.add(request.id); return;}
    socket.end(JSON.stringify(completed.has(request.id) ? reply("completed", summaryFixture()) : reply("unknown")) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    const failed = toolOutput(await client.tool("dm_native_summary", {image_id: 77, request_id: "summary-failed"}), true);
    assert.equal(failed.native_receipt.code, "native_summary_nonfinite_result");
    const unknown = toolOutput(await client.tool("dm_native_summary", {image_id: 77, request_id: "summary-unknown"}), true);
    assert.equal(unknown.native_receipt.state, "unknown");
    const timed = toolOutput(await client.tool("dm_native_summary", {image_id: 77, request_id: "summary-timed"}), true);
    assert.equal(timed.code, "NATIVE_TIMEOUT"); assert.equal(timed.sent, true);
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: "summary-timed"})).sum, -0.75);
    client.send({id: 910, method: "tools/call", params: {name: "dm_native_summary", arguments: {image_id: 77, request_id: "summary-cancelled"}}});
    await sleep(30); client.send({method: "notifications/cancelled", params: {requestId: 910}}); await sleep(180);
    assert.equal(client.messages.some(message => message.id === 910), false);
    assert.equal(toolOutput(await client.tool("dm_native_result", {request_id: "summary-cancelled"})).maximum, 8.5);
    for (const id of ["summary-timed", "summary-cancelled"]) {
      assert.deepEqual(host.requests.filter(request => request.id === id).map(request => request.operation), ["SUMMARY", "QUERY"]);
    }
  } finally {await client.close(); await host.close();}
});

const operationCases = [
  ...["negate", "abs", "square"].map((operation, index) => ["dm_native_unary", {image_id: 77, operation}, "UNARY", [77, index + 1]]),
  ...["add", "subtract", "multiply"].map((operation, index) => ["dm_native_binary", {left_image_id: 77, right_image_id: 78, operation}, "BINARY", [77, 78, index + 1]]),
  ...["forward", "inverse"].map(direction => ["dm_native_fft", {image_id: 77, direction}, direction === "forward" ? "FFT" : "IFFT", [77]]),
  ...["real", "imaginary", "phase", "power"].map((component, index) => ["dm_native_complex", {image_id: 77, component}, ["REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"][index], [77]]),
  ...["smooth", "sobel", "laplace", "sharpen"].map((operation, index) => ["dm_native_filter", {image_id: 77, operation}, "FILTER", [77, index + 1]]),
];

test("new native tools expose finite enums and require saved side-effect IDs before any send", async () => {
  const host = await nativeHost(() => {assert.fail("invalid arguments reached the native pipe");});
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const catalog = (await client.rpc("tools/list")).result.tools;
    assert.equal(catalog.length, nativeCatalog.length); assert.deepEqual(catalog.map(tool => tool.name), nativeCatalog);
    for (const name of nativeCatalog.slice(7, 12)) assert.ok(catalog.find(tool => tool.name === name).inputSchema.required.includes("request_id"));
    const preview = catalog.find(tool => tool.name === "dm_native_preview");
    assert.deepEqual(preview.inputSchema.required, ["image_id"]);
    for (const key of ["max_width", "max_height"]) assert.deepEqual(preview.inputSchema.properties[key], {type: "integer", minimum: 1, maximum: 128, default: 128});
    assert.match(catalog.find(tool => tool.name === "dm_native_complex").description, /平方模.*不是幅值/);
    assert.match(catalog.find(tool => tool.name === "dm_native_show").description, /已合格原生结果/);
    for (const [name, args] of operationCases) {
      assert.equal((await client.tool(name, args)).error.code, -32602, "missing saved ID: " + name);
      for (const request_id of ["", "unsafe id", "x\n", "x".repeat(65), 2]) assert.equal((await client.tool(name, {...args, request_id})).error.code, -32602);
      assert.equal((await client.tool(name, {...args, request_id: "saved", path: "forbidden"})).error.code, -32602);
      const selector = Object.hasOwn(args, "direction") ? "direction" : Object.hasOwn(args, "component") ? "component" : "operation";
      for (const invalid of ["divide", "__proto__", "script()", "", 1]) assert.equal((await client.tool(name, {...args, [selector]: invalid, request_id: "saved"})).error.code, -32602);
    }
    for (const args of [{}, {image_id: "front"}, {image_id: "77"}, {image_id: -1}, {image_id: 77, max_width: 0},
      {image_id: 77, max_height: 129}, {image_id: 77, max_width: 1.5}, {image_id: 77, max_width: null}, {image_id: 77, request_id: "bad id"}, {image_id: 77, output_path: "forbidden"}]) {
      assert.equal((await client.tool("dm_native_preview", args)).error.code, -32602);
    }
    assert.equal(host.requests.length, 0);
  } finally {await client.close(); await host.close();}
});

test("all new finite operation enums map to exact NB2 operations and recover only through QUERY", async () => {
  const records = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") records.set(request.id, {operation: request.operation, args: request.args.map(Number)});
    const original = records.get(request.id);
    socket.end(JSON.stringify(request.operation === "QUERY" ? reply("completed", operationFixture(original.operation, original.args)) : reply("queued")) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (let index = 0; index < operationCases.length; index++) {
      const [name, args, operation, nativeArgs] = operationCases[index], request_id = "operation-" + index;
      const output = toolOutput(await client.tool(name, {...args, request_id}));
      const {native_receipt, ...result} = output;
      assert.deepEqual(result, operationFixture(operation, nativeArgs));
      assert.equal(native_receipt.original_operation, operation); assert.deepEqual(native_receipt.normalized_args, nativeArgs);
      assert.equal(native_receipt.result_version, ["native_fourier_operation","native_gui_rois"].includes(resultTypes[operation]) ? 2 : 1);
      assert.deepEqual(toolOutput(await client.tool("dm_native_result", {request_id})), output);
      assert.deepEqual(host.requests.filter(request => request.id === request_id).map(request => [request.operation, request.args]),
        [[operation, nativeArgs.map(String)], ["QUERY", []], ["QUERY", []]]);
    }
  } finally {await client.close(); await host.close();}
});

test("public Fourier tools reject candidate v1 receipts before polling or claiming qualified results", async () => {
  const host = await nativeHost(({socket, reply}) => socket.end(JSON.stringify(reply("queued", undefined, {result_version: 1})) + "\n"));
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const [name, args] of [["dm_native_fft", {image_id: 77, direction: "forward"}], ["dm_native_complex", {image_id: 77, component: "power"}]]) {
      const request_id = "reject-v1-" + name, message = await client.tool(name, {...args, request_id}), output = toolOutput(message, true);
      assert.equal(output.code, "NATIVE_PROTOCOL"); assert.match(output.error, /version 1 is historical QUERY only/); assert.equal(output.sent, true);
      assert.equal(message.result.content.length, 1);
      assert.equal(host.requests.filter(request => request.id === request_id).length, 1, "old candidate rejection never resubmits or polls");
    }
  } finally {await client.close(); await host.close();}
});

function decodedPreview(message) {
  const output = toolOutput(message);
  assert.equal(message.result.content.length, 2);
  const block = message.result.content[1]; assert.equal(block.type, "image"); assert.equal(block.mimeType, "image/png");
  const png = Buffer.from(block.data, "base64"); assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  const compressed = []; let width, height;
  for (let offset = 8; offset < png.length;) {
    const size = png.readUInt32BE(offset), type = png.toString("ascii", offset + 4, offset + 8), data = png.subarray(offset + 8, offset + 8 + size);
    if (type === "IHDR") {width = data.readUInt32BE(0); height = data.readUInt32BE(4); assert.equal(data[8], 8); assert.equal(data[9], 0);}
    if (type === "IDAT") compressed.push(data);
    offset += size + 12;
  }
  assert.equal(width, output.width); assert.equal(height, output.height);
  const rows = inflateSync(Buffer.concat(compressed)), pixels = Buffer.from(output.gray8_hex, "hex");
  for (let y = 0; y < height; y++) {
    assert.equal(rows[y * (width + 1)], 0);
    assert.deepEqual(rows.subarray(y * (width + 1) + 1, (y + 1) * (width + 1)), pixels.subarray(y * width, (y + 1) * width));
  }
  return output;
}

test("native PREVIEW and its QUERY return bounded display PNG plus exact text without files", async () => {
  const records = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") records.set(request.id, request.args.map(Number));
    socket.end(JSON.stringify(reply("completed", operationFixture("PREVIEW", records.get(request.id)))) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const args of [{image_id: 77}, {image_id: 77, max_width: 2, max_height: 1, request_id: "small-preview"}]) {
      const message = await client.tool("dm_native_preview", args), output = decodedPreview(message), id = output.native_receipt.id;
      assert.equal(output.quantitative, false); assert.equal(output.native_receipt.original_operation, "PREVIEW");
      assert.deepEqual(output.native_receipt.normalized_args, [77, args.max_width ?? 128, args.max_height ?? 128]);
      assert.deepEqual(decodedPreview(await client.tool("dm_native_result", {request_id: id})), output);
      for (const key of ["path", "preview_path", "saved_file", "image"]) assert.equal(Object.hasOwn(output, key), false);
      assert.deepEqual(host.requests.filter(request => request.id === id).map(request => request.operation), ["PREVIEW", "QUERY"]);
    }
  } finally {await client.close(); await host.close();}
});

test("new native result failures, unknown and malformed typed outputs never fall back or gain images", async () => {
  const bad = [
    ["dm_native_unary", {image_id: 77, operation: "negate"}, "UNARY", [77, 1], result => {result.image_id = 77;}],
    ["dm_native_binary", {left_image_id: 77, right_image_id: 78, operation: "add"}, "BINARY", [77, 78, 1], result => {result.sources[1].id = 77;}],
    ["dm_native_filter", {image_id: 77, operation: "sobel"}, "FILTER", [77, 2], result => {result.filter_kind = 1;}],
    ["dm_native_preview", {image_id: 77, max_width: 2, max_height: 2}, "PREVIEW", [77, 2, 2], result => {result.gray8_hex = "00";}],
  ];
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.id === "failed-unary") return socket.end(JSON.stringify(reply("failed", undefined, {code: "native_unary_nonfinite_output", error: "nonfinite output"})) + "\n");
    if (request.id === "unknown-unary") return socket.end(JSON.stringify(reply("unknown")) + "\n");
    const [, , operation, args, change] = bad[Number(request.id.split("-").at(-1))], result = operationFixture(operation, args);
    change(result); socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const request_id of ["failed-unary", "unknown-unary"]) {
      const message = await client.tool("dm_native_unary", {image_id: 77, operation: "negate", request_id});
      const output = toolOutput(message, true); assert.equal(message.result.content.length, 1);
      assert.equal(output.native_receipt.state, request_id.split("-")[0]);
    }
    for (let index = 0; index < bad.length; index++) {
      const [name, args] = bad[index], request_id = "malformed-operation-" + index;
      for (const message of [await client.tool(name, {...args, request_id}), await client.tool("dm_native_result", {request_id})]) {
        assert.equal(toolOutput(message, true).code, "NATIVE_PROTOCOL"); assert.equal(message.result.content.length, 1);
      }
      assert.equal(host.requests.filter(request => request.id === request_id && request.operation !== "QUERY").length, 1);
    }
  } finally {await client.close(); await host.close();}
});

test("cancelled native output and preview waits recover typed results by same-ID QUERY without replay", async () => {
  const records = new Map();
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.operation !== "QUERY") {records.set(request.id, {operation: request.operation, args: request.args.map(Number)}); return;}
    const record = records.get(request.id); socket.end(JSON.stringify(reply("completed", operationFixture(record.operation, record.args))) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    for (const [index, name, args, operation] of [[0, "dm_native_unary", {image_id: 77, operation: "abs"}, "UNARY"],
      [1, "dm_native_preview", {image_id: 77, max_width: 2, max_height: 2}, "PREVIEW"],
      [2, "dm_native_fft", {image_id: 77, direction: "forward"}, "FFT"],
      [3, "dm_native_read", {image_id: 77, rect: [1, 1, 4, 3]}, "READ"]]) {
      const request_id = "cancelled-new-" + index, rpcId = 940 + index;
      client.send({id: rpcId, method: "tools/call", params: {name, arguments: {...args, request_id}}});
      await sleep(30); client.send({method: "notifications/cancelled", params: {requestId: rpcId}}); await sleep(170);
      assert.equal(client.messages.some(message => message.id === rpcId), false);
      const recovered = await client.tool("dm_native_result", {request_id});
      const output = operation === "PREVIEW" ? decodedPreview(recovered) : toolOutput(recovered);
      assert.equal(output.native_receipt.original_operation, operation);
      assert.deepEqual(host.requests.filter(request => request.id === request_id).map(request => request.operation), [operation, "QUERY"]);
    }
  } finally {await client.close(); await host.close();}
});

test("native READ requires explicit bounded half-open ROI and rejects paths or invalid data before send", async () => {
  const host = await nativeHost(() => {assert.fail("invalid READ must never reach native dispatch");});
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session});
  try {
    await client.init();
    const catalog = (await client.rpc("tools/list")).result.tools, read = catalog.find(tool => tool.name === "dm_native_read");
    assert.equal(catalog.length, nativeCatalog.length); assert.deepEqual(read.inputSchema.required, ["image_id", "rect"]);
    assert.match(read.description, /16384/); assert.match(read.description, /不生成图片.*不保存文件/);
    for (const args of [{}, {image_id: 77}, {rect: [0, 0, 1, 1]}, {image_id: "front", rect: [0, 0, 1, 1]},
      {image_id: "77", rect: [0, 0, 1, 1]}, {image_id: -1, rect: [0, 0, 1, 1]}, {image_id: 77, rect: []},
      {image_id: 77, rect: [0, 0, 1]}, {image_id: 77, rect: [0, 0, 1, 1, 1]}, {image_id: 77, rect: [0, 0, "1", 1]},
      {image_id: 77, rect: [0, 0, 1.5, 1]}, {image_id: 77, rect: [-1, 0, 1, 1]}, {image_id: 77, rect: [1, 0, 1, 1]},
      {image_id: 77, rect: [1, 0, 0, 1]}, {image_id: 77, rect: [0, 0, 129, 128]}, {image_id: 77, rect: [0, 0, 4294967296, 1]},
      {image_id: 77, rect: [0, 0, 1, 1], request_id: "unsafe id"}, {image_id: 77, rect: [0, 0, 1, 1], path: "output.npy"}]) {
      assert.equal((await client.tool("dm_native_read", args)).error.code, -32602, JSON.stringify(args));
    }
    assert.equal(host.requests.length, 0);
  } finally {await client.close(); await host.close();}
});

test("native READ emits only exact snapshot text and same-ID QUERY preserves bytes/calibration/provenance", async () => {
  const args = [77, 1, 1, 4, 3], expected = readFixture(args), host = await nativeHost(({socket, request, reply}) => {
    socket.end(JSON.stringify(request.operation === "READ" ? reply("queued") : reply("completed", expected)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const explicit of [false, true]) {
      const message = await client.tool("dm_native_read", {image_id: 77, rect: args.slice(1), ...(explicit ? {request_id: "read-saved"} : {})});
      const output = toolOutput(message), {native_receipt, ...result} = output;
      assert.deepEqual(result, expected); assert.equal(message.result.content.length, 1, "READ must not create an image content block");
      assert.equal(native_receipt.result_type, "native_data_snapshot"); assert.deepEqual(native_receipt.normalized_args, args);
      const recovered = await client.tool("dm_native_result", {request_id: native_receipt.id});
      assert.deepEqual(toolOutput(recovered), output); assert.equal(recovered.result.content.length, 1);
      const bytes = Buffer.from(result.values_base64, "base64"); assert.ok(Object.is(bytes.readFloatLE(0), -0)); assert.equal(bytes.readFloatLE(4), -2.5);
      assert.deepEqual(result.shape, [2, 3]); assert.equal(result.roi_calibration[0].calibrated_value_at_pixel_zero, 0.25);
      assert.equal(result.roi_calibration[1].calibrated_value_at_pixel_zero, 1); assert.equal(result.source_provenance, null);
      assert.deepEqual(host.requests.filter(request => request.id === native_receipt.id).map(request => request.operation), ["READ", "QUERY", "QUERY"]);
      for (const key of ["image_id", "image", "path", "preview_path", "png"]) assert.equal(Object.hasOwn(result, key), false);
    }
  } finally {await client.close(); await host.close();}
});

test("native READ malformed, failed and unknown outcomes cannot claim data handoff or invoke fallback", async () => {
  const changes = [r => {r.byte_order = "big";}, r => {r.roi_calibration[0].origin++;}, r => {r.source_image_id++;},
    r => {r.values_base64 = "not canonical base64";}, r => {r.image_id = 99;}];
  const host = await nativeHost(({socket, request, reply}) => {
    if (request.id === "read-failed") return socket.end(JSON.stringify(reply("failed", undefined, {code: "native_read_nonfinite_sample", error: "nonfinite source sample"})) + "\n");
    if (request.id === "read-unknown") return socket.end(JSON.stringify(reply("unknown")) + "\n");
    const result = readFixture(); changes[Number(request.id.split("-").at(-1))](result); socket.end(JSON.stringify(reply("completed", result)) + "\n");
  });
  const client = mcpClient({DM_MCP_BACKEND: "native", DM_NATIVE_SESSION: host.session, DM_ANALYSIS_PYTHON: "must-never-start.exe"});
  try {
    await client.init();
    for (const request_id of ["read-failed", "read-unknown"]) {
      const message = await client.tool("dm_native_read", {image_id: 77, rect: [1, 1, 4, 3], request_id}), output = toolOutput(message, true);
      assert.equal(message.result.content.length, 1); assert.equal(output.native_receipt.state, request_id === "read-failed" ? "failed" : "unknown");
    }
    for (let index = 0; index < changes.length; index++) {
      const request_id = "bad-read-mcp-" + index;
      for (const message of [await client.tool("dm_native_read", {image_id: 77, rect: [1, 1, 4, 3], request_id}), await client.tool("dm_native_result", {request_id})]) {
        assert.equal(toolOutput(message, true).code, "NATIVE_PROTOCOL"); assert.equal(message.result.content.length, 1);
      }
      assert.deepEqual(host.requests.filter(request => request.id === request_id).map(request => request.operation), ["READ", "QUERY"]);
    }
  } finally {await client.close(); await host.close();}
});
