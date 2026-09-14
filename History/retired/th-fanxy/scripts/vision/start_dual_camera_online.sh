#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK_SERVER_DIR="$TASK_ROOT_DIR/web-control/server"
TASK_RUNTIME_DIR="${VISION_RUNTIME_DIR:-$TASK_ROOT_DIR/artifacts/vision/dual-camera-online}"
TASK_PID_FILE="$TASK_RUNTIME_DIR/server.pid"
TASK_LOG_FILE="$TASK_RUNTIME_DIR/online.log"
TASK_USER_HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
TASK_MODEL_PYTHON="${CAMERA_PYTHON:-$TASK_USER_HOME/miniconda3/envs/thirdhand-remind3d/bin/python}"
TASK_NODE="$(command -v node || true)"
TASK_CONFIG="$TASK_ROOT_DIR/configs/vision/remind3d.yaml"
TASK_ACTIVE_VIEW_CONFIG="$TASK_ROOT_DIR/configs/vision/active_view.yaml"
TASK_ACTIVE_VIEW_EVIDENCE_DIR="${ACTIVE_VIEW_EVIDENCE_DIR:-$TASK_ROOT_DIR/data/calibration/active-view-foundation}"
TASK_ACTIVE_VIEW_CAMERA_EVIDENCE="${ACTIVE_VIEW_CAMERA_EVIDENCE:-$TASK_ACTIVE_VIEW_EVIDENCE_DIR/camera.json}"
TASK_ACTIVE_VIEW_TABLE_EVIDENCE="${ACTIVE_VIEW_TABLE_EVIDENCE:-$TASK_ACTIVE_VIEW_EVIDENCE_DIR/table.json}"
TASK_ACTIVE_VIEW_CATALOG="${ACTIVE_VIEW_CATALOG:-$TASK_ACTIVE_VIEW_EVIDENCE_DIR/observation-catalog.json}"
TASK_LUMOS_HEALTH="http://127.0.0.1:3001/health"
TASK_LUMOS_FRAME="http://127.0.0.1:3001/frame.jpg"
TASK_SYSTEMD_UNIT="thirdhand-dual-camera-online"

usage() {
  printf 'usage: %s [--foreground|--background|--stop|--status]\n' "$0" >&2
}

read_pid() {
  [[ -f "$TASK_PID_FILE" ]] || return 1
  local task_pid
  task_pid="$(tr -d '[:space:]' < "$TASK_PID_FILE")"
  [[ "$task_pid" =~ ^[1-9][0-9]*$ ]] || return 2
  printf '%s\n' "$task_pid"
}

validate_owned_pid() {
  local task_pid task_cwd task_cmdline task_environment
  task_pid="$(read_pid)" || return $?
  if ! kill -0 "$task_pid" 2>/dev/null; then
    return 1
  fi
  [[ -r "/proc/$task_pid/cmdline" && -r "/proc/$task_pid/environ" ]] || return 2
  task_cwd="$(readlink -f "/proc/$task_pid/cwd")"
  task_cmdline="$(tr '\0' ' ' < "/proc/$task_pid/cmdline")"
  task_environment="$(tr '\0' '\n' < "/proc/$task_pid/environ")"
  [[ "$task_cwd" == "$TASK_SERVER_DIR" ]] || return 2
  [[ "$task_cmdline" == *"node"* && "$task_cmdline" == *"proxy.js"* ]] || return 2
  grep -Fxq 'WEB_PORT=3100' <<<"$task_environment" || return 2
  grep -Fxq 'STARTOUCH_SIMULATE=1' <<<"$task_environment" || return 2
  grep -Fxq 'VISION_ONLINE_ENABLED=1' <<<"$task_environment" || return 2
  grep -Fxq 'ACTIVE_VIEW_EXECUTION_ENABLED=0' <<<"$task_environment" || return 2
  grep -Fxq 'GRASP_EXECUTION_ENABLED=0' <<<"$task_environment" || return 2
  grep -Fxq "ACTIVE_VIEW_CONFIG=$TASK_ACTIVE_VIEW_CONFIG" \
    <<<"$task_environment" || return 2
  printf '%s\n' "$task_pid"
}

