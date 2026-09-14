#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
run_dir="${project_root}/artifacts/action/operator"
mkdir -p "$run_dir"

action="${1:-status}"
case "$action" in
  start)
    target="${2:-1}"
    if [[ -f "$run_dir/pid" ]] && kill -0 "$(cat "$run_dir/pid")" 2>/dev/null; then
      echo "已有抓取任务正在运行，PID $(cat "$run_dir/pid")"
      exit 3
    fi
    nohup node "${project_root}/apps/bottle_pick/run.js" start "$target" \
      >"$run_dir/latest.log" 2>&1 </dev/null &
    echo $! >"$run_dir/pid"
    echo "已启动：抓取编号 $target，PID $!"
    ;;
  stop)
    node "${project_root}/apps/bottle_pick/run.js" stop || true
    if [[ -f "$run_dir/pid" ]] && kill -0 "$(cat "$run_dir/pid")" 2>/dev/null; then
      kill "$(cat "$run_dir/pid")" || true
    fi
    rm -f "$run_dir/pid"
    echo "已发送停止指令"
    ;;
  status)
    if [[ -f "$run_dir/status.json" ]]; then cat "$run_dir/status.json"; else echo '{"state":"idle"}'; fi
    ;;
  logs)
    touch "$run_dir/latest.log"
    tail -n 80 "$run_dir/latest.log"
    ;;
  *)
    echo "用法: $0 {start <编号>|stop|status|logs}" >&2
    exit 2
    ;;
esac
