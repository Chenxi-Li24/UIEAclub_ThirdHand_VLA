#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="${THIRDHAND_WORKTREE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PYTHON="${THIRDHAND_PYTHON:-${STARTOUCH_PYTHON:-python3}}"
CONFIG="$WORKTREE/configs/tasks/fixed_pick_place.yaml"
RUNNER="$WORKTREE/web-control/scripts/fixed_pick_place.py"
LOG_DIR="$WORKTREE/logs/fixed_pick_place"
EXPECTED_BRANCH="${THIRDHAND_EXPECTED_BRANCH:-main}"
CAN_INTERFACE="can0"
RESOURCE_GUARD="$WORKTREE/scripts/fixed_pick_place_resource_guard.sh"
# Low-stiffness bottle grasp. Adaptive contact detection adds only a small
# position preload after the fingers stop on the object.
export STARTOUCH_GRIPPER_KP="2.0"
export STARTOUCH_GRIPPER_KD="0.1"

# shellcheck disable=SC1090
source "$RESOURCE_GUARD"

runner_pid=""

forward_stop() {
  echo "STOP_REQUESTED=1"
  if [[ -n "$runner_pid" ]] && kill -0 "$runner_pid" 2>/dev/null; then
    echo "FORWARDING_SIGINT_TO_RUNNER=$runner_pid"
    kill -INT "$runner_pid"
  fi
}

trap forward_stop INT TERM

mkdir -p "$LOG_DIR"
LAUNCH_LOG="$LOG_DIR/demo-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LAUNCH_LOG") 2>&1

fail() {
  local stage="$1"
  shift
  echo "PICK AND PLACE FAILED"
  echo "FAILED_STAGE=$stage"
  echo "ERROR_REASON=$*"
  echo "LOG=$LAUNCH_LOG"
  exit 1
}

resource_conflict() {
  echo "RESOURCE_CONFLICT"
  echo "$*"
  echo "PICK AND PLACE FAILED"
  echo "FAILED_STAGE=RESOURCE_PREFLIGHT"
  echo "ERROR_REASON=$*"
  echo "LOG=$LAUNCH_LOG"
  exit 23
}

run_mode="${DEMO_RUN_MODE:-manual}"
requested_cycles="${DEMO_CYCLES:-}"
requested_confirmation="${DEMO_CONFIRM_EACH_STEP:-}"
case "$run_mode" in
  manual)
    [[ -z "$requested_cycles" && -z "$requested_confirmation" ]] ||
      fail "MODE_CHECK" "manual mode does not accept automatic overrides"
    ;;
  automatic-three-cycle)
    [[ "$requested_cycles" == "3" ]] ||
      fail "MODE_CHECK" "automatic mode requires DEMO_CYCLES=3"
    [[ "$requested_confirmation" == "0" ]] ||
      fail "MODE_CHECK" \
        "automatic mode requires DEMO_CONFIRM_EACH_STEP=0"
    ;;
  *)
    fail "MODE_CHECK" "unknown DEMO_RUN_MODE=$run_mode"
    ;;
esac

if [[ "${DEMO_MODE_VALIDATE_ONLY:-0}" == "1" ]]; then
  echo "RUN_MODE=$run_mode"
  if [[ "$run_mode" == "automatic-three-cycle" ]]; then
    echo "CYCLES=3"
    echo "REQUIRE_STEP_CONFIRMATION=0"
  fi
  echo "DEMO_MODE_VALIDATION_OK"
  echo "LOG=$LAUNCH_LOG"
  exit 0
fi

cd "$WORKTREE" || fail "DIRECTORY_CHECK" "cannot enter $WORKTREE"
[[ "$PWD" == "$WORKTREE" ]] || fail "DIRECTORY_CHECK" "unexpected directory: $PWD"
command -v "$PYTHON" >/dev/null 2>&1 ||
  fail "PYTHON_CHECK" "Python is not executable: $PYTHON"

branch="$(git branch --show-current 2>/dev/null)" ||
  fail "GIT_CHECK" "cannot read current branch"
[[ "$branch" == "$EXPECTED_BRANCH" ]] ||
  fail "GIT_CHECK" "expected $EXPECTED_BRANCH, found $branch"
echo "WORKTREE=$PWD"
echo "BRANCH=$branch"
echo "COMMIT=$(git rev-parse HEAD)"

ip link show "$CAN_INTERFACE" >/dev/null 2>&1 ||
  fail "CAN_CHECK" "$CAN_INTERFACE does not exist"
ip link show "$CAN_INTERFACE" | grep -q "UP" ||
  fail "CAN_CHECK" "$CAN_INTERFACE is not UP"
