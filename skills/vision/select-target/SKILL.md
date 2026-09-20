# Select Vision Target Skill

Read-only/state skill for selecting or releasing a stable bottle target in the Vision Service. Selection only updates perception state and target references. It must not move the robot, close the gripper, open CAN, or approve a manipulation plan.

Use this skill after `vision.detect-bottles` when the user or orchestrator has chosen a stable ID from the current Vision Service state. Reject stale, out-of-range, or missing targets fail-closed.
