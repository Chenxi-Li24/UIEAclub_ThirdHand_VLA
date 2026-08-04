from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from vision_models.offline_replay import (
    IdentityReplayFormatError,
    ReplayLimits,
    _validate_npy_header,
    load_remind3d_config,
    run_identity_replay,
    write_report_atomic,
)


FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = FIXTURES / "remind3d_observations.json"
PROJECT_ROOT = Path(__file__).parents[4]


def test_replay_preserves_long_gap_ids_and_rejects_ambiguous_assignment():
    report = run_identity_replay(MANIFEST)
    by_frame = {frame.frame_id: frame for frame in report.frames}
    assert [(item.object_key, item.identity_id) for item in by_frame[0].assignments] == [
        ("cup_a", 1),
        ("cup_b", 2),
    ]
    assert [(item.object_key, item.identity_id) for item in by_frame[3].assignments] == [
        ("cup_a", 1)
    ]
    ambiguous = by_frame[4].assignments[0]
    assert ambiguous.identity_id is None
    assert ambiguous.status == "ambiguous"
    assert ambiguous.reason == "appearance_candidates_within_margin"
    assert report.metrics.frame_count == 5
    assert report.metrics.observation_count == 5
    assert report.metrics.ambiguous_count == 1
    assert report.metrics.forced_ambiguous_assignments == 0
    assert report.metrics.id_switches == 0
    assert report.metrics.known_identity_transitions == 2


def test_replay_output_is_byte_deterministic(tmp_path):
    report = run_identity_replay(MANIFEST)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_report_atomic(first, report)
    write_report_atomic(second, report)
    assert first.read_bytes() == second.read_bytes()


def copied_manifest(tmp_path):
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    shutil.copyfile(FIXTURES / payload["descriptor_npz"], tmp_path / payload["descriptor_npz"])
    return payload


def write_manifest(tmp_path, payload):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda payload: payload.update(schema_version=2), "schema_version"),
        (
            lambda payload: payload["frames"][1].update(frame_id=0),
            "frame_id",
        ),
        (
            lambda payload: payload["frames"][1].update(monotonic_ns=0),
            "strictly increasing",
        ),
        (
            lambda payload: payload["frames"][0].update(command="move"),
            "execution field",
        ),
        (
            lambda payload: payload["frames"][0]["observations"][0].update(
                descriptor_key="missing"
            ),
            "descriptor",
        ),
    ],
)
def test_replay_rejects_malformed_or_execution_bearing_manifests(tmp_path, mutation, error):
    payload = copied_manifest(tmp_path)
    mutation(payload)
    with pytest.raises(IdentityReplayFormatError, match=error):
        run_identity_replay(write_manifest(tmp_path, payload))


def test_replay_rejects_descriptor_path_traversal(tmp_path):
    payload = copied_manifest(tmp_path)
    payload["descriptor_npz"] = "../outside.npz"
    with pytest.raises(IdentityReplayFormatError, match="relative"):
        run_identity_replay(write_manifest(tmp_path, payload))


def test_replay_enforces_manifest_and_frame_resource_limits(tmp_path):
    payload = copied_manifest(tmp_path)
    manifest = write_manifest(tmp_path, payload)
    with pytest.raises(IdentityReplayFormatError, match="manifest exceeds"):
        run_identity_replay(manifest, limits=ReplayLimits(max_manifest_bytes=20))
    with pytest.raises(IdentityReplayFormatError, match="too many frames"):
        run_identity_replay(manifest, limits=ReplayLimits(max_frames=2))


def test_replay_rejects_oversized_descriptor_vectors_before_identity_processing(tmp_path):
    payload = copied_manifest(tmp_path)
    keys = {
        item["descriptor_key"]
        for frame in payload["frames"]
        for item in frame["observations"]
    }
    npz_path = tmp_path / payload["descriptor_npz"]
    np.savez(npz_path, **{key: np.ones(9, dtype=np.float32) for key in keys})

    with pytest.raises(IdentityReplayFormatError, match="descriptor dimension"):
        run_identity_replay(
            write_manifest(tmp_path, payload),
            limits=ReplayLimits(max_descriptor_dimension=8),
        )


def test_replay_wraps_object_descriptor_load_failure_as_format_error(tmp_path):
    payload = copied_manifest(tmp_path)
    keys = {
        item["descriptor_key"]
        for frame in payload["frames"]
        for item in frame["observations"]
    }
    npz_path = tmp_path / payload["descriptor_npz"]
    arrays = {key: np.asarray([object()], dtype=object) for key in keys}
    np.savez(npz_path, **arrays)

    with pytest.raises(IdentityReplayFormatError, match="numeric scalar dtype"):
        run_identity_replay(write_manifest(tmp_path, payload))


def test_npy_header_is_validated_before_declared_shape_can_allocate_memory():
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        stream,
        {
            "descr": np.dtype("float32").str,
            "fortran_order": False,
            "shape": (1_000_000_000,),
        },
    )
    payload = stream.getvalue()

    with pytest.raises(IdentityReplayFormatError, match="descriptor dimension"):
        _validate_npy_header(
            io.BytesIO(payload),
            entry_size=len(payload),
            limits=ReplayLimits(),
        )


def test_deployment_config_is_fail_closed_and_matches_selected_stack():
    config = load_remind3d_config(PROJECT_ROOT / "configs/vision/remind3d.yaml")
    assert config.canonical_image == "lumos_native_seucm"
    assert config.detector_backend == "rtmdet_tiny_ins"
    assert config.primary_descriptor == "dinov3_vits16"
    assert config.fallback_descriptor == "facebook/dinov2-small"
    assert config.dino_max_long_side == 640
    assert config.gpu_memory_limit_gib == 7.2
    assert config.latency_p95_limit_ms == 300.0
    assert not config.robot_execution_enabled
