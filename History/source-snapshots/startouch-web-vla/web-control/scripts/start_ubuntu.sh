#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This launcher supports Ubuntu only." >&2
  exit 1
fi

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

CAN_INTERFACE="${STARTOUCH_CAN_INTERFACE:-can0}"
if [[ -z "${XVISION_PROXY_ENABLED+x}" ]]; then
  if [[ "${WEB_PORT:-3000}" == "3000" ]]; then
    export XVISION_PROXY_ENABLED=1
  else
    export XVISION_PROXY_ENABLED=0
  fi
fi
export XVISION_SERVICE_URL="${XVISION_SERVICE_URL:-http://127.0.0.1:3100}"
export XVISION_WS_URL="${XVISION_WS_URL:-ws://127.0.0.1:3100/ws}"
export VISION_ROBOT_EXECUTION_ENABLED="${VISION_ROBOT_EXECUTION_ENABLED:-0}"
if [[ "${STARTOUCH_SIMULATE:-0}" != "1" ]]; then
  if ! ip link show "$CAN_INTERFACE" >/dev/null 2>&1; then
    echo "CAN interface does not exist: $CAN_INTERFACE" >&2
    exit 1
  fi
  if ! ip link show "$CAN_INTERFACE" | grep -q "UP"; then
    echo "CAN interface is not UP: $CAN_INTERFACE" >&2
    exit 1
  fi
fi

exec npm --prefix "$ROOT_DIR/server" start
