"""Revision-guarded builder, confined to the temporary validation branch."""
import ast
import hashlib
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected exactly one patch anchor: %r' % old[:120])
    return text.replace(old, new, 1)


p = Path('bridge/dm_bridge.py')
raw = p.read_bytes()
assert hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() == '7b54430b5ce04938689088005971b494f95e6088', 'Unexpected bridge revision'
s = raw.decode('utf-8')
parser = '''def _metadata_prefix_parts(prefix):
    """JSON Pointer tokens; also accept the documented slashless shorthand.

    None/empty selects the root; '/' selects a literal empty label. Do not
    strip whitespace or trailing separators, which can be actual tag labels.
    """
    if prefix is None or prefix == "":
        return []
    if not isinstance(prefix, str):
        raise ValueError("metadata prefix must be a string")
    if len(prefix.encode("utf-8")) > MAX_TAG_VALUE_BYTES:
        raise ValueError("metadata prefix exceeds the byte limit")
    raw = (prefix[1:] if prefix.startswith("/") else prefix).split("/")
    if len(raw) > 64:
        raise ValueError("metadata prefix exceeds 64 path segments")
    for part in raw:
        if any(c == "~" and (i + 1 == len(part) or part[i + 1] not in "01")
               for i, c in enumerate(part)):
            raise ValueError("metadata prefix has an invalid JSON Pointer escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in raw]


'''
s = replace_once(s, 'def _classify(shape, ndim):', parser + 'def _classify(shape, ndim):')
# Mock fixtures honor path/depth semantics without claiming native API coverage.
start = s.index('    def metadata(self, image_id, max_depth, prefix):', s.index('class MockBackend'))
s = s[:start] + s[start:].replace('    def metadata(self, image_id, max_depth, prefix):', '    def _metadata_fixture(self, image_id, max_depth, prefix):', 1)
mock_method = '''    def metadata(self, image_id, max_depth, prefix):
        parts = _metadata_prefix_parts(prefix)
        result = self._metadata_fixture(image_id, max_depth, None)
        max_depth = max(0, min(int(max_depth), 64))
        path = ""
        issues = []
        status = "found"
        node = result["tags"]
        for part in parts:
            path += "/" + part.replace("~", "~0").replace("/", "~1")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif (isinstance(node, list) and part.isascii() and part.isdigit()
                  and (part == "0" or not part.startswith("0"))
                  and len(part) <= len(str(len(node))) and int(part) < len(node)):
                node = node[int(part)]
            else:
                status = "not_found"
                issues.append({"path": path, "reason": "path_not_found"})
                node = None
                break
        remaining = [MAX_TAG_NODES]
        def visit(value, depth, current):
            if not isinstance(value, (dict, list)):
                return value
            if depth > max_depth:
                issues.append({"path": current or "/", "reason": "depth_limit"})
                return {"__unavailable__": "depth_limit"}
            is_dict = isinstance(value, dict)
            out = {} if is_dict else []
            for key, child in (value.items() if is_dict else enumerate(value)):
                if remaining[0] <= 0:
                    issues.append({"path": current or "/", "reason": "node_budget"})
                    break
                remaining[0] -= 1
                child_path = current + "/" + str(key).replace("~", "~0").replace("/", "~1")
                converted = visit(child, depth + 1, child_path)
                if is_dict:
                    out[key] = converted
                else:
                    out.append(converted)
            return out
        canonical = "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)
        result.update({"tags": visit(node, 0, canonical) if status == "found" else None,
                       "prefix": canonical, "path_status": status,
                       "complete": status == "found" and not issues, "issues": issues,
                       "complete_scope": "requested subtree", "synthetic": True})
        if status == "not_found":
            result["error"] = "tag path not found: %s" % canonical
        return result

'''
s = s[:start] + mock_method + s[start:]
# Share descriptor-directed reads between full traversal and path navigation.
entry = '''    def _metadata_read_entry(self, tg, index, path, raw_label=None, label_encoding=None):
        record = {"dm_type": None, "tag_size": None}
        self._tag_types[path] = record
        if isinstance(raw_label, bytes):
            record.update({"label_bytes_hex": raw_label.hex(), "label_encoding": label_encoding})
        try:
            length = int(tg.GetTagTypeLength(index))
            if not 0 <= length <= 64:
                return self._metadata_issue(path, "type_descriptor_limit", length), False
            descriptor = [int(tg.GetTagType(index, k)) for k in range(length)]
            record["dm_type"] = descriptor
        except Exception as exc:
            return self._metadata_issue(path, "type_read_error", exc), False
        try:
            size = tg.GetTagSize(index)
            if size is None or size < 0:
                raise ValueError("unknown or negative native tag size")
            record["tag_size"] = size
        except Exception as exc:
            return self._metadata_issue(path, "tag_size_read_error", exc), False
        if size > MAX_TAG_VALUE_BYTES and descriptor[:1] != [0]:
            return self._metadata_issue(path, "tag_size_limit", size), False
        try:
            # Never guess a getter after failed/truncated type introspection.
            return self._read_tag_typed(tg, index, descriptor, path), True
        except NotImplementedError as exc:
            return self._metadata_issue(path, "unsupported_dm_type", exc), False
        except Exception as exc:
            return self._metadata_issue(path, "read_error", exc), False

    def _metadata_locate(self, node, parts):
        """Read only the selected ancestry; scan sibling labels, not values.

        Lookup has its own bounded budget. An unreadable/ambiguous directory
        cannot establish absence, even when another label matches the request.
        """
        path = ""
        for step, part in enumerate(parts):
            child_path = self._tag_path(path, part)
            if not (hasattr(node, "CountTags") and hasattr(node, "IsList")):
                return self._metadata_issue(child_path, "not_a_container"), "not_found"
            try:
                count = int(node.CountTags())
                is_list = bool(node.IsList())
                if count < 0:
                    raise ValueError("negative tag count")
            except Exception as exc:
                return self._metadata_issue(path, "read_error", exc), "unavailable"
            raw_label = label_encoding = None
            if is_list:
                if not (part.isascii() and part.isdigit()
                        and (part == "0" or not part.startswith("0"))
                        and len(part) <= len(str(count)) and int(part) < count):
                    return self._metadata_issue(child_path, "path_not_found"), "not_found"
                if self._lookup_budget <= 0:
                    return self._metadata_issue(child_path, "lookup_budget", MAX_TAG_NODES), "unavailable"
                self._lookup_budget -= 1
                index = int(part)
            else:
                index = None
                for i in range(count):
                    if self._lookup_budget <= 0:
                        return self._metadata_issue(child_path, "lookup_budget", MAX_TAG_NODES), "unavailable"
                    self._lookup_budget -= 1
                    try:
                        candidate = node.GetTagLabel(i)
                        label, encoding = self._decode_dm_text(candidate)
                    except Exception as exc:
                        return self._metadata_issue(child_path, "label_read_error", exc), "unavailable"
                    if label == part:
                        if index is not None:
                            return self._metadata_issue(child_path, "duplicate_label", i), "unavailable"
                        index, raw_label, label_encoding = i, candidate, encoding
                if index is None:
                    return self._metadata_issue(child_path, "path_not_found"), "not_found"
            value, readable = self._metadata_read_entry(node, index, child_path, raw_label, label_encoding)
            if not readable:
                # The final label exists, even when its payload cannot be read.
                return value, "found" if step == len(parts) - 1 else "unavailable"
            node, path = value, child_path
        return node, "found"

'''
s = replace_once(s, '    def _walk_tags(self, tg, depth, max_depth, path=""):', entry + '    def _walk_tags(self, tg, depth, max_depth, path=""):')
start = s.index('            descriptor = []', s.index('    def _walk_tags('))
end = s.index('            if is_list:\n                out.append(child)', start)
s = s[:start] + '''            value, readable = self._metadata_read_entry(tg, i, child_path, raw_label, label_encoding)
            child = self._metadata_value(value, depth + 1, max_depth, child_path) if readable else value
''' + s[end:]
start = s.index('    def metadata(self, image_id, max_depth, prefix):', s.index('class DmBackend'))
end = s.index('    # -- datasets', start)
s = s[:start] + '''    def metadata(self, image_id, max_depth, prefix):
        parts = _metadata_prefix_parts(prefix)
        canonical = "".join(self._tag_path("", part) for part in parts)
        img = self._resolve(image_id)
        self._node_budget = MAX_TAG_NODES
        self._lookup_budget = MAX_TAG_NODES
        self._tag_types = {}
        self._metadata_issues = []
        max_depth = max(0, min(int(max_depth), 64))
        result = {"id": int(img.GetID()), "name": self._safe(img.GetName)}
        try:
            node, status = self._metadata_locate(img.GetTagGroup(), parts)
            tree = (self._metadata_value(node, 0, max_depth, canonical)
                    if status == "found" and not self._metadata_issues else node)
        except Exception as exc:
            tree = self._metadata_issue(canonical, "read_error", exc)
            status = "unavailable"
        result.update({"tags": None if status == "not_found" else tree,
                       "prefix": canonical, "path_status": status,
                       "tag_types": self._tag_types,
                       "complete": status == "found" and not bool(self._metadata_issues),
                       "complete_scope": "requested subtree", "issues": self._metadata_issues,
                       "limits": {"max_depth": max_depth, "max_nodes": MAX_TAG_NODES,
                                  "max_lookup_nodes": MAX_TAG_NODES, "max_path_segments": 64,
                                  "max_tag_value_bytes": MAX_TAG_VALUE_BYTES},
                       "tag_path_format": "JSON Pointer; calibration dimensions use DM order X,Y,Z,..."})
        if status == "not_found":
            result["error"] = "tag path not found: %s" % canonical
        elif status == "unavailable":
            result["error"] = "tag path could not be resolved completely; inspect issues"
        return result

''' + s[end:]
start = s.index('    def op_metadata(self, a):', s.index('class Dispatcher'))
end = s.index('    def op_stats(', start)
s = s[:start] + '''    def op_metadata(self, a):
        return self.backend.metadata(a.get("image_id"), a.get("max_depth", 8), a.get("prefix"))

''' + s[end:]
ast.parse(s, feature_version=(3, 7))
changes = {'bridge/dm_bridge.py': s}
p = Path('server.mjs'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '读取图像元数据标签树。必须检查 complete、truncation、unsupported 和 read_errors；用 prefix 指定子树，不把截断或读取失败当作标签缺失。', '读取指定元数据子树。先检查 path_status（found/not_found/unavailable），再检查 complete 和 issues；先定位 prefix 再按子树预算读取，不把截断或读取失败当作标签缺失。')
s = replace_once(s, '递归深度上限，默认 8', '所选子树的递归深度上限，默认 8；不限制 prefix 的路径深度')
s = replace_once(s, '标签路径，如 "Acquisition/Instrument"', 'JSON Pointer，如 "/Acquisition/Instrument"；也接受无首斜线形式；~1 表示斜线，~0 表示波浪号；列表用零基索引；省略或空字符串表示根')
s = replace_once(s, 'dm_metadata 检查 complete/read_errors', 'dm_metadata 检查 path_status/complete/issues')
changes[str(p)] = s
p = Path('README.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '## 4D-STEM 调用示例与限制', '''## 元数据子树读取

`dm_metadata(prefix=...)` 先定位标签，再以该子树为深度零点读取；不读取无关 sibling 的值。支持 `/Acquisition/Instrument` 及原有无首斜线写法，列表用零基索引；标签里的 `/`、`~` 分别写作 `~1`、`~0`。省略/空字符串表示根；`/` 表示空名称标签，不再把前后空白或斜线悄悄删去。

检查 `path_status`：`found` 只说明路径存在，值是否完整仍看 `complete` 和 `issues`；`not_found` 表示已确认不存在；`unavailable` 表示查找预算不足、标签读取失败或路径不唯一，不能据此认定不存在。`complete` 仅描述所选子树。查找和子树遍历各有独立节点预算，路径最多 64 段；失败不会丢失诊断信息。类型描述或大小读取失败时停止，不猜测原生 getter。

此改动有合成与 fake-DM 回归覆盖，修复后的真实 DM 元数据路径读取仍为 **NOT_TESTED**。后续开发及真机验收顺序见 [ROADMAP.md](ROADMAP.md)。

## 4D-STEM 调用示例与限制''')
changes[str(p)] = s
p = Path('README.en.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '## 4D-STEM examples and limits', '''## Metadata subtree selection

`dm_metadata(prefix=...)` resolves the path before traversing the selected subtree, whose root has depth zero. Unrelated sibling values are not read. Both `/Acquisition/Instrument` and the existing slashless shorthand are accepted. Lists use zero-based indices; escape literal `/` and `~` as `~1` and `~0`. Omitted/empty prefix selects the root; `/` selects an empty-name tag. Whitespace and trailing slashes are no longer silently removed.

Check `path_status`: `found` establishes existence, not successful/complete value decoding; still check `complete` and `issues`. `not_found` means confirmed absence. `unavailable` means resolution was blocked by lookup limits, unreadable labels or ambiguity, not absence. Completeness applies only to the requested subtree. Lookup and subtree traversal have separate node budgets; paths have at most 64 segments. Type/size introspection failures stop before guessing a native getter.

Synthetic/fake-DM regressions cover this change; repaired real-DM metadata path reading remains **NOT_TESTED**. See [ROADMAP.md](ROADMAP.md) for the next acceptance and development steps.

## 4D-STEM examples and limits''')
changes[str(p)] = s
p = Path('AGENTS.md'); s = p.read_text(encoding='utf-8')
s = replace_once(s, '## Validation and claims', '''10. Resolve metadata prefixes before subtree traversal. Keep lookup and value budgets separate, preserve JSON Pointer escapes/list indices, and distinguish confirmed absence from incomplete resolution. Never guess a native getter after failed or truncated type introspection. `complete` describes the requested subtree, not the whole image metadata.

## Validation and claims''')
changes[str(p)] = s
for path, text in changes.items():
    with open(path, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print('Patched', path)
