#!/usr/bin/env python3
"""Write an offline, non-executable audit of legacy calibration files."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from vision_models.legacy_calibration import audit_legacy_calibration_directory


def write_report(report: dict[str, object], output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                report,
                stream,
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = audit_legacy_calibration_directory(arguments.legacy_dir)
    write_report(report, arguments.output)
    print(
        f"candidate_id={report['candidate_id']} "
        f"validated={report['validated']} executable={report['executable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
