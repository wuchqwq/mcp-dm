# mcp-dm scope and roadmap

## 当前优先级：交互式显微分析，不追求单轮自动判相

用户日常工作包括在 DM 中观察/调整 HRTEM、STEM-ADF 和衍射图像，生成清晰的局部 FFT/衍射出图，测间距与方向，并逐轮修正标注、孪晶/层错/多相等**候选**解释。研究者希望 Agent 能**真正取回并看到 DM 图像、做非破坏式出图、标注并继续对话**。ROI、画线、直方图和索引均是基础能力，不是独立终点。

**当前主要产品路线为[交互式显微分析工作流](docs/INTERACTIVE_MICROSCOPY_ROADMAP.md)。** [衍射与晶格测量](docs/DIFFRACTION_NEXT_STAGE.md)是其中的定量分析子任务；原生 API 对照仍见[接口参考](docs/NATIVE_NEXT_STAGE.md)。这些文档规定下一阶段工作方向，不意味着相关功能已经在 main 完成。PR #12/#13 的 ASE 伴随工具仍须以当时实际 GitHub 合并状态为准。

## Goal and architecture

Let a general-purpose agent inspect DM data, view selected images, invoke common post-acquisition operations correctly and retrieve calibrated results for further work. This repository is a tool interface, not a scientific decision-maker or a new agent application.

An operation labelled DM-native must run through its qualified DM interface. The plugin handles identity, calibration, ownership and delivery, not a second analysis engine. A missing native function is not permission for a hidden Python fallback.

Separately and explicitly, a small optional external crystallographic companion may consume exported numerical data, coordinates and calibration for deterministic geometry and candidate matching. Record that computation as external, preserve its inputs and parameters, and do not claim it is DIFPack or DM-native. The companion is not part of GMS's managed Python environment. Existing v0.6 behavior remains compatible.

## Three next deliverables

1. **Image return and non-destructive presentation.** In an actual ordinary Agent client, retrieve a precisely identified DM image/ROI as a viewable preview; retain the separate lossless numeric capture/calibration. Support reversible contrast, gamma and curve recipes and at least one user-requested revision. A PNG file alone does not prove the model actually viewed the image.
2. **FFT image, independent overlays and revision.** Reuse the qualified native FFT and its scientific frequency grid, add presentation-only controls and editable spot/vector/streak/region annotations, then export both annotated PNG/SVG and unmodified numerical data plus the recipe. The user can correct a peak or ROI and regenerate only affected results. Diffuse streaks and multiple orientations must not be forced into single-crystal indexing.
3. **Evidence-led crystallography / domains / defects.** Apply existing or separately reviewed ASE/SciPy companion measurements to user-selected regions; compare possible reflection sets, lattice spacings, relative orientations and twin/fault hypotheses without claiming unique phase/defect identification. Validate over multiple turns with a real Agent and a known-standard diffraction/manual DM comparison. Ask for corrections only where necessary.

Full UX/data-contract, library options, safe transformation boundaries and staged acceptance are in [INTERACTIVE_MICROSCOPY_ROADMAP.md](docs/INTERACTIVE_MICROSCOPY_ROADMAP.md). [DIFFRACTION_NEXT_STAGE.md](docs/DIFFRACTION_NEXT_STAGE.md) retains the diffraction-specific measurement rules: no secret calibration fit to force a candidate phase and no absolute d without independent scale.

## Existing capabilities to retain

The default v0.6 Python backend remains unchanged. The opt-in native integration exposes nineteen tools with per-operation limits: explicit data/GUI identity, summaries, crop, bounded arithmetic/FFT/filters, profile and histogram results, previews, one-dimensional document delivery, result recovery/release and numerical handoff.

Only the exact Windows x64 GMS 3.53.4137.0 adapter and pinned modules have limited qualification. Inspect [HANDOFF](experiments/native-bridge/mvp/HANDOFF.md), [RESULTS](experiments/native-bridge/RESULTS.md) and [adapter restrictions](experiments/native-bridge/mvp/ADAPTERS.md) before use. Native SHOW does not prove active-tab visibility or model viewing. NPY handoff is not native SaveAs. Historical FAIL and NOT_TESTED scopes remain intact.

Keep source data read-only, coordinates explicit, original-ID recovery, calibrated values and no-overwrite exports. Live image IDs do not freeze pixels. Display PNGs are not numerical input. Never force-close DM or replace a loaded DLL. Only one authorized task owns a real test host at a time; code analysis can use separate worktrees.

## Validation without expanding the platform

Independent numerical tests, protocol substitutes, actual DM execution and model-client trials are distinct evidence. Match testing to the changed code and ABI risk, then run full regression on a frozen integration candidate. A passing focused rerun does not erase a failed complete run. A known numerical limitation is not fixed by changing its recorded tolerance.

A new function is justified when it removes a concrete obstacle in the diffraction/lattice workflow. Track correct task completion, manual intervention, result traceability and the actual steps saved. Tool counts and synthetic assertion counts are not the product metric.

## Deferred, not silently completed

Histogram bar styling, speculative private window/workspace ABI, exhaustive profile geometry, automatic compatibility generation, native 4D-STEM expansion, hardware control, strain/EDS/EELS quantification, unrestricted phase identification or phase fractions, and a new report/chat/agent platform are not current milestones. Start with existing Agent image surfaces and simple editable artifacts; add a separate viewer only if a tested client cannot support necessary image/annotation interactions. Only revisit an ABI or dependency when it blocks the active microscopy task.

Preserve the compatibility-generator [Draft RFC #3](https://github.com/wuchqwq/mcp-dm/pull/3) as a future proposal. Local loopback is not authentication; retain existing data-sharing and filesystem limits. More historical native milestones remain in [RESULTS](experiments/native-bridge/RESULTS.md) and Git history rather than being presented as current pending sessions here.
