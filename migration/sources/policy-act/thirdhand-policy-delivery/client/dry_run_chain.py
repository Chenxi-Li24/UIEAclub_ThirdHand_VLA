#!/usr/bin/env python3
"""
全链路 dry-run 回放：用官方 ``contracts/examples/demo_flow.json`` 的 11 条消息
把完整链路串一遍，Policy 环节用本机的真实 Policy 处理（默认离线直调 handler），验证：

1. traceId 全程一致；
2. replyTo 链连续（11 条消息全部可回链）；
3. Policy 的 msg-005 -> 输出 与官方 msg-006 逐字段一致；
4. Policy 输出通过 schema.json 校验。

用法::

  python3 dry_run_chain.py
  python3 dry_run_chain.py --demo-flow path/to/demo_flow.json
  python3 dry_run_chain.py --endpoint http://192.168.58.68:8080   # 走真实 HTTP 服务
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from thirdhand_policy.handler import handle_policy_action_request
from thirdhand_policy.schema import load_schema


def load_flow(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _call_policy_http(endpoint: str, request: dict) -> dict:
    body = json.dumps(request, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/v1/policy/action",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_chain(flow: dict, *, endpoint: str | None = None) -> None:
    messages = flow["messages"]

    # 1. traceId 全程一致
    trace_ids = {m.get("traceId") for m in messages}
    if len(trace_ids) != 1:
        raise AssertionError(f"traceId 不一致: {trace_ids}")
    trace_id = messages[0]["traceId"]
    print(f"[chain] traceId 一致: {trace_id}")

    # 2. replyTo 链连续
    by_id = {m["messageId"]: m for m in messages}
    for m in messages[1:]:
        if m.get("replyTo") and m["replyTo"] not in by_id:
            raise AssertionError(f"{m['type']} 的 replyTo={m['replyTo']} 找不到前序消息")
    print(f"[chain] replyTo 链连续: {len(messages)} 条消息全部可回链")

    # 3. Policy 环节: 处理官方 msg-005, 与官方 msg-006 对照
    req = by_id["msg-005"]
    expected = by_id["msg-006"]
    if endpoint:
        actual = _call_policy_http(endpoint, req)
    else:
        actual = handle_policy_action_request(json.loads(json.dumps(req)), {})

    checks = [
        ("type", actual["type"], expected["type"]),
        ("status", actual["status"], expected["status"]),
        ("policy.kind", actual["payload"]["policy"]["kind"], expected["payload"]["policy"]["kind"]),
        ("plan.kind", actual["payload"]["executionPlan"]["kind"], expected["payload"]["executionPlan"]["kind"]),
        ("routeStates", actual["payload"]["executionPlan"]["routeStates"], expected["payload"]["executionPlan"]["routeStates"]),
        ("traceId 保留", actual["traceId"], trace_id),
        ("replyTo -> msg-005", actual["replyTo"], "msg-005"),
    ]
    for name, mine, official in checks:
        ok = mine == official
        print(f"[policy] {'OK ' if ok else 'DIFF'} {name}")
        if not ok:
            raise AssertionError(f"{name}: mine={mine} official={official}")

    # 4. schema 校验
    if Draft202012Validator is not None:
        errors = list(Draft202012Validator(load_schema()).iter_errors(actual))
        if errors:
            raise AssertionError(f"schema 校验失败: {errors[0].message}")
        print("[policy] schema.json 校验通过")
    else:
        print("[policy] jsonschema 未安装，跳过 schema 校验")

    print()
    print("结果: 全链路 dry-run 回放通过（Policy 环节与官方 demo_flow 一致）")
    print("说明: 这只是 dry-run 链路成功，不代表真实机器人抓取完成。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo-flow",
        default=None,
        help="demo_flow.json 路径（默认自动找 contracts/examples/demo_flow.json）",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Policy HTTP 服务地址（缺省为离线直调 handler）",
    )
    args = parser.parse_args()

    flow_path = args.demo_flow or str(ROOT / "contracts" / "examples" / "demo_flow.json")
    run_chain(load_flow(flow_path), endpoint=args.endpoint)


if __name__ == "__main__":
    main()
