from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEECH = ROOT / "services" / "speech" / "src"
sys.path.insert(0, str(SPEECH))

import voice_agent


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def tool(name: str, payload: dict, tool_id: str = "tool-1"):
    return SimpleNamespace(type="tool_use", name=name, input=payload, id=tool_id)


class Messages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.responses.pop(0))


class Client:
    def __init__(self, responses):
        self.messages = Messages(responses)


class VisionSkill:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "status": "completed",
            "summary": "桌面上有一个红色罐子。",
            "frame": {
                "frameId": "xvisio-9",
                "sequence": 9,
                "capturedAt": "2026-09-20T10:00:00.000Z",
                "frameAgeMs": 12,
                "timestampSource": "stream-header",
                "widthPx": None,
                "heightPx": None,
            },
            "model": "deepseek-flash",
            "trace": [{
                "stage": "vision.inspect_scene",
                "status": "completed",
                "model": "deepseek-flash",
                "frameId": "xvisio-9",
                "frameAgeMs": 12,
                "retryCount": 0,
            }],
        }
        self.error = error
        self.calls = []

    def invoke(self, question, *, prior_visual_summary=None, language="zh"):
        self.calls.append({
            "question": question,
            "prior_visual_summary": prior_visual_summary,
            "language": language,
        })
        if self.error:
            raise self.error
        return self.result


def controller(responses, *, skill=None, model="auto"):
    client = Client(responses)
    agent = voice_agent.ThirdHandController(
        model=model,
        client=client,
        vision_skill=skill or VisionSkill(),
    )
    return agent, client


def test_uses_explicit_text_model_environment(monkeypatch):
    monkeypatch.setenv("TEXT_LLM_MODEL", "deepseek-v4-pro")
    agent, client = controller([[text("你好")]])

    result = agent.chat("你好")

    assert result == {"text": "你好", "actions": [], "trace": []}
    assert client.messages.calls[0]["model"] == "deepseek-v4-pro"


def test_visual_tool_runs_skill_and_returns_result_to_controller():
    skill = VisionSkill()
    agent, client = controller([
        [tool("vision_inspect_scene", {"question": "前面有什么？"})],
        [text("前方桌面上有一个红色罐子。")],
    ], skill=skill)

    result = agent.chat("帮我看看前面有什么")

    assert result["text"] == "前方桌面上有一个红色罐子。"
    assert result["actions"] == []
    assert result["trace"][0]["stage"] == "vision.inspect_scene"
    assert skill.calls == [{
        "question": "前面有什么？",
        "prior_visual_summary": None,
        "language": "zh",
    }]
    assert len(client.messages.calls) == 2
    first_tools = {item["name"] for item in client.messages.calls[0]["tools"]}
    assert "vision_inspect_scene" in first_tools
    continuation = client.messages.calls[1]["messages"][-1]["content"][0]
    assert continuation["type"] == "tool_result"
    payload = json.loads(continuation["content"])
    assert payload["summary"] == "桌面上有一个红色罐子。"
    assert "jpeg" not in continuation["content"].lower()


def test_visual_context_survives_a_later_motion_candidate():
    skill = VisionSkill()
    agent, _client = controller([
        [tool("vision_inspect_scene", {"question": "看一下"})],
        [text("看到了一个红色罐子。")],
        [tool("open_gripper", {})],
        [tool("vision_inspect_scene", {"question": "它还在吗？"}, "tool-3")],
        [text("红色罐子仍在画面中。")],
    ], skill=skill)

    first = agent.chat("看一下")
    motion = agent.chat("打开夹爪")
    follow_up = agent.chat("它还在吗")

    assert first["actions"] == []
    assert motion["actions"] == [{"tool": "open_gripper", "input": {}}]
    assert follow_up["text"] == "红色罐子仍在画面中。"
    assert skill.calls[-1]["prior_visual_summary"] == "桌面上有一个红色罐子。"


