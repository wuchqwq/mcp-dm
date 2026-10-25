# mcp-dm scope and roadmap

## 当前优先级：衍射标定与晶格间距

维护者已明确：日常任务是衍射图标定、晶面间距/夹角测量、FCC/BCC 等候选索引，以及 HRTEM/STEM-ADF 局部晶格与候选物相比较。画线、直方图和显示是基础能力，不是产品终点。

**下一阶段以 [衍射与晶格测量任务](docs/DIFFRACTION_NEXT_STAGE.md) 为准。** 这是一项开发计划，不是已有自动索引或自动判相能力。旧的 [DM 原生功能对照](docs/NATIVE_NEXT_STAGE.md) 保留为接口参考，不再决定当前开发排序。

## Goal and architecture

Let a general-purpose agent inspect DM data, view selected images, invoke common post-acquisition operations correctly and retrieve calibrated results for further work. This repository is a tool interface, not a scientific decision-maker or a new agent application.

An operation labelled DM-native must run through its qualified DM interface. The plugin handles identity, calibration, ownership and delivery, not a second analysis engine. A missing native function is not permission for a hidden Python fallback.

Separately and explicitly, a small optional external crystallographic companion may consume exported numerical data, coordinates and calibration for deterministic geometry and candidate matching. Record that computation as external, preserve its inputs and parameters, and do not claim it is DIFPack or DM-native. The companion is not part of GMS's managed Python environment. Existing v0.6 behavior remains compatible.

## Three next deliverables

An initial external companion now implements bounded automatic selected-point
measurement and joint FCC/BCC/HCP candidates with ASE CIF/reciprocal-cell support;
see [the runnable workflow](docs/CRYSTALLOGRAPHY_WORKFLOW.md). Automatic centres
stop on ambiguity, absolute spacing requires calibration, and source/model
provenance stays explicit. Synthetic checks do not qualify experimental inputs
or an ordinary MCP client. The next scientific priorities are representative
diffraction/fringe comparisons, localization uncertainty and calibrated reference
validation, rather than more isolated image tools.

1. **Measured diffraction geometry.** Confirm image/ROI, calibration, centre and selected spots. Return reciprocal vectors, d spacings when calibrated, distance ratios and angles, with a position overlay and traceable units. Manual source-coordinate inputs are sufficient initially; no new generic ROI-creation ABI is required.
2. **Bounded cubic indexing candidates.** Jointly compare multiple reflections against FCC/BCC candidates, a shared lattice parameter and zone-axis constraints. Return alternatives, residuals and unmatched observations; geometry alone may remain ambiguous. A Bravais lattice candidate is not a chemical phase identification.
3. **Local high-resolution workflow and actual Agent trial.** Use supported DM FFT on explicit HRTEM/ADF regions, preserve the mathematical frequency grid and compare selected frequencies against specified candidates. Test the complete task with an ordinary Agent rather than using isolated profiles/histograms as the final acceptance objective.

The detailed input contracts, uncertainty boundaries, references and acceptance cases are in [DIFFRACTION_NEXT_STAGE.md](docs/DIFFRACTION_NEXT_STAGE.md). Do not silently recalibrate an unknown sample to fit a proposed phase. A user-supplied known standard and candidate fitting are distinct stages.

## Existing capabilities to retain

The default v0.6 Python backend remains unchanged. The opt-in native integration exposes nineteen tools with per-operation limits: explicit data/GUI identity, summaries, crop, bounded arithmetic/FFT/filters, profile and histogram results, previews, one-dimensional document delivery, result recovery/release and numerical handoff.

Only the exact Windows x64 GMS 3.53.4137.0 adapter and pinned modules have limited qualification. Inspect [HANDOFF](experiments/native-bridge/mvp/HANDOFF.md), [RESULTS](experiments/native-bridge/RESULTS.md) and [adapter restrictions](experiments/native-bridge/mvp/ADAPTERS.md) before use. Native SHOW does not prove active-tab visibility or model viewing. NPY handoff is not native SaveAs. Historical FAIL and NOT_TESTED scopes remain intact.

Keep source data read-only, coordinates explicit, original-ID recovery, calibrated values and no-overwrite exports. Live image IDs do not freeze pixels. Display PNGs are not numerical input. Never force-close DM or replace a loaded DLL. Only one authorized task owns a real test host at a time; code analysis can use separate worktrees.

## Validation without expanding the platform

Independent numerical tests, protocol substitutes, actual DM execution and model-client trials are distinct evidence. Match testing to the changed code and ABI risk, then run full regression on a frozen integration candidate. A passing focused rerun does not erase a failed complete run. A known numerical limitation is not fixed by changing its recorded tolerance.

A new function is justified when it removes a concrete obstacle in the diffraction/lattice workflow. Track correct task completion, manual intervention, result traceability and the actual steps saved. Tool counts and synthetic assertion counts are not the product metric.

## Deferred, not silently completed

Histogram bar styling, generic window/workspace management, exhaustive profile geometry, automatic compatibility generation, native 4D-STEM expansion, hardware control, strain/EDS/EELS quantification, unrestricted phase identification or phase fractions, and a new report/chat/agent platform are not current milestones. Only revisit a specific dependency when it blocks the active crystallographic task.

Preserve the compatibility-generator [Draft RFC #3](https://github.com/wuchqwq/mcp-dm/pull/3) as a future proposal. Local loopback is not authentication; retain existing data-sharing and filesystem limits. More historical native milestones remain in [RESULTS](experiments/native-bridge/RESULTS.md) and Git history rather than being presented as current pending sessions here.
