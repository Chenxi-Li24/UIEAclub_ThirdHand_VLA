# Port-fed operator hand-eye calibration

Independent adapter for the existing calibration page flow. The hand-eye matrix
input contract and OpenCV algorithm selection follow
[IFL-CAMP/easy_handeye](https://github.com/IFL-CAMP/easy_handeye), specifically its
`HandeyeCalibrationBackendOpenCV`. No upstream ROS code is copied or imported;
the project remains a reference, not an installed ROS dependency.

Robot state is subscribed through the existing `9983/ws` gateway. The subscriber
never sends any robot command and never imports a CAN or vendor SDK adapter.
Images and timestamped raw-frame NPZs come from the existing Vision owner on
`3100`. The application does not open a camera device. Port `8089` is retained
for the operator page; the original `calibration/handeye_calib.py` in the operator's home directory
and its results are not overwritten.

The board matches the operator's existing script: 9 x 12 squares, 15 mm square,
11.25 mm marker, DICT_5X5_100. It must remain physically fixed. The existing
robot control page is the only manual motion interface. This page owns no motion.

Capture requires a confirmed healthy stationary flange-frame state, <=500 ms
source age, <=120 ms pose/frame timestamp difference, increasing frame IDs,
stationary feedback bracketing the image timestamp, no moving/invalid intervening
feedback, and no flange drift above 2 mm / 0.5 degrees during capture,
at least 20 board markers and 30 ChArUco corners with sufficient coverage.
The velocity threshold is a sampling quality check, not a safety-rated stop.
Actual RGB/ToF synchronization and sub-frame image age are not independently
verified by this adapter and are recorded as limitations.

Collect >=15 diverse orientations and image positions. Intrinsics are fitted
from the current 640x480 SDK stream with OpenCV's fisheye model; every fifth
image is held out. This is not the factory SEUCM model. It avoids inventing or
reusing mismatched intrinsics, but may fail the <=1 px reprojection gate or show
model bias. Hand-eye calibration compares five OpenCV methods on a 4/5 training,
1/5 held-out split; outputs include individual residuals. Insufficient orientation
diversity or invalid rigid transforms are rejected. Maximum held-out translation
<=10 mm and rotation <=2 degrees only mean numerical consistency; they are not
independent absolute point-error or physical grasp validation.

Every sample is persisted in a new deployment-local session directory and
candidate results use unique filenames. Each candidate binds an immutable sample
manifest and hashes of its raw NPZ files; later captures do not overwrite it.
No result is automatically activated.
`approved_for_bottle_grasp` remains false and physical validation remains pending.
TCP and low-speed physical path checks are still required before gripping.

Runtime: existing `thirdhand-groundedsam2` Python (OpenCV 4.11); Node from the
live deployment, using its existing `ws` package. No dependencies installed and
no online Vision dependency changed.

`THIRDHAND_LIVE_ROOT` optionally overrides the existing runtime checkout location;
the default is `ThirdHand/UIEAclub_ThirdHand_VLA` under the operator's home.

Tests:
```
python -m unittest test_handeye_core test_handeye_web
NODE_PATH=/path/to/live/services/robot/node_modules node --test test_robot_reader.js
```

Deployment verification (2026-10-04): adapter Python tests 13/13 and real
WebSocket subscriber test 1/1 passed; root Node suite 132/132 passed.
Root Python suite: 145 passed, 49 subtests passed, 2 failures remain:
`test_depth_evidence_projects_only_with_physically_approved_handeye` (existing
projection test double lacks `projection_allowed`) and
`test_unified_foundation_has_no_machine_specific_runtime_paths` (three existing
hard-coded path references outside this adapter). This is not a full-suite pass.
Physical calibration, TCP measurement and empty-gripper path validation are not
claimed complete. The live UI currently starts with zero samples.
