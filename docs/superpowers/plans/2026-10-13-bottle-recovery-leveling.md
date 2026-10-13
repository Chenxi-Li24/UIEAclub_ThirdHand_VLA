# Bottle recovery and pre-grasp leveling implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Preserve unrelated work and do not commit, push, or command hardware without the user's request.

**Goal:** Recover a selected bottle after a camera pose change without switching bottles, and prepare a horizontal tool before fresh depth acquisition.

**Architecture:** Stable tracking may reclaim a reseeded native track only with a unique anchored appearance match over three fresh observations. Grasp preparation raises the SDK endpoint to at least 0.3064 m with unchanged orientation, then levels at that height, checking workspace and IK before movement. Depth is read only after preparation settles.

**Tech Stack:** Python/numpy/norfair, Node.js, existing browser UI and robot port-forward transport.

**Spec:** User's approved flow in this conversation: click grasp -> safe-height raise -> level -> fresh depth -> grasp. User approved SDK Z=306.4 mm and confirmed clearance at that height. No actuator commands during development.

## Global constraints

- Preserve measured TCP, hand-eye parameters, speed ceiling and existing transport.
- No unanchored recovery across a motion gap, no ambiguous reassociation, no weakened joint or workspace limits.
- Automatic leveling is explicit configuration; old configurations retain the old behavior.
- No robot/SDK restart. Deployment only while all workflows and arm are idle.

## Review focus

Wrong bottle, duplicate/replayed observation, recycled detector ID, IK failure before preparation, and stale depth from before leveling must fail safely or be rejected. Tests below cover each.

## Task 1: Anchored selected-ID recovery and depth identity

**Files:** tracking/stable_ids.py, tracking/norfair_adapter.py, selection/stable_selector.py under services/vision/python/thirdhand_va/vision; camera_bridge_with_frames.py; new tests/python/vision_service/test_track_recovery_unittest.py.

**Interface:** Existing StableTrackManager.update API; selected lost track exposes target_reacquiring or target_reselection_required blockers. attach_depth_evidence matches backend_track_id, never recycled detection_id.

- [ ] Write and run failing unittest cases for three-fresh-frame recovery, ambiguity, wrong descriptor, movement, replay and lost-target depth collision.
- [ ] Implement bounded <=40 mm anchored recovery and preserve request ownership.
- [ ] Run new and existing motion/projection/geometry unittests in isolated remote worktree.

## Task 2: Checked preparation before depth

**Files:** apps/web/src/grasp/preparation.js (new), geometry.js, coordinator.js, apps/web/public/js/main.js, apps/web/public/index.html, apps/web/configs/web-grasp.json; new Node preparation tests and coordinator regressions.

**Interface:** buildPreparation(robot, config) -> ordered phases of sampled SDK poses. Coordinator checks all samples before dispatch, verifies phase endpoints and stationarity, then calls _depth with no cached observation. Configuration autoLevelBeforeDepth=true, safeLevelSdkZM=0.3064.

- [ ] Write and run failing tests: raise-before-level-before-depth, no descent above safe height, yaw retained, malformed config/workspace/IK rejected without commands, no gripper before fresh depth.
- [ ] Implement geometry and preparation phases using existing move_l transport; preserve horizontal invariant after preparation.
- [ ] Add bounded initial target-recovery waiting, without changing post-depth frozen-target guards.
- [ ] Update UI preparation phases and actionable reselection messages.
- [ ] Run full Node suite and focused Python suite, then fresh-context review.

## Deployment

Back up exact files, check live dirty state and hashes, preserve collaborator changes, restart only web/vision owners while idle, and verify current APIs. No physical grasp claim until a separate observed run.

## Execution record

- Tasks 1 and 2 implemented and deployed on 2026-10-13. No Git commit/push or hardware motion was performed.
- Remote isolated full Node suite: 508/508. Focused Python unittest suite: 50/50 (recovery, motion tracking, geometry, frame projection). Full Python pytest suite was not run; pytest is unavailable in the deployed interpreter.
- Fresh-context review: no remaining critical/important findings. Regression tests first reproduced and then fixed reseeded neighboring-bottle theft, below-minimum preparation height, and recovery waiting on a tilted start.
- Height decision: 306.4 mm is the strict minimum SDK Z before any rotation. Raise target includes 1 mm reach-tolerance headroom; leveling keeps the measured raised SDK position, never lowers to the nominal waypoint.
- Identity decision: freeze competing bottles' anchors at reservation time, including after their native records retire. A visually similar competitor without an anchor prevents automatic reassociation.
- Integration decision: preserve fetched main cf6a9ee English/i18n UI additions and portable frame-policy/calibration IDs; overlay only this task's changes. Do not replace live deployment configuration with the repository portable profile.
- Deployment backup: /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/runtime/bottle-level-repair-20261013.NaN6N0. Web PID 134752, Vision PID 134712. Robot PID 21377 and SDK PID 21385 unchanged. Calibration artifacts, shared execution token and collaborator staged changes verified unchanged.
- Live checks: grasp enabled=true, autoLevelBeforeDepth=true, safeLevelSdkZM=0.3064; camera/inference ready; new confirmed bottle ID1 visible. At verification, only 66-70 valid depth points; no metric target or physical grasp success claimed. Selection cleared by Vision restart; operator must reselect from the new image.
- Review minor deferred: new preparation/status strings are not all registered in the existing bilingual catalog and may display mixed languages. This does not change control behavior.
- Reviewer declined physical clearance, real robot behavior, deployment status and the earlier TCP patch. Clearance was explicitly confirmed by the user; physical motion remains untested; deployment and protected artifacts were independently checked here; earlier TCP compatibility remains unchanged.
