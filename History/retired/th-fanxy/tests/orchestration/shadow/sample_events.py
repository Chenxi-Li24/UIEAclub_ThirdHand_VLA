"""Hand-checked event literals shared by shadow integration tests."""

from __future__ import annotations


def bottle_event_payload(sequence: int = 1) -> dict[str, object]:
    monotonic_ns = sequence * 100
    return {
        "type": "detection_result",
        "blockers": [],
        "active_view_reports": [],
        "canonical_rgb_source": "lumos_rgb",
        "frame_id": sequence,
        "gpu_memory_reserved_gib": 1.5,
        "latency_ms": 80.0,
        "latency_p95_ms": 90.0,
        "metric_depth_source": "d435_depth",
        "model_error": None,
        "model_ready": True,
        "monotonic_ns": monotonic_ns,
        "robot_execution_enabled": False,
        "source_sequence": sequence,
        "targets": [
            {
                "actionable": True,
                "detection_id": sequence,
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
                    "monotonic_ns": monotonic_ns,
                    "xyz_m": [0.42, -0.06, 0.11],
                },
                "reasons": [],
                "registered_depth_points": 142,
                "score": 0.86,
            }
        ],
        "task_checkpoint_validated": True,
        "ts": 1_786_000_000_000 + sequence,
    }
