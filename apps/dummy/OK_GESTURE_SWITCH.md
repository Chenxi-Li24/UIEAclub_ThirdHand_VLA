# Dummy PALM Gesture Target Switching

The trigger is now an open palm (`palm`), not OK. The existing
`ok_switch` configuration/status key, `OkSwitch` class, `ok` selection event,
legacy reason strings and this document's filename remain compatibility names.
They now represent palm-driven selection; telemetry includes
`trigger_label: palm`, and the displayed hand/progress/event labels use PALM.

## Scope

Dummy initially chooses a face automatically. A uniquely associated person may
request selection by holding a PALM hand gesture. Face-first following and the
existing calibrated body head anchor remain in use. Complete target loss still
allows automatic face reacquisition. This is temporal tracking, not biometric
identity recognition.

The gesture detector does not issue robot commands. Only the existing Dummy
runtime sends J1/J4 follow targets through TouchR1Adapter to port 3000. Existing
joint/workspace limits and Robot Service speed policy are unchanged. Keyword
motions are not restricted to J1/J4. Idle breathing remains disabled.

## Model And Preparation

Official HaGRID YOLOv10n gesture checkpoint, 22,442,394 bytes. Its observed label
map has `palm` at class 20; the adapter resolves `palm` by name instead of assuming
that index. Configuration, provenance and SHA-256 are in
`configs/ok-gesture-model.json`. The runtime rejects missing, mismatched or
non-gesture weights. Missing weights disable PALM switching with an explicit
diagnostic while ordinary face/body following remains available.

From the project root, prepare with the project's Python 3.11 runtime:

```bash
local/runtimes/dummy-python/bin/python apps/dummy/apps/prepare_ok_model.py
```

Weights are stored at `local/models/vision/YOLOv10n_gestures.pt`. No dataset is
downloaded. Existing Ultralytics/Torch dependencies are reused; no HaGRID repo
checkout, MediaPipe hand model or second camera process is required. Consult the
upstream HaGRID license linked in the manifest before redistributing weights.

The same preparation command now also verifies/prepares YOLOv8n person pose at
`local/models/vision/yolov8n-pose.pt` (6,832,633 bytes), pinned by
`configs/ok-pose-model.json`. The existing Ultralytics runtime supplies its 17
COCO keypoints: https://docs.ultralytics.com/tasks/pose/ . Pose inference occurs
only when PALM hands are detected, in the existing asynchronous gesture worker;
no second camera stream or motion owner is added. Missing/invalid pose weights
disable PALM switching, not ordinary following. Redistributing this additional
model requires checking its AGPL-3.0/Ultralytics licensing terms.

## Data Flow

1. Vision Service alone owns XVisio. Dummy's existing MJPEG reader receives RGB.
2. YuNet and BoT-SORT process a latest RGB frame; faces and body IDs belong to
   that same frame.
3. One asynchronous gesture worker consumes those in-memory frames, with one
   replaceable pending slot. Default rate is at most 8 Hz on CPU.
4. A result carries its frame ID, receive timestamp, tracker/keyword epoch,
   body and face snapshots, and inference duration. Duplicate frames never
   advance confirmation. Results older than 500 ms cannot switch targets.
5. The same gesture image is passed to the pose model. A visible wrist must
   touch the PALM hand region with a confident elbow/shoulder chain. Its pose box
   must match one BoT-SORT body with IoU >=0.45 and a >=0.15 lead over alternatives.
   Keypoint confidence >=0.35; hand padding is 35%. Hand-in-body rectangles are
   no longer sufficient and there is no ROI fallback if pose evidence is absent.
   The face/body binding may survive a brief missing face (<=0.80 s since a real
   face observation), provided the body ID is unique and continuously observed
   with IoU >=0.5. Missing, overlapping or discontinuous bodies invalidate the
   binding. An unknown person without a real prior face cannot be selected.
   Multiple supported owners or multiple people making PALM reject the switch.
   A competing wrist-compatible arm whose pose cannot uniquely map to a body
   vetoes the entire hand association; it is not discarded to favor another
   person. Explicitly ambiguous faces cannot be repaired by a cached binding,
   and a newer face observation cannot authorize an older gesture image.
