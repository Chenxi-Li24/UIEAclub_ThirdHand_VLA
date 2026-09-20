# Vision Service

The Vision Service owns the XVisio USB camera and listens only on
`127.0.0.1:3100`. The web gateway on port 9983 is the only LAN-facing proxy.

## Runtime boundaries

- Camera capture starts independently from Grounding DINO and SAM2.
- Raw RGB and depth MJPEG continue when model loading or inference fails.
- Recognition output contains boxes, stable IDs 1 through 5, and the selected ID.
- This service has no Startouch imports and never opens CAN.
- Target selection updates perception state only. It does not move the robot.

## Endpoints

- `GET /health`
- `GET /api/vision/status`
- `GET /camera/xvisio/raw`
- `GET /camera/xvisio/vision`
- `GET /camera/xvisio/depth`
- `POST /api/vision/select` with `{"stableId": 1}`
- `POST /api/vision/release`
- `WS /ws` for bounded status, selection, and detection events

The process must use `local/runtimes/vision-python/bin/python`; the base Conda runtime
has a different CUDA/PyTorch combination. Model files live under ignored
`local/models/vision/huggingface` and are verified by the pinned hashes in
`configs/vision.yaml`.
