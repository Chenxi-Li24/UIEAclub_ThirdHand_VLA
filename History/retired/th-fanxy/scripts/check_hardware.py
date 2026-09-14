#!/usr/bin/env python3
"""Hardware connectivity check — CAN bus, camera, robot arm.

Usage: python check_hardware.py
"""
print("Hardware check:")
print("  CAN bus  — check with: candump can0")
print("  Camera   — check with: v4l2-ctl --list-devices")
print("  Robot arm — check with: python -c 'import startouch_sdk'")
# TODO: automate checks when SDKs are installed
