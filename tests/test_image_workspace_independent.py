"""Independent saved-package and output-provenance controls; no DM or UI."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from tools import image_workspace as worker


ROOT = Path(__file__).resolve().parents[1]


class ImageWorkspaceIndependent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory(prefix='independent-image-native-')
        cls.fixtures = Path(cls.fixture_temp.name)
        script = r"""import fs from 'node:fs';import path from 'node:path';
import {readFixture} from OPERATIONS;
import {frameHandoffFixture} from FRAME;
import {pixelReadFixture} from PIXEL;
import {handoff} from HANDOFF;
const base=process.argv[1];
function save(name,result,args){const id='original-'+name,saved=path.join(base,name+'.json');
const native_receipt={protocol:'NB2',session:'a'.repeat(32),id,request_id:id,state:'completed',host_pid:1234,
exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,
result_type:'native_data_snapshot',result_version:1};
fs.writeFileSync(saved,JSON.stringify({...result,native_receipt}));
handoff({workspace:base,output:name,requestId:'encode-'+name,snapshot:saved});}
const frame=frameHandoffFixture({unknownUnits:true}),args=[77,1,1,4,3];
const result=readFixture(args,{source:frame.result.image,provenance:frame.provenance});
result.frame_ancestry=frame.ancestry;
const values=Buffer.alloc(result.raw_bytes);for(let i=0;i<result.sample_count;i++)values.writeFloatLE(i%2?65535:32768,i*4);
result.values_base64=values.toString('base64');save('native-frame',result,args);
for(const [name,options] of [['pixel-frequency',{}],['pixel-spatial',{spatial:true}]]){
 const f=pixelReadFixture(options);save(name,f.read,f.args);
}
"""
        for name, relative in [('OPERATIONS', 'tests/fixtures/native-operations.mjs'),
                               ('FRAME', 'tests/fixtures/native-frame-handoff.mjs'),
                               ('PIXEL', 'tests/fixtures/native-pixel-handoff.mjs'),
                               ('HANDOFF', 'tools/native_snapshot_handoff.mjs')]:
            script = script.replace(name, json.dumps((ROOT / relative).as_uri()))
        run = subprocess.run(['node', '--input-type=module', '-e', script, str(cls.fixtures)],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise RuntimeError(run.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='independent-image-case-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / 'workspace'
        self.number = 0
        self.capture_number = 0

    def execute(self, action, **args):
        self.number += 1
        return worker.execute({'workspace': str(self.workspace), 'request_id': 'independent-' + str(self.number),
                               'action': action, **args})

    def capture(self, name='native-frame'):
        self.capture_number += 1
        target = self.base / (name + '-' + str(self.capture_number))
        shutil.copytree(self.fixtures / name, target)
        return target

    def mutate(self, path, modify):
        info = json.loads((path / 'input.json').read_text(encoding='utf-8'))
        manifest = json.loads((path / 'capture.json').read_text(encoding='utf-8'))
        modify(info, manifest)
        raw = worker.canonical(info)
        digest = hashlib.sha256(raw).hexdigest()
        manifest['input_metadata_sha256'] = manifest['input_metadata_file_sha256'] = digest
        (path / 'input.json').write_bytes(raw)
        (path / 'capture.json').write_bytes(worker.canonical(manifest))

    def test_missing_native_receipt_cannot_downgrade_to_generic_saved_capture(self):
        path = self.capture()
        self.mutate(path, lambda info, manifest: info.pop('native_receipt'))
        result = self.execute('import_capture', source_path=str(path))
        self.assertFalse(result['ok'], 'native source identity was silently bypassed')

    def test_native_ancestry_cannot_hide_behind_removed_receipt_and_relabelled_backend(self):
        path = self.capture()
        def change(info, manifest):
            info.pop('native_receipt')
            manifest['capture_backend'] = 'digitalmicrograph'
            info['frame_ancestry']['result']['candidate_probe'] = True
            manifest['frame_ancestry'] = info['frame_ancestry']
        self.mutate(path, change)
        result = self.execute('import_capture', source_path=str(path))
        self.assertFalse(result['ok'], 'relabelled candidate FRAME bypassed independent validation')

    def test_imported_unknown_calibration_and_pixel_fourier_remain_explicit_image_inputs(self):
        for name in ('native-frame', 'pixel-frequency', 'pixel-spatial'):
            with self.subTest(name=name):
                path = self.capture(name)
                before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
                imported = self.execute('import_capture', source_path=str(path))
                self.assertTrue(imported['ok'], imported)
                self.assertEqual(imported['result']['capture_verification_mode'], 'image')
                np.testing.assert_array_equal(np.load(imported['result']['array_path']), np.load(path / 'input.npy'))
                self.assertEqual(before, {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()})

    def test_imported_native_frequency_view_cannot_claim_spatial_roi_mapping(self):
        path = self.capture('pixel-frequency')
        imported = self.execute('import_capture', source_path=str(path))
        self.assertTrue(imported['ok'], imported)
        viewed = self.execute('view', object_id=imported['result']['object_id'])
        self.assertTrue(viewed['ok'], viewed)
        self.assertIn(viewed['result']['panels'][0]['domain'], ('frequency', 'source_array_indices'))
        annotated = self.execute('annotate', object_id=viewed['result']['object_id'],
                                 annotations=[{'kind': 'point', 'coordinates': [0, 0]}])
        self.assertTrue(annotated['ok'], annotated)
        for mapping in annotated['result']['annotations'][0]['source_mappings']:
            self.assertIn(mapping['domain'], ('frequency', 'source_array_indices'))
            self.assertFalse(mapping.get('spatial_roi_mapping_performed', False))

    def test_export_of_native_import_and_derived_view_keeps_upstream_scientific_metadata(self):
        for derived in (False, True):
            with self.subTest(derived=derived):
                path = self.capture()
                imported = self.execute('import_capture', source_path=str(path))
                self.assertTrue(imported['ok'], imported)
                obj = imported['result']
                if derived:
                    view = self.execute('view', object_id=obj['object_id'], rect=[0, 0, 2, 2])
                    self.assertTrue(view['ok'], view)
                    obj = view['result']
                output = self.base / ('export-view' if derived else 'export-frame')
                exported = self.execute('export', object_id=obj['object_id'], output_dir=str(output))
                self.assertTrue(exported['ok'], exported)
                # The new independent output must carry actual provenance data,
                # not merely hashes or paths requiring the original workspace.
                expected = json.loads((path / 'input.json').read_text(encoding='utf-8'))['frame_ancestry']
                content = '\n'.join(p.read_text(encoding='utf-8') for p in output.rglob('*.json'))
                self.assertIn('tracked_frame', content)
                self.assertIn(expected['request_id'], content)
                self.assertIn('lossless_values', content)
                self.assertIn('unspecified_sequence', content)
                shutil.rmtree(path)
