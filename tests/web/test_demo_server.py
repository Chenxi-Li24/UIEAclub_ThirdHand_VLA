from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import shlex
import signal
import tempfile
import threading
import time
import unittest
from urllib import error as urllib_error
from urllib import request as urllib_request


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
        self.stdin = io.StringIO()
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


class BrokenInput:
    def write(self, _value):
        raise BrokenPipeError("closed")

    def flush(self):
        raise BrokenPipeError("closed")

    def close(self):
        pass


class DemoServerTests(unittest.TestCase):
    def test_process_start_failure_becomes_readable_failed_state(self):
        module = load_server()

        def fail_start(*_args, **_kwargs):
            raise OSError("launcher unavailable")

        controller = module.DemoController(ROOT, popen_factory=fail_start)
        self.assertFalse(controller.start())
        status = controller.status()
        self.assertEqual(status["state"], "FAILED")
        self.assertIn("launcher unavailable", status["message"])

    def test_broken_confirmation_pipe_becomes_readable_failed_state(self):
        module = load_server()
        process = FakeProcess()
        process.stdin = BrokenInput()
        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *_args, **_kwargs: process,
        )
        self.assertTrue(controller.start())
        controller._consume_line("AWAITING_CONFIRMATION=BROKEN_PIPE")
        self.assertFalse(controller.continue_step())
        status = controller.status()
        self.assertEqual(status["state"], "FAILED")
        self.assertIn("确认通道", status["message"])
        process.finish(1)

    def test_stop_signal_race_does_not_escape_as_server_error(self):
        module = load_server()
        process = FakeProcess()
        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *_args, **_kwargs: process,
            killpg=lambda *_args: (_ for _ in ()).throw(
                ProcessLookupError("gone")
            ),
        )
        self.assertTrue(controller.start())
        self.assertFalse(controller.stop())
        self.assertIn(controller.status()["state"], {"STOPPED", "FAILED"})
        process.finish(130)

    def test_http_api_rejects_invalid_actions_and_controls_owned_runner(self):
        module = load_server()
        process = FakeProcess()

        def killpg(_pid, signum):
            process.finish(-signum)

        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *args, **kwargs: process,
            killpg=killpg,
        )
        server = module.create_server(controller, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post(path):
            return urllib_request.urlopen(
                urllib_request.Request(base + path, method="POST"),
                timeout=2,
            )

        try:
            with urllib_request.urlopen(base + "/api/status", timeout=2) as response:
                self.assertEqual(response.status, 200)
            with self.assertRaises(urllib_error.HTTPError) as invalid_continue:
                post("/api/continue")
            self.assertEqual(invalid_continue.exception.code, 409)
            with post("/api/start") as response:
                self.assertEqual(response.status, 202)
            with self.assertRaises(urllib_error.HTTPError) as duplicate_start:
                post("/api/start")
            self.assertEqual(duplicate_start.exception.code, 409)
            controller._consume_line("AWAITING_CONFIRMATION=HTTP_STEP")
            with post("/api/continue") as response:
                self.assertEqual(response.status, 202)
            self.assertEqual(process.stdin.getvalue(), "\n")
            with post("/api/stop") as response:
                self.assertEqual(response.status, 202)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_http_auto_start_injects_fixed_mode_and_disables_continue(self):
        module = load_server()
        process = FakeProcess()
        popen_calls = []

        def popen(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return process

        def killpg(_pid, signum):
            process.finish(-signum)

        controller = module.DemoController(
            ROOT,
            popen_factory=popen,
            killpg=killpg,
        )
        server = module.create_server(controller, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post_status(path):
            try:
                with urllib_request.urlopen(
                    urllib_request.Request(base + path, method="POST"),
                    timeout=2,
                ) as response:
                    return response.status
            except urllib_error.HTTPError as exc:
                return exc.code

        try:
            self.assertEqual(post_status("/api/start-auto"), 202)
            self.assertEqual(len(popen_calls), 1)
            env = popen_calls[0][1]["env"]
            self.assertEqual(env["DEMO_RUN_MODE"], "automatic-three-cycle")
            self.assertEqual(env["DEMO_CYCLES"], "3")
            self.assertEqual(env["DEMO_CONFIRM_EACH_STEP"], "0")
            self.assertEqual(
                controller.status()["run_mode"],
                "automatic-three-cycle",
            )
            self.assertEqual(post_status("/api/start"), 409)
            self.assertEqual(post_status("/api/start-auto"), 409)
            controller._consume_line("AWAITING_CONFIRMATION=AUTO_STEP")
            self.assertEqual(post_status("/api/continue"), 409)
            self.assertEqual(process.stdin.getvalue(), "")
            self.assertEqual(post_status("/api/stop"), 202)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_dashboard_drives_complete_real_config_simulation(self):
        module = load_server()
        runner = ROOT / "web-control" / "scripts" / "fixed_pick_place.py"
        config = ROOT / "configs" / "tasks" / "fixed_pick_place.yaml"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "demo_fixed_pick_place.sh"
            command = " ".join(
                shlex.quote(value)
                for value in (
                    "/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python",
                    str(runner),
                    "--simulate",
                    "--config",
                    str(config),
                    "--speed-scale",
                    "1.0",
                    "--confirm-each-step",
                )
            )
            launcher.write_text(
                "#!/usr/bin/env bash\n"
                f"{command} <&0 &\n"
                "runner_pid=$!\n"
                'wait "$runner_pid"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            controller = module.DemoController(root)
            self.assertTrue(controller.start())
            confirmed_stages = []
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                status = controller.status()
                if status["state"] == "WAITING_CONFIRMATION":
                    stage = status["stage"]
                    if not confirmed_stages or confirmed_stages[-1] != stage:
                        confirmed_stages.append(stage)
                        self.assertTrue(controller.continue_step())
                elif status["state"] in {"COMPLETE", "FAILED", "STOPPED"}:
                    break
                time.sleep(0.01)
            status = controller.status()
            self.assertEqual(status["state"], "COMPLETE", status)
            self.assertEqual(len(confirmed_stages), 20, confirmed_stages)
            self.assertIn("CYCLE_1_RETURN_A_UP_TO_HOME", confirmed_stages)

    def test_dashboard_drives_three_cycle_automatic_simulation(self):
        module = load_server()
        runner = ROOT / "web-control" / "scripts" / "fixed_pick_place.py"
        config = ROOT / "configs" / "tasks" / "fixed_pick_place.yaml"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "demo_fixed_pick_place.sh"
            command = " ".join(
                shlex.quote(value)
                for value in (
                    "/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python",
                    str(runner),
                    "--simulate",
                    "--config",
                    str(config),
                    "--speed-scale",
                    "1.0",
                    "--cycles",
                    "3",
                    "--automatic-three-cycle",
                )
            )
            launcher.write_text(
                "#!/usr/bin/env bash\n"
                '[[ "$DEMO_RUN_MODE" == "automatic-three-cycle" ]]\n'
                '[[ "$DEMO_CYCLES" == "3" ]]\n'
                '[[ "$DEMO_CONFIRM_EACH_STEP" == "0" ]]\n'
                f"{command}\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            controller = module.DemoController(root)
            self.assertTrue(controller.start("automatic-three-cycle"))
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                status = controller.status()
                if status["state"] in {"COMPLETE", "FAILED", "STOPPED"}:
                    break
                time.sleep(0.02)
            status = controller.status()
            output = "\n".join(status["log_tail"])
            self.assertEqual(status["state"], "COMPLETE", status)
            self.assertIn("CYCLE 3/3 COMPLETE", output)
            self.assertNotIn("AWAITING_CONFIRMATION=", output)

    def test_page_has_start_stop_status_and_log(self):
        html = (ROOT / "web-control" / "demo" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="start-demo"', html)
        self.assertIn('id="start-auto-demo"', html)
        self.assertIn("手动逐步演示", html)
        self.assertIn("一键自动循环 3 次", html)
        self.assertIn('id="stop-demo"', html)
        self.assertIn('id="continue-demo"', html)
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

    def test_continue_writes_only_when_owned_runner_is_waiting(self):
        module = load_server()
        process = FakeProcess()
        controller = module.DemoController(
            ROOT,
            popen_factory=lambda *args, **kwargs: process,
        )
        self.assertFalse(controller.continue_step())
        self.assertTrue(controller.start())
        controller._consume_line("AWAITING_CONFIRMATION=OPEN_GRIPPER_READY")
        self.assertEqual(controller.status()["state"], "WAITING_CONFIRMATION")
        self.assertTrue(controller.continue_step())
        self.assertEqual(process.stdin.getvalue(), "\n")
        process.finish(130)

    def test_real_bash_background_runner_receives_web_confirmation(self):
        module = load_server()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "demo_fixed_pick_place.sh"
            launcher.write_text(
                "#!/usr/bin/env bash\n"
                "python3 -u -c '"
                'print(\"AWAITING_CONFIRMATION=TEST_STEP\", flush=True); '
                "input(); "
                'print(\"PICK AND PLACE COMPLETE\", flush=True)'
                "' <&0 &\n"
                "runner_pid=$!\n"
                'wait "$runner_pid"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            controller = module.DemoController(root)
            self.assertTrue(controller.start())
            deadline = time.monotonic() + 3
            while (
                controller.status()["state"] != "WAITING_CONFIRMATION"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(
                controller.status()["state"],
                "WAITING_CONFIRMATION",
            )
            self.assertTrue(controller.continue_step())
            deadline = time.monotonic() + 3
            while (
                controller.status()["owned"]
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            status = controller.status()
            self.assertEqual(status["state"], "COMPLETE")
            self.assertIn("PICK AND PLACE COMPLETE", status["log_tail"])

    def test_real_bash_process_group_stops_while_waiting(self):
        module = load_server()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            launcher = scripts / "demo_fixed_pick_place.sh"
            launcher.write_text(
                "#!/usr/bin/env bash\n"
                "python3 -u -c '"
                "import signal, sys; "
                "signal.signal(signal.SIGINT, "
                "lambda *_: sys.exit(130)); "
                'print(\"AWAITING_CONFIRMATION=TEST_STOP\", flush=True); '
                "input()"
                "' <&0 &\n"
                "runner_pid=$!\n"
                'wait "$runner_pid"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            controller = module.DemoController(root)
            self.assertTrue(controller.start())
            deadline = time.monotonic() + 3
            while (
                controller.status()["state"] != "WAITING_CONFIRMATION"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(controller.stop())
            deadline = time.monotonic() + 3
            while (
                controller.status()["state"] != "STOPPED"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(controller.status()["state"], "STOPPED")

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
