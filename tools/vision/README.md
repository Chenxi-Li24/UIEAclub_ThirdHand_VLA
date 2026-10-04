# Read-only robot-state relay

This deployment-only helper runs on the robot host. It subscribes to
`ws://127.0.0.1:3000/ws` without sending commands and forwards fresh measured
flange telemetry as `arm_state` to `ws://127.0.0.1:3100/ws`.

`vision_server_with_state.js` is a compatibility copy of the live Vision
entrypoint. It retains the live camera/configuration dependencies and adds only
the missing `arm_state` receive route. The original deployment sources are not
overwritten. Run it instead of, never alongside, the original Vision entrypoint.
Its live dependency path is `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`.

Start the relay from the isolated deployment root:

```sh
node tools/vision/robot_state_relay.js
```

Tests:

```sh
VISION_STATE_ENTRY="$PWD/tools/vision/vision_server_with_state.js" \
  node --test tools/vision/robot_state_relay.test.js tools/vision/vision_state_route.test.js
```

Freshness uses the producer's monotonic timestamp unchanged, with a 250 ms
maximum age and increasing sequences/timestamps. Both services must run on the
same host. JavaScript safe-integer nanoseconds limit host uptime to about 104
days; larger values are rejected rather than rounded. Disconnects, malformed
telemetry, replays and stale data invalidate the last stationary observation.
The stationary classification additionally requires reported nonmovement and
joint speeds no greater than 2 degrees/s; it is not approval for physical motion.

Current hand-eye parameters are numerically validated but physically pending.
The running Vision process uses the existing numerical-preview mode. Base
coordinates are preview geometry, not evidence of calibration validity, collision
safety or successful grasping. Neither helper issues movement/gripper commands
or changes calibration approval. The route test substitutes the camera boundary;
the relay test uses real loopback WebSockets and verifies zero robot commands.

The helper is a detached process, not an installed boot service. Its PID is
recorded under `runtime/run/robot-state-relay.pid`; confirm the command line before
stopping that exact process. No robot service restart is required.

Live activation succeeded after operator approval to pause only the legacy
hand-eye Web service's camera acquisition with its `estop_camera` command.
The legacy Web/robot processes remain running. Vision and this relay are active;
target 1 produced `base_pose_status: ready` and finite base coordinates.
Earlier attempts were rolled back while both services were acquiring XVisio.
Do not resume the legacy camera concurrently with Vision. No physical grasp was
performed; numerical preview and remaining perception blockers are unchanged.
