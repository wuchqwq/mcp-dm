"""One-shot repair builder used only on the isolated validation branch."""
from pathlib import Path
import ast
import hashlib


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Expected exactly one patch anchor: %r" % old[:100])
    return text.replace(old, new, 1)


path = Path('bridge/dm_bridge.py')
raw = path.read_bytes()
assert hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() == 'f501e387b2b2f324425f1a24186be5a1120c671d', 'Unexpected bridge source; do not patch another revision'
s = raw.decode('utf-8')
s = replace_once(s, 'import math\n', 'import math\nimport numbers\n')
s = replace_once(s, 'import traceback\n', 'import traceback\nimport uuid\n')
start, end = s.index('def _rect(a, rect):'), s.index('\ndef _classify(')
s = s[:start] + '''def _rect_bounds(shape, rect):
    """Validate a half-open 2D ROI without reading pixels or changing input.

    Only None means the full frame. Explicit empty, noninteger, degenerate or
    out-of-bounds rectangles fail; there is no rounding or clipping mode.
    """
    if len(shape) != 2:
        raise ValueError("rect requires a two-dimensional image")
    h, w = [int(v) for v in shape]
    if h <= 0 or w <= 0:
        raise ValueError("rect requires a nonempty image")
    if rect is None:
        return [0, 0, w, h]
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError("rect must be [x0,y0,x1,y1] with exclusive upper bounds")
    if any(isinstance(v, bool) or not isinstance(v, numbers.Integral) for v in rect):
        raise ValueError("rect coordinates must be integers, not booleans or rounded values")
    x0, y0, x1, y1 = [int(v) for v in rect]
    if x1 <= x0 or y1 <= y0:
        raise ValueError("rect must have positive width and height")
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("OUT_OF_BOUNDS: rect %r exceeds image [width=%d,height=%d]; no clipping"
                         % ([x0, y0, x1, y1], w, h))
    return [x0, y0, x1, y1]


def _rect(a, rect):
    """Return the strictly validated view and its effective source bounds."""
    used = _rect_bounds(a.shape, rect)
    x0, y0, x1, y1 = used
    return a[y0:y1, x0:x1], used


''' + s[end + 1:]
# Preserve rect for existing consumers, and distinguish omitted selection from
# an explicit request. This updates both real and mock statistics / FFT paths.
s = s.replace('"rect": used, "shape": list(sub.shape),',
              '"rect": used, "shape": list(sub.shape),\n            "requested_rect": list(rect) if rect is not None else None, "effective_rect": list(used),')
s = s.replace('right/bottom excluded; rounded then clamped', 'right/bottom excluded; strict bounds, no rounding or clipping')
# Mock crop must obey the same contract before creating a synthetic image.
old = '''        rec = self._images[int(image_id or 1000)]
        x0, y0, x1, y1 = [int(round(float(v))) for v in rect]
        new_id = max(self._images.keys()) + 1'''
new = '''        rec = self._images[int(image_id or 1000)]
        if rect is None:
            raise ValueError("crop requires an explicit rect")
        x0, y0, x1, y1 = _rect_bounds((rec["height"], rec["width"]), rect)
        new_id = max(self._images.keys()) + 1'''
s = replace_once(s, old, new)
s = replace_once(s, '''        return {"source_id": rec["id"], "requested_rect": [x0, y0, x1, y1],
''', '''        return {"source_id": rec["id"], "requested_rect": list(rect),
                "effective_rect": [x0, y0, x1, y1],
''')
# Keep native ImageClone and its existing metadata behavior. A private,
# per-operation nonce binds the returned image to this exact script invocation;
# a user-supplied display name is never used for ownership or fallback selection.
start = s.index('    def crop(self, image_id, rect, name):', s.index('class DmBackend'))
end = s.index('    def run_script(', start)
crop = s[start:end]
a = crop.index('        if not rect or len(rect) != 4:')
b = crop.index('        label = ', a)
crop = crop[:a] + '''        if rect is None:
            raise ValueError("crop requires an explicit rect")
        x0, y0, x1, y1 = _rect_bounds((dims[1], dims[0]), rect)
''' + crop[b:]
crop = replace_once(crop, '        sid = int(img.GetID())\n', '''        sid = int(img.GetID())
        operation_token = "dm_mcp_crop_" + uuid.uuid4().hex
''')
crop = replace_once(crop, ') % (sid, y0, x0, y1, x1, label)', ') % (sid, y0, x0, y1, x1, operation_token)')
a = crop.index('        made = [i for _, _, _, i in self._iter_images()')
b = crop.index('        nw, nh = ', a)
crop = crop[:a] + '''        made = [i for _, _, _, i in self._iter_images()
                if int(i.GetID()) not in before and int(i.GetID()) != sid
                and self._safe(i.GetName) == operation_token]
        if len(made) != 1:
            raise RuntimeError(
                "CROP_RESULT_UNVERIFIED: expected exactly one new image carrying this "
                "operation token, found %d. No existing/unrelated image was selected "
                "or recalibrated; inspect DM Results. Do not automatically retry." % len(made)
            )
        target = made[0]
''' + crop[b:]
crop = replace_once(crop, '        source_file = self._source_files.get(sid)\n', '''        # Apply the human-readable name only after ownership and shape checks.
        target.SetName(label)
        source_file = self._source_files.get(sid)
''')
crop = replace_once(crop, '            "requested_rect": [x0, y0, x1, y1],\n', '''            "requested_rect": list(rect),
            "effective_rect": [x0, y0, x1, y1],
            "result_identity": {"method": "per-operation nonce and new image id",
                                "operation_token": operation_token},
''')
crop = replace_once(crop, '        ImageClone is required to detach the result from its parent.\n', '''        ImageClone is required to detach the result from its parent. A fresh
        internal image label is a one-shot result handoff, not a user display
        name; missing or duplicate handoffs fail without touching other images.
''')
s = s[:start] + crop + s[end:]
ast.parse(s, feature_version=(3, 7))
changes = {'bridge/dm_bridge.py': s}
# Extend the fake only with the native SetName method used by the existing API.
p = Path('tests/test_analysis.py')
s = p.read_text(encoding='utf-8')
s = replace_once(s, '''    def GetName(self):
        return self.name

    def GetTagGroup(self):''', '''    def GetName(self):
        return self.name

    def SetName(self, name):
        self.name = name

    def GetTagGroup(self):''')
