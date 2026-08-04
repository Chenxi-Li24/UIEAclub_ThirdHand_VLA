#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONDA_EXE="${CONDA_EXE:-/home/nieqingcao/miniconda3/bin/conda}"
CONDA_ROOT="$(cd "$(dirname "$CONDA_EXE")/.." && pwd)"
ENV_NAME="thirdhand-remind3d"
ENV_PREFIX="$CONDA_ROOT/envs/$ENV_NAME"
PYTHON_VERSION="3.11"
TORCH_VERSION="2.7.0"
TORCHVISION_VERSION="0.22.0"
PIP_VERSION="26.1.2"
SETUPTOOLS_VERSION="83.0.0"
WHEEL_VERSION="0.47.0"
PYTORCH_INDEX_URL="https://download.pytorch.org/whl/cu128"
REQUIREMENTS="$ROOT_DIR/requirements/remind3d-cu128.txt"

print_plan() {
  printf 'ENV_NAME=%s\n' "$ENV_NAME"
  printf 'ENV_PREFIX=%s\n' "$ENV_PREFIX"
  printf 'PYTHON_VERSION=%s\n' "$PYTHON_VERSION"
  printf 'TORCH_VERSION=%s\n' "$TORCH_VERSION"
  printf 'TORCHVISION_VERSION=%s\n' "$TORCHVISION_VERSION"
  printf 'PIP_VERSION=%s\n' "$PIP_VERSION"
  printf 'SETUPTOOLS_VERSION=%s\n' "$SETUPTOOLS_VERSION"
  printf 'WHEEL_VERSION=%s\n' "$WHEEL_VERSION"
  printf 'PYTORCH_INDEX_URL=%s\n' "$PYTORCH_INDEX_URL"
  printf 'REQUIREMENTS=%s\n' "$REQUIREMENTS"
  printf 'MUTATES_LUMOSTOUCH=0\n'
}

mode="${1:---install}"
case "$mode" in
  --print-plan)
    print_plan
    exit 0
    ;;
  --install)
    ;;
  *)
    printf 'usage: %s [--print-plan|--install]\n' "$0" >&2
    exit 2
    ;;
esac

print_plan
if [[ ! -x "$CONDA_EXE" ]]; then
  printf 'conda executable not found: %s\n' "$CONDA_EXE" >&2
  exit 1
fi
if [[ ! -f "$REQUIREMENTS" ]]; then
  printf 'requirements file not found: %s\n' "$REQUIREMENTS" >&2
  exit 1
fi

if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  "$CONDA_EXE" create --name "$ENV_NAME" "python=$PYTHON_VERSION" pip -y
fi

"$CONDA_EXE" run --name "$ENV_NAME" python -m pip install \
  "pip==$PIP_VERSION" "setuptools==$SETUPTOOLS_VERSION" "wheel==$WHEEL_VERSION"
"$CONDA_EXE" run --name "$ENV_NAME" python -m pip install \
  "torch==$TORCH_VERSION" "torchvision==$TORCHVISION_VERSION" \
  --index-url "$PYTORCH_INDEX_URL"
"$CONDA_EXE" run --name "$ENV_NAME" python -m pip install --requirement "$REQUIREMENTS"

"$CONDA_EXE" run --name "$ENV_NAME" python -c \
  'import cv2, mmdeploy, mmdet, mmengine, numpy, scipy, torch, transformers; print("IMPORT_GATE=PASS"); print("TORCH=" + torch.__version__); print("CUDA_BUILD=" + str(torch.version.cuda))'
"$CONDA_EXE" run --name "$ENV_NAME" python -c \
  'import torch; assert torch.cuda.is_available(), "CUDA unavailable"; capability=torch.cuda.get_device_capability(); arch=f"sm_{capability[0]}{capability[1]}"; assert arch in torch.cuda.get_arch_list(), (arch, torch.cuda.get_arch_list()); print("GPU_GATE=PASS"); print("GPU=" + torch.cuda.get_device_name()); print("CAPABILITY=" + str(capability))'
"$CONDA_EXE" run --name "$ENV_NAME" python -c \
  'import torch; from mmcv.ops import nms; boxes=torch.tensor([[0.0,0.0,10.0,10.0],[1.0,1.0,9.0,9.0]],device="cuda"); scores=torch.tensor([0.9,0.8],device="cuda"); detections,keep=nms(boxes,scores,0.5); assert detections.is_cuda and keep.tolist()==[0], (detections,keep); print("MMCV_OP_GATE=PASS")'

printf 'REMIND3D_ENV_READY=%s\n' "$ENV_PREFIX"