bitrate="$(ip -details link show "$CAN_INTERFACE" | awk '/bitrate/{print $2; exit}')"
[[ "$bitrate" == "1000000" ]] ||
  fail "CAN_CHECK" "expected bitrate 1000000, found ${bitrate:-unknown}"
echo "CAN_INTERFACE=$CAN_INTERFACE"
echo "CAN_BITRATE=$bitrate"

# Permit only this shell and its ancestor chain to have the worktree as cwd.
declare -A allowed_pids
cursor="$$"
while [[ "$cursor" =~ ^[0-9]+$ ]] && (( cursor > 1 )); do
  allowed_pids["$cursor"]=1
  cursor="$(ps -o ppid= -p "$cursor" 2>/dev/null | tr -d ' ')"
done

is_own_descendant() {
  local candidate="$1"
  local parent="$candidate"
  while [[ "$parent" =~ ^[0-9]+$ ]] && (( parent > 1 )); do
    [[ "$parent" == "$$" ]] && return 0
    parent="$(ps -o ppid= -p "$parent" 2>/dev/null | tr -d ' ')"
  done
  return 1
}

for proc in /proc/[0-9]*; do
  pid="${proc##*/}"
  [[ -r "$proc/cmdline" ]] || continue
  cmd="$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null)"
  cwd="$(readlink -f "$proc/cwd" 2>/dev/null || true)"
  [[ -n "${allowed_pids[$pid]:-}" ]] && continue
  is_own_descendant "$pid" && continue
  if process_uses_worktree_files "$proc" "$WORKTREE"; then
    user="$(ps -o user= -p "$pid" | xargs)"
    resource_conflict "user=$user pid=$pid cwd=$cwd cmd=$cmd resource=current_worktree"
  fi
  if is_robot_controller_process "$proc"; then
    user="$(ps -o user= -p "$pid" | xargs)"
    resource_conflict "user=$user pid=$pid cwd=${cwd:-unknown} cmd=$cmd resource=robot_or_can0"
  fi
done

if command -v lsof >/dev/null 2>&1; then
  lock_owner="$(lsof -t /tmp/startouch-web-can0.lock 2>/dev/null || true)"
  [[ -z "$lock_owner" ]] ||
    resource_conflict "pid=$lock_owner resource=/tmp/startouch-web-can0.lock"
fi

preflight="$("$PYTHON" - "$CONFIG" "$WORKTREE" <<'PY'
import importlib.util
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
root = Path(sys.argv[2])
script = root / "web-control" / "scripts" / "fixed_pick_place.py"
spec = importlib.util.spec_from_file_location("fixed_demo_preflight", script)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
config = module.load_config(config_path)
if config["workflow"] != "home_transit_ab":
    raise SystemExit("demo requires workflow=home_transit_ab")
for name in ("home", "pre_pick", "place", "a_up", "b_up"):
    print(f"{name.upper()}=" + ",".join(f"{v:.6f}" for v in config["waypoints"][name]))
segment_limits = config["motion"].get("max_segment_delta_deg")
if segment_limits is None:
    raise SystemExit("motion.max_segment_delta_deg is required")
home = config["waypoints"]["home"]
a = config["waypoints"]["pre_pick"]
b = config["waypoints"]["place"]
a_up = config["waypoints"]["a_up"]
b_up = config["waypoints"]["b_up"]
segments = (
    ("HOME_TO_A_UP", home, a_up),
    ("A_UP_TO_A", a_up, a),
    ("A_TO_A_UP", a, a_up),
    ("A_UP_TO_B_UP", a_up, b_up),
    ("B_UP_TO_B", b_up, b),
    ("B_UP_TO_HOME", b_up, home),
)
for label, left, right in segments:
    violations = [
        f"J{i + 1}={abs(goal - start):.3f}>{limit:.3f}"
        for i, (start, goal, limit) in enumerate(zip(left, right, segment_limits))
        if abs(goal - start) > limit
    ]
    if violations:
        raise SystemExit(label + " segment jump rejected: " + ", ".join(violations))
    print(label + "_DELTA=" + ",".join(
        f"{abs(goal-start):.6f}" for start, goal in zip(left, right)
    ))
cartesian = config.get("cartesian_waypoints", {})
lift_height = float(config["motion"].get("lift_height_m", 0.0))
if not 0.05 <= lift_height <= 0.30:
    raise SystemExit("motion.lift_height_m must be in [0.05, 0.30]")