s = replace_once(s, '    def test_single_pixel_and_clamped_crop(self):', '    def test_single_pixel_and_rejected_out_of_bounds_crop(self):')
s = replace_once(s, '''        result = backend.crop(1, [-2, -3, 4, 5], "clamped")
        self.assertEqual(result["requested_rect"], [0, 0, 4, 5])
        self.assertEqual(result["new_image"]["shape"], [5, 4])''', '''        count = len(backend.DM.images)
        with self.assertRaisesRegex(ValueError, "OUT_OF_BOUNDS"):
            backend.crop(1, [-2, -3, 4, 5], "must_fail")
        self.assertEqual(len(backend.DM.images), count)''')
changes[str(p)] = s
# Communicate the strict contract to tool consumers without changing schemas.
p = Path('server.mjs'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '像素矩形 [x0, y0, x1, y1]，右下边界不包含；省略则整幅', '像素矩形 [x0, y0, x1, y1]，右下边界不包含；必须完整位于图内，不舍入或裁夹；省略则整幅')
s = replace_once(s, '像素矩形 [x0, y0, x1, y1]" },', '像素矩形 [x0, y0, x1, y1]，必须完整位于图内，不舍入或裁夹" },')
changes[str(p)] = s
p = Path('README.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '- 二维矩形为零基', '''- **二维 ROI 契约变化**：统计、FFT 和裁剪严格拒绝越界、空区域及非整数坐标，不再舍入或自动裁夹。省略 `rect` 仅对统计/FFT 表示整幅；裁剪仍要求显式选区。`requested_rect` 保留请求（省略时为 null），`effective_rect` 给出实际区域；旧 `rect` 字段继续保留。
- 裁剪继续使用原生 `ImageClone`，通过每次操作独有的内部令牌和新图像 ID 认领结果；不再按用户显示名称或“最新窗口”回退。缺失或重复令牌时明确失败，不修改无关图像标定。此修复有合成回归覆盖，**修复后的真实 DM 裁剪仍需重新验收（NOT_TESTED）**；它不构成并发像素快照或安全沙箱。
- 二维矩形为零基''')
changes[str(p)] = s
p = Path('README.en.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '- Rectangles are zero-based', '''- **2D ROI contract change:** statistics, FFT and cropping reject out-of-bounds, empty and noninteger rectangles. No rounding or implicit clipping is performed. Omitted `rect` means the full image only for statistics/FFT; crop requires an explicit ROI. `requested_rect` preserves the request (null when omitted), `effective_rect` records the used bounds, and the legacy `rect` result remains available.
- Crop keeps native `ImageClone` and identifies its result by a fresh per-operation internal token and a new image ID, never a user display name or newest-window fallback. Missing/duplicate tokens fail without recalibrating unrelated images. Synthetic regressions cover this repair; **real-DM acceptance of the repaired crop is NOT_TESTED**. This is not an atomic pixel snapshot or a security sandbox.
- Rectangles are zero-based''')
changes[str(p)] = s
p = Path('AGENTS.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '5. Rectangle/bounds upper endpoints are exclusive.', '5. Rectangle/bounds upper endpoints are exclusive. Two-dimensional ROI tools reject invalid types and out-of-bounds rectangles; never reintroduce rounding/clipping or crop-result selection by recency/user names. The crop result handoff requires exactly one new image with the per-operation nonce.')
changes[str(p)] = s
for name, text in changes.items():
    with open(name, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print('Patched', name)
