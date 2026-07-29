#!/usr/bin/env bash

# Return success only when /proc/<pid>/cmdline contains an actual known robot
# controller executable or script. Do not classify arbitrary shell text that
# merely mentions names such as "ros2" during diagnostics.
is_robot_controller_process() {
  local proc="$1"
  local executable=""
  local argument=""
  local basename=""

  executable="$(readlink -f "$proc/exe" 2>/dev/null || true)"
  basename="${executable##*/}"
  case "$basename" in
    roscore|ros2|move_group)
      return 0
      ;;
  esac

  while IFS= read -r -d '' argument; do
    basename="${argument##*/}"
    case "$basename" in
      startouch_bridge.py|proxy.js|fixed_pick_place.py|teach_fixed_point.py)
        return 0
        ;;
      roscore|ros2|move_group)
        return 0
        ;;
    esac
  done < "$proc/cmdline"

  return 1
}
