# -*- coding: utf-8 -*-
"""Real isolated TCP regression for idle timers around synchronous work.

Runs production ``serve`` in a child Python process with a synthetic dispatcher,
an ephemeral loopback port and sub-second delays. No DigitalMicrograph, user
data, existing bridge, or port 8765 is used.
"""

import contextlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import types
import unittest


sys.dont_write_bytecode = True
BRIDGE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "dm_bridge.py"))


def serve_synthetic(port):
    spec = importlib.util.spec_from_file_location("dm_bridge_idle_regression_child", BRIDGE_PATH)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    bridge.HOST = "127.0.0.1"
    bridge.PORT = int(port)
    if bridge.PORT == 8765:
        raise ValueError("test must never bind port 8765")
    bridge.CLIENT_IDLE_TIMEOUT = .10
    bridge.IDLE_TIMEOUT = 10
    bridge.VERBOSE = False

    class SyntheticDispatcher(object):
        stopping = False
        backend = types.SimpleNamespace(name="synthetic-idle-regression-only")

        def handle(self, request):
            operation = request.get("op")
            if operation in ("slow", "slow_error"):
                # Longer than the configured CLIENT_IDLE_TIMEOUT by 2.5x.
                time.sleep(.25)
                if operation == "slow_error":
                    raise ValueError("synthetic slow operation failure")
                return {"synthetic": True, "operation": "slow", "completed": True}
            if operation == "shutdown":
                self.stopping = True
                return {"stopping": True}
            if operation == "ping":
                return {"synthetic": True, "operation": "ping"}
            raise ValueError("unknown synthetic operation")

    bridge.serve(SyntheticDispatcher())


@contextlib.contextmanager
def isolated_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    if port == 8765:
        raise AssertionError("ephemeral reservation unexpectedly selected port 8765")
    process = subprocess.Popen([sys.executable, "-B", os.path.abspath(__file__),
                                "--synthetic-idle-server", str(port)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    connection = None
    try:
        deadline = time.monotonic() + 8
        while connection is None:
            if process.poll() is not None:
                _, error = process.communicate(timeout=1)
                raise RuntimeError("synthetic server exited: " + error.decode("utf-8", "replace"))
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=.1)
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("synthetic server did not become ready")
                time.sleep(.02)
        connection.settimeout(3)
        yield connection, port
    finally:
        if connection is not None:
            connection.close()
        if process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.3) as stop:
                    stop.sendall(b'{"id":999,"op":"shutdown"}\n')
                    stop.recv(1024)
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)


def rpc(connection, identifier, operation):
    connection.sendall((json.dumps({"id": identifier, "op": operation}) + "\n").encode("utf-8"))
    reply = bytearray()
    while not reply.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before the next same-client response")
        reply.extend(chunk)
    value = json.loads(reply.decode("utf-8"))
    if value["id"] != identifier:
        raise AssertionError("response identity mismatch")
    return value


class ClientIdleRegressionTests(unittest.TestCase):
    def test_work_longer_than_client_idle_keeps_same_connection_for_next_request(self):
        with isolated_server() as (connection, _):
            started = time.monotonic()
            first = rpc(connection, 1, "slow")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, .20)
            self.assertTrue(first["ok"])
            self.assertTrue(first["result"]["completed"])
            second = rpc(connection, 2, "ping")
            self.assertTrue(second["ok"])
            self.assertEqual(second["result"]["operation"], "ping")
            # Repeat on the same socket to catch state that only survives once.
            self.assertTrue(rpc(connection, 3, "slow")["ok"])
            self.assertTrue(rpc(connection, 4, "ping")["ok"])

    def test_slow_failed_operation_also_leaves_idle_window_for_next_request(self):
        with isolated_server() as (connection, _):
            failed = rpc(connection, 1, "slow_error")
            self.assertFalse(failed["ok"])
            self.assertIn("synthetic slow operation failure", failed["error"])
            self.assertTrue(rpc(connection, 2, "ping")["ok"])

    def test_truly_idle_client_is_disconnected_and_new_client_can_connect(self):
        with isolated_server() as (connection, port):
            self.assertTrue(rpc(connection, 1, "ping")["ok"])
            # The production recv timeout is 0.5 s; give the loop enough time to
            # wake, observe genuine post-response idle, and close the socket.
            time.sleep(.8)
            self.assertEqual(connection.recv(1), b"")
            with socket.create_connection(("127.0.0.1", port), timeout=1) as fresh:
                fresh.settimeout(2)
                self.assertTrue(rpc(fresh, 2, "ping")["ok"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--synthetic-idle-server":
        serve_synthetic(int(sys.argv[2]))
    else:
        unittest.main()
