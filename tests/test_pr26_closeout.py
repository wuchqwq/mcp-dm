"""Actual immutable workspace regressions, not live-DM qualification."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile

from tools.image_workspace import execute
from crystallography.reflection_compare import load_measurement
from crystallography.analysis_revision import bind_geometry
from crystallography.registration_proposal import geometry_binding, propose, RegistrationError
from tests.test_registration_proposal import simulation, pairs, measurement


class PR26CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'images'
        self.source = self.root / 'synthetic.tiff'
        tifffile.imwrite(self.source, np.arange(2*32*32, dtype=np.uint16).reshape(2,32,32), photometric='minisblack')
        self.source_bytes = self.source.read_bytes()
        self.n = 0
        self.opened = self.ok('open', source_path=str(self.source))
        self.frame = self.ok('frame', object_id=self.opened['object_id'], frame_index=0)

    def request(self, action, **kwargs):
        self.n += 1
        return execute(dict(workspace=str(self.workspace), action=action, request_id='closeout-'+str(self.n), **kwargs))

    def ok(self, action, **kwargs):
        response = self.request(action, **kwargs)
        self.assertTrue(response['ok'], response)
        return response['result']

    def declare(self, ident):
        return self.ok('calibrate', object_id=ident, scope='image', coordinate_domain='reciprocal_space',
                       declare_reciprocal=True, xy_scale={'x':.25,'y':-.5,'unit':'1/nm'},
                       source_text='User explicitly declares this previously untyped detector array reciprocal; independent scale supplied')

    def mixed_fft_measurements(self):
        scale = self.ok('calibrate', object_id=self.frame['object_id'], scope='image',
                        xy_scale={'x':.1,'y':.1,'unit':'nm'}, source_text='Synthetic 1 angstrom original pixel')
        fft = self.ok('fft', object_id=scale['object_id'])
        view = self.ok('view', object_id=fft['object_id'], gamma=.8)
        zoom = self.ok('view', object_id=view['object_id'], gamma=1.2, frequency_rect=[16,16,32,32])
        rows = [self.ok('measure', object_id=obj['object_id'], points=[[0,0],point])
                for obj, point in zip((fft,view,zoom),([.25,0],[0,.25],[.25,.25]))]
        return fft, zoom, rows

    def test_mixed_fft_display_wrappers_register_one_verified_science_grid(self):
        fft, view, rows = self.mixed_fft_measurements()
        original = Path(fft['array_path']).read_bytes()
        saved = [load_measurement(row['manifest_path']) for row in rows]
        binding = bind_geometry([r[0] for r in saved],[r[1] for r in saved],view['object_id'],'continue_current')
        self.assertTrue(binding['current_geometry_checked'])
        self.assertEqual(len({r['source_object_id'] for r in rows}),3)
        result = propose(rows,simulation([[.25,0,0],[0,.25,0],[.25,.25,0]]),
                         pairs((0,[1,0,0]),(1,[0,1,0])),pairs((2,[1,1,0])),
                         {'flip_y':False,'basis':'Known synthetic axes'},1e-12,'real_space_fft',
                         {'source':'synthetic_fixture','source_text':'Independent literal synthetic vectors'})
        self.assertTrue(result['held_out_validation_passed'])
        self.assertEqual(result['experimental_geometry_binding']['binding_version'],2)
        self.assertEqual(result['experimental_geometry_binding']['source_object_id'],fft['object_id'])
        self.assertEqual(Path(fft['array_path']).read_bytes(),original)
        self.assertEqual(self.source.read_bytes(),self.source_bytes)

    def test_display_only_remeasurement_keeps_semantic_binding_not_old_wrapper_ids(self):
        fft, view, rows = self.mixed_fft_measurements()
        updated = [self.ok('remeasure',object_id=view['object_id'],measurement_object_id=row['object_id']) for row in rows]
        self.assertEqual(geometry_binding(rows),geometry_binding(updated))
        self.assertNotEqual(rows[0]['object_id'],updated[0]['object_id'])

    def test_exact_grid_fields_and_calibration_still_refuse_mixed_data(self):
        _, _, rows = self.mixed_fft_measurements()
        self.assertEqual(geometry_binding(rows)['binding_version'],2)
        for key,value in [('source_grid_object_id','f'*32),('array_sha256','0'*64),('shape_yx',[16,64]),
                          ('dtype','complex64'),('source_rect_xyxy',[0,0,16,16])]:
            changed=copy.deepcopy(rows);changed[1]['scientific_grid_identity'][key]=value
            with self.subTest(key=key),self.assertRaises(RegistrationError):geometry_binding(changed)
        changed=copy.deepcopy(rows);changed[1].pop('scientific_grid_identity')
        with self.assertRaises(RegistrationError):geometry_binding(changed)
        changed=copy.deepcopy(rows);changed[1]['scientific_grid_identity']=None
        with self.assertRaises(RegistrationError):geometry_binding(changed)
        # Truly historical records retain the old strict source-object rule.
        old=[measurement([.2,0],1),measurement([0,.3],2)]
        self.assertEqual(geometry_binding(old)['binding_version'],1)
        old[1]['source_object_id']='d'*32
        with self.assertRaises(RegistrationError):geometry_binding(old)

    def test_free_text_saed_context_can_precede_explicit_reciprocal_declaration(self):
        context=self.ok('context',object_id=self.frame['object_id'],metadata={'data_meaning':'SAED diffraction intensity; centre not yet set','source_text':'researcher background'})
        declared=self.declare(context['object_id'])
        self.assertEqual(declared['user_context']['data_meaning'],'SAED diffraction intensity; centre not yet set')
        centre=self.ok('centre',object_id=declared['object_id'],center_xy=[16,16],coordinate_space='source_array_indices',source_text='Independent synthetic centre')
        got=self.ok('measure',object_id=centre['object_id'],points=[[16,16],[20,18]])
        self.assertEqual(got['physical_vector_xy'],[1.,-1.])
        self.assertIsNotNone(got['d_spacing'])
        self.assertEqual(self.source.read_bytes(),self.source_bytes)

    def test_inherited_sequence_context_is_kept_after_frame_declaration(self):
        context=self.ok('context',object_id=self.opened['object_id'],metadata={'data_meaning':'Detector diffraction frames'})
        frame=self.ok('frame',object_id=context['object_id'],frame_index=1)
        declared=self.declare(frame['object_id'])
        self.assertEqual(declared['user_context']['data_meaning'],'Detector diffraction frames')
        self.assertEqual(declared['xy_calibration']['scope'],'image')

    def test_free_text_is_not_domain_inference_and_cannot_override_known_scale(self):
        context=self.ok('context',object_id=self.frame['object_id'],metadata={'data_meaning':'SAED'})
        # Text alone still cannot enable a reciprocal scale.
        no_flag=self.request('calibrate',object_id=context['object_id'],scope='image',coordinate_domain='reciprocal_space',
                             xy_scale={'x':1.,'y':1.,'unit':'1/nm'},source_text='Missing explicit declaration')
        self.assertFalse(no_flag['ok'])
        declared=self.declare(context['object_id'])
        self.assertFalse(self.request('calibrate',object_id=declared['object_id'],scope='sequence',
                                     xy_scale={'x':1.,'y':1.,'unit':'1/nm'},source_text='Not automatically all frames')['ok'])
        known=self.ok('calibrate',object_id=context['object_id'],scope='image',xy_scale={'x':.1,'y':.1,'unit':'nm'},source_text='Explicit real space')
        response=self.request('calibrate',object_id=known['object_id'],scope='image',coordinate_domain='reciprocal_space',declare_reciprocal=True,
                              xy_scale={'x':1.,'y':1.,'unit':'1/nm'},source_text='Must not reinterpret established domain')
        self.assertFalse(response['ok'])

    def test_explicit_reconstruction_type_is_not_silently_reinterpreted(self):
        context=self.ok('context',object_id=self.frame['object_id'],metadata={'data_meaning':'SAED? uncertain note','reconstruction_type':'multislice ptychography'})
        response=self.request('calibrate',object_id=context['object_id'],scope='image',coordinate_domain='reciprocal_space',declare_reciprocal=True,
                              xy_scale={'x':1.,'y':1.,'unit':'1/nm'},source_text='Not a correction of reconstruction type')
        self.assertFalse(response['ok'])
        self.assertEqual(self.source.read_bytes(),self.source_bytes)

if __name__=='__main__':unittest.main()
