# Gripper Control Skill

`manipulation.gripper-control` converts only `gripper.open` and `gripper.close` candidates into one immutable `gripper.set` step. It never creates an arm-joint target and never accesses Startouch SDK or `can0` directly.

Execution requires a current Robot readiness snapshot and an exact, unexpired, one-use `thirdhand.task-authorization.v2`. Success requires fresh gripper feedback within tolerance and proof that all six arm joints remained stationary.

This Skill must remain unavailable until `src/worker.js` is present. Software stop and independent hardware emergency stop remain separate safety mechanisms.
