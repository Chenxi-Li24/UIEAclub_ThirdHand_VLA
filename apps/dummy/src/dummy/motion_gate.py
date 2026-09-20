from __future__ import annotations


def require_motion_enable(enabled: bool) -> None:
    """Reject hardware-follow startup unless the operator explicitly arms it."""

    if not enabled:
        raise RuntimeError(
            "real robot motion is locked; rerun with --enable-motion only after "
            "the operator has cleared the workspace and approved motion"
        )
