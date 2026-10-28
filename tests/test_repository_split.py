"""Migration safety tests over disposable Git repositories; no scientific deps."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'prepare_repository_split.py'
spec = importlib.util.spec_from_file_location('prepare_repository_split', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RepositorySplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='split-unit-')
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic migration fixture')
        self.git('config', 'user.email', 'fixture@localhost')
        self.config = {'schema_version': 1, 'profiles': {}}
        for name in ('microscopy-core', 'mcp-dm'):
            self.config['profiles'][name] = {
                'include': ['LICENSE', 'safe.mjs'], 'required': ['LICENSE', 'safe.mjs'],
                'templates': {'tests/standalone-boundary.test.mjs': 'migration/test-template.mjs'},
                'unit_tests': []}
        self.write('LICENSE', 'MIT fixture\n')
        self.write('safe.mjs', 'export const unchanged = 42;\n')
        self.write('migration/test-template.mjs', 'export const fixture = true;\n')
        self.save_config()
        self.source = self.commit()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True, check=True)
        return result.stdout.decode().strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def save_config(self):
        self.write('migration/ownership.json', json.dumps(self.config))

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'Synthetic source fixture')
        return self.git('rev-parse', 'HEAD')

    def export(self, name='output', source=None, recipe=None):
        return module.export(self.repo, source or self.source, recipe or self.source, self.root / name)

    def test_committed_only_and_source_untouched(self):
        self.write('safe.mjs', 'uncommitted private text\n')
        self.write('.env', 'SECRET=not-for-export\n')
        before = self.git('status', '--porcelain')
        receipt = self.export()
        self.assertEqual((self.root/'output/microscopy-core/safe.mjs').read_text(), 'export const unchanged = 42;\n')
        self.assertFalse((self.root/'output/microscopy-core/.env').exists())
        self.assertEqual(self.git('status','--porcelain'), before)
        self.assertEqual(receipt['source_commit'], self.source)
        self.assertFalse((self.root/'output/INCOMPLETE.txt').exists())

    def test_deterministic_receipts_and_hashes(self):
        a = self.export('one')
        b = self.export('two')
        self.assertEqual(a, b)
        for profile, entries in a['profiles'].items():
            for entry in entries:
                raw = (self.root/'one'/profile/entry['path']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
        self.assertEqual((self.root/'one/split-manifest.json').read_bytes(), (self.root/'two/split-manifest.json').read_bytes())

    def test_existing_output_refused_even_empty(self):
        (self.root/'output').mkdir()
        with self.assertRaisesRegex(module.SplitError, 'must not exist'):
            self.export()
        self.assertEqual(list((self.root/'output').iterdir()), [])

    def test_output_inside_source_refused(self):
        with self.assertRaisesRegex(module.SplitError, 'outside'):
            module.export(self.repo,self.source,self.source,self.repo/'result')

    def test_check_only_does_not_create_output(self):
        products, receipt = module.plan(self.repo,self.source,self.source)
        self.assertEqual(set(products),{'microscopy-core','mcp-dm'})
        self.assertFalse((self.root/'output').exists())
        self.assertEqual(receipt['source_commit'],self.source)

    def test_moving_branch_is_not_a_snapshot(self):
        with self.assertRaisesRegex(module.SplitError, 'full 40-character'):
            module.Snapshot(self.repo,'main')

    def test_missing_reviewed_feature_is_not_silently_dropped(self):
        self.config['profiles']['microscopy-core']['required'].append('tools/researcher_inspector.mjs')
        self.save_config();recipe=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'required reviewed features'):
            self.export(recipe=recipe)
        self.assertFalse((self.root/'output').exists())

    def test_host_import_rejected_before_writing(self):
        self.write('safe.py','import DigitalMicrograph as DM\n')
        self.config['profiles']['microscopy-core']['include'].append('safe.py')
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'Host import'):
            self.export(source=sha,recipe=sha)
        self.assertFalse((self.root/'output').exists())

    def test_missing_local_dependency_fails_closed(self):
        self.write('safe.mjs',"import {bad} from './missing.mjs';\n")
        sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'Unresolved local'):
            self.export(source=sha)

    def test_python_relative_dependency_checked(self):
        self.write('tools/example.py','from .missing import value\n')
        self.config['profiles']['microscopy-core']['include'].append('tools/*.py')
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'Unresolved local'):
            self.export(source=sha,recipe=sha)

    def test_no_vendor_or_experimental_payload(self):
        self.write('sample.dm4','synthetic forbidden placeholder\n')
        self.config['profiles']['microscopy-core']['include'].append('sample.dm4')
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'payload'):
            self.export(source=sha,recipe=sha)

    def test_no_template_path_traversal(self):
        self.config['profiles']['microscopy-core']['templates']['../escape.mjs']='migration/test-template.mjs'
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'Unsafe'):
            self.export(recipe=sha)
        self.assertFalse((self.root/'escape.mjs').exists())

    @unittest.skipIf(os.name=='nt','Synthetic symlink creation needs local Windows privileges')
    def test_symlinked_source_not_followed(self):
        path=self.repo/'safe.mjs';path.unlink();path.symlink_to('/outside/private')
        sha=self.commit()
        with self.assertRaisesRegex(module.SplitError, 'Symlink'):
            self.export(source=sha)

    @unittest.skipIf(os.name=='nt','Synthetic symlink creation needs local Windows privileges')
    def test_symlinked_destination_parent_refused(self):
        (self.root/'linked').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(module.SplitError, 'non-symlinked'):
            module.export(self.repo,self.source,self.source,self.root/'linked/out')

    def test_source_map_keeps_original_hash(self):
        self.config['profiles']['mcp-dm']['source_map']={'NOTICE.md':'LICENSE'}
        self.save_config();sha=self.commit()
        receipt=self.export(recipe=sha)
        entry=next(e for e in receipt['profiles']['mcp-dm'] if e['path']=='NOTICE.md')
        self.assertEqual(entry['source']['path'],'LICENSE')
        self.assertEqual((self.root/'output/mcp-dm/NOTICE.md').read_bytes(),(self.repo/'LICENSE').read_bytes())

    def test_source_map_cannot_bypass_private_file_guard(self):
        self.write('.env','SECRET=fixture\n')
        self.config['profiles']['mcp-dm']['source_map']={'NOTICE.md':'.env'}
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError,'payload'):
            self.export(source=sha,recipe=sha)

    def test_repo_subdirectory_cannot_bypass_output_boundary(self):
        (self.repo/'nested').mkdir()
        with self.assertRaisesRegex(module.SplitError,'outside'):
            module.export(self.repo/'nested',self.source,self.source,self.repo/'output')

    def test_test_command_paths_are_not_shell_commands(self):
        self.config['profiles']['microscopy-core']['unit_tests']=['tests/a.mjs;echo nope']
        self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError,'Unsafe test'):
            self.export(recipe=sha)

    def test_launcher_adaptation_is_exact_and_idempotent(self):
        adapter={'schema_version':1,'source_path':'tools/image_panel.mjs','before':'legacy_env','after':'science_env'}
        self.assertEqual(module.adapt_launcher(b'A legacy_env Z',adapter),(b'A science_env Z',True))
        self.assertEqual(module.adapt_launcher(b'A science_env Z',adapter),(b'A science_env Z',False))
        for value in (b'unrelated',b'legacy_env legacy_env',b'legacy_env science_env'):
            with self.assertRaisesRegex(module.SplitError,'ambiguous'):
                module.adapt_launcher(value,adapter)

    def test_launcher_adaptation_preserves_source_and_records_recipe(self):
        self.write('tools/image_panel.mjs','export const legacy_env = 42;\n')
        self.write('migration/adapter.json',json.dumps({'schema_version':1,'source_path':'tools/image_panel.mjs','before':'legacy_env','after':'science_env'}))
        core=self.config['profiles']['microscopy-core'];core['include'].append('tools/image_panel.mjs');core['launcher_adaptation']='migration/adapter.json'
        self.save_config();sha=self.commit();receipt=self.export(source=sha,recipe=sha)
        self.assertIn('science_env',(self.root/'output/microscopy-core/tools/image_panel.mjs').read_text())
        self.assertIn('legacy_env',(self.repo/'tools/image_panel.mjs').read_text())
        origin=next(x['source'] for x in receipt['profiles']['microscopy-core'] if x['path']=='tools/image_panel.mjs')
        self.assertEqual(origin['kind'],'adapted');self.assertEqual(origin['launcher_adaptation']['commit'],sha)

    def test_rejects_unsupported_manifest_version(self):
        self.config['schema_version']=999;self.save_config();sha=self.commit()
        with self.assertRaisesRegex(module.SplitError,'Unsupported'):
            self.export(recipe=sha)


if __name__=='__main__':
    unittest.main()