6. Formal config confidence >=0.65, hold >=0.10 s, >=3 accepted results from the
   latest 4 distinct results for the same person, with the latest result accepted.
   Duration is measured from the oldest accepted result still in that window.
   A missing hand occupies a negative slot only while historical/current body
   and face-binding evidence remains continuous and unique; it is never an
   accepted vote and cannot itself trigger selection. Ambiguity, identity loss,
   stale results, backwards time, epoch changes or gaps >0.35 s clear confirmation.
   Duplicate results do not count. At 8 Hz, collecting 3 accepted results normally
   takes at least about 0.25 s; the 0.10 s gate is not an end-to-end latency promise.
   Holding PALM produces one event; absence of recognized PALM for
   >=0.30 s while that person remains uniquely face/body-visible rearms.
   Missing/ambiguous people do not count as release. Hand occlusion or low
   confidence may still look like release, so this is not physical hand-state
   verification. Two hands from the same person count as one owner's request.
   Global cooldown is 1 s. PALM by the currently selected person is a no-op.
   Current body loss/ambiguity also interrupts release timing between gesture
   results. Delayed pre-loss images cannot backdate a new release interval.
7. A confirmed switch updates the selected body ID and generation, recalibrates
   its face/body anchor and blends the image point. Runtime clears old-target
   controller error without recentering joints or widening the original
   excursion envelope. Commands are computed from measured joints.
8. Keyword actions inhibit selection. In-flight gesture results are invalidated
   across keyword boundaries without clearing already-held gesture latches.
   Frames received before resume cannot start confirmation. Following and PALM
   confirmation require fresh
   observations afterward. No old PALM event is queued to run later.
   Both explicit PALM changes and automatic face reacquisition are inhibited
   during keyword actions. Current face/body observations update bindings even
   when asynchronous gesture output is absent or duplicated; missing/ambiguous
   current bodies reset an in-progress confirmation immediately.

Thresholds are in `ok_switch` in `configs/dum_e_touch_r1.yaml`. Receive age is
not camera capture latency. Near-time asynchronous hand boxes are mapped with
the associated body's current box for display only and marked `prev#FRAME_ID`;
fresh but unassociated hands are shown with no owner and the original source
coordinates, not reassigned to another body. Stale hands are omitted. This
mapping is not a fresh hand
detection and is never used as switching or motor evidence. Status retains the
actual gesture source frame ID and age separately from the current RGB frame.
Purple shoulder/elbow/wrist lines are display-only evidence from that same
previous gesture image. `raw_bbox` retains the original hand rectangle.

Selection events distinguish `auto_initial`, `auto_reacquire`, and `ok`, carrying
previous/new IDs and generation. PALM by the current person reports
`already_selected`, not a successful identity change.

## HOLDING / LOST Diagnostics

A visible box alone does not authorize following. `loss_reason` distinguishes
`vision_frame_stale` (received frame older than 500 ms), `observation_expired`
(last detected target expired), and selector rejection such as
`selected_person_missing`, `people_overlap_ambiguous`, or `track_discontinuity`.
After body continuity is broken, BODY-only following remains paused with
`identity_reconfirmation_required` until a fresh unique face reestablishes the
anchor. Normal continuous BODY following still works when only the face drops
out; the 0.80 s binding timeout limits PALM selection, not normal BODY following.
Camera stream-unavailable/stale paths also invalidate the body anchor, recent
face bindings and gesture confirmation/release evidence. Normal duplicate RGB
frames do not count as body disappearance and do not advance gesture timing.
The preview explicitly prints the reason and receive age. An old selected body
is gray rather than active cyan; old boxes may remain as historical context.
Receive age now uses the actual received timestamp even when a stale target is
published, instead of the time the stale-frame rejection ran. Duplicate frames
still do not publish a new observation or refresh the control timestamp.

HOLDING with a fresh FACE/BODY and `deadzone` is normal centering, not LOST.
Do not increase freshness limits simply to remove a LOST label. Receive time
still is not a hardware camera capture timestamp.

