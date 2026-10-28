# Microscopy Core — coding boundaries

This repository is the DM-free scientific provider on Windows/macOS/Linux.
Use the existing image/structure tools and scientific journals; do not build
another Agent framework or duplicate numerical engines. No import or install
dependency on mcp-dm, DigitalMicrograph, Gatan SDKs, native DLLs or host scripts.

Keep original data read-only, dtype/axes/signed scales explicit, scientific
arrays distinct from PNG display and annotation layers, calibrated/DC-referenced
measurements traceable, and assumptions distinct from confirmed observations.
Do not infer physical units, image domains, chemical phases or resolved depth.
The saved native-capture verifier validates files only; it does not connect to DM.

Preserve original request IDs and query outcomes after cancellation/timeout;
never replay an unknown side effect. Keep provider journals authoritative and
AnalysisContext reference-only with CAS revisions. Do not alter old source IDs,
hashes, namespaces or worker validation tolerances to make migration pass.

Run affected tests plus `npm test`; with the independent Python environment,
run `npm run test:science`. Optional structure packages and actual browser/model/
Mac/Windows/DM evidence are separate scopes. No real-host qualification follows
from a successful catalog or synthetic test. Never use private specimen data,
credentials or vendor binaries as fixtures. Do not publish or merge without
owner authorization.
