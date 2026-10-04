from __future__ import annotations

from .contracts import DumeFollowCommand
from .depth_estimator import DepthEstimator
from .distance_policy import DistanceAwarePosturePolicy
from .handeye_projector import FollowHandEyeProjector
from .mink_backend import MinkLookAtController
from .target_projector import Virtual3DTargetProjector
from ..visual_servo_gaze import VirtualGimbalCommand


class DumeTouchR1FollowController:
    """Composable real/virtual 3D person-follow controller."""

    def __init__(
        self,
        config,
        *,
        distance_policy=None,
        depth_estimator=None,
        target_projector=None,
        handeye_projector=None,
        ik_backend=None,
        mink_controller=None,
    ):
        self.distance_policy = distance_policy if distance_policy is not None else DistanceAwarePosturePolicy(config)
        self.depth_estimator = depth_estimator if depth_estimator is not None else DepthEstimator(config)
        self.target_projector = target_projector if target_projector is not None else Virtual3DTargetProjector(config)
        self.handeye_projector = handeye_projector if handeye_projector is not None else FollowHandEyeProjector(config)
        self.ik_backend = ik_backend if ik_backend is not None else (
            mink_controller if mink_controller is not None else MinkLookAtController(config)
        )

    def reset(self, joints):
        self.distance_policy.reset()
        if hasattr(self.depth_estimator, "reset"):
            self.depth_estimator.reset()
        if hasattr(self.target_projector, "reset"):
            self.target_projector.reset()
        if hasattr(self.handeye_projector, "reset"):
            self.handeye_projector.reset()
        if hasattr(self.ik_backend, "reset"):
            self.ik_backend.reset(joints)

    def target_for(self, joints, target, debug=None):
        debug = debug or {}
        image_error_px = _image_error(target)
        estimated_depth = self.depth_estimator.estimate(target, debug)
        distance = self.distance_policy.update(joints, target, estimated_depth)
        virtualized = self._prepare_target(target, distance, estimated_depth)
        handeye = self._project_to_base(joints, target)
        if getattr(target, "found", False) and getattr(target, "xyz_m", None) is not None:
            result = self.ik_backend.target_for(joints, target)
            if result.ok:
                mode = "virtual3d" if virtualized else "depth3d"
                frame = "base" if handeye.ok else "camera"
                source = f"mink/{frame}/{mode}/{distance.state}"
                return DumeFollowCommand(
                    True,
                    result.joints_deg,
                    VirtualGimbalCommand(True),
                    source,
                    self._debug(source, distance, target, virtualized, image_error_px, estimated_depth, handeye),
                )
            source = f"mink_failed/{result.reason}"
            return DumeFollowCommand(
                False,
                list(joints),
                VirtualGimbalCommand(False),
                source,
                self._debug(source, distance, target, virtualized, image_error_px, estimated_depth, handeye),
            )
        return DumeFollowCommand(
            False,
            list(joints),
            VirtualGimbalCommand(False),
            "target_missing",
            self._debug("target_missing", distance, target, virtualized, image_error_px, estimated_depth, handeye),
        )

    def _prepare_target(self, target, distance, estimated_depth):
        if not getattr(target, "found", False):
            return False
        try:
            setattr(target, "posture_joints_deg", list(distance.posture_joints_deg))
            setattr(target, "distance_state", distance.state)
        except Exception:
            pass
        return self.target_projector.ensure_xyz(target, depth_hint_m=estimated_depth.depth_m)

    def _project_to_base(self, joints, target):
        before = None if getattr(target, "xyz_m", None) is None else list(getattr(target, "xyz_m"))
        result = self.handeye_projector.project(joints, target)
        if result.ok and result.xyz_m is not None:
            try:
                setattr(target, "camera_xyz_m", before)
                setattr(target, "xyz_m", list(result.xyz_m))
            except Exception:
                pass
        return result

    def _debug(self, source, distance, target, virtualized, image_error_px, estimated_depth, handeye):
        return {
            "control_source": source,
            "control_backend": "mink",
            "target_3d_mode": "virtual3d" if virtualized else ("depth3d" if getattr(target, "xyz_m", None) is not None else "none"),
            "distance_state": distance.state,
            "distance_depth_m": distance.depth_m,
            "distance_depth_valid": distance.depth_valid,
            "distance_depth_source": distance.depth_source,
            "distance_depth_confidence": distance.depth_confidence,
            "estimated_depth_m": estimated_depth.depth_m,
            "estimated_depth_source": estimated_depth.source,
            "estimated_depth_confidence": estimated_depth.confidence,
            "estimated_depth_metric": estimated_depth.metric,
            "estimated_depth_reason": estimated_depth.reason,
            "target_xyz_m": getattr(target, "xyz_m", None),
            "target_camera_xyz_m": getattr(target, "camera_xyz_m", None),
            "handeye_ok": handeye.ok,
            "handeye_source": handeye.source,
            "handeye_reason": handeye.reason,
            "handeye_calibration_id": handeye.calibration_id,
            "image_error_px": image_error_px,
            "posture_joints_deg": list(distance.posture_joints_deg),
        }


def _image_error(target):
    if not getattr(target, "found", False):
        return None
    try:
        return [
            float(getattr(target, "u")) - float(getattr(target, "w")) / 2.0,
            float(getattr(target, "v")) - float(getattr(target, "h")) / 2.0,
        ]
    except (TypeError, ValueError):
        return None
