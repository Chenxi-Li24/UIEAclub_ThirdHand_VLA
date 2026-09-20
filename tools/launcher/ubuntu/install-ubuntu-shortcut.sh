#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
START_SCRIPT="$SCRIPT_DIR/start-thirdhand.sh"
TEMPLATE="$SCRIPT_DIR/thirdhand-start.desktop.in"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [[ -z "$DESKTOP_DIR" ]]; then
  DESKTOP_DIR="$HOME/Desktop"
fi
TARGET="$DESKTOP_DIR/Start ThirdHand.desktop"

mkdir -p "$DESKTOP_DIR"
chmod +x "$START_SCRIPT"
escaped_start=${START_SCRIPT//|/\\|}
sed "s|@START_SCRIPT@|$escaped_start|" "$TEMPLATE" > "$TARGET"
chmod +x "$TARGET"
if command -v gio >/dev/null 2>&1; then
  gio set "$TARGET" metadata::trusted true >/dev/null 2>&1 || true
fi

printf 'Created Ubuntu desktop shortcut: %s\n' "$TARGET"
