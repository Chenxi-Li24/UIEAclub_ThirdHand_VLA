#!/usr/bin/env bash

# Return success only when /proc/<pid>/cmdline contains an actual known robot
# controller executable or script. Do not classify arbitrary shell text that
# merely mentions names such as "ros2" during diagnostics.
is_robot_controller_process() {
  local proc="$1"
  local executable=""
  local argument=""
  local basename=""
  local index=0
  local -a arguments=()

  while IFS= read -r -d '' argument; do
    arguments+=("$argument")
  done < "$proc/cmdline"

  # The XV camera/CharUco stack is a ROS 2 launch process, but it neither
  # controls the arm nor owns can0. Match this exact camera launch before the
  # deliberately conservative generic ros2 rule below.
  for ((index = 0; index + 3 < ${#arguments[@]}; index++)); do
    if [[ "${arguments[index]##*/}" == "ros2" &&
          "${arguments[index + 1]}" == "launch" &&
          "${arguments[index + 2]}" == "xv_sdk_ros2" &&
          "${arguments[index + 3]##*/}" == "xv_sdk_node_launch.py" ]]; then
      return 1
    fi
  done

  executable="$(readlink -f "$proc/exe" 2>/dev/null || true)"
  basename="${executable##*/}"
  case "$basename" in
    roscore|ros2|move_group)
      return 0
      ;;
  esac

  for argument in "${arguments[@]}"; do
    basename="${argument##*/}"
    case "$basename" in
      startouch_bridge.py|proxy.js|fixed_pick_place.py|teach_fixed_point.py)
        return 0
        ;;
      roscore|ros2|move_group)
        return 0
        ;;
    esac
  done

  return 1
}

# A process whose cwd happens to be the worktree is not necessarily editing or
# executing it. Treat the worktree as occupied only while the process has an
# actual open file descriptor inside the tree.
process_uses_worktree_files() {
  local proc="$1"
  local worktree="$2"
  local descriptor=""
  local target=""

  for descriptor in "$proc"/fd/*; do
    [[ -e "$descriptor" || -L "$descriptor" ]] || continue
    target="$(readlink -f "$descriptor" 2>/dev/null || true)"
    case "$target" in
      "$worktree"|"$worktree"/*)
        return 0
        ;;
    esac
  done
  return 1
}
