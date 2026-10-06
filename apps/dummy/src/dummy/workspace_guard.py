"""Compatibility import of the Robot Service's shared geometry guard."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "services/robot/src"))
from workspace_guard import WorkspaceGuard, _LinkMesh, _read_stl_vertices

__all__ = ["WorkspaceGuard"]
