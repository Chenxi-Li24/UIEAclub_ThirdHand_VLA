from pathlib import Path

import numpy as np
import pytest

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.perception.fixed_bottle import FixedBottleVerifier
from thirdhand_va.vision.perception.interfaces import RawCandidate
from thirdhand_va.vision.perception.references import ReferenceBank


@pytest.fixture
def config() -> VisionConfig:
    return VisionConfig.from_yaml(Path("configs/vision.yaml"))


def bottle_mask() -> np.ndarray:
    mask = np.zeros((80, 40), dtype=bool)
    mask[5:20, 16:24] = True
    mask[20:75, 10:30] = True
    return mask


def candidate(
    *,
    label: str = "coca-cola plastic bottle",
    score: float = 0.92,
    mask: np.ndarray | None = None,
    descriptor: np.ndarray | None = None,
    detection_id: int = 1,
) -> RawCandidate:
    return RawCandidate(
        detection_id=detection_id,
        prompt_label=label,
        score=score,
        bbox_xyxy=(5.0, 3.0, 35.0, 77.0),
        mask=bottle_mask() if mask is None else mask,
        descriptor=(
            np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            if descriptor is None
            else descriptor
        ),
    )


def verifier(config: VisionConfig) -> FixedBottleVerifier:
    references = ReferenceBank.from_descriptors(
        (np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),)
    )
    return FixedBottleVerifier(config, references)


def test_coke_can_is_rejected_even_with_brand_score(
    config: VisionConfig,
) -> None:
    can = np.zeros((80, 40), dtype=bool)
    can[20:60, 10:30] = True

    result = verifier(config).verify(
        np.zeros((80, 40, 3), dtype=np.uint8),
        (candidate(mask=can),),
    )

    assert result[0].authorized is False
    assert "container_type_not_bottle" in result[0].reasons


def test_pepsi_reference_conflict_is_rejected(config: VisionConfig) -> None:
    result = verifier(config).verify(
        np.zeros((80, 40, 3), dtype=np.uint8),
        (
            candidate(
                descriptor=np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
            ),
        ),
    )

    assert result[0].authorized is False
    assert "fixed_reference_mismatch" in result[0].reasons


def test_fixed_bottle_requires_valid_mask_and_reference(
    config: VisionConfig,
) -> None:
    result = verifier(config).verify(
        np.zeros((80, 40, 3), dtype=np.uint8),
        (candidate(),),
    )

    assert len(result) == 1
    assert result[0].authorized is True
    assert result[0].reasons == ()


def test_close_overlapping_competitor_blocks_authorization(
    config: VisionConfig,
) -> None:
    coke = candidate(score=0.70)
    pepsi = candidate(
        label="pepsi bottle",
        score=0.68,
        detection_id=2,
    )

    result = verifier(config).verify(
        np.zeros((80, 40, 3), dtype=np.uint8),
        (coke, pepsi),
    )

    assert result[0].authorized is False
    assert "competitor_margin_too_small" in result[0].reasons


def test_empty_reference_bank_fails_closed(config: VisionConfig) -> None:
    result = FixedBottleVerifier(config, ReferenceBank.empty()).verify(
        np.zeros((80, 40, 3), dtype=np.uint8),
        (candidate(),),
    )

    assert result[0].authorized is False
    assert "fixed_reference_missing" in result[0].reasons
