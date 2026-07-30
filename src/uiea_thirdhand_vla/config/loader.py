"""
YAML configuration loader with Pydantic validation.

Loads configs/ *.yaml files, validates against Pydantic models,
and supports environment variable overrides.
"""

from pathlib import Path
from typing import TypeVar

import yaml

from .models import (
    AppConfig,
    AsrTtsConfig,
    CameraConfig,
    RobotConfig,
    VLAConfig,
    WebConfig,
    WorkspaceConfig,
)

T = TypeVar("T")


class ConfigLoader:
    """Loads YAML configs with Pydantic validation."""

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)

    def load_app_config(self) -> AppConfig:
        """Load and merge all domain configs into AppConfig."""
        return AppConfig(
            robot=self._load("robot.yaml", RobotConfig),
            camera=self._load("camera.yaml", CameraConfig),
            workspace=self._load("workspace.yaml", WorkspaceConfig),
            asr_tts=self._try_load("asr_tts.yaml", AsrTtsConfig),
            vla=self._try_load("vla.yaml", VLAConfig),
            web=self._load("web.yaml", WebConfig),
        )

    def _load(self, filename: str, model_cls: type[T]) -> T:
        path = self.config_dir / filename
        if not path.exists():
            return model_cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return model_cls(**data)

    def _try_load(self, filename: str, model_cls: type[T]) -> T | None:
        path = self.config_dir / filename
        if not path.exists():
            return None
        return self._load(filename, model_cls)
