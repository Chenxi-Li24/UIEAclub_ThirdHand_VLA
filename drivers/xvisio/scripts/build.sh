#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
source_dir="${repo_root}/drivers/xvisio/native"
build_dir="${repo_root}/runtime/build/xvisio"

cmake -S "${source_dir}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${build_dir}" --parallel
test -x "${build_dir}/xvisio_rgbd_stream"
printf 'Built %s\n' "${build_dir}/xvisio_rgbd_stream"