## Read-Only Verification

```bash
local/runtimes/dummy-python/bin/python -m pip install -r apps/dummy/requirements-tests.txt
local/runtimes/dummy-python/bin/python -m pytest apps/dummy/tests -q
local/runtimes/dummy-python/bin/python apps/dummy/apps/run_head_body_follow.py \
  --no-keywords --max-frames 300 --telemetry-port 31025
```

Without `--enable-motion`, there is no Robot Service adapter or motor command.
Use two separated people: initial face A, B holds PALM for about one second, keep
holding (no repeat), release, then A holds PALM. Verify selected ID/generation and
`ok_switch.reason/progress` through read-only telemetry `/api/status` or frame
`/api/frame`. Test poor confidence, missing faces, overlapping bodies, stale
frames and simultaneous PALM; none should force a switch. Physical effectiveness
is not established by unit tests alone.

Existing web Dummy preview uses this same telemetry frame, not another detector.
This change does not start Dummy, reconnect the SDK or restart the web server.
Existing controls will load it on the next separately authorized Dummy start.

## Shutdown

SIGTERM/Ctrl+C stops Dummy keyword intake, its own continuous follow session,
MJPEG reader, detection worker, PALM worker and telemetry server. The shared
3000/SDK, web, speech and Vision Service remain running. No home/zero movement,
SDK disconnect or idle breathing is triggered by exit.

## Verification Record: 2026-10-08

The records in this section were obtained before changing the trigger from OK
to palm. The palm-specific verification is recorded separately below.

- Full Dummy suite: 246 passed, including 22 new PALM regression cases.
- Existing Node suite: 243 passed.
- Existing Python suite: 268 passed and 58 subtests passed; the remaining
  simulation lifecycle case passed separately in a copied, isolated fixture
  project. Running it in the deployed directory conflicts with project-wide
  service state, so no hardware services were stopped to accommodate the test.
- Repository boundary audit passed; model size and SHA-256 matched manifest.
- Shared live-video read-only test: 69 tracking reads over about 12 seconds,
  68 distinct gesture results, inference median 19.1 ms, maximum 58.7 ms,
  no worker error and no remaining Dummy threads after close.
- No face or PALM hand was detected during this sample. Human two-person PALM
  effectiveness and physical following have not been validated by this work.
  No motion adapter was constructed and no real motion/gripper command sent.
- Existing SDK/robot staged changes were preserved. No commit, push, branch
  switch, 3000/SDK restart or deployment service restart was performed.
- Dummy source, tests, documentation and preparation metadata are staged.
  The verified local HaGRID weight remains untracked pending permission to
  append its entry to the shared runtime delivery inventory. Do not stage it
  alone: the boundary audit requires `configs/assets/runtime-assets.json` to
  enumerate each tracked `local/` payload. The dedicated Dummy manifest and
  preparation script already support preparing it on a fresh checkout.

### Owner Association Repair

The existing live test recorded PALM detections but confirmation was frequently
reset by missing face/body associations. Foreground hands overlapped background
people, and some target changes were automatic reacquisition rather than PALM.
The repair adds same-frame pose ownership, bounded recent-face bindings,
separate hand/face confidence thresholds, explicit selection events and honest
LOST age/reasons. Offline regression tests do not prove physical two-person
switching accuracy. The running motion process is not restarted automatically;
activation and any supervised motion verification require separate approval.
Both locally prepared gesture/pose weights remain outside Git staging until
the shared runtime inventory is approved; source manifests/preparation are
included in Dummy. SDK calibration and robot speed/limits are unchanged.

### Repair Verification And Activation Status: 2026-10-08

- Full Dummy suite after ownership/continuity repairs: 273 passed. Regression
  cases cover competing arms, historical face ambiguity, missing current
  bodies during duplicate gesture output, binding priming between results,
  future-face evidence, BODY anchor invalidation, camera-gap recovery, interrupted
  release timing and keyword selection gates.
