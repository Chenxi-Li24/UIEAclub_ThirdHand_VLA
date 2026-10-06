# Changelog

## 0.1.7 - 2026-06-05

### Gripper Type Configuration

- Added the `gripper_control.type` configuration option.
- Added `TypeFZ` for the existing gripper mechanism with a `1.056071rad`
  motor-angle offset and `0.085m` maximum opening distance.
- Added `TypeLJ` for the new gripper mechanism with a `1.210426rad`
  motor-angle offset and `0.08m` maximum opening distance.
- Rebuilt the bundled runtime libraries for supported x86 Ubuntu systems and
  ARM64.

## 0.1.6 - 2026-05-29

### IK Fallback Strategy

- Added `kdl_with_approx_fallback` as the default IK mode.
- Kept strict KDL and the existing nearby-XYZ fallback as the primary path.
- Runs approximate residual IK only after the KDL paths fail.
- Validates approximate fallback with FK residual tolerances and a
  velocity-derived joint delta limit:
  `joint_trajectory.max_vel_limits * ik_solver.max_joint_delta_time_sec`.
- Fixed FK quaternion residual handling for IK validation.

## 0.1.5 - 2026-05-22

### Important IK Behavior Change

This release adds a configurable KDL IK fallback for singularity-adjacent
targets.

When strict KDL IK fails and `ik_fallback.enabled` is `true`, the SDK lower
layer may retry nearby XYZ targets within `ik_fallback.position_tolerance_m`.
The default tolerance is `0.005` meters. Orientation is not relaxed.

If fallback succeeds:

- The API returns success, so waypoint/chunk execution can continue.
- The SDK prints a warning with the original target, adjusted target, FK error,
  candidate count, and elapsed time.
- FK error is logged for visibility and does not stop execution.

To restore the previous strict-only behavior:

```yaml
ik_fallback:
  enabled: false
```

Full configuration:

```yaml
ik_fallback:
  enabled: true
  position_tolerance_m: 0.005
  max_candidates: 32
  max_time_ms: 3.0
```

### Other Changes

- Updated SDK version to `0.1.5`.
- Rebuilt Ubuntu 20.04, 22.04, and 24.04 runtime libraries.
- Added the public `README.md` entry point.
- Removed internal recovery docs from the public SDK package.
