# Model assets

Model weights are deployment artifacts. The repository ignores `*.pt` and
`*.onnx`; keep them in a local model directory or reference them through an
environment variable.

## YOLOv8 nano

The packaged YOLO detector and the D435 camera bridge default to
`yolov8n.pt`. Install the optional vision dependencies and let Ultralytics fetch
the official weight on first load:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[vision-ml]"
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

From the repository root, this creates `yolov8n.pt` locally. Point the Startouch
camera bridge at it without copying it into Git:

```bash
export CAMERA_YOLO_MODEL="$PWD/yolov8n.pt"
```

An ONNX export is optional:

```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
```

This produces a local `yolov8n.onnx`, which is also ignored.

## REMIND-3D detector and descriptor assets

The reproducible CUDA environment is defined by
`requirements/remind3d-cu128.txt` and created with:

```bash
bash scripts/vision/bootstrap_remind3d_env.sh --print-plan
bash scripts/vision/bootstrap_remind3d_env.sh --install
```

`configs/vision/remind3d.yaml` identifies the expected local RTMDet deployment
files:

```text
models/vision/rtmdet/rtmdet-ins_tiny_lumos.py
models/vision/rtmdet/rtmdet-ins_tiny_lumos.pth
```

The `.pth` file is a project-specific checkpoint and has no authoritative public
download URL in this repository. Obtain the reviewed checkpoint from the model
owner or reproduce it through the documented training/deployment process before
running a real-model smoke test. Do not substitute an unrelated checkpoint:
the adapter verifies that checkpoint class metadata matches the configured
labels.

The configured DINO descriptor IDs are resolved by the Transformers/Hugging Face
cache when the model adapter is first initialized. For an offline robot host,
populate that cache during environment preparation and verify it with
`scripts/vision/smoke_remind3d_models.py` before disconnecting the network.

## Verification rules

- Never commit downloaded weights or cache contents.
- Record the source and checksum in deployment records when a reviewed custom
  checkpoint is supplied.
- Keep `safety.robot_execution_enabled: false` until calibration, identity,
  depth, latency, and GPU-memory acceptance gates have passed.
