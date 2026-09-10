#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OperationsTests(unittest.TestCase):
    def test_runtime_env_reuses_9981_chain_with_only_new_ports(self) -> None:
        text = (ROOT / "config" / "runtime.env.example").read_text("utf-8")
        expected = {
            "WEB_HOST=127.0.0.1",
            "WEB_PORT=9983",
            "VOICE_HOST=127.0.0.1",
            "VOICE_PORT=3004",
            "VOICE_ENDPOINT=ws://127.0.0.1:3004/v1/voice",
            "LANGUAGE_UPSTREAM_WS=ws://127.0.0.1:3000/ws",
            "LOCAL_ROBOT_BRIDGE_ENABLED=0",
            "LOCAL_CAMERA_BRIDGE_ENABLED=0",
            "CAMERA_ENABLED=0",
            "LUMOS_MANAGED=0",
        }
        self.assertTrue(expected.issubset(set(text.splitlines())))

    def test_scripts_are_manual_project_local_and_never_install_autostart(self) -> None:
        combined = "\n".join(
            (ROOT / "scripts" / name).read_text("utf-8")
            for name in ("start", "stop", "status")
        )
        self.assertIn('dirname -- "${BASH_SOURCE[0]}"', combined)
        self.assertNotIn("/home/nieqingcao/TH_new_asr_0820", combined)
        self.assertNotIn("systemctl", combined)
        self.assertNotIn("crontab", combined)
        self.assertNotIn("/etc/", combined)

    def test_stop_validates_pid_cwd_before_sigterm(self) -> None:
        text = (ROOT / "scripts" / "stop").read_text("utf-8")
        self.assertIn("/proc/$pid/cwd", text)
        self.assertIn("resolved_cwd", text)
        self.assertLess(text.index("resolved_cwd"), text.index("kill -TERM"))

    def test_start_refuses_existing_pids_and_uses_bundled_runtime(self) -> None:
        text = (ROOT / "scripts" / "start").read_text("utf-8")
        self.assertIn("runtime/python/bin/python3.11", text)
        self.assertIn("runtime/node/bin/node", text)
        self.assertIn("kill -0", text)
        self.assertIn("voice_bridge.py", text)
        self.assertIn("proxy.js", text)

    def test_start_checks_listener_on_configured_bind_address_only(self) -> None:
        text = (ROOT / "scripts" / "start").read_text("utf-8")
        self.assertIn('ss -ltnH "src $host and sport = :$port"', text)
        self.assertIn('refuse_listener "$VOICE_HOST" "$VOICE_PORT"', text)
        self.assertIn('refuse_listener "$WEB_HOST" "$WEB_PORT"', text)
        self.assertNotIn('ss -ltn "sport = :$port"', text)

    def test_delivery_uses_offline_verifiers_instead_of_downloaders(self) -> None:
        scripts = ROOT / "scripts"
        self.assertFalse((scripts / "install").exists())
        self.assertFalse((scripts / "download-models").exists())
        self.assertTrue((scripts / "verify-runtime").is_file())
        self.assertTrue((scripts / "verify-models").is_file())


if __name__ == "__main__":
    unittest.main()
