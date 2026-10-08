# Integration Review: 2026-10-07

## State

Offline integration is verified; a merge commit still requires human approval.
No integration commit, push, PR merge or live
deployment switch has occurred. The approved source snapshot is 727aa2c.
All changes below concern the isolated integration worktree.

## Fresh Verification

- Node: 235 passed after the Vision repair and approved Meituan read-only corrections.
- Formal Python: 256 passed, 58 subtests passed in the existing test runtime.
- Clean CI venv: initially failed 29 tests due to missing dependencies; after
  adding IKPy, Torch/Transformers and Norfair with the runtime's NumPy/OpenCV
  constraints, 256 passed and 58 subtests passed; pip check passed.
- Formal Dummy: 224 passed; its apps/src/configs/tests match remote baseline.
- Additional clean-venv full Dummy run initially failed two optional Mink tests
  because the slim CI environment intentionally lacks Mink/MuJoCo. Installing
  the declared experimental engines plus DAQP yielded all 224 passed and a clean
  pip check. DAQP is now explicit in requirements-dummy.txt; CI's 85-test default
  Dummy subset does not require the optional experimental engines.
- Legacy experimental Dummy: 119 passed after test fixture/async entry updates.
- CI Dummy subset: 85 passed in the clean lightweight environment before the
  expanded model-interface dependencies were installed.
- Source boundary audit ready; staged whitespace check clean.
- Resource verify-only: 4097 size/SHA-256 checks passed; zero assembled files.
- Inventories: 147 snapshot paths and 85 external source paths accounted for.
  Axis-response, pending-confidence test and both original normalized evidence
  files preserve their original bytes. No calibration values changed.

These are offline checks, not a real-world grasp, tracking or deployment test.

## Independent Review Findings

1. Important, addressed by approved scope restriction: Meituan has only local 1034 route ownership.
   During a route hold, the common 3000 admission check can accept motion or
   gripper commands from 9983/other callers. Shared route ownership at Robot
   Service requires additional adaptation. The user chose source migration only,
   without enabling Meituan motion. The 1034 gateway now refuses raw mutation,
   approval dispatch and active-depth HTTP start; status, IK preview, recognition
   and software stop remain available. Old enabling environment variables cannot
   bypass this explicit restriction. Four fake-transport/HTTP tests failed before
   correction, then passed; the complete Node suite passed 235 tests.
   Executor source remains preserved, but shared route ownership must be verified
   before any later motion enablement. Formal 9983 and Dummy are unaffected.
2. Important, fixed: shared Vision listener repair overlaid the entire profile
   environment on an existing process. It now preserves the captured environment
   and changes only MEITUAN_VISION_HOST / MEITUAN_VISION_PORT. A fake-process test
   with conflicting bridge/Python/config/handeye/URDF/battery-module values failed
   before correction, then the full 231-test Node suite passed. No live Vision
   process was signaled or restarted.
3. Minor, deferred: ordinary web proxy retains pending request entries after a
   browser disconnect. This can leave hasActiveControl true and block optional
   grasp admission. The default optional grasp implementation is absent; this
   finding does not establish that its execution feature is usable.
4. Dependency residual: npm audit reports indirect fast-uri moderate advisory
   GHSA-hrr3-gc8f-f4qj. No unrelated automatic dependency upgrade was performed.

## Review Exclusions

The fresh reviewer explicitly did not certify:

- CAN/SDK behavior, physical stopping, follow performance, homing, speed or torque.
- Physical calibration, collision clearance, grip TCP, battery retention or placement.
- Pending runtime-confidence APIs and UI protocol.
- Complete motion-preview routing and non-lift-only buildPlan.
- Absent optional WEB_GRASP_CONFIG implementation or autonomous grasp execution.
- Default projected-coordinate availability while relay is not enabled.
- Old policy bindings against external/live SDK binaries and configuration.
- External prototype originality beyond inventoried source/hash evidence.
- Legacy Dummy algorithms and old gateway hardware behavior.
- Fixed-TCP hardware behavior and concurrent SDK ownership.
- Live Meituan model/SDK agreement, taught points and complete protocol compatibility.
- Browser rendering, camera capture, inference quality, speech or provider behavior.
- Actual launcher restart, process recovery, LAN access or Windows shortcut execution.
- Package-index availability and broad-suite execution; the implementer ran those.
- Vendor internals and supply-chain provenance beyond inspected copied identity.
- The 4097-resource verification; the implementer ran it separately.

These exclusions remain limitations, not approvals or claims of functionality.

## 2026-10-08 Supplement

See `OMISSION_SUPPLEMENT_20261008.md` for the latest-primary source integration,
historical calibration disposition and pending ordinary-merge ancestry. The
initial verification counts above describe the earlier snapshot, not this run.
Fresh supplement checks passed Node 243, formal Python 263 plus 58 subtests,
formal Dummy 224 and legacy Dummy 119; boundary audit and 4097 resource hashes
also passed. All 147/85 original inventory entries remain accounted for.

The previously deferred ordinary web disconnect cleanup is included in the
later primary fixed-TCP changes: session-owned forwarded motion entries are
removed on browser close. Fixed-TCP cancellation and global dry-run regression
tests failed before the isolated corrections and passed afterward. A clean
environment exposed a legacy repeated-frame timing defect; its deterministic
stale-frame regression now passes without altering formal Dummy.

The one bounded supplementary review found four additional source issues. Each
was addressed in the isolated worktree with fake-transport/arm regressions:

1. Important: reconnect could clear the reusable stop event of an unfinished
   demo. Per-run irreversible cancellation, connection generations and reconnect
   refusal while a worker remains active now prevent that revival. A blocking
   fake demo reproduces the old defect and verifies cancellation remains set.
2. Important: fixed time-mode demo stages bypassed the ordinary waypoint speed
   scale. All stages now use bounded SDK speed mode, preserving the configured
   lower service scale and leaving Dummy's separate continuous-follow policy
   unchanged. Geometry is retained; SDK retiming is not hardware-certified.
3. Moderate: another socket could reuse an active broadcast ID, be rejected, then
   acquire cancellation rights. Cancellation now checks admitted owner and ID.
   Controller and two-client tests use a stub bridge, without constructing SDKs.
4. Moderate: discarded queued work or lost transport could retain stale proxy
   busy records. Queued cancellation receives one terminal error; active demo
   cancellation is terminal. Proxy cleanup distinguishes confirmed stop from
   uncertain loss, requiring fresh idle feedback before clearing uncertainty.

The new regressions failed before their corrections; targeted checks and the
complete Node/Python suites passed after them. No second reviewer was dispatched.
Final staging and whitespace are checked before requesting merge-save approval.
Physical/deployment exclusions still apply: the demo shares port 3000's SDK owner
but has not been certified on hardware, and source review is not real-world
stopping or collision validation.
