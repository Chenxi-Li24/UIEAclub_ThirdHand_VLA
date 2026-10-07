#!/usr/bin/env python3
"""Explicitly download and verify YuNet. Never start detection or robot control."""
import hashlib
import json
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "apps/dummy/configs/face-model.json"


def verified_payload(payload, manifest):
    if len(payload) != manifest["size_bytes"]:
        raise ValueError("YuNet model size mismatch")
    if hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
        raise ValueError("YuNet model SHA256 mismatch")
    return payload


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    destination = (ROOT / manifest["destination"]).resolve()
    if not destination.is_relative_to((ROOT / "local/models").resolve()):
        raise ValueError("model destination must be inside local/models")
    if destination.exists():
        verified_payload(destination.read_bytes(), manifest)
    else:
        with urllib.request.urlopen(manifest["url"], timeout=30) as response:
            payload = verified_payload(response.read(manifest["size_bytes"] + 1), manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    license_path = destination.with_suffix(".LICENSE.txt")
    if not license_path.exists():
        with urllib.request.urlopen(manifest["license_url"], timeout=30) as response:
            license_path.write_bytes(response.read(65536))
    print(json.dumps({"model": str(destination), "sha256": manifest["sha256"],
                      "license": str(license_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
