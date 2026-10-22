"""Revision-guarded scope repair builder; validation branch only."""
from pathlib import Path
import ast
import hashlib

BASE = 'd92cff64c7abeb8d8bd14c8d2b68fd89c6bd3695'

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected one patch anchor: %r (found %d)' % (old[:100], text.count(old)))
    return text.replace(old, new, 1)

def write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print('Updated', path)

p = Path('tools/analysis_worker.py')
raw = p.read_bytes()
assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == '3c025c6e3a48e7828f3a7076955800ad9b717cec', 'Unexpected worker revision'
s = raw.decode('utf-8')
a = s.index('from PIL import Image, ImageDraw')
b = s.index('\n\nHERE =', a)
s = s[:a] + '''# Only the requested capability loads its optional display dependencies.
# State inspection and numerical verification need NumPy, not a plotting stack.
Image = ImageDraw = matplotlib = plt = None


def _require_preview():
    global Image, ImageDraw
    if Image is None:
        try:
            from PIL import Image as image_module, ImageDraw as draw_module
        except ImportError as exc:
            raise RuntimeError("Preview requires requirements-preview.txt in the external Python environment; do not change GMS: %s" % exc)
        Image, ImageDraw = image_module, draw_module


def _require_report():
    global matplotlib, plt
    _require_preview()
    if plt is None:
        try:
            import matplotlib as plotting_module
            plotting_module.use("Agg")
            import matplotlib.pyplot as pyplot_module
        except ImportError as exc:
            raise RuntimeError("Optional report rendering requires requirements-analysis.txt in the external Python environment: %s" % exc)
        matplotlib, plt = plotting_module, pyplot_module
''' + s[b:]
s = once(s, 'PNG_INLINE_LIMIT = 2 * 1024 * 1024\n', '''PNG_INLINE_LIMIT = 2 * 1024 * 1024
PREVIEW_MEMORY_BUDGET = 256 * 1024 * 1024
PREVIEW_TILE_SIDE = 512
''')
a = s.index('def _finite_range(array):')
b = s.index('\ndef _gray_image(', a)
s = s[:a] + '''def _finite_range(array):
    """Scan bounded tiles, never make a full-frame finite mask or value copy."""
    low = high = None
    count = 0
    h, w = array.shape
    for y in range(0, h, PREVIEW_TILE_SIDE):
        for x in range(0, w, PREVIEW_TILE_SIDE):
            tile = np.asarray(array[y:y + PREVIEW_TILE_SIDE, x:x + PREVIEW_TILE_SIDE])
            finite = tile[np.isfinite(tile)]
            if finite.size:
                lo, hi = float(finite.min()), float(finite.max())
                low = lo if low is None else min(low, lo)
                high = hi if high is None else max(high, hi)
                count += int(finite.size)
    return low, high, count

''' + s[b:]
s = once(s, 'def _gray_image(array):\n    a = np.asarray(array)\n', 'def _gray_image(array, display_range=None):\n    _require_preview()\n    a = np.asarray(array)\n')
s = once(s, '    low, high, count = _finite_range(a)\n', '    low, high, count = _finite_range(a) if display_range is None else display_range\n')
s = once(s, '            scaled[finite] = np.clip((a[finite].astype(np.float64) - low) / (high - low), 0, 1)\n', '''            # Normalize first to avoid overflow for opposite-sign finite extrema.
            norm = max(abs(low), abs(high))
            scaled[finite] = np.clip((a[finite].astype(np.float64) / norm - low / norm) /
                                     (high / norm - low / norm), 0, 1)
''')
s = once(s, '    return Image.fromarray(rgb, "RGB"), {', '    return Image.fromarray(rgb), {')
s = once(s, '    base, display = _gray_image(array)\n    h, w = array.shape\n', '    h, w = array.shape\n')
s = once(s, '''    if (pw, ph) != (w, h):
        base = base.resize((pw, ph), Image.Resampling.BOX)
    draw = ImageDraw.Draw(base)
''', '''    # Allocate display buffers only at the requested output resolution. The
    # source remains a read-only memmap; small tiles determine its finite range.
    estimated = (pw * ph * (array.dtype.itemsize + 64) +
                 PREVIEW_TILE_SIDE ** 2 * (array.dtype.itemsize + 2) + 65536)
    if estimated > PREVIEW_MEMORY_BUDGET:
        raise RuntimeError("preview workspace exceeds budget; explicitly reduce max_side")
    display_range = _finite_range(array)
    if (pw, ph) == (w, h):
        shown = array
    else:
        columns = ((2 * np.arange(pw, dtype=np.int64) + 1) * w) // (2 * pw)
        rows = ((2 * np.arange(ph, dtype=np.int64) + 1) * h) // (2 * ph)
        shown = array[np.ix_(rows, columns)]
    base, display = _gray_image(shown, display_range)
    display.update({"resampling": "nearest source pixel to each preview pixel center; display only; small features may be missed",
                    "range_scope": "all finite pixels of the capture, scanned in bounded tiles",
                    "workspace_estimate_bytes": estimated,
                    "workspace_budget_bytes": PREVIEW_MEMORY_BUDGET})
    draw = ImageDraw.Draw(base)
''')
s = once(s, 'def _save_analysis_figures(folder, array, info, roi, profile_result, fft_array, fft_meta):\n', 'def _save_analysis_figures(folder, array, info, roi, profile_result, fft_array, fft_meta):\n    _require_report()\n')
s = once(s, '        ax.set_ylabel("Intensity (%s)" % (info.get("intensity_calibration", {}).get("unit") or "a.u."))', '        ax.set_ylabel("Raw pixel value (intensity calibration not applied)")')
# Share coordinate-frame conversion between the optional report and verifier.
marker = 'def _compute(capture_dir, params, result_dir, operation_id):'
helper = '''def _profile_result(array, info, request):
    sx0, sy0 = _source_rect(info)[:2]
    (px0, py0), (px1, py1) = request["start"], request["end"]
    result = core.profile(array, _local_calibration(info, 0, 0),
                          px0 - sx0, py0 - sy0, px1 - sx0, py1 - sy0, request["width"])
    local = result["sampled_coordinates"]
    result.update({"sampled_coordinates_local": local,
                   "sampled_coordinates": [[x + sx0, y + sy0] for x, y in local],
                   "coordinate_frame": "original source pixel centers",
                   "local_coordinate_frame": "captured array pixel centers",
                   "calibration_coordinate_frame": "captured array pixel centers",
                   "request": request,
                   "intensity_value_mode": "raw pixel values; intensity calibration retained but not applied",
                   "intensity_calibration": info.get("intensity_calibration")})
    return result


'''
s = once(s, marker, helper + marker)
s = once(s, '    request_identity = {"capture_id": info["capture_id"], "input_sha256": info["input_sha256"],\n', '    request_identity = {"capture_id": info["capture_id"], "input_sha256": info["input_sha256"],\n                        "input_metadata_sha256": capture_manifest["input_metadata_sha256"],\n')
s = once(s, '''        return inspect_result({"result_dir": result_dir}, expected_operation_id=operation_id)
    os.makedirs(result_dir)
''', '''        return inspect_result({"result_dir": result_dir}, expected_operation_id=operation_id)
    _require_report()  # Fail before reserving a result directory when deps are absent.
    os.makedirs(result_dir)
''')
a = s.index('            source_x0, source_y0 = _source_rect(info)[:2]')
b = s.index('            with open(os.path.join(result_dir, "profile.csv")', a)
s = s[:a] + '            profile_result = _profile_result(array, info, profile_request)\n' + s[b:]
s = once(s, 'writer.writerow(["distance_" + profile_result["unit"], "intensity", "finite_samples"])', 'writer.writerow(["distance_" + profile_result["unit"], "raw_intensity", "finite_samples"])')
s = s.replace('"intensity_calibration": info.get("intensity_calibration"),\n', '"intensity_calibration": info.get("intensity_calibration"),\n                      "intensity_value_mode": "raw pixel values; intensity calibration retained but not applied",\n')
s = once(s, '        report = "# 2D STEM analysis\\n\\n"', '        report = "# Optional 2D analysis example\\n\\n"')
s = once(s, 'The statistics and profile describe the captured pixel values.', 'The statistics and profile describe raw captured pixel values. Intensity scale/origin/unit are retained as metadata, not applied; these values are not labeled as calibrated counts or another physical intensity unit.')
a = s.index('        sx0, sy0, _, _ = info["source_rect_xyxy"]', s.index('def _verify_bundle'))
b = s.index('        good, why = _recursive_numeric_equal(profile,', a)
s = s[:a] + '        profile = _profile_result(array, info, profile_request)\n' + s[b:]
s = once(s, '''    sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=False,
                                allow_nan=False) + "\\n")
''', '''    successful = action != "verify" or result.get("state") == "verified"
    reply = {"ok": successful, "result": result}
    if not successful:
        reply["error"] = result.get("error") or "verification did not complete: %s" % result.get("state")
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, allow_nan=False) + "\\n")
    return 0 if successful else 1
''')
s = once(s, '    try:\n        main()\n', '    try:\n        sys.exit(main())\n')
ast.parse(s)
write(p, s)

