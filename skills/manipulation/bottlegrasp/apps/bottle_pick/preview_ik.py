"""Offline URDF IK for browser-only bottle grasp animation; never talks to CAN."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np
from ikpy.chain import Chain
from scipy.spatial.transform import Rotation


def interpolate(start, end, max_step_m=0.015):
    count = max(1, int(math.ceil(float(np.linalg.norm(end - start)) / max_step_m)))
    for index in range(1, count + 1):
        yield start + (end - start) * index / count


def solve(payload):
    urdf = Path(payload["urdf"])
    parsed = Chain.from_urdf_file(str(urdf), base_elements=["base_link"],
                                  active_links_mask=[False] + [True] * 6 + [False])
    chain = Chain(parsed.links[:7], active_links_mask=[False] + [True] * 6)
    q = np.asarray([0.0, *np.deg2rad(payload["startJointsDeg"])], dtype=float)
    if q.shape != (7,) or not np.isfinite(q).all():
        raise ValueError("initial_joints_invalid")
    start_fk = chain.forward_kinematics(q)
    flange = np.asarray(payload["startFlangeM"], dtype=float)
    if flange.shape != (3,) or np.linalg.norm(start_fk[:3, 3] - flange) > 0.010:
        raise ValueError("robot_urdf_fk_mismatch")
    frames = [{"stage": "current", "jointsDeg": np.rad2deg(q[1:]).tolist(),
               "gripperPosition": 1}]
    current = start_fk[:3, 3]
    for stage in payload["stages"]:
        destination = np.asarray(stage["positionM"], dtype=float)
        euler = np.asarray(stage["eulerRad"], dtype=float)
        if destination.shape != (3,) or euler.shape != (3,) or not np.isfinite(destination).all():
            raise ValueError("waypoint_invalid")
        target = np.eye(4)
        target[:3, :3] = Rotation.from_euler("xyz", euler).as_matrix()
        for position in interpolate(current, destination):
            target[:3, 3] = position
            solved = chain.inverse_kinematics_frame(target, initial_position=q)
            fk = chain.forward_kinematics(solved)
            rotation_error = Rotation.from_matrix(target[:3, :3].T @ fk[:3, :3]).magnitude()
            if (not np.isfinite(solved).all()
                    or np.linalg.norm(fk[:3, 3] - position) > 0.010
                    or rotation_error > 0.12
                    or np.max(np.abs(np.rad2deg(solved[1:] - q[1:]))) > 25):
                raise ValueError(f"ik_unreachable:{stage['stage']}")
            q = solved
            frames.append({"stage": stage["stage"],
                           "jointsDeg": np.rad2deg(q[1:]).tolist(),
                           "gripperPosition": stage["gripperPosition"]})
        current = destination
    zero = np.zeros(7)
    steps = max(1, int(np.ceil(np.max(np.abs(np.rad2deg(q[1:]))) / 5)))
    for index in range(1, steps + 1):
        joints = q + (zero - q) * index / steps
        frames.append({"stage": "return_zero", "jointsDeg": np.rad2deg(joints[1:]).tolist(),
                       "gripperPosition": 1})
    return {"schema": "thirdhand-kinematic-preview-v1", "complete": True,
            "collisionValidated": False, "robotCommandsSent": False, "frames": frames}


if __name__ == "__main__":
    try:
        print(json.dumps(solve(json.loads(sys.argv[1]))))
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({"schema": "thirdhand-kinematic-preview-v1", "complete": False,
                          "reason": str(error), "frames": [], "robotCommandsSent": False}))
