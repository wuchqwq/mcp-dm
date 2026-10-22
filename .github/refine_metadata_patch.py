"""Focused corrections on the temporary validation branch only."""
import ast
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected one correction anchor: %r' % old[:100])
    return text.replace(old, new, 1)


p = Path('bridge/dm_bridge.py')
s = p.read_text(encoding='utf-8')
s = replace_once(s, '''        path = ""
        for step, part in enumerate(parts):''', '''        if not (hasattr(node, "CountTags") and hasattr(node, "IsList")):
            return self._metadata_issue("", "read_error", "invalid native metadata root"), "unavailable"
        path = ""
        for step, part in enumerate(parts):''')
s = replace_once(s, '''            if size is None or size < 0:
                raise ValueError("unknown or negative native tag size")''', '''            if (isinstance(size, bool) or not isinstance(size, numbers.Real)
                    or not math.isfinite(size) or size < 0):
                raise ValueError("unknown, nonfinite or negative native tag size")''')
ast.parse(s, feature_version=(3, 7))
with open(str(p), 'w', encoding='utf-8', newline='\n') as stream:
    stream.write(s)

p = Path('tests/test_metadata_paths.py')
s = p.read_text(encoding='utf-8')
s = replace_once(s, '''        with mock.patch.object(bridge, 'MAX_TAG_NODES', 2):
            result = self.get('/Target', 0)''', '''        with mock.patch.object(bridge, 'MAX_TAG_NODES', 2), mock.patch.object(
                self.image.tags, 'GetTagTypeLength', wraps=self.image.tags.GetTagTypeLength) as type_lengths:
            result = self.get('/Target', 0)''')
s = replace_once(s, '''        self.assertEqual(set(i for i, k in self.image.tags.type_calls), {1})''', '''        # A group has an empty descriptor, so GetTagType itself is never called.
        # Observe the actual introspection entry point, not a nonexistent scalar read.
        type_lengths.assert_called_once_with(1)''')
extra = '''    def test_invalid_native_root_is_not_complete_even_without_prefix(self):
        for root in (None, {}, 7, object()):
            for prefix in (None, '/Instrument'):
                with self.subTest(root=type(root).__name__, prefix=prefix), mock.patch.object(
                        self.image, 'GetTagGroup', return_value=root):
                    result = self.get(prefix)
                    self.assertEqual(result['path_status'], 'unavailable')
                    self.assertFalse(result['complete'])
                    self.reason(result, 'read_error')

    def test_empty_native_root_is_valid_and_complete(self):
        self.image.tags = FakeTagGroup({})
        result = self.get()
        self.assertEqual(result['path_status'], 'found')
        self.assertTrue(result['complete'])
        self.assertEqual(result['tags'], {})

    def test_invalid_sizes_stop_before_native_value_getters(self):
        for size in (None, -1, float('nan'), float('inf'), True, '4'):
            with self.subTest(size=size):
                self.image.tags = FakeTagGroup({'value': 7})
                with mock.patch.object(self.image.tags, 'GetTagSize', return_value=size):
                    result = self.get('/value')
                self.assertEqual(result['path_status'], 'found')
                self.assertFalse(result['complete'])
                self.reason(result, 'tag_size_read_error')
                self.assertEqual(self.image.tags.reader_calls, [])
                self.assertEqual(self.image.tags.group_reads, [])


'''
s = replace_once(s, 'class MockMetadataPathTests(unittest.TestCase):', extra + 'class MockMetadataPathTests(unittest.TestCase):')
ast.parse(s, feature_version=(3, 7))
with open(str(p), 'w', encoding='utf-8', newline='\n') as stream:
    stream.write(s)
print('Refined metadata root/type-size guards and regression assertions')
