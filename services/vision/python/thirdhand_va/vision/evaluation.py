"""Deterministic fixed-bottle acceptance metrics."""
from collections import Counter
from typing import Any, Sequence
import numpy as np

class EvaluationError(RuntimeError):
    pass

def aggregate_metrics(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positives = [x for x in samples if x.get("truth") == "positive"]
    negatives = [x for x in samples if x.get("truth") == "negative"]
    if not positives or not negatives:
        raise EvaluationError("evaluation requires both positive and negative samples")
    recall = sum(x.get("authorized") is True for x in positives) / len(positives)
    false_auth = sum(x.get("authorized") is True for x in negatives)
    depth = np.asarray([float(x["depth_valid_ratio"]) for x in samples])
    latency = np.asarray([float(x["latency_ms"]) for x in samples])
    if not np.isfinite(depth).all() or not np.isfinite(latency).all():
        raise EvaluationError("metrics must be finite")
    poses = np.asarray([x["pose_point_m"] for x in positives if x.get("authorized") is True and x.get("pose_point_m") is not None])
    repeatability = float("inf")
    if poses.ndim == 2 and poses.shape[1] == 3 and len(poses):
        repeatability = float(np.linalg.norm(poses - np.median(poses, axis=0), axis=1).max())
    blockers = Counter(str(r) for x in samples for r in x.get("blockers", ()))
    passed = recall >= 0.95 and false_auth == 0 and repeatability <= 0.005
    return {
        "schema": "thirdhand-va-fixed-bottle-evaluation-v1",
        "positive_count": len(positives), "negative_count": len(negatives),
        "positive_recall": recall, "false_authorization_count": false_auth,
        "mean_depth_valid_ratio": float(depth.mean()),
        "depth_valid_ratio_p05": float(np.percentile(depth, 5)),
        "pose_repeatability_max_m": repeatability,
        "latency_ms": {"p50": float(np.percentile(latency, 50)), "p95": float(np.percentile(latency, 95))},
        "blocker_counts": dict(sorted(blockers.items())),
        "gates": {"positive_recall_min": 0.95, "false_authorization_max": 0, "pose_repeatability_max_m": 0.005},
        "passed": bool(passed),
    }
