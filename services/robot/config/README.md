# Joint-speed policy

All Robot service joint, preset, alignment, and Cartesian motion routes use
SDK speed-mode trajectory planning. The maximum commanded joint velocities
are J1–J3: 30 degrees/s and J4–J6: 100 degrees/s at the explicitly authorized
10% ceiling. The default remains 5% (15/50 degrees/s); a lower configured scale
remains lower and a higher scale is capped at 0.10. Formal pregrasp and follow
guards retain their separate 5% bounds. Legacy `time_sec` inputs
cannot override this policy. Cartesian commands remain `move_l`; the separate
20/30 mm/s and Cartesian angular-duration formulas are no longer applied.
The SDK plans the complete joint trajectory, not just endpoint deltas, and
reports its planned duration on command completion.

## Runtime SDK prerequisite

The SDK is an external, ignored runtime asset, not a bundled copy. Its
`joint_trajectory.max_vel_limits` reference must be 300/1000 degrees/s
(in radians). Scaling that reference by 0.05 gives 15/50 degrees/s, and by
0.10 gives the approved 30/100 degrees/s ceiling.
The Robot bridge checks the reference before constructing the hardware SDK
and refuses connection if it does not match. This check is skipped in simulation.

On a stopped, authorized deployment, from its repository root:

```sh
git apply --check --unidiff-zero services/robot/config/sdk-joint-speed.patch
git apply --unidiff-zero services/robot/config/sdk-joint-speed.patch
```

The patch changes only the velocity-reference field in
`local/sdk/startouch/src/config/robot_kinematics.yaml`; it does not replace
other calibration or runtime configuration. If already applied, do not apply
it again. For a custom `STARTOUCH_SDK_PATH`, update only that SDK's corresponding
field to the values in the patch. Do not patch or restart a shared live SDK
while another operator is controlling the arm.

Revert this field only together with a rollback of the new bridge policy:

```sh
git apply --reverse --check --unidiff-zero services/robot/config/sdk-joint-speed.patch
git apply --reverse --unidiff-zero services/robot/config/sdk-joint-speed.patch
```

## Completion and safety

Language joint, home, directional, and camera-X actions retain a bounded
45-second default completion wait instead of the old endpoint-only estimate.
Timeout, software-stop, fresh-state, joint-limit, workspace, and explicit
confirmation checks remain in place. The wait is a deadline, not a commanded
movement duration; slower custom settings or unusually long routes may need
an explicit larger timeout.

Tests use simulation or a fake SDK and never command real hardware.
