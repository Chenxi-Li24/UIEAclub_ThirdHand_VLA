# PR #16 Conflict Resolution and Offline Verification

## Scope

- PR: Chenxi-Li24/UIEAclub_ThirdHand_VLA#16.
- Head: Xavier/web-grasp-tcp-integration at 73e3a097.
- Main merged without rebasing or rewriting history: 56114e8e.
- Development occurs in the isolated web-grasp-tcp-ci-20261011 worktree.
- Commit, push, deployment and physical motion require separate approval.

## Merge Decisions

- Bottle grasp behavior follows the Xavier branch. Keep its fixed initial depth target, horizontal approach, phase-linear execution, measured TCP integration, one-click UI, and contact/lift result reporting.
- index.html retains both the TCP calibration link and main's language selector and language assets. Keep the Xavier stylesheet and main-module versions.
- test_joint_speed.py retains both branches' tests: explicit 10% ceiling coverage and generated SDK configuration consistency checks before SDK construction. The ordinary default remains 5%; Dummy follow limits are independent.
- Main's removal of the migrated Meituan copies remains in the merge. This is inherited main history, not an extra deletion of running deployment files.

## CI Fixes

- The motion tracking test accessed THIRDHAND_LIVE_ROOT during module collection, before the autouse fixture could set it. Default to the root derived from __file__, retaining an explicit environment override.
- Main changes only the generated SDK velocity reference and the bridge's pre-construction configuration validation. Update the corresponding provenance hashes and linked policy/calibration IDs. Record the previous IDs.
- No handeye extrinsic, SDK tool transform, grasp TCP offset, joint range, or physical-validation status is changed. The handeye physical-validation status remains pending.
- Register mock WebSocket cleanup before constructing the vision service, so a policy validation exception cannot leave Node tests hanging. Bound the regression test's runtime.
- Add a regression test requiring the language controls, TCP calibration link and Xavier grasp panel to coexist.

## Deployment Boundary

- Tests use fake robot/vision sockets or pure calculations. No production service is started, stopped or reconnected by these changes.
- Passing offline CI does not establish physical grasp accuracy or authorize motion.
- Existing active TCP artifacts remain immutable. A changed frame-policy identity is not silently accepted as a new physical calibration.
- The checked-in policy binds the repository's current file representation, including SDK LFS pointers in a source-only checkout. A production checkout with hydrated SDK binaries must validate or prepare its runtime policy against those actual binaries before deployment; do not bypass the hash guard or rewrite measured artifacts just to unlock execution.
