#!/usr/bin/env python3
"""Compatibility entry point for the current three-model recording-lock test."""

import asyncio

from live_recording_lock_acceptance import main


if __name__ == "__main__":
    asyncio.run(main())
