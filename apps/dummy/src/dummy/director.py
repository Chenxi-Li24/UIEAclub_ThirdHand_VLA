from __future__ import annotations

import asyncio
import math
import time

from .follow_director import FollowDirector
from .gestures import GestureLibrary
from .motion_player import MotionPlayer
from .state_machine import State
from .tracker import HumanTracker
from .vision_service_tracker import VisionServiceTracker
from .wake_word import WakeWordDetector


class DummyDirector:
    def __init__(self, adapter, config):
        self.adapter = adapter
        self.config = config
        self.state = State.IDLE
        self.gestures = GestureLibrary(config)
        self.player = MotionPlayer(adapter, config)
        self.follow = FollowDirector(config)
        if config.get("vision_service", {}).get("enabled", True):
            self.tracker = VisionServiceTracker(config)
            self._tracker_mode = "vision_service"
        else:
            self.tracker = HumanTracker(config)
            self._tracker_mode = "opencv_v4l"
        self.wake = WakeWordDetector(config)
        timing = config.get("timing", {})
        self.lost_hold_s = float(timing.get("lost_hold_s", 1.2))
        self.search_s = float(timing.get("search_s", 4.0))
        self.sleep_after_s = float(timing.get("sleep_after_s", 25.0))
        self.search_scale = float(config.get("follow", {}).get("search_scale", 0.30))
        self.last_seen = 0.0
        self.search_started = 0.0
        self.last_activity = time.time()
        self.idle_base = None
        self._last_logged_state = None
        self._last_target_log = 0.0
        self._last_motion_log = 0.0

    def _set_state(self, state):
        if state != self.state:
            print(f"[dummy] state {self.state.value} -> {state.value}", flush=True)
        self.state = state

    def _enter_search(self, joints, now):
        # Search around the pose where the person was last visible.  Keeping
        # the old startup base makes the arm snap back before it searches.
        self.follow.reset_base(joints)
        self._set_state(State.SEARCH)
        self.idle_base = None
        self.search_started = float(now)

    async def _send_search_command(self, joints, phase):
        command = self.follow.search_target(joints, phase, scale=self.search_scale)
        try:
            await self.adapter.send_joint_target(command)
        except Exception as exc:
            print(f"[dummy] search command rejected: {exc}", flush=True)
            self.follow.reset_base(joints)
            return False
        return True

    async def gesture(self, name):
        await self.player.play(name, self.gestures.get(name))

    async def wake_response(self):
        self.player.interrupt()
        self._set_state(State.ATTENTIVE)
        self.last_activity = time.time()
        await self.gesture("wake_up")
        await self.gesture("nod")

    async def _wake_loop(self):
        async for _ in self.wake.events():
            await self.wake_response()

    async def run(self):
        await self.adapter.connect()
        print("[dummy] robot connected; starting wake_up", flush=True)
        if self.config.get("robot", {}).get("go_home_on_start", True) and hasattr(self.adapter, "go_home"):
            print("[dummy] going to configured Home preset", flush=True)
            await self.adapter.go_home()
            self.follow.reset_base((await self.adapter.get_state()).joints_deg)
        await self.gesture("wake_up")
        if hasattr(self.tracker, "open"):
            opened = self.tracker.open()
            print(f"[dummy] tracker={self._tracker_mode} open={opened}", flush=True)
        print("[dummy] running; type ThirdHand + Enter for wake response", flush=True)
        wake_task = asyncio.create_task(self._wake_loop())
        hz = float(self.config.get("director", {}).get("hz", 7))
        period = 1.0 / hz
        phase = 0.0
        try:
            while True:
                state = await self.adapter.get_state()
                joints = state.joints_deg
                if len(joints) != 6:
                    await asyncio.sleep(period)
                    continue

                now = time.time()
                if self._tracker_mode == "vision_service":
                    target, _frame, error = self.tracker.read_frame()
                    if error and now - self._last_target_log > 5.0:
                        print(f"[dummy] vision stream warning: {error}", flush=True)
                        self._last_target_log = now
                else:
                    target = self.tracker.read()
                phase += period * 2 * math.pi / 3.0

                if target.found:
                    if self.state in {State.SEARCH, State.IDLE, State.SLEEP}:
                        await self.gesture("perk_up")
                    self._set_state(State.FOLLOW)
                    self.idle_base = None
                    self.last_seen = now
                    self.last_activity = now
                    if now - self._last_target_log > 0.5:
                        print(f"[dummy] target {target.kind} u={target.u:.0f} v={target.v:.0f}", flush=True)
                        self._last_target_log = now
                    cmd = self.follow.target_for(joints, target)
                    log_motion = now - self._last_motion_log > 0.5
                    if log_motion:
                        ex, ey = self.follow.last_error_px
                        print(
                            "[dummy] follow cmd "
                            f"err=({ex:.0f},{ey:.0f}) "
                            f"j{self.follow.pan_joint + 1}={cmd[self.follow.pan_joint]:.2f} "
                            f"j{self.follow.tilt_joint + 1}={cmd[self.follow.tilt_joint]:.2f} "
                            f"j{self.follow.roll_joint + 1}={cmd[self.follow.roll_joint]:.2f}",
                            flush=True,
                        )
                        self._last_motion_log = now
                    try:
                        await self.adapter.send_joint_target(cmd)
                    except Exception as exc:
                        print(f"[dummy] follow command rejected: {exc}", flush=True)
                        self.follow.reset_base(joints)
                        await asyncio.sleep(period)
                        continue
                    if log_motion:
                        print("[dummy] follow command sent", flush=True)
                    await asyncio.sleep(period)
                    continue

                if self.state == State.FOLLOW and now - self.last_seen > self.lost_hold_s:
                    self._enter_search(joints, now)

                if self.state == State.SEARCH:
                    if now - self.search_started < self.search_s:
                        sent = await self._send_search_command(joints, phase)
                        if sent and now - self._last_motion_log > 2.0:
                            cmd = self.follow.current
                            print(
                                "[dummy] search cmd "
                                f"j{self.follow.pan_joint + 1}={cmd[self.follow.pan_joint]:.2f} "
                                f"j{self.follow.tilt_joint + 1}={cmd[self.follow.tilt_joint]:.2f}",
                                flush=True,
                            )
                            self._last_motion_log = now
                    else:
                        await self.gesture("droop")
                        if self.config.get("robot", {}).get("go_home_on_lost", True) and hasattr(self.adapter, "go_home"):
                            print("[dummy] target lost; returning to Home preset", flush=True)
                            await self.adapter.go_home()
                            self.follow.reset_base((await self.adapter.get_state()).joints_deg)
                        self._set_state(State.IDLE)
                        self.idle_base = None
                        self.last_activity = now
                elif self.state in {State.IDLE, State.AWAKE, State.ATTENTIVE}:
                    if self.idle_base is None:
                        self.idle_base = list(joints)
                    amp = float(self.config.get("idle", {}).get("breath_deg", 0.10))
                    cmd = list(self.idle_base)
                    cmd[1] += math.sin(phase) * amp
                    cmd[2] -= math.sin(phase) * amp
                    await self.adapter.send_joint_target(cmd)
                    if now - self.last_activity > self.sleep_after_s:
                        await self.gesture("sleep")
                        self._set_state(State.SLEEP)
                elif self.state == State.SLEEP:
                    await asyncio.sleep(period)

                await asyncio.sleep(period)
        finally:
            wake_task.cancel()
            self.tracker.close()
