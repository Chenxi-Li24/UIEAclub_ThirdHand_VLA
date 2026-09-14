#!/usr/bin/env bash
set -euo pipefail

task_script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
task_root_dir=$(cd "$task_script_dir/../.." && pwd -P)
task_port=43130

if [[ $# -gt 0 ]]; then
    if [[ $# -ne 2 || "$1" != "--port" ]]; then
        printf '用法: bash scripts/vision/start_active_view_demo.sh [--port PORT]\n' >&2
        exit 2
    fi
    task_port=$2
fi

if [[ ! "$task_port" =~ ^[0-9]+$ ]] || (( task_port < 1024 || task_port > 65535 )); then
    printf '端口必须是 1024 到 65535 之间的整数\n' >&2
    exit 2
fi

printf 'ThirdHand 主动视角纯浏览器模拟\n'
printf '不会连接相机、机械臂或夹爪；所有执行锁保持关闭。\n'
printf '打开: http://127.0.0.1:%s/camera-test.html?demo=1\n' "$task_port"

exec python3 -m http.server "$task_port" \
    --bind 127.0.0.1 \
    --directory "$task_root_dir/web-control/web"
