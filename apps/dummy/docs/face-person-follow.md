# Face-first person tracking

## Scope and deployment

YuNet locates faces. YOLOv8n + BoT-SORT tracks person boxes on the exact same
latest XVisio frame. This is temporal tracking, not biometric identification.
The shared Vision Service remains the only camera owner. Dummy reads its raw
stream; this adds no second camera connection or outgoing video stream.

`person_tracking.enabled` is true after read-only validation and explicit approval
for supervised activation. The finite read-only test enables the feature in memory.
Changing that flag alone does not change a running Dummy; a supervised Dummy-only
restart is needed after visual association validation.
Do not restart Robot Service, its SDK or CAN to apply this feature.

## Selection and control points

1. Initially confirm a face using the existing FaceLockTracker. Person boxes
   alone never choose the first target.
2. Bind its center to one unambiguous person box's upper half and store that
   person's `track_id`. Remember the face center's normalized `(x, y)` within
   the person box. This is the head anchor, not the torso center.
3. FACE: use a fresh face belonging to that selected person.
4. BODY: when the face is unavailable but that person is freshly observed,
   transform the calibrated anchor using the current person's box dimensions.
   Continue following this ID even after more than one second without a face.
5. Blend FACE/BODY transitions for 0.30 seconds through one shared OneEuro filter.
6. LOST: no observed target, ambiguous overlap, association conflict or sudden
   track discontinuity returns `found=false`. Existing runtime pauses continuous
   follow. Cached/predicted lost boxes never drive motion. Frames older than
   0.5 seconds and duplicates are rejected before inference.
7. After one second without a usable face or body, confirm a new face and allow
   automatic reselection, as requested. A visible, nearby face may temporarily
   continue alone if the body detector misses, but cannot bind to another ID.

Only J1/J4 follow. Existing Robot Service velocity, acceleration, jerk, joint
limits, workspace guards and keyword action behavior are unchanged. No depth
or bottle-grasp path is enabled. Idle breathing remains disabled.

## Read-only test

Use the prepared vision Python environment and explicit local model paths:

```bash
python -m pip install -r apps/dummy/configs/requirements-person-tracking.txt
python apps/dummy/apps/test_face_person_readonly.py --seconds 60 --port 31025
```

Set `DUMMY_YOLO_MODEL` / `DUMMY_YUNET_MODEL` if the models are elsewhere in the
local project resources. The default paths are project-relative. Missing weights
or lap fail closed; the tracking startup does not download a model or dependency.
This script never creates a Robot adapter, never connects to port 3000 and never
executes keyword actions. It closes its stream reader and preview server on exit.

The preview API binds loopback on a different port from live Dummy:

- `http://127.0.0.1:31025/api/status`: FACE/BODY/LOST, selected ID, head anchor,
  source receive age (not full camera latency), total/person inference times.
- `http://127.0.0.1:31025/api/frame`: the same observation plus annotated JPEG.

Selected person box is cyan, other boxes gray; selected face green, control point
yellow and frame center white. The image label includes source and selected ID.
The regular web Dummy preview gets the same additional metadata after restart.

For an Ubuntu desktop view during the read-only test, use the existing viewer:

```bash
python apps/dummy/apps/visualize_person_follow_window.py --observation http://127.0.0.1:31025/api/frame
```

This viewer does not run another detector. It reads this test's annotated frame
and closes after the test server goes offline. The existing live Dummy's viewer
continues to use port 31024; the two observation sources must not be confused.

Check frontal face -> turn away -> face return without an ID change. Move farther
away, cross paths with another person, briefly occlude, then leave the frame.
Confirm BODY tracks the head location, overlap pauses and LOST never keeps a
stale control point active. Check detection time and receive age under load.

## Limitations and next phase

BoT-SORT explicitly uses sparse optical flow camera-motion compensation and no
ReID model. Detection NMS IoU is explicitly 0.45 to reduce duplicate person boxes
before association; the separate 0.35 overlap pause rule is not disabled.
Its IDs can switch during heavy occlusion; pause rules reduce but do
not eliminate that risk. A person detector must still detect a visible body.
Far-away faces initially undetected cannot be selected solely from a body box.
Torso occlusion/box clipping can reduce anchor accuracy. No long occlusion
prediction is used for robot motion.

OK gesture recognition and hand-to-person association are not implemented here.
The selected person ID is the integration point for that later feature. Selected
head-ROI YuNet upscaling or ReID can be evaluated later if needed; neither is
silently enabled in this phase.

## Validation record (2026-10-06)

Ubuntu fork read-only real-camera run: 60 seconds, 365 observations. FACE 236,
BODY 122, LOST 7. All 358 usable FACE/BODY observations retained person ID 1;
FACE -> BODY -> FACE was observed with the operator turning away and returning.
One LOST frame was initial confirmation; the final six were overlap ambiguity
or selected-person loss. Every sample had `motion_enabled=false`.

Excluding the initial model warm-up (about 1.06 seconds), total inference averaged
30.47 ms (15.42..45.08 ms). Receive age averaged 80.51 ms (20.59..139.35 ms);
this is NOT camera-to-motor end-to-end latency. The shared SDK PID 543817 was
unchanged. This test did not establish physical body-follow tracking quality,
long-occlusion identity guarantees or OK gesture operation.

Final focused regression suite: 94 tests passed, including FACE/BODY continuity,
ID binding, loss/reselection, stale telemetry, explicit BoT-SORT configuration,
J1/J4 runtime and legacy face mode. A supervised Dummy-only restart was approved.
Live BODY control returned `accepted=true` from Robot Service, with measured
J1/J4 feedback changing. The NMS fix retained true overlap-pausing rather than
bypassing ambiguity checks. Live FACE control was also observed after restart.
No automatic Zero/Home, SDK restart or keyword action was issued in this phase.
These observations establish the basic execution connection, not a complete
tracking-quality, crowded-scene or long-distance acceptance test.

Sources: [Ultralytics tracking API](https://docs.ultralytics.com/modes/track/),
plus the actual installed Ultralytics 8.4.160 tracker implementation inspected
on Ubuntu. `lap==0.5.12` was explicitly installed in the prepared vision runtime;
YOLOv8n was copied from the existing local file into the fork's
`local/models/vision/yolov8n.pt`, preserving the original file.

The face implementation was separately pushed as commit `7307574`. This new
person-tracking phase remains staged pending a separate commit approval.
