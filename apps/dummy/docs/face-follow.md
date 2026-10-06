# Face Detection and Face-Only Mode

The current configuration also enables bound person tracking. See
[Face-first person tracking](face-person-follow.md) for FACE/BODY/LOST behavior,
activation and test results. The face-only behavior below applies when
`person_tracking.enabled` is false and remains available as a fallback mode.

## Model and Scope

Dummy configuration sets `vision_service.follow_target: face`.
OpenCV YuNet is the default face-box detector (`face_detector: yunet`). It does
not recognize names or biometric identities. The previous short-range BlazeFace
backend remains selectable explicitly. No HaGRID or OK gesture recognition has
been installed in this stage.

Dummy reads the existing shared XVisio raw stream. The detector returns all faces;
`FaceLockTracker` selects one face and only its filtered center reaches the
existing J1/J4 continuous-follow controller. YOLO body inference, Haar/body/motion
fallbacks, wave-region selection, health target fallback and RGB-D target
replacement are not used in this mode. The Robot Service, SDK and CAN owner are
unchanged. Keywords still use their separate all-joint gesture scheduler.

## Selection and Loss

- Startup automatically selects a high-confidence, near-center face after two
  fresh observations. No face means no follow command.
- Continuation uses proximity to the last raw face box and compatible box area,
  rather than choosing the biggest/highest-confidence face again each frame.
- Missing or ambiguous face observations immediately pause follow. A matching
  face may resume within the one-second loss-confirmation window.
- After more than one second without a matched face, `auto_reacquire: true`
  discards the old selection and automatically confirms a new visible face over
  two fresh frames. This may be the returning person or a different person.
  A stream outage also counts as a loss when frames resume.
- No permanent OK-wait latch is used by default. Explicit
  `auto_reacquire: false` retains that alternative behavior; OK switching itself
  is not connected yet. Stable visible targets are still not ranked/replaced
  every frame. Page refresh does not reset the server-owned Dummy process.

This initial tracker provides spatial continuity, not proven person identity.
It pauses for close competing detections but cannot guarantee identification
when a different face replaces another at the same image location. Multi-person
tracking and hand-to-person association remain the next stage before OK switching.

## Configuration

`face_lock` contains `auto_reacquire: true`, `confirm_frames: 2`, `loss_timeout_s: 1.0`,
`max_distance_px: 120.0`, `ambiguity_margin_px: 30.0` and OneEuro filter settings.
The matching radius scales with the last face-box size, with a 60-pixel floor
for motion between low-rate source frames. YuNet's detection threshold is 0.80
(`yunet_face_min_score`). It is not an identity guarantee or an OK threshold.
BlazeFace's old 0.20 threshold applies only when that backend is selected.

Telemetry reports `follow_target`, `lock_state`, `face_count` and
`face_boxes_xywh`, face scores, backend and selection generation, using the exact
observations sent to the controller. Gray
boxes are all face candidates, the green box is the selected fresh face, and the
yellow circle is its filtered command point. A gray point represents a held
observation. `face_reacquiring_face`/`face_confirming_face` pause commands while a
new selection is being confirmed. The permanent wait only applies if explicitly
configured with automatic reacquisition disabled.

## Model Preparation

Run `apps/prepare_face_model.py` with the prepared vision Python. It explicitly
downloads the official 229,738-byte YuNet model at the pinned revision recorded
in `configs/face-model.json`, checks its SHA256, and retains the MIT license next
to the model in the ignored `local/models/vision` directory. Model loading never
downloads implicitly. This variant uses dynamic dimensions for OpenCV 5.x,
matching the current prepared Ubuntu runtime. OS version alone does not determine
OpenCV compatibility. `DUMMY_YUNET_MODEL` can override the local model path.

Reference: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet

Same-frame read-only comparison: `apps/compare_face_detectors_readonly.py --frames 20`.
In the observed lab scene, old BlazeFace produced low-score oversized boxes;
YuNet produced consistent small face boxes. This is a scene-specific comparison,
not a general accuracy benchmark or proof of identity tracking.

## Manual Acceptance

The finite `apps/test_face_follow_readonly.py --frames 40` check reads the real
camera and prints model availability, face count, lock state and detection time.
It never creates a robot adapter or SDK. Run it with the prepared vision Python
and prepared local YuNet weights (or `DUMMY_YUNET_MODEL` override).
Exit this check before starting physical follow.

1. With Dummy stopped, reload the fork web page and expand its Dummy panel.
2. Clear the motion workspace, keep on-site supervision and the independent
   hardware emergency stop available. Initially disable keyword subscription.
3. Start Dummy through the existing motion confirmation, then enable its preview.
   The selected green box must surround a face, not the torso; the yellow point
   must follow the face center. Check telemetry `target.kind: face_lock`.
4. Make small head movements and observe actual J1/J4 feedback. The existing
   50 degrees/s caps, geometry checks and other-joint holds remain unchanged.
5. Add a second person away from the selected face. Their larger/higher-score
   box must not replace the selected target. Close/ambiguous faces should pause.
6. Cover or leave the selected face. Verify missing/ambiguous frames pause
   commands, then another/returning face is automatically selected after the
   one-second loss timeout plus two fresh confirmations. With no face visible,
   no target commands or automatic search motion may be issued.
7. Stop Dummy and verify Robot Service stays connected and ordinary web controls
   still work. Software stop is not a hardware emergency stop.
