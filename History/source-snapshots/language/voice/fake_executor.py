"""
Fake Executor — simulated robot execution feedback for Voice Bridge.

Returns explicit simulated results for known intents so the browser TTS +
confirmation round-trip can be tested without real hardware.

FUTURE: 真机验证时替换为实际机械臂执行 + 传感器反馈。
        execute() 应返回::

            {"success": bool, "message": str, "intent": str}

        其中 message 是人类可读的中文反馈，如 "夹爪已成功打开至 0.05m"。
"""

from __future__ import annotations

from typing import Any


class FakeExecutor:
    """Simulated execution with Chinese-language feedback messages."""

    FAKE_RESULTS: dict[str, str] = {
        "gripper.open": "模拟执行完成：夹爪打开至最大位置 (0.05m)",
        "gripper.close": "模拟执行完成：夹爪闭合",
        "gripper.grip": "模拟执行完成：夹取目标物体",
        "gripper.release": "模拟执行完成：夹爪松开",
        "robot.preset": "模拟执行完成：机械臂回到预设位 (home)",
        "robot.estop": "模拟执行完成：触发软件停止预览",
        "robot.move_to": "模拟执行完成：机械臂移动至目标位置",
        "robot.status": "模拟状态：各关节就绪",
    }

    def execute(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Return a fake execution result for *candidate*.

        Parameters
        ----------
        candidate:
            An ``intent.candidate`` object with at least an ``intent`` key.

        Returns
        -------
        dict
            ``{"success": True, "message": "...", "intent": "..."}``
        """
        intent = candidate.get("intent", "")
        message = self.FAKE_RESULTS.get(
            intent,
            f"模拟执行完成：{intent}",
        )
        return {
            "success": True,
            "message": message,
            "intent": intent,
            "simulated": True,
            "executor": "fake",
        }
