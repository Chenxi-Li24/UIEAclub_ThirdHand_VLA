from __future__ import annotations


def should_advance_local_joints(*, enable_motion: bool, guard_ok: bool, sent: bool) -> bool:
    if not guard_ok:
        return False
    if not enable_motion:
        return True
    return bool(sent)


def clamp_to_workspace_guard(current, target, guard, *, iterations: int = 12):
    ok, reason = guard.check(target)
    if ok:
        return list(target), True, reason
    current_ok, current_reason = guard.check(current)
    if not current_ok:
        return list(current), False, current_reason
    lo = 0.0
    hi = 1.0
    best = list(current)
    best_reason = current_reason
    for _ in range(max(1, int(iterations))):
        mid = (lo + hi) / 2.0
        candidate = [
            float(src) + (float(dst) - float(src)) * mid
            for src, dst in zip(current, target)
        ]
        candidate_ok, candidate_reason = guard.check(candidate)
        if candidate_ok:
            lo = mid
            best = candidate
            best_reason = candidate_reason
        else:
            hi = mid
    return best, False, f"clamped_workspace: {best_reason}"
