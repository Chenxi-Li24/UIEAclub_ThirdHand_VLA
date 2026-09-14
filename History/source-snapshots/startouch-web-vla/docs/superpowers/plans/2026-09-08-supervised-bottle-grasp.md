# Supervised real bottle grasp implementation plan

**Goal:** Reuse the existing RGB-D, detector, hand-eye transform, Startouch bridge and four-stage controller to lift one specified upright soft plastic water bottle at least 5 cm and hold 3 seconds. No placement. Five physical trials, at least four observed successes.

**Scope authority:** User's 2026-09-08 explicit Test 1–5 instructions in this task. A person is present and has confirmed access to the hardware emergency stop. Each new physical stage still requires the user's confirmation.

**Architecture:** Existing PinZi camera/model code produces timestamped observation JSON lines. A standalone terminal runner consumes those observations and actual robot states, prints a candidate plan, and adapts the existing GraspController to the hardware-tested TH-Fanxy StartouchBridge. Existing production execution/approval flags are unchanged. Pending calibration remains visibly pending; supervised physical checks are recorded as such, never fabricated as approved calibration.

**Tech stack:** Existing Python/NumPy/OpenCV/Grounded SAM, Node.js, Startouch SDK and SocketCAN. No new learned grasp planner or web service.

- [x] Locate and actually exercise live XVisio RGB-D and existing bottle detector.
- [x] Reproduce and fix lost/invalid/stale target before close in `web-control/server/grasp-controller.js`, with regression tests.
- [ ] Add `web-control/server/supervised-grasp-plan.js`: strict observation/robot freshness, workspace and fixed-pose plan checks, distance-based low-speed duration, verified hold metrics. Test with hand-derived fixtures in `web-control/server/test/supervised-grasp-plan-smoke.js`.
- [ ] Add `web-control/scripts/grasp_bottle_real.js`: CLI composition, direct observer and existing bridge process, manual Test 1–5 stages, target-pose printouts, append-only trial records, and powered holding until explicit operator release/stop. No automatic cleanup while holding a bottle.
- [ ] Add the independent observer and tests in the existing PinZi project; use mask valid depth median/MAD, real capture timestamps and explicit target selection. No robot actions from Vision.
- [ ] Add an offline VS Code launch configuration and a short operator guide alongside this entrypoint.
- [ ] Run module tests, simulated controller/bridge integration, then Test 1 live observation with passive robot pose.
- [ ] Test 2: print Home/hover goals; user confirms; execute low speed; wait for physical alignment confirmation.
- [ ] Test 3: descend only after accepted hover; wait for physical grasp-height confirmation.
- [ ] Test 4: close only after fresh valid same-target evidence and confirmation; do not lift.
- [ ] Test 5: lift 8 cm, hold at least 3 seconds, retain powered hold; user records actual bottle clearance/retention.
- [ ] Repeat and record five physical attempts with failure categories detection/depth/calibration/hover/descend/grasp/slip/robot_command. Do not infer success from command completion alone.

## Current bounded correction: stable body XY and supervised nearfield

The last real hover stopped before horizontal travel because viewpoint-dependent body height/width changed the estimated center by 22 mm. Reuse the existing Base-Z 0.120 +/- 0.005 m band and operator-measured 0.063 m bottle diameter; retain independent fixed action Z 0.130 m. Preserve raw depth, observed width and rule provenance separately.

After manually verified hover, freeze a fresh measured RGB-D reference for this trial/target/calibration. Reuse SAM2 and existing SEUCM projection to check live RGB against the anchored body points; missing nearfield depth is never fabricated. Moving segments require fresh same-target RGB; each next segment and close require a post-stop frame, fresh stationary pose and consistent projection. After verified contact the expected reference follows actual TCP translation with orientation-change rejection. Keep the existing controller, low speed, bounded steps, no automatic release and physical lift confirmation.

Validate changed producer, guard and CLI modules plus their boundary contract; then load once with onsite support for the SDK's known disable-on-exit behavior. Resume Test 2 hover, Test 3 descend, Test 4 close, Test 5 lift/hold with operator checkpoints. No new framework or broad refactor.
