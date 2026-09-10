from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from vision.active_view_replay import ActiveViewReplayError, run_active_view_replay


FIXTURE = Path(__file__).parent / "fixtures/active_view_replay.json"


def test_replay_selects_expected_pose_and_never_emits_execution() -> None:
    first = run_active_view_replay(FIXTURE)
    second = run_active_view_replay(FIXTURE)

    assert first.to_dict() == second.to_dict()
    assert first.frame_count == 5
    assert first.proposal_count == 3
    assert first.pose_selection_accuracy == pytest.approx(1.0)
    assert first.depth_quality_acceptance_rate == pytest.approx(0.5)
    assert first.identity_switches == 0
    assert first.execution_proposals == 0
    assert first.rejection_reasons == {
        "depth_quality_sufficient": 1,
        "target_not_covered": 1,
    }


def test_replay_rejects_nonfinite_stale_and_inconsistent_calibration(tmp_path: Path) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["frames"][1]["monotonic_ns"] = raw["frames"][0]["monotonic_ns"]
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="strictly increasing"):
        run_active_view_replay(stale)

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["frames"][0]["targets"][0]["center_xy_m"][0] = float("nan")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="non-finite"):
        run_active_view_replay(nonfinite)

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["frames"][0]["targets"][0]["calibration_id"] = "sha256:" + "9" * 64
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="calibration"):
        run_active_view_replay(mismatch)


def test_replay_rejects_path_traversal_commands_and_unbounded_frames(tmp_path: Path) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["include"] = "../outside.json"
    traversal = tmp_path / "traversal.json"
    traversal.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="path traversal"):
        run_active_view_replay(traversal)

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["move_l"] = [0, 0, 0]
    command = tmp_path / "command.json"
    command.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="command"):
        run_active_view_replay(command)

    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["frames"] = [{}] * 10_001
    too_many = tmp_path / "too-many.json"
    too_many.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ActiveViewReplayError, match="10,000"):
        run_active_view_replay(too_many)


def test_active_view_replay_is_a_public_pure_vision_interface() -> None:
    import vision

    assert "run_active_view_replay" in vision.__all__
    assert vision.run_active_view_replay is run_active_view_replay
