from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT.parents[1]


def test_source_map_has_complete_records() -> None:
    payload = json.loads((ROOT / "SOURCE_MAP.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["source_commit"]) == 40
    assert payload["records"]
    for record in payload["records"]:
        assert set(record) == {"source_path", "source_sha256", "sdk_paths", "notes"}
        assert len(record["source_sha256"]) == 64
        assert record["sdk_paths"]


def test_source_verifier_accepts_recorded_originals() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_source_unchanged.py"),
            "--source-root",
            str(SOURCE_ROOT),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "all selected source files match" in result.stdout


def test_manifest_uses_sha256sum_compatible_layout() -> None:
    lines = (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        digest, relative = line.split("  ", maxsplit=1)
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)
        path = Path(relative)
        assert relative
        assert not path.is_absolute()
        assert ".." not in path.parts
