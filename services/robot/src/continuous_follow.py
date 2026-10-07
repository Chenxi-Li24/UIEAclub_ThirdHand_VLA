"""Latest-target J1/J4 interpolation, independent of SDK and transport."""
import math

from joint_speed_policy import REFERENCE_DEG_S, bounded_speed_percent


class ContinuousFollow:
    def __init__(self, guard, speed_percent=0.05, watchdog_s=0.5, j1_speed_deg_s=50):
        self.guard = guard
        self.speed = [math.radians(v * bounded_speed_percent(speed_percent)) for v in REFERENCE_DEG_S]
        self.acceleration = [v / 0.3 for v in self.speed]
        self.jerk = [a / 0.1 for a in self.acceleration]
        j1_speed = float(j1_speed_deg_s)
        if not math.isfinite(j1_speed) or not 0 < j1_speed <= 50:
            raise ValueError("J1 follow speed must be within (0, 50] deg/s")
        # Raising the follow velocity must not also raise acceleration or jerk.
        self.speed[0] = math.radians(j1_speed)
        self.watchdog_s = watchdog_s
        self.active = False
        self.session_id = None
        self.anchor = None
        self.sequence = -1
        self.stopping = False
        self.reason = None

    @staticmethod
    def vector(values):
        if not isinstance(values, list) or len(values) != 6:
            raise ValueError("follow requires six joint values")
        result = [float(v) for v in values]
        if not all(math.isfinite(v) for v in result):
            raise ValueError("follow joint values must be finite")
        return result

    def begin(self, session_id, measured, now):
        if self.active:
            raise ValueError("follow already active")
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            raise ValueError("invalid follow stream ID")
        measured = self.vector(measured)
        if self.guard is None or not self.guard.check([math.degrees(q) for q in measured])[0]:
            raise ValueError("follow start workspace rejected")
        if abs(measured[3]) > math.radians(35.05):
            raise ValueError("J4 outside follow range")
        if session_id == self.session_id and abs(measured[0] - self.anchor[0]) > math.radians(85.05):
            raise ValueError("J1 outside original follow envelope")
        # Pauses/gestures on one stream never widen its original J1 envelope.
        if session_id != self.session_id:
            self.anchor = list(measured)
            self.sequence = -1
        self.session_id = session_id
        self.q = list(measured)
        self.body_hold = list(measured)
        self.target = list(measured)
        self.v = [0.0] * 6
        self.a = [0.0] * 6
        self.active = True
        self.stopping = False
        self.reason = None
        self.last_update = now

    def update(self, session_id, sequence, values, observed_at_ms, now, wall_ms):
        if not self.active or self.stopping or session_id != self.session_id:
            raise ValueError("follow stream inactive")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= self.sequence:
            raise ValueError("follow sequence must increase")
        if not isinstance(observed_at_ms, (int, float)) or not math.isfinite(observed_at_ms):
            raise ValueError("follow observation timestamp required")
        if not -50 <= wall_ms - observed_at_ms <= 500:
            raise ValueError("follow observation stale")
        target = self.vector(values)
        for index in (1, 2, 4, 5):
            if abs(target[index] - self.body_hold[index]) > math.radians(0.05):
                raise ValueError("follow may change J1/J4 only")
        if abs(target[0] - self.anchor[0]) > math.radians(85) + 1e-9:
            raise ValueError("J1 follow excursion exceeded")
        if abs(target[3]) > math.radians(35) + 1e-9:
            raise ValueError("J4 follow range exceeded")
        if not self.guard.check([math.degrees(q) for q in target])[0]:
            raise ValueError("follow target workspace rejected")
        self.target = target
        self.sequence = sequence
        self.last_update = now

    def stop(self, reason="requested"):
        if self.active:
            self.stopping = True
            self.reason = reason

    def tick(self, now, dt):
        if not self.active:
            return None
        if now - self.last_update > self.watchdog_s:
            self.stop("observation_timeout")
        dt = min(max(dt, 0.001), 0.025)
        proposal = list(self.q)
        for i in (0, 3):
            desired_a = -self.v[i] / 0.12 if self.stopping else 16 * (self.target[i] - self.q[i]) - 8 * self.v[i]
            desired_a = max(-self.acceleration[i], min(self.acceleration[i], desired_a))
            self.a[i] += max(-self.jerk[i] * dt, min(self.jerk[i] * dt, desired_a - self.a[i]))
            new_v = max(-self.speed[i], min(self.speed[i], self.v[i] + self.a[i] * dt))
            if self.stopping and (new_v * self.v[i] <= 0 or abs(new_v) < 1e-4):
                new_v = 0.0
                self.a[i] = 0.0
            proposal[i] += new_v * dt
            lo, hi = ((max(math.radians(-162), self.anchor[0] - math.radians(85)),
                       min(math.radians(162), self.anchor[0] + math.radians(85))) if i == 0
                      else (math.radians(-35), math.radians(35)))
            if not lo <= proposal[i] <= hi:
                proposal[i] = min(hi, max(lo, proposal[i]))
                new_v = self.a[i] = 0.0
            self.v[i] = new_v
        if not self.guard.check([math.degrees(q) for q in proposal])[0]:
            # Never apply an unchecked deceleration path at a geometry boundary.
            self.stop("workspace_boundary")
            self.v = self.a = [0.0] * 6
            proposal = list(self.q)
        self.q = proposal
        finished = self.stopping and max(abs(v) for v in self.v) < 1e-4
        if finished:
            self.active = False
        return list(self.q), list(self.v), finished
