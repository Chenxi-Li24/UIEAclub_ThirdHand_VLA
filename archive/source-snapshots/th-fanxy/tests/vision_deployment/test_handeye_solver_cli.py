from __future__ import annotations

import json
from pathlib import Path

from test_calibration_pipeline import _write_handeye_manifest


def test_solver_cli_writes_validated_content_addressed_result(tmp_path: Path) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/solve_handeye_dataset.py"
    namespace: dict[str, object] = {
        "__name__": "solve_handeye_dataset_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    manifest = _write_handeye_manifest(tmp_path / "dataset")
    output = tmp_path / "result.json"

    result = namespace["solve_manifest"](manifest, output)

    assert result["validated"] is True
    assert result["content_id"].startswith("sha256:")
    assert result["dataset_id"].startswith("sha256:")
    assert result["validation"]["position_p95_m"] < 1e-7
    assert result["audit_payload"]["validation"]["position_rmse_m"] < 1e-7
    assert json.loads(output.read_text(encoding="utf-8")) == result
