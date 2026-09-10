# Robot Assets

This directory is the runtime mount for robot geometry used by `apps/web`.

## Startouch FastTouchV3

Expected local path:

```text
assets/robot/startouch-v3/
  FastTouchV3.SLDASM.urdf
  meshes/*.STL
```

The payload was copied from the previously accepted Startouch web-control source at
`/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA/web-control/web/models/startouch-v3`.
The source path is provenance only and is never used at runtime.

The payload is intentionally excluded from Git. Its expected directory hash and
size are recorded as `robot.startouch-v3.geometry` in
`configs/assets/ubuntu20.manifest.json`. Prepare another machine with:

```bash
PYTHONPATH=. python3 tools/assets/prepare_robot_assets.py \
  --source /path/to/startouch-v3 \
  --manifest configs/assets/ubuntu20.manifest.json
```

The web gateway mounts this directory at `/models`, so the current page loads
`/models/startouch-v3/FastTouchV3.SLDASM.urdf`.
