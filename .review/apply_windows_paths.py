from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1]).resolve()
p = root / 'lib/image_workspace.mjs'
s = p.read_text(encoding='utf-8')
old = '          const root=realpathSync(this.workspace),file=realpathSync(result.image_path),relative=path.relative(root,file);'
new = '''          // Python resolves Windows 8.3 aliases to long paths. Canonicalize
          // both sides through the native filesystem before containment checks.
          const root=realpathSync.native(this.workspace),file=realpathSync.native(result.image_path),relative=path.relative(root,file);'''
assert s.count(old) == 1
p.write_bytes(s.replace(old, new).encode('utf-8'))
p = root / 'tests/image-worker-lifecycle.test.mjs'
s = p.read_text(encoding='utf-8')
changes = [
 ("if case in ('png','outside_png','large_png','non_png'):", "if case in ('png','resolved_png','outside_png','outside_resolved_png','large_png','non_png'):"),
 (" target=(root.parent if case=='outside_png' else root)/('preview-'+ident+'.png')", " target=(root.parent if case in ('outside_png','outside_resolved_png') else root)/('preview-'+ident+'.png')"),
 (" target.write_bytes(png);result['image_path']=str(target)", " target.write_bytes(png);result['image_path']=str(target.resolve() if case in ('resolved_png','outside_resolved_png') else target)"),
 ("  for(const [id,kind,reason] of [['outside','outside_png',/escapes workspace/],['large','large_png',/2 MiB/],['invalid','non_png',/not PNG/]])", """  // On Windows os.tmpdir() may use RUNNER~1 while Python Path.resolve()
  // returns the same directory's long name. It is not an escape.
  const canonical=await call(f,'canonical-png','resolved_png');
  assert.equal(canonical.content[1].type,'image');
  for(const [id,kind,reason] of [['outside','outside_png',/escapes workspace/],['outside-resolved','outside_resolved_png',/escapes workspace/],['large','large_png',/2 MiB/],['invalid','non_png',/not PNG/]])"""),
]
for old, new in changes:
 assert s.count(old) == 1, old
 s = s.replace(old, new)
p.write_bytes(s.encode('utf-8'))
expected = {
 'tools/image_workspace.py': '518b7eea6a968985f8d0f8eb7989a78ed360afe3',
 'lib/image_workspace.mjs': '4ee2d28fa4698cbdb97326b613ee6a9bab9b549d',
 'tests/image-worker-lifecycle.test.mjs': '690cf802c5166138b7f527a547a0465ed9e4ded3',
 'tests/image-workspace-mcp.test.mjs': 'be42e44a4c9d1cc89a2d36cf3dfcf0db95e00edd',
 'tests/test_image_workspace_revisions.py': '8f2b92f3d42ba7aea261d70b601eb1e021a1392d',
 'docs/PIXEL_IMAGE_WORKFLOW.md': '95573a0aacbeb44355fc9c12a8605a23606bb3e9',
}
for name, wanted in expected.items():
 raw = (root / name).read_bytes()
 actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
 print(name, actual)
 assert actual == wanted, (name, actual, wanted)
