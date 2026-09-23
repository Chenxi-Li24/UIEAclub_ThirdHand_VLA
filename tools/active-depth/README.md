# Active-depth offline preview

This tool only reads a JSON fixture. It cannot connect to or move the robot.
Its pixel prediction is a **rotation-only bearing estimate** because a bottle
without depth has unknown range; the camera itself can still translate as the
wrist rotates. Do not use the displayed joint angles as a motion command.

Run from the repository root:

```sh
node tools/active-depth/preview.js --fixture /path/to/fixture.json --target-id 2
```

The fixture contains `observation` (Vision Service `frameId`, `observedAtMs`,
`selectedStableId`, `targets`, `camera_mount_id`, `registration_id`),
`robotSnapshot` (`jointsDeg`, `startJointsDeg` after a prior step,
`observedAtMs`, `stateName: "IDLE"`, `jointLimitsDeg`), `mount`
(`matrix_4x4`, camera and registration IDs, `physical_validation.status`),
and optionally `previousStep` (`targetId`, `beforePixel`, `predictedPixel`,
`completedAtMs`). `nowMs` may be supplied for deterministic fixture replay.

The current Vision Service observation does not carry the camera identity
fields, so a raw response alone correctly produces `camera_evidence_missing`.
Use evidence from the same camera/registration source, not invented IDs. The
checked-in mount is physically unverified and therefore adds
`mount_unverified`. Exit code 2 means at least one blocker or invalid CLI
input; no result is executable even when there are no blockers.

## Web-triggered alignment

The reviewed online path is available in the XVisio drawer as **开始深度对准**.
Selecting a target never starts motion: the operator must select stable target
1–5 and press the button separately. Service startup also never starts a
session. `robotControlEnabled:false` in Vision is expected because Vision owns
evidence, not robot execution; it is not the alignment gate.

The Web Gateway reads fresh Vision evidence and stationary Robot state, plans
J4–J6 first, and uses J1–J3 only after the wrist tier has no valid improving
candidate. Every step goes through authenticated loopback `/execution`; the
manual `/ws` route is never a fallback. Limits are 2° per wrist step and 10°
cumulative per wrist joint, 1° per arm step and 5° cumulative per arm joint,
5 mm camera displacement per step, 20 mm camera displacement per session,
20 completed steps, and 90 seconds. Three increasing depth-valid frames are
required for `depth_acquired`.

Status phases are `idle`, `observing`, `moving`, `depth_acquired`, `failed`,
`stopped`, and `uncertain`. Stop uses the protected execution channel. An
`uncertain` result requires physical inspection; the software does not retry,
reverse, grasp, descend, or place automatically.

Start the normal hardware profile from the repository root:

```sh
./thirdhand start --profile manual-control
```

The launcher supplies Robot and Web with the same owner-only
`runtime/run/robot-execution.token`. Before the first live session, keep the
physical E-stop reachable, clear the entire swept workspace, place the target
near the depth ROI, and observe the first wrist and fallback steps separately.
