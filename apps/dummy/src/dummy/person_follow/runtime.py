from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import math
import threading
import time

from ..follow_loop_state import clamp_to_workspace_guard
from ..image_jacobian_servo import ImageJacobianServo
from ..tracker import Target


@dataclass(frozen=True)
class Observation:
    sequence: int
    target: Target
    detection_ms: float = 0.0


class TrackerWorker:
    """Own blocking detection without queuing old frames on the asyncio loop."""

    def __init__(self, tracker, publish, period_s):
        self.tracker = tracker
        self.publish = publish
        self.period_s = period_s
        self.stop = threading.Event()
        self.thread = None
        self.error = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="dummy-detection", daemon=False)
        self.thread.start()

    def _run(self):
        try:
            self.tracker.open()
            while not self.stop.is_set():
                started = time.monotonic()
                if hasattr(self.tracker, "reader"):
                    target, _frame, _error = self.tracker.read_frame()
                else:
                    target = self.tracker.read()
                self.publish(target, detection_ms=(time.monotonic() - started) * 1000)
                self.stop.wait(max(0, self.period_s - (time.monotonic() - started)))
        except Exception as exc:
            self.error = exc
            self.publish(Target(False, kind="detection_failed", ts=time.time()))

    def close(self):
        self.stop.set()
        try:
            if hasattr(self.tracker, "reader"):
                self.tracker.reader.close()
        finally:
            if self.thread is not None:
                self.thread.join(timeout=8.0)
                if self.thread.is_alive():
                    raise RuntimeError("Dummy detection worker did not stop; shared services were not stopped")
            self.tracker.close()