# No tool removals or mode flags: compatibility is retained; workflow is optional.
p = Path('server.mjs'); s = p.read_text(encoding='utf-8')
s = once(s, ' * The process is a thin MCP facade; all work happens inside the running\n * DigitalMicrograph instance via dm_bridge.py over loopback TCP.', ' * DM operations go through dm_bridge.py over loopback TCP. Optional preview\n * and report helpers run outside GMS; reports are not required for core tools.')
s = once(s, '  "二维任务 A：dm_datasets 检查图像 → dm_2d_capture 一次捕获明确图像/当前 front → dm_2d_preview 核对预览与 source-coordinate 选区 → dm_2d_analyze 生成结果包 → dm_2d_result 查询状态。分析只读捕获副本。",', '''  "定位：可靠的 DM 工具接口，不是固定分析流水线。先用 dm_status/dm_datasets 识别数据，再按目标选择 metadata/stats/profile/fft/crop/export；简单操作无需捕获包或报告。多步调用应固定显式 image_id。",
  "需要看图或固定多步输入时，可用 dm_2d_capture + dm_2d_preview；显示 PNG 不参与计算。dm_2d_analyze 是可选的完整报告示例，只在用户需要这种组合时调用。dm_2d_result 可独立查询状态。",''')
s = once(s, '    "对捕获包执行有限值统计、双线性剖面与完整二维 FFT，并在全新目录保存原始副本、真实数值、图、参数、哈希、Markdown 报告与 replay.py。operation_id + result_dir 用于超时后查询，绝不自动重跑不确定任务。",', '    "可选报告示例，不是使用 DM 的必经步骤。对捕获包组合统计、剖面和完整 FFT，在新目录保存数值、图、报告及复跑脚本。需要独立报告环境；简单测量优先用单独工具。operation_id + result_dir 用于查询，不自动重跑不确定任务。",')
write(p, s)

