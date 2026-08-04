"""
VLA API client — sends camera frames + context to Claude, gets action recommendations.

Supports: Anthropic Claude, DeepSeek, OpenAI-compatible APIs.
The VLA does NOT directly control the robot — suggestions are validated
by the state machine and safety system.
"""

import base64
import json
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

from .vla_session import VLASession
from .vla_tools import VLA_TOOLS


@dataclass
class VLARecommendation:
    """Structured output from VLA reasoning."""
    action: str = "none"              # "pick" | "place" | "sort" | "ask" | "none" | "recover"
    target_label: str = ""            # which object/marker to manipulate
    target_id: str = ""               # marker ID or class name
    confidence: float = 0.0           # VLA's own confidence
    reasoning: str = ""               # VLA's explanation
    recovery_steps: list[str] = field(default_factory=list)
    question: str = ""                # clarification question (if action="ask")
    raw_response: dict = field(default_factory=dict)


class VLAClient:
    """Cloud VLA API client for vision-language reasoning."""

    # System prompt that defines the VLA's role and constraints
    SYSTEM_PROMPT = """You are a robotic arm vision-language-action (VLA) system controlling a
6-DOF desktop robot arm.

Your job is to look at camera images of a tabletop workspace and decide what action to take next.

Available information:
- Camera view of the workspace (image attached)
- Detected objects with their IDs, labels, and positions
- Current robot state

You have these tools:
- select_object: Pick which detected object to manipulate next (grasp, move, sort)
- request_clarification: Ask the user when the scene is ambiguous
- suggest_recovery: Suggest recovery steps after a failure

Rules:
1. You CANNOT directly move the robot — only suggest actions
2. Be specific about which object to pick
3. If multiple objects are detected, choose the most logical one
4. If the scene is empty or unclear, ask for clarification
5. Prioritize safety — if uncertain, ask rather than guess"""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.provider = cfg.get("provider", "anthropic")
        self.model = cfg.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.image_quality = cfg.get("image_quality", 85)
        self.image_max_side = cfg.get("image_max_side", 1024)

        # API key from environment
        self.api_key = os.environ.get(
            "ANTHROPIC_API_KEY",
            os.environ.get("OPENAI_API_KEY", "")
        )

        self._session: VLASession | None = None

    # ---- Public API ----

    async def reason(self, frame: np.ndarray, context: dict,
                     session: VLASession = None) -> VLARecommendation:
        """
        Send camera frame + context to cloud VLA, return recommendation.

        Args:
            frame: BGR image (numpy array)
            context: Dict with 'detections', 'robot_state', 'task', etc.
            session: VLASession for conversation continuity
        """
        if session:
            self._session = session
        if self._session is None:
            self._session = VLASession()

        # Encode frame
        image_b64 = self._encode_frame(frame)

        # Build user message
        user_text = self._build_context_text(context)
        self._session.add_user_message(user_text, image_b64)

        # Call API
        try:
            response = await self._call_api()
            recommendation = self._parse_response(response)
            recommendation.raw_response = response
            return recommendation
        except Exception as e:
            return VLARecommendation(
                action="none",
                reasoning=f"API error: {str(e)}",
                confidence=0.0,
            )

    def reason_sync(self, frame: np.ndarray, context: dict,
                    session: VLASession = None) -> VLARecommendation:
        """Synchronous version of reason()."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.reason(frame, context, session))

    # ---- Internals ----

    def _encode_frame(self, frame: np.ndarray) -> str:
        """Encode numpy BGR frame to base64 JPEG."""
        if frame is None:
            return ""
        # Resize if needed
        h, w = frame.shape[:2]
        if max(h, w) > self.image_max_side:
            scale = self.image_max_side / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        _, buffer = cv2.imencode('.jpg', frame,
                                 [cv2.IMWRITE_JPEG_QUALITY, self.image_quality])
        return base64.b64encode(buffer).decode('utf-8')

    def _build_context_text(self, context: dict) -> str:
        """Build text description of current context for the VLA."""
        parts = []

        task = context.get("task", "unknown")
        parts.append(f"Current task: {task}")

        detections = context.get("detections", [])
        if detections:
            parts.append(f"\nDetected objects ({len(detections)}):")
            for d in detections:
                label = getattr(d, 'label', str(d))
                conf = getattr(d, 'confidence', 0)
                pid = getattr(d, 'id', '?')
                pose = getattr(d, 'pose_camera', None)
                pose_str = ""
                if pose and hasattr(pose, 'position'):
                    p = pose.position
                    pose_str = f" at (x={p[0]:.3f}, y={p[1]:.3f}, z={p[2]:.3f})m"
                parts.append(f"  - [{pid}] {label} (conf={conf:.2f}){pose_str}")
        else:
            parts.append("\nNo objects detected in the scene.")

        robot = context.get("robot_state", {})
        if robot:
            parts.append(f"\nRobot state: {json.dumps(robot)}")

        error = context.get("error", "")
        if error:
            parts.append(f"\nError: {error}")

        return "\n".join(parts)

    async def _call_api(self) -> dict:
        """Call the appropriate API based on provider."""
        if self.provider == "anthropic":
            return await self._call_anthropic()
        elif self.provider == "openai":
            return await self._call_openai()
        elif self.provider == "deepseek":
            return await self._call_deepseek()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def _call_anthropic(self) -> dict:
        """Call Anthropic Claude API."""
        import aiohttp

        assert self._session is not None
        # Use system message as the first message
        system_msg = {
            "role": "system",
            "content": self.SYSTEM_PROMPT
        }
        messages = [system_msg] + self._session.get_messages()

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }

        # Add tools if available
        if VLA_TOOLS:
            payload["tools"] = VLA_TOOLS

        # Anthropic API key handling
        if not self.api_key:
            # Try to get from Claude Code's own auth
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with aiohttp.ClientSession() as http:
            async with http.post(
                "https://api.anthropic.com/v1/messages",
                json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"API error {resp.status}: {text}")
                return await resp.json()

    async def _call_openai(self) -> dict:
        """Call OpenAI-compatible API."""
        import aiohttp

        assert self._session is not None
        # Convert messages to OpenAI format
        oai_messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        for msg in self._session.get_messages():
            oai_messages.append(self._to_openai_format(msg))

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": oai_messages,
        }
        if VLA_TOOLS:
            payload["tools"] = [self._to_openai_tool(t) for t in VLA_TOOLS]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

        async with aiohttp.ClientSession() as http:
            async with http.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"OpenAI error {resp.status}: {text}")
                return await resp.json()

    async def _call_deepseek(self) -> dict:
        """Call DeepSeek API (OpenAI-compatible)."""
        self.model = self.model or "deepseek-chat"
        return await self._call_openai()  # DeepSeek uses OpenAI-compatible API

    def _parse_response(self, response: dict) -> VLARecommendation:
        """Parse API response into structured VLARecommendation."""
        if self.provider == "anthropic":
            return self._parse_anthropic(response)
        else:
            return self._parse_openai(response)

    def _parse_anthropic(self, response: dict) -> VLARecommendation:
        """Parse Anthropic response format."""
        content = response.get("content", [])

        text = ""
        tool_calls = []

        for block in content:
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        rec = VLARecommendation(reasoning=text)

        # Parse tool calls
        for tc in tool_calls:
            name = tc.get("name", "")
            inp = tc.get("input", {})

            if name == "select_object":
                rec.action = "pick"
                rec.target_label = inp.get("object_label", "")
                rec.reasoning = inp.get("reasoning", text)
                rec.confidence = 0.8
            elif name == "request_clarification":
                rec.action = "ask"
                rec.question = inp.get("question", "")
            elif name == "suggest_recovery":
                rec.action = "recover"
                rec.recovery_steps = inp.get("steps", [])
                rec.reasoning = inp.get("strategy", "")

        # If no tool call, infer from text
        if not tool_calls and text:
            text_lower = text.lower()
            if "pick" in text_lower or "grasp" in text_lower:
                rec.action = "pick"
            elif "place" in text_lower:
                rec.action = "place"
            elif "sort" in text_lower:
                rec.action = "sort"
            elif "?" in text or "clarif" in text_lower:
                rec.action = "ask"

        return rec

    def _parse_openai(self, response: dict) -> VLARecommendation:
        """Parse OpenAI/DeepSeek response format."""
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})

        text = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        rec = VLARecommendation(reasoning=text or "")

        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            try:
                inp = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                inp = {}

            if name == "select_object":
                rec.action = "pick"
                rec.target_label = inp.get("object_label", "")
                rec.reasoning = inp.get("reasoning", "")
                rec.confidence = 0.8
            elif name == "request_clarification":
                rec.action = "ask"
                rec.question = inp.get("question", "")
            elif name == "suggest_recovery":
                rec.action = "recover"
                rec.recovery_steps = inp.get("steps", [])

        return rec

    # ---- Format conversion helpers ----

    def _to_openai_format(self, msg: dict) -> dict:
        """Convert Anthropic-format message to OpenAI format."""
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            return {"role": role, "content": content}

        # Multi-part content
        oai_content = []
        for block in content:
            if block.get("type") == "text":
                oai_content.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "image":
                b64 = block.get("source", {}).get("data", "")
                oai_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })

        return {"role": role, "content": oai_content}

    def _to_openai_tool(self, tool: dict) -> dict:
        """Convert Anthropic tool definition to OpenAI format."""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            }
        }