def test_skill_failure_is_explicit_and_does_not_call_pro_again():
    error = RuntimeError("当前摄像头画面不可用。")
    error.code = "stream_unavailable"
    skill = VisionSkill(error=error)
    agent, client = controller([
        [tool("vision_inspect_scene", {"question": "看一下"})],
    ], skill=skill)

    result = agent.chat("看一下")

    assert "摄像头画面不可用" in result["text"]
    assert result["actions"] == []
    assert result["trace"] == [{
        "stage": "vision.inspect_scene",
        "status": "failed",
        "code": "stream_unavailable",
    }]
    assert len(client.messages.calls) == 1


def test_visual_turn_cannot_emit_a_motion_candidate_after_observation():
    agent, _client = controller([
        [tool("vision_inspect_scene", {"question": "look ahead"})],
        [tool("open_gripper", {}, "tool-motion")],
    ])

    result = agent.chat("look ahead and then open the gripper")

    assert result["actions"] == []
    assert "视觉检查仅用于描述" in result["text"]
    assert result["trace"][-1] == {
        "stage": "controller.policy",
        "status": "failed",
        "code": "vision_motion_separation",
    }


def test_visual_turn_may_convert_say_tool_to_natural_language_only():
    agent, _client = controller([
        [tool("vision_inspect_scene", {"question": "look ahead"})],
        [tool("say", {"text": "前面有一个红色罐子。"}, "tool-say")],
    ])

    result = agent.chat("look ahead")

    assert result["text"] == "前面有一个红色罐子。"
    assert result["actions"] == []
    assert result["trace"][0]["stage"] == "vision.inspect_scene"


def test_visual_and_motion_tools_cannot_be_mixed_in_one_model_response():
    skill = VisionSkill()
    agent, client = controller([[tool(
        "vision_inspect_scene",
        {"question": "look ahead"},
    ), tool("open_gripper", {}, "tool-motion")]], skill=skill)

    result = agent.chat("look ahead and then open the gripper")

    assert result["actions"] == []
    assert "视觉检查与机械臂动作需要分开请求" in result["text"]
    assert skill.calls == []
    assert len(client.messages.calls) == 1


def test_history_window_starts_at_a_complete_user_turn():
    agent, _client = controller([[text("unused")]])
    history = []
    for index in range(6):
        call = tool("open_gripper", {}, f"tool-{index}")
        history.extend([
            {"role": "user", "content": f"turn-{index}"},
            {"role": "assistant", "content": [call]},
            {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": "candidate",
            }]},
        ])
    agent._history = history

    window = agent._history_window(max_entries=8)

    assert window[0]["role"] == "user"
    assert isinstance(window[0]["content"], str)
    seen_tool_ids = set()
    for message in window:
        content = message["content"]
        if message["role"] == "assistant" and isinstance(content, list):
            seen_tool_ids.update(block.id for block in content)
        if message["role"] == "user" and isinstance(content, list):
            for result in content:
                assert result["tool_use_id"] in seen_tool_ids


def test_raw_text_model_exception_is_not_returned_to_the_user():
    class FailingMessages:
        def create(self, **_kwargs):
            raise RuntimeError("provider URL token=must-not-leak")

    client = SimpleNamespace(messages=FailingMessages())
    agent = voice_agent.ThirdHandController(client=client)

    result = agent.chat("hello")

    assert result["text"] == "语言模型暂时不可用，请稍后重试。"
    assert "must-not-leak" not in json.dumps(result, ensure_ascii=False)
    assert result["trace"] == [{
        "stage": "controller.text",
        "status": "failed",
        "code": "llm_unavailable",
    }]


def test_controller_stops_a_second_visual_tool_call_in_the_same_turn():
    agent, client = controller([
        [tool("vision_inspect_scene", {"question": "看一下"})],
        [tool("vision_inspect_scene", {"question": "再看一次"}, "tool-2")],
    ])

    result = agent.chat("看一下")

    assert "本轮视觉检查次数已达到上限" in result["text"]
    assert result["actions"] == []
    assert len(client.messages.calls) == 2


def test_compatibility_alias_keeps_existing_voice_bridge_factory():
    assert voice_agent.ClaudeAgent is voice_agent.ThirdHandController