zh_intro = '''**让通用 Agent 能够了解 DigitalMicrograph 中的数据、查看指定图像、正确调用常用的采集后分析操作，并取得带标定、可继续处理的结果。**

`mcp-dm` 是本机 Gatan DigitalMicrograph（DM）的工具接口，不是新的聊天产品或自动科研分析平台。Agent 负责理解目标、组合工具、选择方法和组织解释；本项目负责正确的数据对象、坐标、单位、操作结果和失败状态。只处理**采集后分析**，不控制相机、束流、样品台或光路。

## 项目边界

| 层次 | 本项目提供 | 不强制做的事 |
|---|---|---|
| 核心 MCP | 连接与状态、数据集、元数据、常用数值操作、裁剪和保标定导出 | 不要求捕获包、报告、Skill 或外部绘图库 |
| 图像与数据交接 | 有界二维副本、显示预览、源坐标映射 | 预览不参与数值计算；当前预览使用 `capture → preview` 两步 |
| 可选工作流示例 | 既有二维报告、结果查询与复跑脚本 | 不替用户决定科学方法，不是使用核心工具的前置条件 |

不追求封装所有 DM API，不承诺自动物相识别、应变、光谱定量或重构。4D-STEM 既有接口按已声明范围保留，近期不扩展。新功能先判断是否为可靠访问 DM 所必需，优先复用通用 Agent 与外部科学计算工具。

## 从一个具体操作开始

可以让 Agent：“列出已打开图像并读取这张图的标定”“对我指定的区域取剖面”“计算该区域 FFT 并返回频率”“导出一个不覆盖原图的新文件”。它应先确认真实后端与明确的 `image_id`，然后只调用需要的工具。显式 ID 固定对象，不冻结内容；多步分析需要固定像素时再捕获独立副本。

**不需要每次执行“捕获 → 统计 → 剖面 → FFT → 报告”。** 成功标准是连接可用、操作正确、结果可继续使用，而不是能否生成一篇报告。
'''
en_intro = '''**Let general-purpose agents inspect data in DigitalMicrograph, view selected images, correctly invoke common post-acquisition operations, and retrieve calibrated results they can use in further work.**

`mcp-dm` is a tool interface to a local Gatan DigitalMicrograph (DM) instance, not another chat application or an autonomous research platform. The agent chooses methods, composes tools and explains results. This project owns data targeting, coordinates, units, operation results and honest failure states. It is **post-acquisition only**, with no camera, beam, stage or microscope-optics controls.

## Project boundary

| Layer | What is provided | What is not required |
|---|---|---|
| Core MCP | Connection/status, datasets, metadata, common numerical operations, cropping and calibrated exports | No capture package, report, Skill or external plotting stack |
| Images and data handoff | Bounded 2D copies, display previews and source-coordinate mappings | Display pixels never become numerical inputs; viewing currently uses two calls: capture then preview |
| Optional workflow example | Existing 2D report, result inspection and replay helpers | Not a mandatory analysis pipeline or a scientific decision-maker |

The goal is not to wrap every DM API or promise crystallographic identification, strain, spectral quantification or reconstruction. Existing 4D-STEM interfaces retain their documented limits; expansion is deferred. Add capabilities needed for reliable access to DM, and reuse general-purpose agents and external scientific tools for the rest.

## Start with one useful operation

Ask an agent to list open images and inspect a selected calibration, take a profile through a specified region, compute an ROI FFT, or export a new calibrated file without overwriting the source. It should first verify the real backend and an explicit `image_id`, then invoke only the needed tools. An ID binds an object, not immutable pixels; capture a separate bounded copy when a multi-step task needs fixed data.

**Do not force every request through capture, statistics, profile, FFT and a report.** Success means a usable connection, correct operations and reusable results, not automatic report generation.
'''
for name, intro, heading in [('README.md', zh_intro, '## 当前验证范围'), ('README.en.md', en_intro, '## Validation scope')]:
    p = Path(name); text = p.read_text(encoding='utf-8')
    a = text.index('\n\n', text.index('AGENTS.md)')) + 2
    b = text.index('```text', a)
    text = text[:a] + intro + '\n' + text[b:]
    # Make the basic registration command independent of any optional interpreter.
    text = text.replace(' --env "DM_ANALYSIS_PYTHON=$analysisPython" -- $nodeExe', ' -- $nodeExe')
    if name == 'README.md':
        text = once(text, '若要使用二维预览和结果图，另建外部分析环境；不要改 GMS 管理的 Python/NumPy：', '核心连接、元数据、统计、剖面、FFT、裁剪、导出和捕获不需要以下外部环境。**仅在需要图像预览时**，另建 Python 3.10+ 环境；不要改 GMS 管理的 Python/NumPy：')
        text = once(text, '-m pip install -r requirements-analysis.txt', '-m pip install -r requirements-preview.txt')
        note = '\n预览环境只需 NumPy 和 Pillow。可选报告的 Matplotlib 在调用报告时才加载；状态查询与数值验证不依赖 Pillow/Matplotlib。预览用有界分块统计显示范围，只在目标分辨率上分配显示缓冲；缩略图可能遗漏细节，需要时显式提高分辨率或缩小捕获区域。\n'
        anchor = '$analysisPython = (Resolve-Path .\\.analysis-env\\Scripts\\python.exe).Path\n```'
        text = once(text, anchor, anchor + note)
        text = once(text, '## 二维任务 A：捕获、核对、分析与复跑', '## 可选示例：二维分析报告与复跑')
        anchor = '新注册 MCP 时可将外部分析解释器交给注册脚本：'
        text = once(text, anchor, '''以下是已有组合示例，不是核心 MCP 的默认工作流。只想看图时，到 `dm_2d_preview` 即可；只想取剖面或 FFT，也可直接使用单独工具。生成完整报告才需要额外安装：

```powershell
.\\.analysis-env\\Scripts\\python.exe -m pip install -r requirements-analysis.txt
```

''' + anchor)
        text = text.replace('| `dm_2d_analyze`、`dm_2d_result` | 对同一捕获数据计算并查询统计、剖面、完整 FFT 与分析包 |', '| `dm_2d_analyze`、`dm_2d_result` | 可选组合报告／独立状态查询；不作为其他工具的前置条件 |')
        text = text.replace('PNG 只用于核对，**不参与统计、剖面或 FFT，也不是科学数据导出**。', '缩略图按最近源像素中心采样，仅供查看，可能遗漏细节。PNG 只用于核对，**不参与统计、剖面或 FFT，也不是科学数据导出**。')
        text += '\n## 可选 Skill 与兼容性\n\n`skills/dm-2d-analysis/SKILL.md` 是可选使用指南。注册 MCP 不会自动安装它；可直接要求 Agent 阅读该文件。Codex 本地发现时，可将整个 `dm-2d-analysis` 目录复制到工作目录的 `.agents/skills/`，已有同名目录先检查，不覆盖。[官方 Skill 文档](https://developers.openai.com/codex/skills/)\n\n工具名称与 21 项目录保持兼容，没有新增模式开关。可选报告的剖面 `sampled_coordinates` 现为原图坐标，副本坐标在 `sampled_coordinates_local`；强度明确为原始像素值，强度标定只保留为元数据；`replay.py --verify` 失败或状态未知时非零退出。旧结果包保留自己的复跑代码，不原位改写。新变更的真实 DM/客户端验收仍须分别执行。范围决策与剩余限制见 [ROADMAP.md](ROADMAP.md) 和 [审计记录](docs/SCOPE_AUDIT.md)。\n'
    else:
        text = once(text, 'For 2D previews and result figures, install an external analysis environment. Do not change GMS-managed Python or NumPy:', 'Core connection, metadata, statistics, profiles, FFT, cropping, export and capture do not need the following environment. **Only for image previews**, create a separate Python 3.10+ environment. Do not change GMS-managed Python or NumPy:')
        text = once(text, '-m pip install -r requirements-analysis.txt', '-m pip install -r requirements-preview.txt')
        anchor = '$analysisPython = (Resolve-Path .\\.analysis-env\\Scripts\\python.exe).Path\n```'
        text = once(text, anchor, anchor + '\nPreview needs only NumPy and Pillow. Matplotlib loads only for optional report rendering; status inspection and numerical verification do not require Pillow/Matplotlib. Preview range calculation scans bounded tiles and display buffers use the requested output resolution, not the full source size. Thumbnails may miss small features; explicitly increase resolution or capture a smaller region when needed.\n')
        # Locate the optional section by the first heading containing task A.
        section = next(line for line in text.splitlines() if line.startswith('## ') and ('task A' in line or 'Task A' in line))
        text = once(text, section, '## Optional example: 2D report and replay')
        text = once(text, '## Optional example: 2D report and replay\n', '''## Optional example: 2D report and replay

This is an existing composition example, not the default MCP workflow. Stop after preview when viewing is enough; use individual measurement tools for simple tasks. Only report generation needs the additional plotting dependency:

```powershell
.\\.analysis-env\\Scripts\\python.exe -m pip install -r requirements-analysis.txt
```
''')
        text = text.replace('| `dm_2d_analyze`, `dm_2d_result` | Compute/query statistics, profile and full FFT from the same capture package |', '| `dm_2d_analyze`, `dm_2d_result` | Optional combined report / independent status query; not prerequisites for other tools |')
        text += '\n## Optional Skill and compatibility\n\n`skills/dm-2d-analysis/SKILL.md` is optional guidance, not installed by MCP registration. Ask an agent to read it directly, or copy the whole `dm-2d-analysis` directory into the working project\'s `.agents/skills/` for Codex local discovery. Inspect any existing same-name directory first; do not overwrite it. [Official Skill documentation](https://developers.openai.com/codex/skills/)\n\nTool names and the 21-entry catalog are retained; no new mode flag is required. In optional reports, `sampled_coordinates` now uses original-image coordinates and `sampled_coordinates_local` retains capture-relative coordinates. Intensities are explicitly raw pixel values; intensity calibration is retained as metadata, not applied. `replay.py --verify` exits nonzero for failed or unresolved verification. Existing bundles keep their own replay code and are not rewritten. New real-DM/client behavior still needs separate acceptance. See [ROADMAP.md](ROADMAP.md) and the [scope audit](docs/SCOPE_AUDIT.md).\n'
    # Historical evidence is explicitly distinct from this edit's acceptance.
    if name == 'README.md':
        text = text.replace('仓库只含合成测试。', '仓库分发的是合成数据测试与显式运行的宿主验收脚本，不含实验数据。上述真实宿主记录属于既有版本；本次范围/预览修改不继承其实机通过结论。')
        text = text.replace('Actions 仅手动触发，未将 CI 计入验证结论。', '常规 Actions 保持手动触发；隔离验证只证明合成行为，不证明真实 DM 可用。')
    else:
        text = text.replace('Only synthetic tests are included.', 'The repository distributes synthetic tests and explicitly invoked host-acceptance scripts, not experimental data. Real-host records above describe earlier behavior; they do not certify the current scope/preview changes.')
        text = text.replace('Actions is manual only, and hosted CI is not included in validation claims.', 'the normal Actions workflow remains manual. Isolated hosted checks provide synthetic evidence only, not real-DM acceptance.')
    write(p, text)

