import hashlib
import json
from pathlib import Path

import pytest

from tools.assets.import_assets import import_asset
from tools.assets.verify_assets import verify_manifest


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_manifest_accepts_matching_local_asset(tmp_path: Path):
    payload = b"verified-model"
    asset = tmp_path / "local/models/asr/medium/model.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "asr.medium",
                        "kind": "model",
                        "required": True,
                        "relativePath": "local/models/asr/medium/model.bin",
                        "sha256": _sha(payload),
                        "sizeBytes": len(payload),
                        "licenseStatus": "recorded",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = verify_manifest(tmp_path, manifest)

    assert report["ok"] is True
    assert report["assets"][0]["status"] == "ready"


def test_verify_manifest_rejects_hash_mismatch(tmp_path: Path):
    asset = tmp_path / "local/sdk/startouch/libstartouch.so"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"unexpected")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "startouch.sdk",
                        "kind": "sdk",
                        "required": True,
                        "relativePath": "local/sdk/startouch/libstartouch.so",
                        "sha256": "0" * 64,
                        "sizeBytes": 10,
                        "licenseStatus": "unknown",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = verify_manifest(tmp_path, manifest)

    assert report["ok"] is False
    assert report["assets"][0]["status"] == "hash_mismatch"


def test_verify_manifest_rejects_paths_outside_project(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "escape",
                        "kind": "model",
                        "required": True,
                        "relativePath": "../outside.bin",
                        "sha256": "0" * 64,
                        "sizeBytes": 1,
                        "licenseStatus": "recorded",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside project root"):
        verify_manifest(tmp_path, manifest)


def test_import_asset_refuses_different_existing_destination(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"new")
    destination = tmp_path / "project/local/models/model.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")

    result = import_asset(
        source,
        destination,
        project_root=tmp_path / "project",
        expected_sha256=_sha(b"new"),
    )

    assert result["status"] == "destination_conflict"
    assert destination.read_bytes() == b"existing"