class PersonFollowRuntime:
    """Single motion owner for J1/J4 following and full-joint keyword gestures.

    Observations replace one slot. Motion completion never drains a FIFO of old
    detections. Shutdown drains the already-issued bounded motion but starts no
    new motion and never disconnects the shared Robot Service from its SDK.
    """

    def __init__(self, adapter, max_observation_age_s=0.5, *, config=None,
                 servo=None, guard=None, joints=None, period_s=0.1):
        self.adapter = adapter
        self.max_observation_age_s = float(max_observation_age_s)
        self.config = config or {}
        self.servo = servo if servo is not None else ImageJacobianServo(self.config)
        if any(axis.joint_index not in (0, 3) for axis in self.servo.axes):
            raise ValueError("person following permits J1/J4 only")
        self.guard = guard
        self.joints = list(joints or [0.0] * 6)
        self.period_s = max(0.1, float(period_s))
        self._latest = None
        self._sequence = 0
        self._consumed = 0
        self._lock = threading.Lock()
        self._keywords = deque(maxlen=4)
        self.stopping = asyncio.Event()
        self.mode = "IDLE"
        self.last_reason = "waiting_for_observation"
        self.metrics = {}
        self.servo.reset(self.joints)

    def publish(self, target, *, detection_ms=0.0):
        with self._lock:
            self._sequence += 1
            self._latest = Observation(self._sequence, target, detection_ms)

    def queue_keyword(self, name, *, received_at=None):
        if name not in self.config.get("gestures", {}):
            return False
        self._keywords.append((name, time.monotonic() if received_at is None else received_at))
        return True

    def request_stop(self):
        self.stopping.set()

    async def _measured_joints(self):
        if self.adapter is not None:
            # Finish busy work before reading the latest observation, not after.
            state = await self.adapter.wait_idle(timeout=35.0)
            self.joints = list(state.joints_deg)
        return list(self.joints)

    async def _send(self, target, *, time_sec=None, before_send=None):
        if self.stopping.is_set():
            return False
        if self.guard is not None:
            allowed, reason = self.guard.check(target)
            if not allowed:
                self.last_reason = reason
                return False
        if self.adapter is not None:
            sent = await self.adapter.send_joint_target(target, time_sec=time_sec, skip_if_busy=True, before_send=before_send)
            self.metrics["request_id"] = getattr(self.adapter, "last_request_id", None)
            self.metrics["completed"] = sent
            return sent
        self.joints = list(target)
        return True

    def _latest_follow_target(self, joints):
        with self._lock:
            observation = self._latest
        if observation is None:
            return None
        target = observation.target
        age = time.time() - float(target.ts or 0)
        if (not target.found or "hold" in str(target.kind) or not math.isfinite(age)
                or age < -0.05 or age > self.max_observation_age_s):
            return None
        self._consumed = observation.sequence
        self.metrics.update(observation_sequence=observation.sequence, receive_age_ms=age * 1000,
                            detection_ms=observation.detection_ms)
        started = time.monotonic()
        command = self.servo.update(joints, target, dt_s=self.period_s)
        self.metrics["controller_ms"] = (time.monotonic() - started) * 1000
        self.last_reason = command.reason
        if not command.ok:
            return None
        desired = command.joints_deg
        if self.guard is not None:
            started = time.monotonic()
            desired, _exact, _reason = clamp_to_workspace_guard(joints, desired, self.guard)
            self.metrics["guard_ms"] = (time.monotonic() - started) * 1000
        if max(abs(a - b) for a, b in zip(joints, desired)) < 1e-5:
            return None
        return desired

    async def step(self):
        current = await self._measured_joints()
        if self.stopping.is_set():
            return False
        while self._keywords:
            name, received_at = self._keywords.popleft()
            if time.monotonic() - received_at <= 3.0:
                return await self._gesture(name, current)
        with self._lock:
            observation = self._latest
        if observation is None or observation.sequence <= self._consumed:
            self.last_reason = "no_new_observation"
            return False
        self._consumed = observation.sequence
        target = observation.target
        age = time.time() - float(target.ts or 0)
        if (not target.found or "hold" in str(target.kind) or not math.isfinite(age)
                or age < -0.05 or age > self.max_observation_age_s):
            self.last_reason = "target_stale_or_held"
            self.mode = "HOLDING"
            return False
        command = self.servo.update(current, target, dt_s=self.period_s)
        self.last_reason = command.reason
        if not command.ok or max(abs(a - b) for a, b in zip(current, command.joints_deg)) < 1e-5:
            return False
        desired = command.joints_deg
        if self.guard is not None:
            desired, _exact, reason = clamp_to_workspace_guard(current, desired, self.guard)
            if max(abs(a - b) for a, b in zip(current, desired)) < 1e-5:
                self.last_reason = reason
                return False
        self.mode = "FOLLOWING"
        # A final state request or send-rate wait can outlive the selected frame.
        # Re-read the single latest slot immediately before sending to 3000.
        return await self._send(desired, before_send=lambda state: (
            None if self.stopping.is_set() else self._latest_follow_target(list(state.joints_deg))
        ))

    async def _gesture(self, name, current):
        frames = self.config["gestures"][name].get("keyframes", [])
        targets = []
        previous_t = 0.0
        # Validate the whole gesture before issuing its first segment.
        for frame in frames:
            offset = frame.get("offset_deg", [])
            timestamp = float(frame.get("t", 0))
            if (len(offset) != 6 or not math.isfinite(timestamp) or timestamp < previous_t
                    or not all(math.isfinite(float(x)) for x in offset)):
                raise ValueError("invalid gesture keyframe")
            target = [float(q) + float(delta) for q, delta in zip(current, offset)]
            if self.adapter is not None:
                target = self.adapter._validate(target)
            if self.guard is not None and not self.guard.check(target)[0]:
                self.last_reason = "gesture_workspace_rejected"
                return False
            targets.append((target, timestamp - previous_t))
            previous_t = timestamp
        self.mode = "GESTURE"
        try:
            for target, duration in targets:
                if self.stopping.is_set():
                    break
                measured = await self._measured_joints()
                if max(abs(a - b) for a, b in zip(measured, target)) < 1e-5:
                    continue
                if not await self._send(target, time_sec=max(0.2, duration)):
                    self.last_reason = "gesture_interrupted_or_rejected"
                    return False
            return True
        finally:
            self.servo.reset(await self._measured_joints())
            # Images collected during a gesture may now be old. step() checks age.
            self.mode = "IDLE"

    async def run(self, *, tracker=None, keywords=None, max_steps=0):
        worker = TrackerWorker(tracker, self.publish, self.period_s) if tracker is not None else None
        producer = None
        async def collect_keywords():
            async for event in keywords.events():
                self.queue_keyword(event.get("action", "wake_up"))
        try:
            if worker is not None:
                worker.start()
            if keywords is not None:
                producer = asyncio.create_task(collect_keywords())
            steps = 0
            last_log = 0.0
            while not self.stopping.is_set():
                if worker is not None and worker.error is not None:
                    raise RuntimeError("Dummy detection failed") from worker.error
                if producer is not None and producer.done():
                    producer.result()
                    raise RuntimeError("Dummy keyword subscription ended")
                started = time.monotonic()
                try:
                    await self.step()
                except (ValueError, RuntimeError, TimeoutError, ConnectionError) as exc:
                    # Ambiguous execution must not be followed by another motion.
                    self.last_reason = str(exc)
                    print(f"[dummy] motion paused: {exc}", flush=True)
                    raise
                steps += 1
                self.metrics["cycle_ms"] = (time.monotonic() - started) * 1000
                if time.monotonic() - last_log >= 2.0:
                    last_log = time.monotonic()
                    print(f"[dummy] mode={self.mode} reason={self.last_reason} metrics={self.metrics}", flush=True)
                if max_steps and steps >= max_steps:
                    break
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=max(0.001, self.period_s - (time.monotonic() - started)))
                except asyncio.TimeoutError:
                    pass
        finally:
            self.request_stop()
            self._keywords.clear()
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            try:
                if worker is not None:
                    await asyncio.to_thread(worker.close)
            finally:
                if self.adapter is not None:
                    await self.adapter.close()
                self.mode = "STOPPED"

    async def handle(self, observation, now: float):
        age = now - float(observation.get("captured_at", 0))
        if not math.isfinite(age) or age < 0 or age > self.max_observation_age_s:
            return "HOLDING"
        if observation.get("identity_state") != "LOCKED" or not observation.get("identity_id"):
            return "HOLDING"
        return "LOCKED"
