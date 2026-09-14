import json
from pathlib import Path

import numpy as np
import pytest

from thirdhand_va.vision.perception.references import ReferenceBank, ReferenceError


def test_reference_manifest_round_trip_is_content_addressed(
    tmp_path: Path,
) -> None:
    descriptors = (
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.8, 0.2, 0.0], dtype=np.float32),
    )
    path = tmp_path / "manifest.json"

    bank = ReferenceBank.write_manifest(path, descriptors)
    loaded = ReferenceBank.from_manifest(path)

    assert len(bank) == 2
    assert len(loaded) == 2
    assert loaded.max_similarity(np.array([1.0, 0.0, 0.0])) == pytest.approx(1.0)


def test_reference_manifest_rejects_tampered_descriptor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    ReferenceBank.write_manifest(
        path,
        (np.array([1.0, 0.0, 0.0], dtype=np.float32),),
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["entries"][0]["descriptor"][0] = 0.5
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ReferenceError, match="content"):
        ReferenceBank.from_manifest(path)


def test_reference_bank_rejects_descriptor_dimension_mismatch() -> None:
    bank = ReferenceBank.from_descriptors(
        (np.array([1.0, 0.0], dtype=np.float32),)
    )

    with pytest.raises(ReferenceError, match="dimension"):
        bank.max_similarity(np.array([1.0, 0.0, 0.0], dtype=np.float32))
