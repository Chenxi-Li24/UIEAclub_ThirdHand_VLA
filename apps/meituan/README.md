# Meituan Source Migration

This app contains the separately developed 1034 UI and battery workflow source.
It shares the project Robot, Speech, Vision and robot assets; it never owns CAN
or opens a second camera.

## Current Boundary

The user approved source migration only, without enabling Meituan robot motion.
The gateway permits state, ping, IK preview and software stop, but refuses robot
connect/disconnect, motion, presets, gripper writes, Skill execution approval and
active-depth HTTP start with `meituan_motion_not_enabled`. Recognition and voice
service access remain available. Environment flags alone cannot enable motion.
Formal 9983 control and Dummy direct-3000 control are not changed by this boundary.

The preserved route executor has only per-gateway ownership. It must acquire
shared Robot Service route ownership before a future, separately approved motion
enablement; a hold between steps must not allow another caller to insert motion.
Taught poses, SDK-model agreement, calibration and real operation still require
separate commissioning. Source migration and fake-backend tests do not approve
physical execution. Software stop is not a hardware emergency stop.

## Entry and Verification

Start services only during an authorized deployment, using the project root:

```bash
./thirdhand start --profile meituan-web
```

`configs/runtime/meituan-web.json` selects `apps/meituan/src/server.js` and port
1034. The existing manual-control profile supplies the shared dependencies.
Offline checks use only fake transports and a temporary loopback HTTP server:

```bash
node --test tests/node/web/meituan-read-only.test.js
```

See `docs/deployment/DEPLOYMENT_TO_MAIN_20261007.md` and
`docs/deployment/INTEGRATION_REVIEW_20261007.md` for provenance and remaining gaps.