p = Path('AGENTS.md'); s = p.read_text(encoding='utf-8')
s = once(s, '## Architecture and ownership', '''## Product boundary

The core product is a reliable DM tool interface: inspect data, view images,
execute explicit post-acquisition operations and return calibrated results.
Do not require every task to capture, compute every operator or produce a report.
Reports/replay are optional examples retained for compatibility, not the core
acceptance gate. Keep native APIs, coordinate contracts, source protection and
honest errors. Do not add an agent framework, scheduler, report platform or
4D features as part of scope cleanup. Scope decisions are in docs/SCOPE_AUDIT.md.

## Architecture and ownership''')
s = s.replace('`tools/analysis_worker.py`: preview, result-package and replay logic', '`tools/analysis_worker.py`: lightweight preview/status plus optional report/replay helpers')
s = s.replace('`requirements-analysis.txt` is not for the GMS runtime.', '`requirements-preview.txt` adds NumPy/Pillow outside GMS; `requirements-analysis.txt` adds optional report rendering. Load plotting only for rendering. Neither belongs in GMS.')
s = s.replace('`skills/dm-2d-analysis/SKILL.md`: user-facing analysis workflow;', '`skills/dm-2d-analysis/SKILL.md`: optional tool-use guide, not a mandatory workflow;')
s = s.replace('hosted CI has not been verified and has no real DM or experimental data.', 'hosted runs cover synthetic behavior only and have no real DM or experimental data.')
s += '\nOptional worker contracts: profile sampled_coordinates are source coordinates; sampled_coordinates_local and its calibration are capture-relative. Report intensity is raw, not calibrated by a unit label alone. Verification failure/unresolved state must exit nonzero. Preview allocations must be bounded before source scans/display allocation; full-frame floating/RGB intermediates are prohibited. No automatic Skill installation or overwriting user settings.\n'
write(p, s)
