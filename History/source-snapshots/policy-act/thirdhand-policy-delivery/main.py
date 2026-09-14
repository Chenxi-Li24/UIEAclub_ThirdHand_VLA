#!/usr/bin/env python3
"""Entry point for the ThirdHand Policy service.

Usage:
  THIRDHAND_POLICY_PORT=8080 python main.py
"""

from __future__ import annotations

import os

import uvicorn

from thirdhand_policy.service import app  # noqa: F401  (imported to build the app)


def main() -> None:
    host = os.environ.get("THIRDHAND_POLICY_HOST", "0.0.0.0")
    port = int(os.environ.get("THIRDHAND_POLICY_PORT", "8080"))
    uvicorn.run("thirdhand_policy.service:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
