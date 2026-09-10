from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TOP_LEVEL_DIRS = {
    "apps",
    "platform",
    "services",
    "skills",
    "drivers",
    "configs",
    "assets",
    "local",
    "runtime",
    "tools",
    "tests",
    "archive",
    "docs",
}


def test_required_top_level_directories_exist():
    missing = sorted(name for name in REQUIRED_TOP_LEVEL_DIRS if not (ROOT / name).is_dir())
    assert missing == []


def test_local_and_runtime_payloads_are_ignored():
    probes = ["local/sdk/startouch/libstartouch.so", "runtime/logs/service.log"]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT,
        input="\n".join(probes) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(probes)
