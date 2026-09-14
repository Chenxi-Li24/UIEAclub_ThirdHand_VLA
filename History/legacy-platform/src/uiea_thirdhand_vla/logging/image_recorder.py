"""
Image recorder  timestamped frame capture during task execution.
"""
from pathlib import Path
from datetime import datetime


class ImageRecorder:
    """Save camera frames with timestamps for debugging and dataset creation."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir) / "frames"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, image, label: str, step: int) -> str:
        """Save a frame with label and step number. Returns file path."""
        filename = f"{step:06d}_{label}.jpg"
        filepath = self.output_dir / filename
        return str(filepath)  # TODO: implement cv2.imwrite
