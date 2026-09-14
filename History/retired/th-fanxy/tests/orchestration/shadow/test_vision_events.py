from copy import deepcopy

import pytest
from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.runtime.models import RobotState
from uiea_thirdhand_vla.orchestration.shadow.vision_events import (
    VisionEvent,
    VisionEventAdapter,
)


def accepted_bottle_payload() -> dict[str, object]:
    return {
        "type": "detection_result",
        "blockers": [],
        "active_view_reports": [],
        "canonical_rgb_source": "lumos_rgb",
        "frame_id": 7,
        "gpu_memory_reserved_gib": 1.5,
        "latency_ms": 82.0,
        "latency_p95_ms": 95.0,
        "metric_depth_source": "d435_depth",
        "model_error": None,
        "model_ready": True,
        "monotonic_ns": 700,
        "robot_execution_enabled": False,
        "source_sequence": 7,
        "targets": [
            {
                "actionable": True,
                "detection_id": 11,
                "identity_id": 2,
                "identity_status": "confirmed",
                "identity_memory": {
                    "hits": 4,
                    "work_prototype_count": 2,
                    "stable_prototype_count": 2,
                    "appearance_similarity": 0.94,
                    "association_cost": 0.08,
                    "association_reason": "matched",
                },
                "label": "bottle",
                "grasp_preview": None,
                "pose": {
                    "calibration_id": "calibration-accepted-1",
                    "covariance_m2": [
                        [0.000001, 0.0, 0.0],
                        [0.0, 0.000004, 0.0],
                        [0.0, 0.0, 0.000009],
                    ],
                    "frame": "robot_base",
                    "monotonic_ns": 700,
                    "xyz_m": [0.42, -0.06, 0.11],
                },
                "reasons": [],
                "registered_depth_points": 142,
                "score": 0.86,
            }
        ],
        "task_checkpoint_validated": True,
        "ts": 1_786_000_000_000,
    }


def fact_value(observation, name: str):
    return next(item.value for item in observation.facts if item.name == name)


def test_checked_event_becomes_actionable_runtime_object():
    event = VisionEvent.model_validate(accepted_bottle_payload())

    observation = VisionEventAdapter("episode-vision-1").to_observation(event)

    assert observation.episode_id == "episode-vision-1"
    assert observation.sequence == 7
    assert observation.source == "thirdhand.vision.detection_result"
    target = observation.objects[0]
    assert target.identity_id == 2
    assert target.label == "bottle"
    assert target.visible is True
    assert target.ambiguous is False
    assert target.actionable is True
    assert target.depth_valid is True
    assert target.position_std_m == pytest.approx(0.003)
    assert fact_value(observation, "vision_model_ready") is True
    assert fact_value(observation, "task_checkpoint_validated") is True
    assert observation.evidence[0].evidence_id.startswith("sha256:")


def test_unvalidated_checkpoint_cannot_produce_actionable_object():
    payload = accepted_bottle_payload()
    payload["task_checkpoint_validated"] = False

    observation = VisionEventAdapter("episode-vision-1").to_observation(
        VisionEvent.model_validate(payload)
    )

    assert observation.objects[0].actionable is False
    assert fact_value(observation, "task_checkpoint_validated") is False


def test_ambiguous_identity_is_visible_but_not_actionable():
    payload = accepted_bottle_payload()
    target = payload["targets"][0]
    target["identity_status"] = "ambiguous"
    target["reasons"] = ["appearance_candidates_within_margin"]

    observation = VisionEventAdapter("episode-vision-1").to_observation(
        VisionEvent.model_validate(payload)
    )

    assert observation.objects[0].visible is True
    assert observation.objects[0].ambiguous is True
    assert observation.objects[0].actionable is False


def test_missing_identity_is_preserved_as_blocker_not_invented_object():
    payload = accepted_bottle_payload()
    payload["targets"][0]["identity_id"] = None
    payload["targets"][0]["identity_status"] = "tentative"

    observation = VisionEventAdapter("episode-vision-1").to_observation(
        VisionEvent.model_validate(payload)
    )

    assert observation.objects == ()
    assert fact_value(observation, "unbound_target_count") == 1


def test_explicit_robot_state_is_preserved_without_mutation():
    robot = RobotState(holding_known=True, held_object_id=2, evidence_ids=())

    observation = VisionEventAdapter("episode-vision-1").to_observation(
        VisionEvent.model_validate(accepted_bottle_payload()),
        robot,
    )

    assert observation.robot is robot


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload.update(robot_execution_enabled=True), "False"),
        (lambda payload: payload.update(unexpected=True), "Extra inputs"),
        (lambda payload: payload.update(latency_ms=float("nan")), "finite"),
        (
            lambda payload: payload["targets"][0]["pose"].update(
                covariance_m2=[[1.0, 0.0], [0.0, 1.0]]
            ),
            "3x3",
        ),
    ],
)
def test_unsafe_or_malformed_event_is_rejected(mutation, match: str):
    payload = deepcopy(accepted_bottle_payload())
    mutation(payload)

    with pytest.raises(ValidationError, match=match):
        VisionEvent.model_validate(payload)
