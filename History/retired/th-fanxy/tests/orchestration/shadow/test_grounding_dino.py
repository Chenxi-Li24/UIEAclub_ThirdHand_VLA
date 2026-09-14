import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.shadow.grounding_dino import (
    GroundingDinoCandidateProvider,
    GroundingDinoConfig,
    GroundingDinoUnavailable,
    HuggingFaceGroundingDinoBackend,
    RawGroundingCandidate,
)

ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = ROOT / "scripts" / "orchestration" / "check_grounding_dino.py"


class FixedBackend:
    def __init__(self, candidates: tuple[RawGroundingCandidate, ...]) -> None:
        self.candidates = candidates
        self.received_labels: tuple[str, ...] | None = None

    def predict(
        self,
        image_path: Path,
        labels: tuple[str, ...],
        config: GroundingDinoConfig,
    ) -> tuple[RawGroundingCandidate, ...]:
        assert image_path.is_file()
        assert config.model_path.is_dir()
        self.received_labels = labels
        return self.candidates


def local_inputs(tmp_path: Path) -> tuple[Path, Path]:
    model_path = tmp_path / "grounding-dino-local"
    model_path.mkdir()
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"checked-image-bytes")
    return model_path, image_path


def test_provider_normalizes_filters_and_keeps_proposals_non_actionable(tmp_path: Path):
    model_path, image_path = local_inputs(tmp_path)
    backend = FixedBackend(
        (
            RawGroundingCandidate(
                label="bottle",
                score=0.91,
                box_xyxy_px=(10.0, 20.0, 80.0, 160.0),
            ),
            RawGroundingCandidate(
                label="cup",
                score=0.30,
                box_xyxy_px=(1.0, 2.0, 5.0, 7.0),
            ),
            RawGroundingCandidate(
                label="chair",
                score=0.99,
                box_xyxy_px=(1.0, 2.0, 5.0, 7.0),
            ),
        )
    )
    provider = GroundingDinoCandidateProvider(
        GroundingDinoConfig(
            model_path=model_path,
            device="cpu",
            box_threshold=0.4,
            text_threshold=0.3,
            max_candidates=4,
        ),
        backend=backend,
    )

    candidates = provider.propose(image_path, (" Bottle ", "CUP"))

    assert backend.received_labels == ("bottle", "cup")
    assert len(candidates) == 1
    assert candidates[0].label == "bottle"
    assert candidates[0].score == 0.91
    assert candidates[0].box_xyxy_px == (10.0, 20.0, 80.0, 160.0)
    assert candidates[0].actionable is False
    assert candidates[0].evidence_id.startswith("sha256:")
    assert candidates[0].candidate_id.startswith("sha256:")


@pytest.mark.parametrize(
    "candidate",
    [
        RawGroundingCandidate(
            label="bottle",
            score=0.8,
            box_xyxy_px=(10.0, 20.0, 5.0, 40.0),
        ),
        RawGroundingCandidate(
            label="bottle",
            score=0.8,
            box_xyxy_px=(float("nan"), 20.0, 50.0, 40.0),
        ),
    ],
)
def test_provider_rejects_invalid_backend_boxes(tmp_path: Path, candidate):
    model_path, image_path = local_inputs(tmp_path)
    provider = GroundingDinoCandidateProvider(
        GroundingDinoConfig(model_path=model_path),
        backend=FixedBackend((candidate,)),
    )

    with pytest.raises(GroundingDinoUnavailable, match="box"):
        provider.propose(image_path, ("bottle",))


def test_provider_rejects_empty_duplicate_labels_and_symlink_image(tmp_path: Path):
    model_path, image_path = local_inputs(tmp_path)
    image_link = tmp_path / "linked.jpg"
    image_link.symlink_to(image_path)
    provider = GroundingDinoCandidateProvider(
        GroundingDinoConfig(model_path=model_path),
        backend=FixedBackend(()),
    )

    with pytest.raises(GroundingDinoUnavailable, match="unique"):
        provider.propose(image_path, ("bottle", " Bottle "))
    with pytest.raises(GroundingDinoUnavailable, match="non-empty"):
        provider.propose(image_path, (" ",))
    with pytest.raises(GroundingDinoUnavailable, match="symlink"):
        provider.propose(image_link, ("bottle",))


def test_config_requires_local_non_symlink_model_directory(tmp_path: Path):
    missing = tmp_path / "missing"
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "model-link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValidationError, match="local directory"):
        GroundingDinoConfig(model_path=missing)
    with pytest.raises(ValidationError, match="symlink"):
        GroundingDinoConfig(model_path=link)


def test_lazy_backend_reports_missing_dependencies_without_downloading(tmp_path: Path):
    model_path, image_path = local_inputs(tmp_path)

    def missing_dependencies():
        raise ImportError("transformers unavailable")

    backend = HuggingFaceGroundingDinoBackend(dependency_loader=missing_dependencies)
    provider = GroundingDinoCandidateProvider(
        GroundingDinoConfig(model_path=model_path),
        backend=backend,
    )

    with pytest.raises(GroundingDinoUnavailable, match="optional dependencies"):
        provider.propose(image_path, ("bottle",))


def test_smoke_cli_reports_unavailable_for_empty_local_model(tmp_path: Path):
    model_path = tmp_path / "empty-local-model"
    model_path.mkdir()

    completed = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--model", str(model_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["local_files_only"] is True
    assert payload["robot_execution_enabled"] is False
