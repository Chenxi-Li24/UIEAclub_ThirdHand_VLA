"""
Run logger — structured CSV logging per task execution.
"""

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2


@dataclass
class RunLogEntry:
    timestamp: str = ""
    state: str = ""
    rgb_path: str = ""
    joint_positions: str = ""
    ee_pose: str = ""
    gripper_distance: float = 0.0
    command: str = ""
    detected_marker_id: str = ""
    target_pixel: str = ""
    target_base: str = ""
    result: str = ""
    failure_reason: str = ""
    elapsed_time: float = 0.0


class RunLogger:
    """Structured per-run data logger (CSV + images)."""

    def __init__(self, output_dir: str = "logs"):
        self.output_dir = Path(output_dir) / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.start_time = datetime.now()
        self._csv_path = self.output_dir / "run_log.csv"
        self._csv_file = open(self._csv_path, 'w', newline='')
        self._writer = csv.DictWriter(self._csv_file, fieldnames=[
            "timestamp", "state", "rgb_path", "joint_positions", "ee_pose",
            "gripper_distance", "command", "detected_marker_id",
            "target_pixel", "target_base", "result", "failure_reason",
            "elapsed_time"
        ])
        self._writer.writeheader()
        self._frame_count = 0

    def log(self, entry: RunLogEntry):
        """Append entry to CSV."""
        entry.timestamp = datetime.now().isoformat()
        elapsed = (datetime.now() - self.start_time).total_seconds()
        entry.elapsed_time = elapsed
        self._writer.writerow(asdict(entry))
        self._csv_file.flush()

    def log_detections(self, detections: list):
        """Log detection results."""
        for d in detections:
            self.log(RunLogEntry(
                state="DETECT",
                detected_marker_id=str(d.id),
                target_pixel=str(d.center_pixel),
                result="detected",
            ))

    def save_frame(self, image, label: str = "") -> str:
        """Save a frame as PNG. Returns path."""
        if image is None:
            return ""
        path = self.output_dir / f"frame_{self._frame_count:06d}_{label}.png"
        cv2.imwrite(str(path), image)
        self._frame_count += 1
        return str(path)

    def close(self):
        """Close CSV and save metadata."""
        self._csv_file.close()

        # Save run metadata
        meta = {
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "total_frames": self._frame_count,
        }
        with open(self.output_dir / "metadata.json", 'w') as f:
            json.dump(meta, f, indent=2)
