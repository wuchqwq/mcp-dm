"""Prepare a narrowly reviewed native-core merge; never install or start DM."""
from pathlib import Path
import subprocess

BASE = '3c9715c388e0a109d468de2dbeee2c8b0d8d5d67'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Unexpected patch anchor: ' + old[:100])
    return text.replace(old, new, 1)

def save(path, text):
    Path(path).write_text(text, encoding='utf-8', newline='\n')

p = Path('server.mjs')
s = p.read_text(encoding='utf-8')
a, b = s.index('const nativeTools = ['), s.index('\nasync function callNativeTool')
section = s[a:b]
section = replace_once(section, '}, ["image_id", "rect"]),', '}, ["image_id", "rect", "request_id"]),')
section = replace_once(section, '实验性指定构建的原生二维独立副本裁剪；', '实验性指定构建的原生二维独立副本裁剪；必须在调用前生成并保存 request_id；')
s = s[:a] + section + s[b:]
s = replace_once(s, '可在提交前指定 request_id，以便取消后仍能查询；若取消前未保存 ID，将无法保证恢复。', '原生 dm_crop 必须在提交前指定并保存 request_id；只读工具仍可省略。取消或断连后只能在同一存活 session 查询原 ID。')
save(p, s)

p = Path('tests/native-mcp.test.mjs')
s = p.read_text(encoding='utf-8')
s = replace_once(s, '    assert.match(crop.description, /不创建可见 DM 文档/);', '''    assert.match(crop.description, /不创建可见 DM 文档/);
    assert.deepEqual(crop.inputSchema.required, ["image_id", "rect", "request_id"]);
    for (const request_id of [undefined, "", "bad id", "x".repeat(65), 123]) {
      const args = {image_id: 77, rect};
      if (request_id !== undefined) args.request_id = request_id;
      assert.equal((await client.tool("dm_crop", args)).error?.code, -32602);
    }
    assert.equal(host.requests.length, 0, "missing/invalid recovery IDs never dispatch");''')
s = replace_once(s, '    ]) assert.equal((await client.tool("dm_crop", args)).error?.code, -32602, JSON.stringify(args));', '    ]) assert.equal((await client.tool("dm_crop", {...args, request_id: "invalid-crop"})).error?.code, -32602, JSON.stringify(args));')
save(p, s)

zh = ('\n**本次部分合并边界：**主线接纳已审阅的 `3c9715c` 基础原生后端，并要求原生 `dm_crop` 在提交前提供并保存 `request_id`。默认 v0.6 后端不变。后续 Show/可见文档交付、原始均值标定策略调整及最新试用验收仍留在 `feature/native-bridge-mvp`，其 HOLD/NOT_QUALIFIED 不因本次合并解除；详见 [合并范围](docs/NATIVE_MERGE_SCOPE.md)。\n')
en = ('\n**Partial merge boundary:** main integrates the reviewed `3c9715c` native core and now requires a caller-saved `request_id` for native `dm_crop`. The default v0.6 backend is unchanged. Later Show/document delivery, raw-mean calibration policy changes and current trial acceptance remain on `feature/native-bridge-mvp`; their HOLD/NOT_QUALIFIED status is not cleared. See [merge scope](docs/NATIVE_MERGE_SCOPE.md).\n')
for path, anchor, addition in [('README.md', '## 可选原生 C++ 实验后端\n', zh), ('README.en.md', '## Optional native C++ experiment\n', en)]:
    s = Path(path).read_text(encoding='utf-8')
    if path.endswith('.en.md') and anchor not in s:
        headings = [line for line in s.splitlines() if line.startswith('## ') and 'native' in line.lower()]
        if len(headings) != 1:
            raise RuntimeError('Ambiguous English native section: ' + repr(headings))
        anchor = headings[0] + '\n'
    save(path, replace_once(s, anchor, anchor + addition))

for path in ['experiments/native-bridge/mvp/README.md', 'experiments/native-bridge/mvp/HANDOFF.md']:
    s = Path(path).read_text(encoding='utf-8')
    first, rest = s.split('\n', 1)
    addition = ('\nMainline integration note: this snapshot retains the reviewed `3c9715c` native implementation. '
                'Native `dm_crop` now requires the caller to save and supply `request_id` before dispatch; '
                'read-only tool IDs remain optional. Later SHOW delivery and raw-mean policy changes stay '
                'on the feature branch until their separate acceptance is complete. '
                'See [merge scope](../../../docs/NATIVE_MERGE_SCOPE.md).\n')
    save(path, first + '\n' + addition + rest)

save('docs/NATIVE_MERGE_SCOPE.md', '''# Native core partial integration

## Accepted scope

Main integrates the previously reviewed native MVP snapshot `3c9715c` as an
**explicitly selected experiment**, not as a stable replacement for v0.6.
The Python backend and its existing 21-tool catalog remain the default.
The native catalog contains status, datasets, raw native mean, result query
and a plugin-retained crop. The native adapter retains its exact build gate,
ASCII-qualified scope, idle-host/serialized-operation requirement and existing
bounded ownership rules. No native runtime or ABI code is changed by this
integration follow-up.

One facade-only safeguard is added: native `dm_crop` requires a caller-saved
`request_id` before any submission. Missing/invalid IDs fail before dispatch.
An old ID can only recover a result in its original live session, not after
STOP, host restart or a new session. Read-only tools keep optional IDs.

## Deliberately not integrated

The later commits through `6837bab` remain on `feature/native-bridge-mvp`:
visible document SHOW and lifetime handoff, relaxed spatial-calibration policy
for raw mean, the latest client-trial scripts, cross-client Windows E2E/fault
injection additions, and the latest Unicode investigation. They form one
uncompleted trial revision and must not inherit this baseline's acceptance.
Do not cherry-pick those tests alone: they depend on the later implementation.

The current feature trial remains HOLD. Its pending desktop/document checks,
independent pixel/source checks, post-STOP ownership, final document-reference
release, normal removal and actual WorkBuddy use must be completed separately.
The last reported local state was stopped experimental IPC with the test DM
and DLL still loaded; this document does not assert the current machine state.

Before further host acceptance, fix the reviewed trial-oracle gaps: bind the
actual oracle process PID, validate the saved STOP request identity, and
preserve bytes/str distinctions in the Unicode diagnostic. Do not retrofit
old PASS evidence or guess an encoding conversion.

## Validation boundary

The integration follow-up runs isolated Python, Node and mock regression;
Windows synthetic native tests are recorded separately when run. No genuine
DM process, installation or scientific data is accessed here. Historical
real-host evidence belongs to the unchanged baseline implementation, not to
new operators or broader compatibility. No Release/tag is created.

## Continuing development

Keep the existing feature branch; do not reset or force-push it to this
snapshot. Fetch main and reconcile the small request-ID/doc changes by a
normal merge when needed. Preserve newer feature code and its HOLD notes.
Unlocking the desktop permits inspection; it is not by itself acceptance.
''')
print('Prepared bounded native-core integration; no vendor code, installation or host access.')
