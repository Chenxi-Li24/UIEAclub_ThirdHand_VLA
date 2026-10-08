from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .filters import clamp, ease_in_out, ease_out_back


@dataclass
class Keyframe:
    t: float
    offsets: list[float]
    gripper: float | None = None
    ease: str = "ease_in_out"


def ease_value(name, t):
    return ease_out_back(t) if name == "ease_out_back" else ease_in_out(t)


class MotionPlayer:
    def __init__(self, adapter, config):
        self.adapter = adapter
        self.config = config
        self.hz = float(config.get("motion", {}).get("hz", 10))
        self._token = 0

    def interrupt(self):
        self._token += 1

    async def play(self, name, gesture, *, priority=50):
        self.interrupt()
        token = self._token
        state = await self.adapter.get_state()
        base = list(state.joints_deg)
        if len(base) != 6:
            raise RuntimeError("robot state lacks six joints")
        frames = [
            Keyframe(
                float(k.get("t", 0)),
                [float(x) for x in k.get("offset_deg", [0, 0, 0, 0, 0, 0])],
                k.get("gripper"),
                k.get("ease", "ease_in_out"),
            )
            for k in gesture.get("keyframes", [])
        ]
        if not frames:
            return
        frames = sorted(frames, key=lambda k: k.t)
        final_gripper = next((frame.gripper for frame in reversed(frames) if frame.gripper is not None), None)
        if frames[0].t > 0:
            frames.insert(0, Keyframe(0, [0, 0, 0, 0, 0, 0]))
        start = time.time()
        end = frames[-1].t
        idx = 0
        while True:
            if token != self._token:
                return
            now = time.time() - start
            if now >= end:
                break
            while idx + 1 < len(frames) and now > frames[idx + 1].t:
                idx += 1
            a = frames[idx]
            b = frames[min(idx + 1, len(frames) - 1)]
            span = max(1e-6, b.t - a.t)
            p = clamp((now - a.t) / span, 0, 1)
            e = ease_value(b.ease, p)
            off = [oa + (ob - oa) * e for oa, ob in zip(a.offsets, b.offsets)]
            await self.adapter.send_joint_target([x + y for x, y in zip(base, off)])
            await asyncio.sleep(1.0 / self.hz)
        final = frames[-1]
        await self.adapter.send_joint_target([x + y for x, y in zip(base, final.offsets)])
        if final_gripper is not None:
            await self.adapter.wait_idle()
            await self.adapter.set_gripper(float(final_gripper))
