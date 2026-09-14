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
