# Meituan competition waypoints

Joint angles are in degrees. These are manually recorded reference poses, not a validated motion path.

| Point | J1 | J2 | J3 | J4 | J5 | J6 | Source |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| OBSERVE | 0.0 | 90.0 | -90.0 | 90.0 | 0.0 | 0.0 | Operator confirmed this pose was tested on 2026-10-03 |
| TASK1_A | 31.2 | 116.0 | -97.4 | 71.9 | 0.2 | -57.7 | Joint-control screenshot supplied on 2026-10-02 |
| TASK1_T0 | -22.5 | 98.0 | -74.8 | 67.1 | -0.6 | -112.0 | Operator-designated joint-control screenshot supplied on 2026-10-03 |
| TASK2_A | 35.6 | 121.2 | -106.4 | 76.5 | 0.2 | -52.6 | Operator-designated joint-control screenshot supplied on 2026-10-03 |
| TASK2_B | 26.0 | 111.8 | -92.8 | 72.4 | 0.2 | -62.4 | Operator-designated joint-control screenshot supplied on 2026-10-03 |
| TASK2_C | 44.6 | 107.4 | -85.9 | 71.0 | 0.4 | -43.7 | Operator-designated second joint-control screenshot supplied on 2026-10-03 |
| TASK2_D | 32.8 | 95.3 | -71.7 | 68.7 | 0.0 | -55.4 | Operator-designated first joint-control screenshot supplied on 2026-10-03 |
| TASK2_P1 | -5.912 | 111.350 | -89.603 | 73.035 | -2.415 | -96.007 | Recorded from 1034 live joint feedback |
| TASK2_P2 | -29.540 | 124.792 | -109.798 | 79.854 | -4.120 | -124.289 | Recorded from 1034 live joint feedback |
| TASK2_P3 | -45.867 | 93.078 | -67.746 | 67.899 | -4.098 | -140.966 | Recorded from 1034 live joint feedback |
| TASK2_A_BEFORE | 35.463 | 122.563 | -120.312 | 89.887 | 0.208 | -52.511 | Recorded from 1034 live joint feedback |
| TASK2_A_AFTER | 35.507 | 126.956 | -135.961 | 98.000 | 0.186 | -52.511 | Recorded from 1034 live joint feedback; J4 capped from 98.083° at the 98.000° joint limit |
| TASK2_B_BEFORE | 26.021 | 112.246 | -105.034 | 85.034 | 0.186 | -62.150 | Recorded from 1034 live joint feedback |
| TASK2_B_AFTER | 26.021 | 114.323 | -116.508 | 94.520 | 0.186 | -62.325 | Recorded from 1034 live joint feedback |
| TASK2_C_BEFORE | 44.577 | 107.372 | -97.493 | 83.636 | 0.361 | -43.878 | Recorded from 1034 live joint feedback |
| TASK2_C_AFTER | 44.577 | 108.531 | -108.115 | 92.815 | 0.382 | -43.703 | Recorded from 1034 live joint feedback |
| TASK2_D_BEFORE | 32.818 | 95.001 | -82.914 | 81.384 | -0.055 | -55.353 | Recorded from 1034 live joint feedback |
| TASK2_D_AFTER | 32.818 | 95.438 | -92.313 | 90.018 | -0.055 | -55.353 | Recorded from 1034 live joint feedback |
| TASK2_P1_BEFORE | -6.612 | 109.143 | -99.394 | 84.269 | -2.197 | -94.520 | Recorded from 1034 live joint feedback |
| TASK2_P1_AFTER | -6.655 | 110.345 | -110.039 | 93.668 | -2.218 | -94.498 | Recorded from 1034 live joint feedback |
| TASK2_P2_BEFORE | -28.950 | 128.027 | -128.420 | 94.957 | -4.142 | -123.852 | Recorded from 1034 live joint feedback |
| TASK2_P3_BEFORE | -44.708 | 94.673 | -82.171 | 81.231 | -3.923 | -139.917 | Recorded from 1034 live joint feedback |
| TASK2_P3_AFTER | -44.708 | 95.438 | -90.958 | 89.428 | -3.923 | -139.939 | Recorded from 1034 live joint feedback |
| TASK1_A_BEFORE | 31.091 | 116.137 | -109.383 | 84.532 | 0.208 | -57.473 | Recorded from 1034 live joint feedback |
| TASK1_A_AFTER | 31.091 | 118.607 | -121.710 | 94.302 | 0.208 | -57.648 | Recorded from 1034 live joint feedback |
| TASK1_T0_BEFORE | -22.458 | 97.668 | -85.297 | 78.893 | -0.667 | -111.897 | Recorded from 1034 live joint feedback |
| TASK1_T0_AFTER | -22.458 | 98.061 | -94.498 | 87.286 | -0.688 | -111.897 | Recorded from 1034 live joint feedback |

`OBSERVE` is the operator-verified top-down viewing pose. This validates the recorded joint target, not a collision-free path from every starting pose.
`TASK1_A` is the Task 1 reference point accepted by the operator. Values are transcribed from the screenshot at 0.1-degree precision; they are not the previous calculated target angles.
Verify robot state and clearance before using this point for physical motion.

## Task 1 gripper openings

| Action | Target opening | Evidence |
| --- | ---: | --- |
| Grasp | 35% | Operator tested: holds the battery |
| Release | 70% | Operator tested: does not pull the battery away |

These are target openings, not force settings. The commanded grasp/release openings and shared Robot Service hardware parameters remain unchanged.

For the Meituan route's `grasp` step, keep commanding 35%; do not replace it with a 39% or 40% target. The command-local acceptance rule is fresh finite measured opening `0% <= actual < 40%`, with no 35% lower bound. The shared service completes when this condition first holds; the route then requires fresh stable IDLE feedback below 40% for 300 ms before lifting. Release and preparation retain the existing reached/target-opening checks. Opening feedback alone does not prove battery retention.

## Transfer timing and height parameters

The operator-taught `*_BEFORE` joints are the nominal contact +60 mm poses; the taught `*_AFTER` joints are the nominal contact +100 mm poses. The table below preserves those labels and hold durations. Execution sends the recorded six-axis targets directly; it does not generate new BEFORE/AFTER poses from these distances.

| Parameter | Value | Meaning |
| --- | ---: | --- |
| Pre-contact above | 60 mm | Nominal taught BEFORE height |
| Post-contact above | 100 mm | Nominal taught AFTER height |
| Lift hold | 2000 ms | Start after the battery is lifted and stable |
| Release hold | 3000 ms | Start after complete release and stable placement |

## Cross-zone carrying rule

Use the source AFTER point's actual model-derived base Z for the horizontal transfer to the destination BEFORE XY; do not lower the commanded transfer Z below the operator-verified 146 mm carrying floor. Check fresh transfer feedback against the same floor. This rule applies only while carrying between the source and destination zones; the recorded contact and approach/retreat joints remain unchanged. The operator has physically validated this 146 mm floor.

For now, `TASK2_P2_AFTER` uses the same recorded six-axis target as `TASK2_P2_BEFORE`. This is an explicit operator-selected substitution, not a new point measurement. Keep this substitution in route planning until a separate P2 AFTER target is recorded.
