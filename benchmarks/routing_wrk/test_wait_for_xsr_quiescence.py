from __future__ import annotations

import importlib.util
import socket
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("wait_for_xsr_quiescence.py")
SPEC = importlib.util.spec_from_file_location("wait_for_xsr_quiescence", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def status_line(pid: int, active: int, reaped: int) -> bytes:
    entries = active * 6
    return (
        f"pid={pid} active_connection_sets={active} free_slot_sets={2730-active} "
        f"quarantined_slot_sets=0 accepted_total={reaped+active} reaped_total={reaped} "
        f"sockmap_entries={entries} routes_entries={entries} "
        f"http_flows_entries={active} route_decisions_entries=0\n"
    ).encode("ascii")


class FakeStatusServer:
    def __init__(self, path: Path, responses: list[bytes]):
        self.path = path
        self.responses = responses
        self.thread = threading.Thread(target=self.run)
        self.ready = threading.Event()

    def run(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.path))
            server.listen()
            self.ready.set()
            for response in self.responses:
                client, _ = server.accept()
                with client:
                    client.sendall(response)

    def __enter__(self) -> "FakeStatusServer":
        self.thread.start()
        self.ready.wait(2)
        return self

    def __exit__(self, *args: object) -> None:
        self.thread.join(2)


class QuiescenceTest(unittest.TestCase):
    def test_waits_for_all_maps_and_active_sets_to_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.sock"
            responses = [status_line(42, 2, 3), status_line(42, 0, 5)]
            with FakeStatusServer(path, responses):
                status = MODULE.wait_for_quiescence(path, 42, 2, minimum_reaped=5)
            self.assertEqual(status["active_connection_sets"], 0)
            self.assertEqual(status["sockmap_entries"], 0)
            self.assertEqual(status["reaped_total"], 5)

    def test_rejects_a_different_router_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.sock"
            with FakeStatusServer(path, [status_line(43, 0, 0)]):
                with self.assertRaisesRegex(RuntimeError, "PID changed"):
                    MODULE.wait_for_quiescence(path, 42, 1)


if __name__ == "__main__":
    unittest.main()
