from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import signal
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "web-control" / "demo" / "demo_server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("fixed_demo_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProcess:
    def __init__(self, output="", returncode=None):
        self.pid = 4242
        self.stdout = io.StringIO(output)
        self._returncode = returncode
        self._finished = threading.Event()
        if returncode is not None:
            self._finished.set()

    def poll(self):
        return self._returncode if self._finished.is_set() else None

    def wait(self):
        self._finished.wait(2)
        return self._returncode

    def finish(self, returncode):
        self._returncode = returncode
        self._finished.set()


class DemoServerTests(unittest.TestCase):
    def test_page_has_start_stop_status_and_log(self):
        html = (ROOT / "web-control" / "demo" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="start-demo"', html)
        self.assertIn('id="stop-demo"', html)
        self.assertIn('id="demo-status"', html)
        self.assertIn('id="demo-log"', html)

    def test_server_defaults_to_ubuntu_localhost(self):
        module = load_server()
        self.assertEqual(module.DEFAULT_HOST, "127.0.0.1")
        self.assertEqual(module.DEFAULT_PORT, 8766)

    def test_idle_status_does_not_spawn_or_open_can(self):
        module = load_server()
        calls = []
        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        status = controller.status()
        self.assertEqual(status["state"], "IDLE")
        self.assertEqual(calls, [])
        self.assertFalse(status["owned"])

    def test_stop_signals_only_owned_process_group(self):
        module = load_server()
        process = FakeProcess()
        signals = []

        def killpg(pid, signum):
            signals.append((pid, signum))
            process.finish(-signum)

        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *args, **kwargs: process,
            killpg=killpg,
        )
        self.assertTrue(controller.start())
        self.assertTrue(controller.stop())
        self.assertEqual(signals, [(process.pid, signal.SIGINT)])

    def test_resource_conflict_is_reported_without_signalling(self):
        module = load_server()
        process = FakeProcess(
            "RESOURCE_CONFLICT\n"
            "PICK AND PLACE FAILED\n"
            "FAILED_STAGE=RESOURCE_PREFLIGHT\n",
            returncode=23,
        )
        signals = []
        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *args, **kwargs: process,
            killpg=lambda pid, signum: signals.append((pid, signum)),
        )
        self.assertTrue(controller.start())
        deadline = time.monotonic() + 2
        while (
            controller.status()["state"] == "PREFLIGHT"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        status = controller.status()
        self.assertEqual(status["state"], "FAILED")
        self.assertIn("RESOURCE_CONFLICT", status["message"])
        self.assertEqual(status["stage"], "RESOURCE_PREFLIGHT")
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
