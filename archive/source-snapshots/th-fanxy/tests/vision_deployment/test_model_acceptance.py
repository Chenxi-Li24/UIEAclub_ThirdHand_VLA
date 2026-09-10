from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision.model_acceptance import (
    ModelAcceptanceError,
    evaluate_task_checkpoint,
    validate_task_checkpoint,
)


def _manifest() -> dict:
    samples = []
    for index in range(12):
        samples.append(
            {
                "image_sha256": "sha256:" + f"{index + 1:064x}",
                "expected_objects": [
                    {"object_id": "center-bottle", "label": "bottle"},
                    {"object_id": "left-bottle", "label": "bottle"},
                ],
                "predictions": [
                    {
                        "identity_id": 11,
                        "label": "bottle",
                        "matched_object_id": "center-bottle",
                    },
                    {
                        "identity_id": 12,
                        "label": "bottle",
                        "matched_object_id": "left-bottle",
                    },
                ],
            }
        )
    return {
        "schema_version": 1,
        "created_at": "2026-08-07T03:00:00+00:00",
        "label_scope": ["bottle"],
        "samples": samples,
    }


def test_acceptance_is_content_addressed_and_bound_to_current_models(tmp_path: Path):
    detector_config = tmp_path / "detector.py"
    checkpoint = tmp_path / "detector.pth"
    detector_config.write_text("model = 'rtmdet'\n", encoding="utf-8")
    checkpoint.write_bytes(b"checkpoint")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    output = tmp_path / "acceptance.json"

    result = evaluate_task_checkpoint(
        manifest,
        detector_config_path=detector_config,
        detector_checkpoint_path=checkpoint,
        descriptor_model_id="facebook/dinov2-small",
        output_path=output,
    )

    assert result["validated"] is True
    assert result["accepted_labels"] == ["bottle"]
    assert result["metrics"]["precision"] == 1.0
    assert result["metrics"]["recall"] == 1.0
    assert result["metrics"]["id_continuity"] == 1.0
    assert result["content_id"].startswith("sha256:")
    assert validate_task_checkpoint(
        output,
        detector_config_path=detector_config,
        detector_checkpoint_path=checkpoint,
        descriptor_model_id="facebook/dinov2-small",
        requested_labels=("bottle",),
    ) == ("bottle",)

    checkpoint.write_bytes(b"different checkpoint")
    with pytest.raises(ModelAcceptanceError, match="checkpoint hash"):
        validate_task_checkpoint(
            output,
            detector_config_path=detector_config,
            detector_checkpoint_path=checkpoint,
            descriptor_model_id="facebook/dinov2-small",
            requested_labels=("bottle",),
        )


def test_acceptance_rejects_unmeasured_labels_and_identity_discontinuity(tmp_path: Path):
    detector_config = tmp_path / "detector.py"
    checkpoint = tmp_path / "detector.pth"
    detector_config.write_text("model = 'rtmdet'\n", encoding="utf-8")
    checkpoint.write_bytes(b"checkpoint")
    payload = _manifest()
    for index, sample in enumerate(payload["samples"]):
        sample["predictions"][0]["identity_id"] = index + 100
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "acceptance.json"

    result = evaluate_task_checkpoint(
        manifest,
        detector_config_path=detector_config,
        detector_checkpoint_path=checkpoint,
        descriptor_model_id="facebook/dinov2-small",
        output_path=output,
    )
    assert result["validated"] is False
    assert "id_continuity_below_threshold" in result["failure_reasons"]

    with pytest.raises(ModelAcceptanceError, match="not validated"):
        validate_task_checkpoint(
            output,
            detector_config_path=detector_config,
            detector_checkpoint_path=checkpoint,
            descriptor_model_id="facebook/dinov2-small",
            requested_labels=("cup",),
        )
