import json
import os
from pathlib import Path
import queue
import shutil
import socketserver
import subprocess
import threading
import time
import unittest


FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
NGRAM_FEATURES = 4096
NGRAM_MASK = NGRAM_FEATURES - 1
ROUTE_COUNTER_NAMES = {
    "coding": "route coding",
    "general": "route general",
    "reasoning": "route reasoning",
}


def hash3(c0, c1, c2):
    value = FNV_OFFSET
    for char in (c0, c1, c2):
        value ^= char
        value = (value * FNV_PRIME) & 0xFFFFFFFF
    return value & NGRAM_MASK


def route_prompt(model, prompt):
    scores = list(model["bias"])
    data = prompt.lower().encode()

    for i in range(max(0, len(data) - 2)):
        feature = hash3(data[i], data[i + 1], data[i + 2])
        for class_id in range(3):
            scores[class_id] += model["weights"][class_id][feature]

    route = max(range(3), key=lambda class_id: scores[class_id])
    return model["classes"][route], scores


class OpenAIRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        request = b""

        while b"\r\n\r\n" not in request:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            request += chunk

        header_bytes, body = request.split(b"\r\n\r\n", 1)
        headers = header_bytes.decode("iso-8859-1", errors="replace").split("\r\n")
        content_length = 0

        for header in headers[1:]:
            name, _, value = header.partition(":")
            if name.lower() == "content-length":
                content_length = int(value.strip())

        while len(body) < content_length:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            body += chunk

        self.server.requests.put(body[:content_length])
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 12\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b'{"ok":true}\n'
        )


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def openai_chat_body(prompt):
    return json.dumps(
        {
            "model": "gpt-4.1-mini",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0,
        },
        separators=(",", ":"),
    )


class NgramRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_path = Path(__file__).resolve().parents[1] / "models" / "xdp_ngram_model_fnv.json"
        with model_path.open() as file:
            cls.model = json.load(file)

    def test_model_shape_matches_xdp_constants(self):
        self.assertEqual(["coding", "general", "reasoning"], self.model["classes"])
        self.assertEqual([3, 3], self.model["ngram_range"])
        self.assertEqual(NGRAM_FEATURES, self.model["n_features"])
        self.assertEqual("xdp_fnv_v1", self.model["hash"])
        self.assertEqual(3, len(self.model["weights"]))
        self.assertTrue(all(len(weights) == NGRAM_FEATURES for weights in self.model["weights"]))

    def test_prompt_routes_are_deterministic(self):
        cases = {
            "Debug this Python TypeError in my code": "coding",
            "Write a Python function that parses JSON safely": "coding",
            "Refactor this Rust code to improve error handling": "coding",
            "Solve this logic puzzle step by step": "reasoning",
            "What is the capital of France?": "general",
            "Explain renewable energy in simple terms": "general",
            "Optimize a C implementation of quicksort.": "coding",
            "Analyze the tradeoffs and choose a strategy for planning a migration with rollback risk.": "reasoning",
            "Give me a practical checklist for planning a monthly budget." : "general",
            "Explain sleep hygiene in simple terms for a beginner.": "general"
        }

        for prompt, expected_route in cases.items():
            with self.subTest(prompt=prompt):
                route, scores = route_prompt(self.model, prompt)
                print(f"{prompt!r} -> {route} {scores}")
                self.assertEqual(expected_route, route)

    def test_openai_chat_request_routes_through_xdp(self):
        if os.environ.get("RUN_XDP_INTEGRATION") != "1":
            self.skipTest("set RUN_XDP_INTEGRATION=1 to run the XDP integration test")

        if os.geteuid() != 0:
            self.skipTest("XDP integration test must run as root")

        if not shutil.which("curl"):
            self.skipTest("curl is required to send the request from the network namespace")

        if not shutil.which("ip"):
            self.skipTest("iproute2 is required for the network namespace check")

        stdbuf = shutil.which("stdbuf")
        project_dir = Path(__file__).resolve().parents[1]
        prompt = "Optimize a C implementation of quicksort and explain the bug in this code."
        expected_route, expected_scores = route_prompt(self.model, prompt)
        counter_name = ROUTE_COUNTER_NAMES[expected_route]
        port = int(os.environ.get("XDP_TEST_PORT", "8081"))
        server_host = os.environ.get("XDP_TEST_SERVER_HOST", "0.0.0.0")
        client_url = os.environ.get(
            "XDP_TEST_URL", f"http://10.10.0.1:{port}/v1/chat/completions"
        )
        namespace = os.environ.get("XDP_TEST_NETNS", "ns1")
        body = openai_chat_body(prompt)

        self.assertEqual("coding", expected_route, expected_scores)

        try:
            subprocess.run(
                ["ip", "link", "show", "dev", "veth0"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            self.skipTest("veth0 is required for the XDP integration test")

        try:
            subprocess.run(
                ["ip", "netns", "exec", namespace, "true"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            self.skipTest(f"network namespace {namespace!r} is required")

        subprocess.run(["make"], cwd=project_dir, check=True)
        subprocess.run(
            ["ip", "link", "set", "dev", "veth0", "xdp", "off"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        server = ThreadedTCPServer((server_host, port), OpenAIRequestHandler)
        server.requests = queue.Queue()
        router = None
        output = queue.Queue()

        def read_router_output():
            for line in router.stdout:
                output.put(line.rstrip())

        try:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()

            router_command = [str(project_dir / "xdp_router")]
            if stdbuf:
                router_command = [stdbuf, "-oL", "-eL", "./xdp_router"]

            router = subprocess.Popen(
                router_command,
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            reader = threading.Thread(target=read_router_output, daemon=True)
            reader.start()

            deadline = time.time() + 10
            attached = False
            while time.time() < deadline:
                try:
                    line = output.get(timeout=0.2)
                except queue.Empty:
                    if router.poll() is not None:
                        self.fail(f"xdp_router exited early with code {router.returncode}")
                    continue

                if "XDP attached" in line:
                    attached = True
                    break

            self.assertTrue(attached, "xdp_router did not attach within 10 seconds")

            subprocess.run(
                [
                    "ip",
                    "netns",
                    "exec",
                    namespace,
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/json",
                    "--data-binary",
                    body,
                    client_url,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            received = server.requests.get(timeout=5)
            self.assertEqual(json.loads(body), json.loads(received))

            deadline = time.time() + 10
            observed_count = 0
            while time.time() < deadline:
                try:
                    line = output.get(timeout=0.2)
                except queue.Empty:
                    if router.poll() is not None:
                        self.fail(f"xdp_router exited early with code {router.returncode}")
                    continue

                prefix = f"{counter_name}: "
                if line.startswith(prefix):
                    observed_count = int(line[len(prefix) :])
                    if observed_count > 0:
                        break

            self.assertGreater(
                observed_count,
                0,
                f"xdp_router did not increment {counter_name!r} for OpenAI body",
            )
        finally:
            if router:
                router.terminate()
                try:
                    router.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    router.kill()
                    router.wait(timeout=5)
                if router.stdout:
                    router.stdout.close()

            server.shutdown()
            server.server_close()
            subprocess.run(
                ["ip", "link", "set", "dev", "veth0", "xdp", "off"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
