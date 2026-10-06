#!/usr/bin/env bash
# Prepare a fresh Ubuntu x86_64 clone without starting services or enabling motors.
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)"
cd "$root"
python_command="${THIRDHAND_SETUP_PYTHON:-python3.11}"
test "$(uname -m)" = x86_64 || { echo 'This SDK delivery targets Linux x86_64.' >&2; exit 2; }
"$python_command" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 is required"'
git lfs install --local
git lfs pull
"$python_command" tools/assets/restore_runtime_assets.py

if [[ ${1:-} == --assets-only ]]; then
  exit 0
fi
command -v node >/dev/null
test "$(node -p 'process.versions.node.split(".")[0]')" = 24 || {
  echo 'Install Node.js 24 before preparing dependencies.' >&2; exit 2;
}
sudo apt-get install -y build-essential cmake libeigen3-dev libopencv-dev python3.11-dev python3.11-venv libportaudio2 ffmpeg libusb-1.0-0-dev libudev-dev
if ! dpkg-query -W xvsdk >/dev/null 2>&1; then
  sudo apt-get install -y "$root/local/sdk/xvisio/xv/sdk/20260123/XVSDK_focal_amd64.deb"
fi
mkdir -p local/runtimes
if [[ ! -x local/runtimes/python/bin/python ]]; then
  "$python_command" -m venv local/runtimes/python
fi
local/runtimes/python/bin/python -m pip install -r tools/assets/requirements-runtime.txt
local/runtimes/python/bin/python -m pip install -c tools/assets/requirements-runtime.txt ./local/vendor/funasr
if [[ ${1:-} == --with-high-asr ]]; then
  local/runtimes/python/bin/python -m pip install 'vllm==0.19.1'
fi
if [[ ! -x local/runtimes/vision-python/bin/python ]]; then
  ln -s python local/runtimes/vision-python
fi
# Vision uses Norfair/NumPy 1; YuNet 2026 requires OpenCV 5/NumPy 2.
# Keep Dummy isolated so pip cannot replace Vision's compatible packages.
if [[ ! -x local/runtimes/dummy-python/bin/python ]]; then
  "$python_command" -m venv local/runtimes/dummy-python
fi
local/runtimes/dummy-python/bin/python -m pip install -r tools/assets/requirements-dummy.txt
npm ci
local/runtimes/python/bin/python tools/assets/build_startouch_python.py --project-root "$root"
bash drivers/xvisio/scripts/build.sh
printf '\nClone prepared. Configure your own LLM credentials and WEB_HOST in configs/runtime/manual-control.json.\n'
printf 'Then run: ./thirdhand ensure --profile manual-control\n'
printf 'Use setup_clone.sh --with-high-asr to also install the high ASR backend (compatible CUDA GPU required).\n'
