# StarTouch SDK

StarTouch SDK provides the Python interface and prebuilt C++ runtime libraries
for controlling StarTouch/FastTouch robotic arms.

Current SDK version: `0.1.7`.

Version note: `2026-06-05`, author `Charlie`.

## Important Change in 0.1.7

Version `0.1.7` adds the `gripper_control.type` configuration option. Select
`TypeFZ` for the existing gripper mechanism or `TypeLJ` for the new mechanism
with its adjusted motor-angle offset and maximum opening distance.

## Important Change in 0.1.6

Version `0.1.6` changes the default IK strategy to
`kdl_with_approx_fallback`: strict KDL and the existing nearby-XYZ fallback run
first, and the approximate residual IK path is used only after those fail. The
approximate fallback is accepted only when FK residuals are inside configured
tolerances and the joint delta is within the limit derived from
`joint_trajectory.max_vel_limits * ik_solver.max_joint_delta_time_sec`.

## Important Change in 0.1.5

Version `0.1.5` changes IK failure handling for KDL-based pose and waypoint
motion. Strict IK is still attempted first. If strict IK fails and
`ik_fallback.enabled` is `true`, the lower layer may retry nearby XYZ targets
within the configured tolerance, default `5mm`, so singularity-adjacent waypoint
chunks can continue instead of stopping immediately.

This behavior is configurable in `src/config/robot_kinematics.yaml`:

```yaml
ik_fallback:
  enabled: true
  position_tolerance_m: 0.005
  max_candidates: 32
  max_time_ms: 3.0
```

Set `enabled: false` to restore the previous strict-only behavior. See
[CHANGELOG.md](CHANGELOG.md), [README_INSTALL.md](README_INSTALL.md), and
[README_API.md](README_API.md) for details.

## Documentation

- [Changelog](CHANGELOG.md)
  - Version-level behavior changes
  - Breaking or important compatibility notes
- [Installation and Runtime Guide](README_INSTALL.md)
  - Supported Ubuntu versions
  - System and Python dependencies
  - Build/install commands
  - CAN setup
  - Runtime configuration, including IK fallback
- [Python API Reference](README_API.md)
  - Arm initialization
  - Joint, pose, gripper, and motion APIs
  - IK behavior and fallback notes
  - Example usage

Start with `README_INSTALL.md` for environment setup, then use
`README_API.md` while writing control scripts.

## Quick Version Check

```bash
python -c "import startouch; from startouchclass import __version__; print(startouch.__version__, __version__)"
```

Expected output for this release:

```text
0.1.5 0.1.5
```

## Supported Ubuntu Runtime Libraries

The SDK ships prebuilt `libstartouch.so` variants:

- Ubuntu 20.04: `src/libstartouch.so.20`
- Ubuntu 22.04: `src/libstartouch.so.22`
- Ubuntu 24.04: `src/libstartouch.so.24`

The build selects the matching library for the local system. When C++ symbols or
runtime behavior change, all three variants should be rebuilt and verified
before publishing.
