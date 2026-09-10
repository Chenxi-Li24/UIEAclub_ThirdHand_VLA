#!/usr/bin/env python3
"""Capture a small controlled two-bottle acceptance set from the live stack."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen


def fetch(url: str) -> bytes:
    with urlopen(url, timeout=3.0) as response:
        return response.read()


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:3100")
    parser.add_argument("--lumos", default="http://127.0.0.1:3001/frame_raw.jpg")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval-ms", type=int, default=300)
    arguments = parser.parse_args()
    if not 10 <= arguments.samples <= 100:
        raise SystemExit("samples must be within [10, 100]")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    stable_identity_by_object: dict[str, int] = {}
    for index in range(arguments.samples):
        deadline = time.monotonic() + 8.0
        bottles = []
        reports = {}
        while len(bottles) < 2 and time.monotonic() < deadline:
            status = json.loads(fetch(arguments.server + "/api/vision/status"))
            reports = {
                item.get("identityId"): item
                for item in status.get("activeView", {}).get("reports", [])
                if item.get("identityId") is not None
            }
            bottles = [
                item
                for item in status.get("targets", [])
                if item.get("label") == "bottle"
                and item.get("identityId") is not None
                and item.get("identityStatus") == "confirmed"
                and reports.get(item.get("identityId"), {}).get("coarseCenterXYM") is not None
            ]
            if len(bottles) < 2:
                time.sleep(0.1)
        bottles.sort(
            key=lambda item: abs(reports[item["identityId"]]["coarseCenterXYM"][1])
        )
        if len(bottles) < 2:
            raise SystemExit(f"sample {index + 1}: two confirmed bottles are required")
        frame = fetch(arguments.lumos)
        selected = bottles[:2]
        assignments = (
            ("center-bottle", selected[0]),
            ("left-bottle", selected[1]),
        )
        predictions = []
        for object_id, item in assignments:
            identity_id = int(item["identityId"])
            stable_identity_by_object.setdefault(object_id, identity_id)
            predictions.append(
                {
                    "identity_id": identity_id,
                    "label": "bottle",
                    "matched_object_id": object_id,
                }
            )
        image_path = arguments.output_dir / f"lumos-{index + 1:02d}.jpg"
        image_path.write_bytes(frame)
        samples.append(
            {
                "image_sha256": "sha256:" + hashlib.sha256(frame).hexdigest(),
                "expected_objects": [
                    {"label": "bottle", "object_id": "center-bottle"},
                    {"label": "bottle", "object_id": "left-bottle"},
                ],
                "predictions": predictions,
            }
        )
        if index + 1 < arguments.samples:
            time.sleep(max(0, arguments.interval_ms) / 1000.0)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label_scope": ["bottle"],
        "samples": samples,
        "schema_version": 1,
    }
    atomic_json(arguments.output_dir / "dataset-manifest.json", manifest)
    print(json.dumps(stable_identity_by_object, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
