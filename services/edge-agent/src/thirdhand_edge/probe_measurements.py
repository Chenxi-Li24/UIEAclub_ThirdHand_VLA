"""Bounded monotonic ping/pong measurements; never a hardware timing profile."""
from collections import deque
import math


class ProbeMeasurements:
    def __init__(self):
        self._rtts = deque(maxlen=36000)
        self._count = 0
        self._last_ns = None
        self._max_gap_ms = 0.0

    def add(self, rtt_ms, received_ns):
        if not math.isfinite(rtt_ms) or rtt_ms < 0:
            raise ValueError("Invalid ping measurement")
        self._rtts.append(rtt_ms)
        self._count += 1
        if self._last_ns is not None:
            self._max_gap_ms = max(self._max_gap_ms, (received_ns - self._last_ns) / 1_000_000)
        self._last_ns = received_ns

    def report(self):
        values = sorted(self._rtts)
        def percentile(q):
            return round(values[max(0, math.ceil(q * len(values)) - 1)], 3)
        return {"samples": self._count, "retainedSamples": len(values),
                "rttMs": {"min": round(values[0], 3), "p50": percentile(.5),
                          "p95": percentile(.95), "p99": percentile(.99),
                          "max": round(values[-1], 3)} if values else None,
                "maxHeartbeatGapMs": round(self._max_gap_ms, 3) if self._count > 1 else None}
