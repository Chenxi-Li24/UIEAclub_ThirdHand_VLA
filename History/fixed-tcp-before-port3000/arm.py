from __future__ import annotations

import os
import sys


def create_startouch_arm(*, sdk_path: str, module_path: str | None, can_interface: str, gripper: bool, dry_run: bool):
    if not sdk_path:
        raise RuntimeError("STARTOUCH_SDK_PATH or --sdk-path is required")
    module = module_path or os.path.join(sdk_path, "interface_py")
    if not os.path.isdir(module):
        raise FileNotFoundError(f"Startouch Python module directory not found: {module}")
    if module not in sys.path:
        sys.path.insert(0, module)
    from startouchclass import SingleArm

    return SingleArm(
        can_interface_=can_interface,
        gripper=gripper,
        enable_fd_=False,
        dry_run=dry_run,
    )
