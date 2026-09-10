# Closed-loop numbered bottle pick

The voice/UI integration sends only the overlay number:

```http
POST /api/vision/pick
Content-Type: application/json

{"target_index": 2}
```

Equivalent WebSocket command:

```json
{"cmd":"closed_loop_pick","target_index":2}
```

Cancel with `POST /api/vision/pick/cancel` or
`{"cmd":"cancel_closed_loop_pick"}`.

The controller locks the selected bottle in `robot_base`, requires five fresh
stable depth previews, moves to a clearance pose, reacquires after every move,
uses at most 5 mm refinement steps, and hands the final frozen preview to the
existing side-grasp controller.  The final insertion remains linear along base
`+X`; close, contact check, vertical lift and Home-area placement remain in the
existing grasp controller.

Current calibrated correction is supplied by the service environment:
`VISION_GRASP_OFFSET_X_M=0.0475`, `VISION_GRASP_OFFSET_Y_M=0.010`,
`VISION_GRASP_OFFSET_Z_M=0`.  Do not add it again in a caller.

Physical execution is fail-closed.  It requires both the existing grasp switch
and `VISION_CLOSED_LOOP_EXECUTION_ENABLED=1`.  Keep both off for visualization
or unattended operation.
