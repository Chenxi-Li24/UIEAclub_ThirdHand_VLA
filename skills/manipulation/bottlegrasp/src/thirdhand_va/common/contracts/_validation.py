"""Private validation helpers shared by immutable data contracts."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def readonly_array(
    value: object, *, dtype: np.dtype | type | None = None
) -> NDArray:
    array = np.array(value, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


def finite_triplet(value: object, name: str) -> tuple[float, float, float]:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (3,) or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain three finite values")
    return tuple(float(item) for item in array)
