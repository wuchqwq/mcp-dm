import json
import os
from pathlib import Path
import tempfile
import unittest

import client


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "fresh"
        self.session = client.prepare(self.root)

    def test_partial_request_is_not_visible_until_atomic_publish(self):
        staged = client.reserve(self.root, "ping")
        self.assertFalse((self.root / "request_0.ready").exists())
        self.assertEqual(client.query(self.root, 0)["state"], "unknown")
        client.publish(self.root, staged["slot"])
        data = (self.root / "request_0.ready").read_bytes()
        self.assertEqual(len(data), 128)
        self.assertEqual(data[:32].decode(), self.session["token"])
        self.assertEqual(data[33:65].decode(), staged["request_id"])
        self.assertFalse((self.root / "request_0.pending").exists())

    def test_publish_never_replaces_existing_destination(self):
        staged = client.reserve(self.root, "ping")
        target = self.root / "request_0.ready"
        target.write_bytes(b"existing")
        with self.assertRaises(FileExistsError): client.publish(self.root, staged["slot"])
        self.assertEqual(target.read_bytes(), b"existing")

    def test_changed_staging_rejected(self):
        client.reserve(self.root, "ping")
        (self.root / "request_0.pending").write_bytes(b"changed")
        with self.assertRaises(ValueError): client.publish(self.root, 0)

    def test_invalid_identity_or_operation_rejected(self):
        for value in ("../path", "A"*32, '"'*32):
            with self.assertRaises(ValueError): client.reserve(self.root, "ping", value)
        with self.assertRaises(ValueError): client.reserve(self.root, "execute_python")

    def test_unknown_does_not_publish_or_resubmit(self):
        client.reserve(self.root, "ping")
        first = client.query(self.root, 0)
        second = client.query(self.root, 0)
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.root / "issued").glob("*.json"))), 1)
        self.assertFalse((self.root / "request_0.ready").exists())

    def test_matching_terminal_reply_and_mismatch(self):
        staged = client.reserve(self.root, "ping")
        reply = dict(staged, state="success", code="pong")
        path = self.root / "reply_0.json"
        client.save(path, reply)
        self.assertEqual(client.query(self.root, 0)["state"], "success")
        reply["request_id"] = "0"*32
        path.write_text(json.dumps(reply))
        self.assertEqual(client.query(self.root, 0)["state"], "unknown")

    def test_incomplete_reply_stays_unknown(self):
        client.reserve(self.root, "ping")
        (self.root / "reply_0.json").write_text('{"state":')
        self.assertEqual(client.query(self.root, 0)["state"], "unknown")

    def test_limit_and_unique_slots(self):
        requests = [client.reserve(self.root, "ping") for _ in range(32)]
        self.assertEqual([r["slot"] for r in requests], list(range(32)))
        self.assertEqual(len(set(r["request_id"] for r in requests)), 32)
        with self.assertRaises(RuntimeError): client.reserve(self.root, "ping")

    def test_stop_is_request_not_completion(self):
        self.assertEqual(client.stop(self.root)["state"], "stop_requested_not_proof_of_stopped")
        self.assertFalse((self.root / "stopped.json").exists())
        with self.assertRaises(FileExistsError): client.stop(self.root)

    def test_missing_host_evidence_cannot_pass(self):
        self.assertEqual(client.verify(self.root)["status"], "INCOMPLETE")

    def complete_receipts(self):
        session = client.read(self.root / "session.json")
        client.save(self.root / "registered.json", dict(token=session["token"],
                    source_template_sha256=session["template_sha256"], object_id=12, version=[3,53,1]))
        stats = dict(image_id=10, shape_yx=[8,12], dtype="float32", zero_xy=[1.25,-2.5],
                     scale_xy=[-0.25,0.5], units_xy=["nm","nm"], rect_xyxy=[2,1,7,5],
                     count=20, sum=580, mean=29, min=12, max=46)
        for slot, op in enumerate(("ping", "stats", "ping")):
            issued = client.reserve(self.root, op)
            reply = dict(issued, state="success", code="pong" if op=="ping" else "stats",
                         executions=slot+1, ticks=slot+1)
            if op=="stats": reply.update(stats)
            path = self.root / ("reply_%d.json" % slot)
            client.save(path, reply)
            os.utime(str(path), (slot*10+1, slot*10+1))
        ordinary = self.root / "ordinary_host_checked.json"
        client.bind_host(self.root, 123)
        client.save(ordinary, dict(token=session["token"], sum_0_to_10=55, host_checked=True, pid=123))
        client.save(self.root / "ordinary_native_proof.json", dict(token=session["token"], object_id=12,
                    version=[3,53,1], object_valid=1))
        os.utime(str(ordinary), (15,15))
        client.save(self.root / "stopped.json", dict(token=session["token"], executions=3,
                    processed_slots=3, source_unchanged=1, owned_image_closed=1))
        client.save(self.root / "cleanup_check.json", dict(token=session["token"],
                    object_id=12, object_valid=0))

    def test_independent_oracle_rejects_bad_sum(self):
        self.complete_receipts()
        self.assertEqual(client.verify(self.root)["status"], "PASS")
        path = self.root / "reply_1.json"
        reply = client.read(path)
        reply["sum"] = 581
        path.write_text(json.dumps(reply))
        self.assertFalse(client.verify(self.root)["checks"]["independent_stats_oracle"])

    def test_duplicate_execution_count_cannot_pass(self):
        self.complete_receipts()
        path = self.root / "stopped.json"
        reply = client.read(path)
        reply["executions"] = 4
        path.write_text(json.dumps(reply))
        self.assertFalse(client.verify(self.root)["checks"]["final_slot_and_execution_counts"])

    def test_retained_native_object_cannot_pass_cleanup(self):
        self.complete_receipts()
        path = self.root / "cleanup_check.json"
        data = client.read(path)
        data["object_valid"] = 1
        path.write_text(json.dumps(data))
        self.assertFalse(client.verify(self.root)["checks"]["native_task_object_released"])

    def test_foreign_python_process_cannot_pass_host_check(self):
        self.complete_receipts()
        path = self.root / "ordinary_host_checked.json"
        data = client.read(path)
        data["pid"] = 456
        path.write_text(json.dumps(data))
        self.assertFalse(client.verify(self.root)["checks"]["ordinary_python_completed"])

    def test_plain_python_receipt_cannot_pass_host_check(self):
        self.complete_receipts()
        (self.root / "ordinary_native_proof.json").unlink()
        self.assertFalse(client.verify(self.root)["checks"]["ordinary_python_completed"])

    def test_no_overwrite_and_finite_generated_python(self):
        with self.assertRaises(FileExistsError): client.prepare(self.root)
        p = self.root / "02_ordinary_python.py"
        compile(p.read_text(), str(p), "exec")
        script = (self.root / "01_register.s").read_text()
        self.assertNotIn("@TOKEN@", script)
        self.assertNotIn("WaitOnSignal", script)
        self.assertNotIn("ExecutePythonScript", script)


if __name__ == "__main__": unittest.main()
