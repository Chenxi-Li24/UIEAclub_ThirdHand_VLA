import pytest

from thirdhand_va.vision.evaluation import EvaluationError, aggregate_metrics


def samples() -> list[dict]:
    return [
        {
            "truth": "positive",
            "authorized": True,
            "depth_valid_ratio": 0.80,
            "pose_point_m": [0.080, 0.000, 0.450],
            "latency_ms": 80.0,
            "blockers": [],
        },
        {
            "truth": "positive",
            "authorized": True,
            "depth_valid_ratio": 0.78,
            "pose_point_m": [0.082, 0.001, 0.451],
            "latency_ms": 90.0,
            "blockers": [],
        },
        {
            "truth": "negative",
            "authorized": False,
            "depth_valid_ratio": 0.75,
            "pose_point_m": None,
            "latency_ms": 70.0,
            "blockers": ["fixed_reference_mismatch"],
        },
        {
            "truth": "negative",
            "authorized": False,
            "depth_valid_ratio": 0.72,
            "pose_point_m": None,
            "latency_ms": 100.0,
            "blockers": ["container_type_not_bottle"],
        },
    ]


def test_aggregate_metrics_covers_identity_depth_pose_and_latency() -> None:
    report = aggregate_metrics(samples())

    assert report["positive_recall"] == 1.0
    assert report["false_authorization_count"] == 0
    assert report["mean_depth_valid_ratio"] == pytest.approx(0.7625)
    assert report["pose_repeatability_max_m"] < 0.005
    assert report["latency_ms"]["p95"] == pytest.approx(98.5)
    assert report["blocker_counts"]["fixed_reference_mismatch"] == 1
    assert report["passed"] is True


@pytest.mark.parametrize("truth", ["positive", "negative"])
def test_report_refuses_missing_positive_or_negative_class(truth: str) -> None:
    only_one_class = [item for item in samples() if item["truth"] == truth]

    with pytest.raises(EvaluationError, match="positive and negative"):
        aggregate_metrics(only_one_class)


def test_false_authorization_fails_report() -> None:
    fixture = samples()
    fixture[2]["authorized"] = True

    report = aggregate_metrics(fixture)

    assert report["false_authorization_count"] == 1
    assert report["passed"] is False
