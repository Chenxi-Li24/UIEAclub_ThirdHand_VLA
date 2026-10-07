from __future__ import annotations

import cv2


def render_head_body_overlay(
    frame,
    target,
    command,
    joints,
    *,
    debug=None,
    error=None,
    enabled=False,
    robot_url="ws://127.0.0.1:3000/ws",
):
    out = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if len(frame.shape) == 2 else frame.copy()
    h, w = out.shape[:2]
    cx, cy = w // 2, h // 2
    fresh = bool(getattr(target, "found", False)) and not str(getattr(target, "kind", "")).endswith("_hold")
    color = (80, 255, 80) if fresh else (0, 180, 255)
    if error:
        color = (0, 0, 255)

    cv2.line(out, (cx - 24, cy), (cx + 24, cy), (235, 235, 235), 1)
    cv2.line(out, (cx, cy - 24), (cx, cy + 24), (235, 235, 235), 1)
    cv2.circle(out, (cx, cy), 34, (105, 105, 105), 1)

    debug = debug or {}
    if debug.get("bbox"):
        x, y, bw, bh = [int(value) for value in debug["bbox"]]
        cv2.rectangle(out, (x, y), (x + bw, y + bh), (0, 180, 255), 1)
        _tag(out, "raw bbox", x, max(14, y - 6), (0, 180, 255))
        raw = debug.get("raw_target")
        if raw:
            cv2.circle(out, (int(raw[0]), int(raw[1])), 4, (0, 180, 255), -1)
    if getattr(target, "found", False):
        u, v = int(target.u), int(target.v)
        cv2.circle(out, (u, v), 14, color, 2)
        cv2.circle(out, (u, v), 3, color, -1)
        cv2.arrowedLine(out, (cx, cy), (u, v), color, 2, tipLength=0.12)
        status = f"{target.kind}  err=({target.u - cx:+.0f},{target.v - cy:+.0f})  score={target.score:.2f}"
        _tag(out, "LOCK", u + 16, max(14, v - 10), color)
    else:
        status = f"target={getattr(target, 'kind', 'none')}"

    _draw_status_strip(out, status, debug, error, enabled, robot_url, color)
    _draw_joint_bars(out, joints, command, x=max(20, w - 250), y=max(90, h // 2 - 52))
    return out


def _joint_line(label, values):
    if not values or len(values) != 6:
        return f"{label}: unavailable"
    return f"{label}: " + " ".join(f"J{i + 1}={float(value):6.2f}" for i, value in enumerate(values))


def _panel(frame, x1, y1, x2, y2):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (90, 90, 90), 1)


def _soft_panel(frame, x1, y1, x2, y2, alpha=0.42):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


def _put(frame, text, x, y, color):
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 1, cv2.LINE_AA)


def _tag(frame, text, x, y, color):
    cv2.putText(frame, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.44, color, 1, cv2.LINE_AA)


def _draw_status_strip(frame, status, debug, error, enabled, robot_url, color):
    h, w = frame.shape[:2]
    strip_h = 58
    y0 = h - strip_h
    _soft_panel(frame, 0, y0, w, h, alpha=0.46)
    mode = "ARMED" if enabled else "DRY RUN"
    depth_line = _compact_target_line(debug)
    control = str(debug.get("control_source", "-"))
    lock = f"candidates={debug.get('candidate_count', '-')} lock={debug.get('lock_state', '-')}"
    if error:
        control = f"vision warning: {error}"
        color = (0, 80, 255)
    if debug.get("rejected"):
        lock = f"reject={debug['rejected']}"
    _put(frame, f"{mode}  {status}", 14, y0 + 22, color)
    _put(frame, f"{depth_line}   {lock}", 14, y0 + 46, (180, 230, 255))
    _put(frame, f"{control}   {robot_url}", max(14, w - 600), y0 + 46, _control_color(control))


def _draw_joint_bars(frame, joints, command, *, x, y):
    if not joints or not command or len(joints) != 6 or len(command) != 6:
        return
    _soft_panel(frame, x - 12, y - 20, x + 232, y + 78, alpha=0.38)
    for index, (src, dst) in enumerate(zip(joints, command)):
        row_y = y + index * 15
        delta = float(dst) - float(src)
        _tag(frame, f"J{index + 1}", x, row_y, (230, 230, 230))
        cv2.line(frame, (x + 30, row_y - 5), (x + 132, row_y - 5), (90, 90, 90), 3)
        center = x + 81
        end = int(center + max(-48, min(48, delta * 18)))
        cv2.line(frame, (center, row_y - 5), (end, row_y - 5), (80, 255, 255), 5)
        _tag(frame, f"{delta:+.1f}", x + 148, row_y, (120, 255, 255))


def _compact_target_line(debug):
    depth = debug.get("estimated_depth_m", debug.get("distance_depth_m"))
    depth_text = "-" if depth is None else f"{float(depth):.2f}m"
    source = debug.get("estimated_depth_source", debug.get("distance_depth_source", "-"))
    return (
        f"{debug.get('target_3d_mode', '-')} "
        f"{debug.get('distance_state', '-')} "
        f"depth={source}:{depth_text}"
    )


def _xyz_text(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return "-"
    try:
        return "(" + ",".join(f"{float(v):+.2f}" for v in value) + ")m"
    except (TypeError, ValueError):
        return "-"


def _control_color(source):
    text = str(source or "")
    if text.startswith(("mink/base/depth3d", "mink/camera/depth3d", "mink/depth3d")):
        return (120, 255, 180)
    if text.startswith(("mink/base/virtual3d", "mink/camera/virtual3d", "mink/virtual3d")):
        return (0, 220, 255)
    if text.startswith("mink_failed"):
        return (0, 120, 255)
    return (220, 220, 220)
