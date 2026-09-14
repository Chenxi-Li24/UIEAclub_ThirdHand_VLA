from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_authorized_gripper_chain_without_hardware():
    result = subprocess.run(
        [
            "node",
            "--test",
            "tests/node/integration/authorized-gripper-chain.test.js",
            "tests/node/robot_service/execution-gateway.test.js",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
