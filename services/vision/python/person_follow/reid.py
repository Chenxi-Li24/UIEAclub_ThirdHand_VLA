from __future__ import annotations

import numpy as np


def cosine_similarity(left, right):
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    denom = np.linalg.norm(left) * np.linalg.norm(right)
    return float(left @ right / denom) if denom else 0.0


class ReIdAdapter:
    def __init__(self, backend=None, model_id="osnet"):
        self.backend = backend
        self.model_id = model_id

    def embed(self, frame, tracks):
        if self.backend is None:
            raise RuntimeError("MODEL_UNAVAILABLE")
        return self.backend(frame, tracks)
