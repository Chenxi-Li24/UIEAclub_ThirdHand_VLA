#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source_dir="${repo_root}/native/vision/xvisio_rgbd_stream"
build_dir="${repo_root}/build/vision/xvisio_rgbd_stream"

cmake -S "${source_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" --parallel
test -x "${build_dir}/xvisio_rgbd_stream"
printf 'Built %s\n' "${build_dir}/xvisio_rgbd_stream"