usb_present() {
  local task_vendor="$1" task_product="$2" task_device
  for task_device in /sys/bus/usb/devices/*; do
    [[ -r "$task_device/idVendor" && -r "$task_device/idProduct" ]] || continue
    if [[ "$(<"$task_device/idVendor")" == "$task_vendor" \
      && "$(<"$task_device/idProduct")" == "$task_product" ]]; then
      return 0
    fi
  done
  return 1
}

preflight() {
  [[ -x "$TASK_MODEL_PYTHON" ]] || {
    printf 'model Python not executable: %s\n' "$TASK_MODEL_PYTHON" >&2
    return 1
  }
  [[ -n "$TASK_NODE" && -x "$TASK_NODE" ]] || {
    printf 'node executable not found\n' >&2
    return 1
  }
  [[ -f "$TASK_CONFIG" ]] || {
    printf 'vision config not found: %s\n' "$TASK_CONFIG" >&2
    return 1
  }
  [[ -f "$TASK_ACTIVE_VIEW_CONFIG" ]] || {
    printf 'active-view config not found: %s\n' "$TASK_ACTIVE_VIEW_CONFIG" >&2
    return 1
  }
  [[ -f "$TASK_ACTIVE_VIEW_CAMERA_EVIDENCE" ]] || {
    printf 'camera evidence not found: %s\n' "$TASK_ACTIVE_VIEW_CAMERA_EVIDENCE" >&2
    return 1
  }
  [[ -f "$TASK_ACTIVE_VIEW_TABLE_EVIDENCE" ]] || {
    printf 'table evidence not found: %s\n' "$TASK_ACTIVE_VIEW_TABLE_EVIDENCE" >&2
    return 1
  }
  usb_present 040e f408 || {
    printf 'Lumos USB 040e:f408 not found\n' >&2
    return 1
  }
  usb_present 8086 0b07 || {
    printf 'D435 USB 8086:0b07 not found\n' >&2
    return 1
  }
  curl --fail --silent --show-error "$TASK_LUMOS_HEALTH" | \
    "$TASK_MODEL_PYTHON" -c 'import json,sys; value=json.load(sys.stdin); assert value.get("ready") is True, value'
  local task_headers
  task_headers="$(mktemp)"
  if ! curl --fail --silent --show-error --dump-header "$task_headers" \
    --output /dev/null "$TASK_LUMOS_FRAME"; then
    rm -f "$task_headers"
    return 1
  fi
  if ! grep -qi '^X-Lumos-Sequence:' "$task_headers" \
    || ! grep -qi '^X-Lumos-Monotonic-Ns:' "$task_headers"; then
    printf 'Lumos snapshot provenance headers are missing\n' >&2
    rm -f "$task_headers"
    return 1
  fi
  rm -f "$task_headers"
  PYTHONPATH="$TASK_SERVER_DIR" "$TASK_MODEL_PYTHON" - \
    "$TASK_CONFIG" "$TASK_ACTIVE_VIEW_CONFIG" <<'PY'
import pathlib
import pyrealsense2 as rs
import sys
from vision_models.active_view_online import load_active_view_config
from vision_models.online import load_online_vision_config
config = load_online_vision_config(pathlib.Path(sys.argv[1]))
active_view = load_active_view_config(pathlib.Path(sys.argv[2]))
assert config.robot_execution_enabled is False
assert active_view.execution_enabled is False
assert config.roles.canonical_rgb_source == "lumos_rgb"
assert config.roles.metric_depth_source == "d435_depth"
print("VISION_PREFLIGHT=PASS")
PY
  "$TASK_MODEL_PYTHON" - <<'PY'
import pyrealsense2 as rs
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
profile = pipeline.start(config)
try:
    frames = pipeline.wait_for_frames(3000)
    assert frames.get_depth_frame() and frames.get_color_frame()
    print("D435_RGBD_PREFLIGHT=PASS")
finally:
    pipeline.stop()
PY
  "$TASK_MODEL_PYTHON" - <<'PY'
import socket
probe = socket.socket()
try:
    probe.bind(("127.0.0.1", 3100))
finally:
    probe.close()
PY
}

server_environment() {
  exec env \
    STARTOUCH_SIMULATE=1 \
    STARTOUCH_CAN_INTERFACE=thirdhand-vision-test \
    STARTOUCH_GRIPPER=0 \
    STARTOUCH_REQUIRE_CAN_RX=0 \
    STARTOUCH_PYTHON=python3 \
    CAMERA_ENABLED=1 \
    CAMERA_PYTHON="$TASK_MODEL_PYTHON" \
    VISION_ONLINE_ENABLED=1 \
    ACTIVE_VIEW_EXECUTION_ENABLED=0 \
    GRASP_EXECUTION_ENABLED=0 \
    VISION_CONFIG="$TASK_CONFIG" \
    ACTIVE_VIEW_CONFIG="$TASK_ACTIVE_VIEW_CONFIG" \
    ACTIVE_VIEW_EVIDENCE_DIR="$TASK_ACTIVE_VIEW_EVIDENCE_DIR" \
    ACTIVE_VIEW_CAMERA_EVIDENCE="$TASK_ACTIVE_VIEW_CAMERA_EVIDENCE" \
    ACTIVE_VIEW_TABLE_EVIDENCE="$TASK_ACTIVE_VIEW_TABLE_EVIDENCE" \
    ACTIVE_VIEW_CATALOG="$TASK_ACTIVE_VIEW_CATALOG" \
    LUMOS_SNAPSHOT_URL="$TASK_LUMOS_FRAME" \
    LUMOS_STREAM_URL=http://127.0.0.1:3001/camera_lumos \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=3100 \
    "$TASK_NODE" proxy.js
}

start_background() {
  if validate_owned_pid >/dev/null 2>&1; then
    printf 'dual-camera online service is already running\n' >&2
    return 1
  fi
  preflight
  mkdir -p "$TASK_RUNTIME_DIR"
  command -v systemd-run >/dev/null
  command -v systemctl >/dev/null
  if systemctl --user is-active --quiet "$TASK_SYSTEMD_UNIT.service"; then
    printf 'systemd unit is already active without a verified PID file: %s\n' \
      "$TASK_SYSTEMD_UNIT.service" >&2
    return 1
  fi
  systemctl --user reset-failed "$TASK_SYSTEMD_UNIT.service" 2>/dev/null || true
  systemd-run --user \
    --unit="$TASK_SYSTEMD_UNIT" \
    --collect \
    --service-type=exec \
    --working-directory="$TASK_SERVER_DIR" \
    --property="StandardOutput=append:$TASK_LOG_FILE" \
    --property="StandardError=append:$TASK_LOG_FILE" \
    --setenv=STARTOUCH_SIMULATE=1 \
    --setenv=STARTOUCH_CAN_INTERFACE=thirdhand-vision-test \
    --setenv=STARTOUCH_GRIPPER=0 \
    --setenv=STARTOUCH_REQUIRE_CAN_RX=0 \
    --setenv=STARTOUCH_PYTHON=python3 \
    --setenv=CAMERA_ENABLED=1 \
    --setenv=CAMERA_PYTHON="$TASK_MODEL_PYTHON" \
    --setenv=VISION_ONLINE_ENABLED=1 \
    --setenv=ACTIVE_VIEW_EXECUTION_ENABLED=0 \
    --setenv=GRASP_EXECUTION_ENABLED=0 \
    --setenv=VISION_CONFIG="$TASK_CONFIG" \
    --setenv=ACTIVE_VIEW_CONFIG="$TASK_ACTIVE_VIEW_CONFIG" \
    --setenv=ACTIVE_VIEW_EVIDENCE_DIR="$TASK_ACTIVE_VIEW_EVIDENCE_DIR" \
    --setenv=ACTIVE_VIEW_CAMERA_EVIDENCE="$TASK_ACTIVE_VIEW_CAMERA_EVIDENCE" \
    --setenv=ACTIVE_VIEW_TABLE_EVIDENCE="$TASK_ACTIVE_VIEW_TABLE_EVIDENCE" \
    --setenv=ACTIVE_VIEW_CATALOG="$TASK_ACTIVE_VIEW_CATALOG" \
    --setenv=LUMOS_SNAPSHOT_URL="$TASK_LUMOS_FRAME" \
    --setenv=LUMOS_STREAM_URL=http://127.0.0.1:3001/camera_lumos \
    --setenv=WEB_HOST=0.0.0.0 \
    --setenv=WEB_PORT=3100 \
    "$TASK_NODE" proxy.js
  local task_pid=""
  for _ in $(seq 1 30); do
    task_pid="$(systemctl --user show "$TASK_SYSTEMD_UNIT.service" -p MainPID --value)"
    if [[ "$task_pid" =~ ^[1-9][0-9]*$ ]]; then
      break
    fi
    sleep 0.1
  done
  if [[ ! "$task_pid" =~ ^[1-9][0-9]*$ ]]; then
    printf 'systemd did not report an owned service PID\n' >&2
    return 1
  fi
  printf '%s\n' "$task_pid" > "$TASK_PID_FILE"
  for _ in $(seq 1 50); do
    if ! kill -0 "$task_pid" 2>/dev/null; then
      printf 'dual-camera online service exited during startup; see %s\n' "$TASK_LOG_FILE" >&2
      rm -f "$TASK_PID_FILE"
      return 1
    fi
    if curl --fail --silent --output /dev/null http://127.0.0.1:3100/api/vision/status; then
      printf 'started pid=%s url=http://127.0.0.1:3100/camera-test.html\n' "$task_pid"
      return 0
    fi
    sleep 0.1
  done
  printf 'server did not expose status API; see %s\n' "$TASK_LOG_FILE" >&2
  kill -TERM "$task_pid" 2>/dev/null || true
  rm -f "$TASK_PID_FILE"
  return 1
}

start_foreground() {
  if validate_owned_pid >/dev/null 2>&1; then
    printf 'dual-camera online service is already running\n' >&2
    return 1
  fi
  preflight
  mkdir -p "$TASK_RUNTIME_DIR"
  (
    cd "$TASK_SERVER_DIR"
    server_environment
  ) &
  local task_pid=$!
  printf '%s\n' "$task_pid" > "$TASK_PID_FILE"
  trap 'kill -TERM "$task_pid" 2>/dev/null || true' INT TERM
  set +e
  wait "$task_pid"
  local task_status=$?
  set -e
  if [[ "$(read_pid 2>/dev/null || true)" == "$task_pid" ]]; then
    rm -f "$TASK_PID_FILE"
  fi
  return "$task_status"
}

stop_service() {
  local task_pid task_result
  set +e
  task_pid="$(validate_owned_pid)"
  task_result=$?
  set -e
  if [[ $task_result -eq 1 ]]; then
    printf 'dual-camera online service is stopped\n'
    return 1
  fi
  if [[ $task_result -ne 0 ]]; then
    printf 'refusing to signal an unverified PID file: %s\n' "$TASK_PID_FILE" >&2
    return 2
  fi
  kill -TERM "$task_pid"
  for _ in $(seq 1 100); do
    if ! kill -0 "$task_pid" 2>/dev/null; then
      rm -f "$TASK_PID_FILE"
      printf 'stopped pid=%s\n' "$task_pid"
      return 0
    fi
    sleep 0.1
  done
  printf 'verified process did not stop after SIGTERM: %s\n' "$task_pid" >&2
  return 1
}

status_service() {
  local task_pid task_result
  set +e
  task_pid="$(validate_owned_pid)"
  task_result=$?
  set -e
  if [[ $task_result -eq 0 ]]; then
    printf 'running pid=%s url=http://127.0.0.1:3100/camera-test.html\n' "$task_pid"
    return 0
  fi
  if [[ $task_result -eq 2 ]]; then
    printf 'unsafe or mismatched PID file: %s\n' "$TASK_PID_FILE" >&2
    return 2
  fi
  printf 'stopped\n'
  return 1
}

task_mode="${1:---background}"
case "$task_mode" in
  --foreground) start_foreground ;;
  --background) start_background ;;
  --stop) stop_service ;;
  --status) status_service ;;
  *) usage; exit 2 ;;
esac
