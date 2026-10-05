#!/usr/bin/env python3
"""Compatibility entrypoint; following is J1/J4 only, gestures use all joints."""
from run_head_body_follow import run

if __name__ == "__main__":
    raise SystemExit(run())
