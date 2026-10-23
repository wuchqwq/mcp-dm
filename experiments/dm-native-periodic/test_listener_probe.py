from pathlib import Path
import tempfile
import unittest

import client
import listener_probe as probe


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"new"
        probe.prepare(self.root,123)

    def fake_registration(self):
        token=client.read(self.root/"listener"/"session.json")["token"]
        client.save(self.root/"starter_complete.json",dict(host_pid=123))
        client.save(self.root/"listener"/"registered.json",dict(token=token,trigger_id=12,
                    source_id=11,source_sha256="synthetic"))

    def test_requires_completed_starter(self):
        with self.assertRaises(RuntimeError): probe._request_for_protocol_tests(self.root,"wake")

    def test_only_fixed_actions(self):
        with self.assertRaises(ValueError): probe._request_for_protocol_tests(self.root,"execute")

    def test_request_publication_and_unknown_not_retried(self):
        self.fake_registration()
        issued=probe._request_for_protocol_tests(self.root,"wake")
        self.assertEqual(len((self.root/"request_0.ready").read_bytes()),128)
        self.assertIn("unknown",probe.query(self.root,issued["slot"])["python_state"])
        self.assertEqual(len(list((self.root/"issued").glob("*.json"))),1)

    def test_partial_python_receipt_stays_unknown(self):
        self.fake_registration()
        issued=probe._request_for_protocol_tests(self.root,"wake")
        path=self.root/"listener"/"replies"/(issued["request_id"]+".json")
        path.write_text('{"state":')
        self.assertEqual(probe.query(self.root,0)["state"],"unknown")

    def test_fixed_generated_python_compiles(self):
        for path in self.root.glob("*.py"):
            compile(path.read_text(),str(path),"exec")
        self.assertNotIn("DigitalMicrograph",(self.root/"bounded_busy.py").read_text())
        self.assertIn("time.sleep(10)",(self.root/"bounded_busy.py").read_text())

    def test_public_requests_remain_quarantined_even_after_registration(self):
        self.fake_registration()
        for action in ("wake","hold"):
            with self.assertRaisesRegex(RuntimeError,"QUARANTINED"):
                probe.request(self.root,action)
        self.assertEqual(list((self.root/"issued").glob("*.json")),[])

    def test_starter_refuses_before_any_host_import(self):
        path=self.root/"01_start_listener.py"
        with self.assertRaisesRegex(RuntimeError,"QUARANTINED"):
            exec(compile(path.read_text(),str(path),"exec"),{})


if __name__=="__main__": unittest.main()
