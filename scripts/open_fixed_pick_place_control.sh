#!/usr/bin/env bash
set -euo pipefail

WORKTREE="/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place"
PYTHON="/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python"

cd "$WORKTREE"
exec "$PYTHON" web-control/demo/demo_server.py \
  --host 127.0.0.1 \
  --port 8766 \
  --open-browser
