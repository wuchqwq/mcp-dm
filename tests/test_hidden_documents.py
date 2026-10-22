"""Hidden DM document lifetime and enumeration regression tests.

Uses only FakeDM, synthetic pixels and temporary files; no DM or socket.
Run: python -B -m unittest discover -s tests -p test_hidden_documents.py -v
"""

import gc
import os
import tempfile
import unittest
import weakref

import numpy as np

from test_analysis import FakeImage, bridge


class HiddenDocument(object):
    def __init__(self, dm, images):
        self.dm = weakref.ref(dm)
        self.images = images
        self.valid = True
        self.show_calls = 0
        for image in images:
            image.document = self

    def IsValid(self):
        return self.valid

    def CountImages(self):
        if not self.valid:
            raise RuntimeError("closed document")
        return len(self.images)

    def GetImage(self, index):
        if not self.valid:
            raise RuntimeError("closed document")
        return self.images[index]

    def GetName(self):
        return "hidden fixture"

    def GetWorkspace(self):
        return 0

    def Show(self):
        self.show_calls += 1
        self.dm().visible.append(self)


class HiddenFakeDM(object):
    """Workspace ownership begins only when Show is explicitly called."""

    def __init__(self, images_per_document=1):
        self.visible = []
        self.last_document = None
        self.last_images = []
        self.images_per_document = images_per_document

    def OpenImage(self, path):
        images = [FakeImage(np.arange(12, dtype=np.uint32).reshape(3, 4),
                            image_id=100 + index, name="hidden%d" % index)
                  for index in range(self.images_per_document)]
        doc = HiddenDocument(self, images)
        self.last_document = weakref.ref(doc)
        self.last_images = [weakref.ref(image) for image in images]
        return images[0]

    def CountImageDocumentsOfAllWorkspaces(self):
        return len(self.visible)

    def GetImageDocumentOfAllWorkspaces(self, index):
        return self.visible[index]

    def FindImageByID(self, target):
        for doc in self.visible:
            for image in doc.images:
                if image.GetID() == target:
                    return image
        return None


class HiddenDocumentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "fixture.tif")
        with open(self.path, "wb") as stream:
            stream.write(b"synthetic input; FakeDM does not decode it")

    def tearDown(self):
        self.folder.cleanup()

    def test_hidden_document_survives_and_resolves_without_show(self):
        dm = HiddenFakeDM(images_per_document=2)
        backend = bridge.DmBackend(dm)
        opened = backend.open_file(self.path, False)
        gc.collect()
        self.assertEqual(opened["image_ids"], [100, 101])
        self.assertIsNotNone(dm.last_document())
        self.assertEqual(dm.last_document().show_calls, 0)
        self.assertEqual(dm.visible, [])
        self.assertEqual([entry[3].GetID() for entry in backend._iter_images()], [100, 101])
        for image_id in opened["image_ids"]:
            self.assertEqual(backend._resolve(image_id).GetID(), image_id)
        listed = backend.list_datasets()
        self.assertEqual(listed["count"], 2)
        self.assertTrue(all(item["doc_index"] == -1 for item in listed["datasets"]))
        output = os.path.join(self.folder.name, "hidden.npy")
        self.assertTrue(backend.export(101, output, "npy")["exported"])
        np.testing.assert_array_equal(np.load(output, allow_pickle=False),
                                      np.arange(12, dtype=np.uint32).reshape(3, 4))

    def test_document_later_shown_is_enumerated_once(self):
        dm = HiddenFakeDM()
        backend = bridge.DmBackend(dm)
        backend.open_file(self.path, False)
        doc = dm.last_document()
        doc.Show()
        # Model duplicated workspace enumeration as well as registry overlap.
        dm.visible.append(doc)
        listed = backend.list_datasets()
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["datasets"][0]["doc_index"], 0)
        self.assertEqual(doc.show_calls, 1)

    def test_closed_retained_document_is_removed(self):
        dm = HiddenFakeDM()
        backend = bridge.DmBackend(dm)
        backend.open_file(self.path, False)
        dm.last_document().valid = False
        self.assertEqual(list(backend._iter_images()), [])
        self.assertEqual(backend._opened_documents, {})
        gc.collect()
        self.assertIsNone(dm.last_document())
        with self.assertRaisesRegex(RuntimeError, "image_id=100"):
            backend._resolve(100)

    def test_backend_release_releases_hidden_document_without_show_or_close(self):
        dm = HiddenFakeDM()
        backend = bridge.DmBackend(dm)
        backend.open_file(self.path, False)
        document_ref = dm.last_document
        image_refs = dm.last_images
        del backend
        gc.collect()
        self.assertIsNone(document_ref())
        self.assertTrue(all(ref() is None for ref in image_refs))
        self.assertEqual(dm.visible, [])

    def test_open_with_show_does_not_duplicate_retained_image(self):
        dm = HiddenFakeDM()
        backend = bridge.DmBackend(dm)
        backend.open_file(self.path, True)
        self.assertEqual(dm.last_document().show_calls, 1)
        self.assertEqual(backend.list_datasets()["count"], 1)


if __name__ == "__main__":
    unittest.main()
