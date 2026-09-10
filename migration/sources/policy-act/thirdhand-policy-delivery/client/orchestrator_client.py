#!/usr/bin/env python3
"""
Orchestrator 联调示例：如何调用 Policy 服务。

把 Vision 的 ``vision.target.result`` 里的 ``target`` 原样放进
``policy.action.request``，POST 到 Policy 服务，解析 ``policy.action.result``。

用法::

  python3 orchestrator_client.py                                  # 只打印构造好的请求
  python3 orchestrator_client.py --endpoint http://192.168.58.68:8080   # 真实调用并打印计划
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def now_ms() -> int:
    return int(time.time() * 1000)


def build_policy_action_request(
    *,
    vision_target_result: dict,
    robot_state_ref: str,
    allowed_policy_kinds: list[str],
    mode: str = "dry-run",
) -> dict:
    """由 Vision 的 ``vision.target.result`` 构造 ``policy.action.request``。

    关键映射（契约规定，不要另起字段）：
    - vision.payload.target      -> policy.payload.target（原样）
    - vision.payload.candidateId -> policy.payload.candidateId
    - sessionId / traceId 原样传递
    - replyTo = vision 消息的 messageId
    """
    vision_payload = vision_target_result.get("payload") or {}
    return {
        "schemaVersion": "1.0",
        "type": "policy.action.request",
        "messageId": new_id("msg"),
        "replyTo": vision_target_result.get("messageId"),
        "sessionId": vision_target_result.get("sessionId"),
        "traceId": vision_target_result.get("traceId"),
        "ts": now_ms(),
        "source": "orchestrator",
        "target": "policy",
        "mode": mode,
        "payload": {
            "candidateId": vision_payload.get("candidateId"),
            "target": vision_payload.get("target"),
            "robotStateRef": robot_state_ref,
            "actionSpaceId": "startouch-j1-j6-rad-gripper-v1",
            "allowedPolicyKinds": allowed_policy_kinds,
        },
    }


def call_policy(endpoint: str, request: dict, timeout_s: float = 15.0) -> dict:
    """POST ``policy.action.request`` 到 Policy 服务，返回响应 JSON。

    endpoint 形如 http://192.168.58.68:8080；超时参考契约 timeoutsMs.policy = 15000。
    """
    url = f"{endpoint.rstrip('/')}/v1/policy/action"
    body = json.dumps(request, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_plan(result: dict) -> dict:
    """从 ``policy.action.result`` 取出 ``executionPlan``（转发给 Robot 的内容）。"""
    if result.get("type") == "service.error":
        raise RuntimeError(
            f"policy returned service.error: {result['error']['code']} {result['error']['message']}"
        )
    if result.get("status") != "ready":
        raise RuntimeError(f"policy not ready: status={result.get('status')}")
    return result["payload"]["executionPlan"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Policy 服务地址，如 http://192.168.58.68:8080（缺省只打印请求）",
    )
    args = parser.parse_args()

    # 示例：一份 Vision 的 vision.target.result（字段与官方 demo_flow.json 一致）
    vision_result = {
        "schemaVersion": "1.0",
        "type": "vision.target.result",
        "messageId": "msg:vision-demo",
        "replyTo": "msg:vision-request",
        "sessionId": "session:demo",
        "traceId": "trace:demo",
        "ts": now_ms(),
        "source": "vision",
        "target": "orchestrator",
        "mode": "dry-run",
        "status": "ready",
        "payload": {
            "candidateId": "candidate:demo",
            "frame": {
                "frameId": "frame-1",
                "cameraId": "xvisio-rgbd-01",
                "capturedAt": now_ms(),
                "widthPx": 640,
                "heightPx": 480,
            },
            "target": {
                "targetId": "coke:frame-1:0",
                "label": "coke_bottle",
                "confidence": 0.9,
                "bbox": {
                    "format": "xyxy",
                    "coordinateSpace": "pixel",
                    "values": [213, 368, 307, 478],
                },
                "maskRef": "mask-1",
                "frameId": "frame-1",
                "uniqueTarget": True,
                "authorized": True,
            },
        },
    }

    request = build_policy_action_request(
        vision_target_result=vision_result,
        robot_state_ref="robot-state-1",
        allowed_policy_kinds=["fixed_baseline", "fake_act"],
        mode="dry-run",
    )

    if args.endpoint:
        result = call_policy(args.endpoint, request)
        plan = extract_plan(result)
        print("policy.action.result 中的 executionPlan（可转发给 Robot）：")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print("未指定 --endpoint，仅打印构造好的 policy.action.request：")
        print(json.dumps(request, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
