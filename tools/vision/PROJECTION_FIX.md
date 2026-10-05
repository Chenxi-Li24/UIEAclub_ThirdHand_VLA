# Frame-bound projection wiring compatibility bridge

This mirror preserves the existing live camera bridge's capture, stream-demand,
raw/selected-target export and inference behavior without editing that checkout.
Source baseline SHA256:
`72a2eb8a7bd270da4631d6e5584d07128ec39118be231aaa9895331cc3bf62e4`.

The only runtime behavior change passes the timestamp-bound `T_base_camera` into
`VisionPipeline.process` via `UnifiedVisionRuntime` when projection is allowed.
This enables the existing calibrated upright and approach constraints. Missing
or disallowed projection retains the existing camera-only mode; it does not
authorize base-frame motion. Numerical-only diagnostics do not change physical
approval or robot-control flags.

Activation: use the existing Node Vision service with `VISION_BRIDGE_SCRIPT`
pointing to this directory's `camera_bridge_with_projection.py`. Set
`THIRDHAND_LIVE_ROOT` if the live checkout is not under the operator home's
`ThirdHand/UIEAclub_ThirdHand_VLA`. Reuse that checkout's Python runtime and
modules; no dependencies installed. The original bridge is unchanged and is
the rollback default when the override is absent.

Regression command from this directory, with the live services/vision/python
directory on PYTHONPATH: `python -m unittest test_projection_runtime`.

Known remaining limitations: one of five captured diagnostic frames still
rejects `table_plane_normal_mismatch`; foreground/background depth separation
and display-vs-grasp point semantics remain separate work. Geometry and emitted
depth evidence currently query projection independently; freezing a shared
frame transform should be addressed before any motion authorization. No TCP,
path or physical handeye approval is claimed by this patch.
