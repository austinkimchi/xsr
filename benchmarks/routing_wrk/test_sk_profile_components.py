from __future__ import annotations

import importlib.util
import io
import socket
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "sk_profile_components.py"
SPEC = importlib.util.spec_from_file_location("sk_profile_components", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


PROFILE_RESPONSE = """\
profile_enabled=1 cpu_count=2 stage_count=3
cpu=0 parse_signal_count=2 parse_signal_total_ns=2000 decision_count=2 decision_total_ns=400 redirect_count=2 redirect_total_ns=100
cpu=1 parse_signal_count=3 parse_signal_total_ns=4500 decision_count=3 decision_total_ns=900 redirect_count=3 redirect_total_ns=250
"""


class FakeProfileServer:
    def __init__(self, path: Path, response: str):
        self.path = path
        self.response = response
        self.command = ""
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run)

    def run(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            self.path.unlink(missing_ok=True)
            server.bind(str(self.path))
            server.listen(1)
            self.ready.set()
            client, _ = server.accept()
            with client:
                self.command = client.recv(128).decode("ascii").strip()
                client.sendall(self.response.encode("ascii"))

    def __enter__(self) -> "FakeProfileServer":
        self.thread.start()
        self.ready.wait(2)
        return self

    def __exit__(self, *args: object) -> None:
        self.thread.join(2)
        self.path.unlink(missing_ok=True)


class ProfileComponentsTest(unittest.TestCase):
    def test_sums_every_cpu_and_computes_stage_means(self) -> None:
        result = MODULE.aggregate_response(PROFILE_RESPONSE)
        self.assertEqual(result["completed_requests"], 5)
        self.assertEqual(result["stages"]["parse_signal"]["total_ns"], 6500)
        self.assertEqual(result["parse_signal_mean_us"], 1.3)
        self.assertEqual(result["decision_mean_us"], 0.26)
        self.assertEqual(result["redirect_mean_us"], 0.07)
        self.assertAlmostEqual(result["total_profiled_kernel_mean_us"], 1.63)

    def test_rejects_inconsistent_completed_request_counts(self) -> None:
        inconsistent = PROFILE_RESPONSE.replace("redirect_count=3", "redirect_count=2")
        with self.assertRaisesRegex(RuntimeError, "stage counts differ"):
            MODULE.aggregate_response(inconsistent)

    def test_read_and_reset_commands_use_the_control_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.sock"
            with FakeProfileServer(path, PROFILE_RESPONSE) as server:
                raw = MODULE.request(path, "read")
            self.assertEqual(server.command, "profile read")
            self.assertEqual(MODULE.aggregate_response(raw)["completed_requests"], 5)

            with FakeProfileServer(path, "profile_enabled=1 reset=ok\n") as server:
                raw = MODULE.request(path, "reset")
            self.assertEqual(server.command, "profile reset")
            MODULE.confirm_reset(raw)

    def test_csv_and_human_formats_include_all_measured_stages(self) -> None:
        result = MODULE.aggregate_response(PROFILE_RESPONSE)
        output = io.StringIO()
        MODULE.render_csv(result, output)
        csv_text = output.getvalue()
        human_text = MODULE.render_human(result)
        for stage in MODULE.STAGES:
            self.assertIn(stage, csv_text)
            self.assertIn(stage, human_text)
        self.assertNotIn("other", csv_text)

    def test_backend_response_path_precedes_request_profile_accounting(self) -> None:
        source = (ROOT / "bpf" / "programs" / "sk_router.bpf.c").read_text()
        backend = source.index("if (entry->flags & SK_ROUTER_FLAG_BACKEND)")
        response_redirect = source.index("bpf_sk_redirect_map", backend)
        request_profile = source.index("profile_flow = bpf_map_lookup_elem", backend)
        request_redirect = source.index("bpf_sk_redirect_map", request_profile)
        records = source.index("sk_profile_record(SK_PROFILE_PARSE_SIGNAL", request_redirect)
        self.assertLess(backend, response_redirect)
        self.assertLess(response_redirect, request_profile)
        self.assertLess(request_profile, request_redirect)
        self.assertLess(request_redirect, records)


if __name__ == "__main__":
    unittest.main()