for base, raised in (("a", "a_up"), ("b", "b_up")):
    if base not in cartesian or raised not in cartesian:
        raise SystemExit(f"missing Cartesian metadata for {base}/{raised}")
    low = cartesian[base]
    high = cartesian[raised]
    if len(low) != 6 or len(high) != 6:
        raise SystemExit(f"invalid Cartesian metadata for {base}/{raised}")
    if abs((high[2] - low[2]) - lift_height) > 0.001:
        raise SystemExit(f"{raised} must be {lift_height:.3f}m above {base}")
    if max(abs(high[i] - low[i]) for i in (0, 1, 3, 4, 5)) > 1e-6:
        raise SystemExit(f"{raised} must preserve XY and orientation from {base}")
print(f"LIFT_HEIGHT_M={lift_height:.3f}")
print(f"SPEED_SCALE={config['demo']['speed_scale']:.4f}")
print(f"CONFIG_CYCLES={config['demo']['cycles']}")
print(
    "CONFIG_REQUIRE_STEP_CONFIRMATION="
    f"{int(config['demo']['require_step_confirmation'])}"
)
print(f"VALIDATED_REAL_CYCLES={config['demo']['validated_real_cycles']}")
PY
)" || fail "POINT_VALIDATION" "point configuration is missing or unsafe"
echo "$preflight"

speed_scale="$(awk -F= '/^SPEED_SCALE=/{print $2}' <<<"$preflight")"
config_cycles="$(awk -F= '/^CONFIG_CYCLES=/{print $2}' <<<"$preflight")"
config_confirmation="$(
  awk -F= '/^CONFIG_REQUIRE_STEP_CONFIRMATION=/{print $2}' <<<"$preflight"
)"
validated_cycles="$(awk -F= '/^VALIDATED_REAL_CYCLES=/{print $2}' <<<"$preflight")"
[[ -n "$speed_scale" ]] || fail "SPEED_CHECK" "speed scale is missing"
if ! "$PYTHON" - "$speed_scale" <<'PY'
import sys
speed = float(sys.argv[1])
if not 0 < speed <= 0.30:
    raise SystemExit(1)
PY
then
  fail "SPEED_CHECK" "speed scale must be in (0, 0.30]"
fi

if [[ "$run_mode" == "automatic-three-cycle" ]]; then
  cycles=3
  require_confirmation=0
else
  cycles="$config_cycles"
  require_confirmation="$config_confirmation"
fi
echo "RUN_MODE=$run_mode"
echo "CYCLES=$cycles"
echo "REQUIRE_STEP_CONFIRMATION=$require_confirmation"
echo "LOG_DIRECTORY=$LOG_DIR"
if [[ "${DEMO_PREFLIGHT_ONLY:-0}" == "1" ]]; then
  echo "DEMO_PREFLIGHT_OK"
  echo "LOG=$LAUNCH_LOG"
  exit 0
fi

echo "请把测试物体放在固定A点，并清空机械臂工作区。"
for seconds in 3 2 1; do
  echo "$seconds..."
  sleep 1
done

runner_args=(
  "$RUNNER"
  --real
  --config "$CONFIG"
  --speed-scale "$speed_scale"
)
if [[ "$run_mode" == "automatic-three-cycle" ]]; then
  runner_args+=(--cycles 3 --automatic-three-cycle)
elif [[ "$require_confirmation" == "1" || "$validated_cycles" -lt 3 ]]; then
  runner_args+=(--confirm-each-step)
fi

echo "RUN_COMMAND=$PYTHON ${runner_args[*]}"
"$PYTHON" "${runner_args[@]}" <&0 &
runner_pid=$!
wait "$runner_pid"
rc=$?
while kill -0 "$runner_pid" 2>/dev/null; do
  wait "$runner_pid"
  rc=$?
done
runner_pid=""
if (( rc == 0 )); then
  echo "PICK AND PLACE COMPLETE"
  echo "LOG=$LAUNCH_LOG"
  exit 0
fi

latest_runner_log="$(find "$LOG_DIR" -maxdepth 1 -type f -name 'run-*.log' -printf '%T@ %p\n' |
  sort -nr | awk 'NR==1{print $2}')"
failed_stage="UNKNOWN"
error_reason="runner exited with code $rc"
if [[ -n "$latest_runner_log" && -f "$latest_runner_log" ]]; then
  failed_stage="$(grep ' STATE ' "$latest_runner_log" | tail -1 | sed -E 's/.* STATE ([A-Z_]+).*/\1/' || true)"
  error_reason="$(grep ' ERROR ' "$latest_runner_log" | tail -1 | sed -E 's/.* ERROR //' || true)"
  [[ -n "$error_reason" ]] || error_reason="runner exited with code $rc"
fi
echo "PICK AND PLACE FAILED"
echo "FAILED_STAGE=${failed_stage:-UNKNOWN}"
echo "ERROR_REASON=$error_reason"
echo "RUNNER_LOG=${latest_runner_log:-unavailable}"
echo "LOG=$LAUNCH_LOG"
exit "$rc"
