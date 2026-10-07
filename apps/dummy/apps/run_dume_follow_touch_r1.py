#!/usr/bin/env python3
"""Run the DUM-E Touch R1 follow behavior.

This is the production-facing entry point for the current DUM-E follow stack:
vision target -> visual servo gaze -> virtual gimbal -> Touch R1 joints.
"""

from __future__ import annotations

from run_head_body_follow import run


if __name__ == "__main__":
    raise SystemExit(run())