- Repository boundary audit passed; scoped `git diff --check` passed.
- The Node suite passed 243 tests earlier in this repair session. Root Python
  tests passed 268 tests and 58 subtests; deployed-project simulation lifecycle
  was explicitly excluded this session and is not claimed as freshly retested.
- Model size/hash validation and a blank-image pose inference passed. Replaying
  a previously recorded annotated PALM frame associated the supported foreground
  arm with person 1 instead of the old background choice; annotated replay is
  not a clean live-camera accuracy evaluation.
- The user subsequently deferred physical testing. Dummy remains stopped.
  No motion/gripper commands, SDK reconnection or shared-service restart were
  performed. The small supervised two-person test still needs a separate start
  after the robot has exited teach mode and the user authorizes testing.
- Source/model manifests are available in the primary Ubuntu project, but the
  repaired behavior is not active until Dummy is separately started. No new
  commit or push has been made for these repairs.

### Palm Trigger Change: 2026-10-08

- Only model class `palm` is accepted by both the detector and selector.
  OK and stop classes do not select a person; no model replacement is required.
- Hold/release/cooldown, confidence, same-frame arm ownership, recent-face
  binding and identity-continuity rules were unchanged by the class replacement.
  The later parameter update below only changes confidence and hold duration.
  Robot joint ranges,
  speeds, keyword actions and shutdown behavior are unchanged.
- Tests cover palm-only inference filtering, missing-palm model rejection,
  palm confirmation, OK rejection and the rendered PALM preview labels.
- Full Dummy suite: 278 passed; Node suite: 243 passed; root Python suite:
  268 passed and 58 subtests passed, with the deployed-project simulation
  lifecycle case explicitly excluded to avoid shared-service state conflicts.
  Repository boundary audit and scoped whitespace checks passed. The actual
  checkpoint resolved palm to class 20 and completed blank-image inference.
- No Dummy start, motor/gripper command or SDK/shared-service restart is part
  of this change. Activation requires a separately authorized Dummy start;
  live palm accuracy and physical target switching are not claimed verified.

### Palm Sensitivity Update: 2026-10-08

At this earlier update, the formal YAML profile used confidence >=0.65 and hold >=0.30 s.
At least 3 distinct valid frames are still required: two frames 0.30 s apart
cannot select a person. Below-threshold hands still cannot trigger selection.
Face confidence remains 0.80, pose keypoint confidence 0.35, release 0.30 s,
cooldown 1 s and all owner/continuity checks are unchanged. This changes the
profile loaded by the launcher, not standalone helper fallback defaults.
Activation requires starting/restarting Dummy; this edit does not start it.
Full Dummy offline suite after this parameter update: 281 passed. Regression
cases exercise the actual YAML loader, exact 0.65 acceptance/lower rejection,
the 0.30 s time boundary and the unchanged minimum of 3 distinct frames.

### Rolling Palm Confirmation: 2026-10-08

The current formal YAML uses `confirmation_window_frames: 4`, `confirm_frames: 3`
and `hold_s: 0.10`, retaining confidence 0.65. It tolerates one missing hand result
within the window without treating missing/ambiguous identity as a hand dropout.
Older accepted votes slide out of the window; results from different people are
not combined, and the latest result must contain a valid same-owner palm.
Callers without the optional window key retain the legacy consecutive-result
mode; the formal launcher loads the YAML and therefore uses the rolling mode.
Release (0.30 s), cooldown (1 s), ownership/freshness checks, joint limits and
speed policy are unchanged. No crop detector or display-frame cache was added.

- Full Dummy offline suite: 294 passed. New cases cover 3-of-4 patterns, time
  boundary, negative latest result, owner changes, duplicates, missing historical
  bodies, stale results, long gaps, backwards time and keyword interruption.
- Node suite: 243 passed. Root Python suite: 268 passed and 58 subtests passed;
  deployed-project simulation lifecycle was excluded to avoid live-service
  state conflicts. This is not a fresh lifecycle or physical motion validation.
- No Dummy/SDK restart, motor command, commit or push was performed for this
  update. A running Dummy retains its loaded configuration until separately
  restarted; a config-file edit is not hot activation.
