from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path


FIELDNAMES = [
    "timestamp",
    "target_x", "target_y", "target_z",
    "actual_x", "actual_y", "actual_z",
    "error_mm",
    "target_roll", "target_pitch", "target_yaw",
    "actual_roll", "actual_pitch", "actual_yaw",
    "q1", "q2", "q3", "q4", "q5", "q6",
    "loop_hz",
    "ik_status",
]


class CsvPoseLogger:
    def __init__(self, log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = log_dir / f"fixed_tcp_demo_{stamp}.csv"
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()

    def write(
        self,
        *,
        timestamp: float,
        target_xyz: list[float],
        actual_xyz: list[float],
        error_mm: float,
        target_rpy: list[float],
        actual_rpy: list[float],
        joints: list[float],
        loop_hz: float,
        ik_status: str,
    ) -> None:
        row = {
            "timestamp": f"{timestamp:.6f}",
            "error_mm": f"{error_mm:.6f}",
            "loop_hz": f"{loop_hz:.3f}",
            "ik_status": ik_status,
        }
        row.update({f"target_{axis}": f"{value:.9g}" for axis, value in zip("xyz", target_xyz)})
        row.update({f"actual_{axis}": f"{value:.9g}" for axis, value in zip("xyz", actual_xyz)})
        row.update(
            {f"target_{name}": f"{value:.9g}" for name, value in zip(("roll", "pitch", "yaw"), target_rpy)}
        )
        row.update(
            {f"actual_{name}": f"{value:.9g}" for name, value in zip(("roll", "pitch", "yaw"), actual_rpy)}
        )
        row.update({f"q{index}": f"{value:.9g}" for index, value in enumerate(joints, start=1)})
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._file.close()

