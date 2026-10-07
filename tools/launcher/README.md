# One-click startup

The Ubuntu desktop shortcut and Windows `Start ThirdHand.lnk` use
`./thirdhand ensure-all` in the formal Ubuntu checkout.

The command preserves the existing launcher behavior:

1. Ensure `manual-control` in the formal checkout (3000, 3004, 3100, 8766, 9983).
2. Ensure `meituan-web` in the Meituan checkout (1034).
3. Check 1035; if its listener is missing, start or repair only its shared Vision owner.

1035 is a second listener in the **existing 3100 vision process**. It uses the
same camera owner and does not launch another camera or load another model.
The manual-control vision configuration enables this listener at startup.

Healthy services are reused. Missing configured services are started through
their existing launchers. The command does not send robot motion commands.
If any ensure operation or the 1035 health check fails, it exits nonzero;
both shortcuts keep their existing partial-readiness/error behavior.

If 1035 refuses connections, the command takes an OS-level `flock` and rechecks
readiness. If 3100 is also missing, it starts only the configured Vision service.
Otherwise it validates the existing 3100 owner (same user, executable, entrypoint
and process-start identity), stops it gracefully, then restarts the **same**
entrypoint with its original working directory and environment plus the 1035
listener settings. This preserves the deployed camera bridge and calibration.
The accepted entrypoints are the formal Vision server and the
`deployments/<deployment>/tools/vision/vision_server_with_state.js` compatibility
server. Other processes, occupied/mismatched 1035 endpoints and changed identities
are reported as failures, not killed. A shutdown timeout never starts another
camera owner. Recovery does not restart Robot, Speech or Web; the original
manual-control CAN recovery behavior remains unchanged.

A healthy 1035 is reused without restarting Vision. A Vision repair briefly
interrupts both 3100 and 1035 video. Diagnostic logs and the lock live under the
formal checkout's ignored `runtime/` directory, never in source commits.

Default locations on this installation:

- Formal checkout: `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`
- Meituan checkout: `/home/nieqingcao/ThirdHand/worktrees/cyb_branch/meituan`

The formal checkout is derived from the launcher location. Override
`THIRDHAND_FORMAL_ROOT` or `THIRDHAND_MEITUAN_ROOT` if these directories move.
1035's host and port are read from the formal `manual-control.json` vision
environment (`MEITUAN_VISION_HOST`, `MEITUAN_VISION_PORT`).

The Windows shortcut still prompts before opening the existing 9983 page.
Adding 1034/1035 does not change the browser's default destination.
