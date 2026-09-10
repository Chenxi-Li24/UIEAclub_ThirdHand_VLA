import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str):
    env = {**os.environ, "THIRDHAND_PROFILE": "simulation"}
    return subprocess.run(
        [str(ROOT / "thirdhand"), *args, "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_simulated_start_status_stop_cycle():
    started = _run("start")
    assert started.returncode == 0, started.stderr
    assert json.loads(started.stdout)["overall"] == "ready"

    first_pids = {
        service_id: service["pid"]
        for service_id, service in json.loads(started.stdout)["services"].items()
    }
    started_again = _run("start")
    second_pids = {
        service_id: service["pid"]
        for service_id, service in json.loads(started_again.stdout)["services"].items()
    }
    assert second_pids == first_pids

    status = _run("status")
    assert status.returncode == 0
    assert json.loads(status.stdout)["services"]["robot"]["state"] == "ready"

    stopped = _run("stop")
    assert stopped.returncode == 0, stopped.stderr
    assert json.loads(stopped.stdout)["overall"] == "stopped"
