# Website visual mesh

`robot-visuals.glb` and its deterministic gzip representation are derived runtime
assets stored in Git LFS. Restore with `git lfs pull --include="assets/robot/startouch-v3/web/*.glb*" --exclude=""`.
The original URDF and all nine complete STL files remain canonical and unchanged.

Rebuild using Python 3.11+, Node 24 and `npm ci`:

```sh
python tools/assets/build_web_robot.py
node tools/assets/pack_web_robot.cjs
node --test tests/node/web/compact-model.test.js
```

All 448,604 triangles retain their original order, winding and float32 position
bits. There is no decimation, coordinate conversion, quantization or Meshopt
filter. Per-face normals are derived from geometry using flat shading; the
original repeated STL normal attributes are not transmitted. `build-report.json`
records input/output hashes, local bounds, sizes and expanded-position digests.
The runtime continues to use the original URDF joint hierarchy, axes, limits,
mount transform, gripper linkage and TCP offset. This is a visualization asset,
not a new calibrated geometry or a grant for physical control.
