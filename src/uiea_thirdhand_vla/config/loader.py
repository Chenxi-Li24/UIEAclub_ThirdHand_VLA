"""
YAML configuration loader.
"""

from pathlib import Path

import yaml


def load_config(config_path: str = None) -> dict:
    """Load and merge config from YAML files. Returns a unified dict."""
    if config_path:
        path = Path(config_path)
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {}

    # Try to load from default configs/ directory
    config_dir = Path(__file__).parent.parent.parent.parent / "configs"
    if not config_dir.exists():
        config_dir = Path("configs")

    config = {}
    for name in ["camera", "robot", "workspace", "vla", "web"]:
        fpath = config_dir / f"{name}.yaml"
        if fpath.exists():
            try:
                data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                if data:
                    config[name] = data
            except Exception:
                pass

    return config
