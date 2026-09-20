# Detect Bottles Skill

Read-only skill for querying the Vision Service for currently visible, grasp-relevant bottle targets from the XVisio RGB-D camera. It may return stable IDs, labels, confidence, frame references, pose summaries, and rejection reasons. It must not command the robot, gripper, CAN bus, active viewpoint motion, or Startouch SDK.

Use this skill when the caller needs to know which bottles are visible or selectable. If the Vision Service, XVisio camera, or pinned vision models are unavailable, return `skill_unavailable` or `target_lost` instead of inventing targets.
