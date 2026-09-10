#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="${THIRDHAND_WORKTREE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON="${THIRDHAND_PYTHON:-${STARTOUCH_PYTHON:-python3}}"

cd "$WORKTREE"
exec "$PYTHON" web-control/demo/demo_server.py \
  --host 127.0.0.1 \
  --port 8766 \
  --open-browser
