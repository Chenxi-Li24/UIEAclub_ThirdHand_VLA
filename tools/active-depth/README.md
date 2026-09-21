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

Live aiming requires a separately reviewed authenticated joint-motion
primitive, a verified mount, fresh stationary robot state, collision
clearance, and operator confirmation. The existing manual WebSocket path is
not a substitute.
