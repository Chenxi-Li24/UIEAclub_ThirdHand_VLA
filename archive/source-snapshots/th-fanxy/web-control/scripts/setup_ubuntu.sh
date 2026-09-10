#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${STARTOUCH_PYTHON:-$HOME/miniconda3/envs/LumosTouch/bin/python}"
SDK_PATH="${STARTOUCH_SDK_PATH:-$HOME/arm/startouch_sdk}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This setup script supports Ubuntu only." >&2
  exit 1
fi

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "Expected Ubuntu, found ${ID:-unknown}." >&2
    exit 1
  fi
  case "${VERSION_ID:-}" in
    20.04|22.04) ;;
    *) echo "Warning: Ubuntu ${VERSION_ID:-unknown} has not been validated." >&2 ;;
  esac
fi

for command in node npm ip; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if (( NODE_MAJOR < 18 )); then
  echo "Node.js 18 or newer is required; found $(node --version)." >&2
  exit 1
fi

if [[ "${STARTOUCH_SIMULATE:-0}" != "1" ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Startouch Python is not executable: $PYTHON_BIN" >&2
    echo "Set STARTOUCH_PYTHON to the LumosTouch Python executable." >&2
    exit 1
  fi
  if [[ ! -d "$SDK_PATH/interface_py" ]]; then
    echo "Startouch SDK interface directory not found: $SDK_PATH/interface_py" >&2
    echo "Set STARTOUCH_SDK_PATH to the startouch_sdk checkout." >&2
    exit 1
  fi
  STARTOUCH_SDK_PATH="$SDK_PATH" "$PYTHON_BIN" -c \
    'import os, sys; sys.path.insert(0, os.path.join(os.environ["STARTOUCH_SDK_PATH"], "interface_py")); import startouchclass; print("Startouch SDK import OK:", startouchclass.__file__)'
fi

npm --prefix "$ROOT_DIR/server" ci

echo "Web control dependencies are ready."
echo "Configure can0, then run: $ROOT_DIR/scripts/start_ubuntu.sh"
