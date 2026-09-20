# ThirdHand Vision LLM Skill Design

## Goal

Add read-only visual question answering to the active ThirdHand Language chain. The text controller remains the default brain (`deepseek-v4-pro`); it may call a dedicated vision Skill (`deepseek-flash`) when the current request requires the live camera view.

## Scope

Phase A only:

- Answer questions such as “看看前面有什么” and visual follow-ups.
- Read one fresh RGB JPEG from the already-running XVisio MJPEG service.
- Return natural-language descriptions in the 9983 interaction panel.
- Emit safe diagnostic events to the existing 9983 communication log.

Out of scope:

- Target selection, coordinates, depth reasoning, grasp planning, trajectory generation, or robot execution.
- Opening `/dev/video*`, starting/restarting XVisio, changing calibration, or changing the detector.
- Continuous video upload or background visual analysis.

## Architecture

```text
9983 text/voice
    -> 3004 VoiceBridge
    -> ThirdHandController (TEXT_LLM_MODEL=deepseek-v4-pro)
         |-- ordinary response / motion candidate
         `-- tool call: vision_inspect_scene
               -> VisionInspectSceneSkill
               -> GET existing 3100 /camera/xvisio/raw MJPEG
               -> save bounded local debug JPEG
               -> Anthropic-compatible image request
                  (VISION_LLM_MODEL=deepseek-flash)
               -> structured observation
         -> tool_result returned to ThirdHandController
         -> final natural-language answer
```

The existing motion tools remain confirmation-gated candidates. The vision Skill never emits a robot action and has no Robot Service or CAN dependency.

## Naming ruling

The agreed conceptual name was `vision.inspect_scene@1`. The repository manifest schema only permits lowercase letters, digits, dots, and hyphens. Therefore:

- Manifest ID: `vision.inspect-scene`
- Manifest version: `1.0.0`
- Anthropic tool name: `vision_inspect_scene`
- Directory: `skills/vision/inspect-scene/`

This preserves the meaning and major version while keeping the repository contract valid.

## Controller

`ClaudeAgent` is refactored into `ThirdHandController`, with a temporary `ClaudeAgent = ThirdHandController` compatibility alias so the existing VoiceBridge factory and tests keep working.

The controller:

- Reads `TEXT_LLM_MODEL`, default `deepseek-v4-pro`.
- Offers motion candidate tools plus `vision_inspect_scene` to the text model.
- Lets the model decide when vision is needed; there is no fixed keyword router.
- Honors explicit user overrides in the system prompt: “重新看一下” requires a fresh visual call, while “不要看摄像头/只根据刚才结果” forbids a new frame.
- Executes at most one visual Skill invocation per user turn and at most two text-model calls per turn.
- Sends the Skill result back as `tool_result`, then asks the text model for the final response.
- Retains a bounded prior visual summary across turns and does not clear it when motion semantics appear.
- Never executes motion tools; they remain entries in `actions` for existing confirmation handling.

## Vision Skill contract

Input:

```json
{
  "question": "前面有什么？",
  "priorVisualSummary": null,
  "language": "zh"
}
```

Successful internal result:

```json
{
  "status": "completed",
  "summary": "前方桌面上有一个红色罐装饮料。",
  "frame": {
    "frameId": "xvisio-1234",
    "sequence": 1234,
    "capturedAt": "2026-09-20T19:30:00.000+08:00",
    "frameAgeMs": 42,
    "timestampSource": "stream-header",
    "widthPx": null,
    "heightPx": null
  },
  "model": "deepseek-flash"
}
```

The 9983 chat receives only the final natural-language answer. Internal model names, timing, JSON, frame IDs, and confidence data go only to trace/log events.

## Frame acquisition and freshness

- Default stream: `http://127.0.0.1:3100/camera/xvisio/raw`.
- The Skill only subscribes to the existing MJPEG stream. It never opens a camera device or starts a service.
- A newly delivered MJPEG part must include a positive `X-ThirdHand-Sequence`; the sequence must advance relative to the Skill’s previous call.
- If the stream later exposes an acquisition timestamp header, it is used directly. With the current stream, delivery time is recorded as an explicit `mjpeg-delivery` fallback; freshness is additionally guaranteed by waiting for a newly published sequence.
- Visual-QA budget: `VISION_QA_MAX_FRAME_AGE_MS=2000`.
- One quick retry is allowed for stream timeout, transient provider errors, or a repeated sequence. Authentication, invalid model, and invalid request errors fail immediately.
- After failure, the user receives an explicit unavailable message. No cached image is presented as current.

Future reserved budgets remain separate: target selection 500 ms and motion verification 300 ms. Phase A does not implement those workflows.

## Image retention

Debug images are stored under:

`skills/vision/inspect-scene/test_pics/`

Rules:

- Raw RGB JPEG only in Phase A.
- Maximum 20 files.
- Maximum age 24 hours.
- Cleanup runs after every successful save.
- JPEG files are ignored by Git; only `.gitignore` is tracked.
- No Base64 image or image bytes are written to application logs.

## Model access

DeepSeek’s official API supports `deepseek-flash` image input through its Anthropic-compatible endpoint. The Skill reuses the same resolved DeepSeek base URL and credential as the text controller. It does not require a second key unless the existing credential lacks vision-model permission.

Configuration:

```env
TEXT_LLM_MODEL=deepseek-v4-pro
VISION_LLM_MODEL=deepseek-flash
VISION_STREAM_URL=http://127.0.0.1:3100/camera/xvisio/raw
VISION_QA_MAX_FRAME_AGE_MS=2000
```

There is no silent fallback from Flash to Pro because Pro does not support image input.

## Trust and response rules

- Describe only visible evidence.
- State uncertainty for blur, occlusion, unreadable text, or ambiguous identity.
- Confirm brand, text, or model only when visibly legible.
- Do not invent unseen objects.
- Visual output is observation evidence, never an execution instruction.
- Future grasp requests may use it only as a candidate/verification input and must keep the existing confirmation boundary.

## Trace events

VoiceBridge emits `agent.trace` events after understanding completes. Allowed fields are stage, status, model label, frame ID/sequence, frame age, retry count, and elapsed milliseconds. The frontend forwards these lines to the existing 9983 communication log through a callback owned by `main.js`.

Forbidden trace content: API keys, authorization headers, request bodies, Base64, raw model prompts, image bytes, or full provider exceptions that may contain credentials.

## Failure behavior

- Camera/stream unavailable: retry once, then explicit visual-unavailable answer.
- Frozen/repeated frame: retry once, then explicit stale/frozen answer.
- Flash authentication/model/configuration error: fail immediately and log a sanitized code.
- Flash transient/network error: retry once, then explicit model-unavailable answer.
- Pro never substitutes for Flash.
- No robot action is created from a visual failure.

## Validation

Automated tests cover MJPEG parsing, new-sequence enforcement, 2-second freshness behavior, retention cleanup, vision request format, retry classification, controller tool loop, no-motion boundary, visual-context retention, model environment variables, sanitized trace events, and 9983 log rendering.

Live acceptance is read-only:

1. Confirm 3100 and 3004 health without restarting them.
2. Invoke the Skill against the current raw stream.
3. Verify one JPEG is retained and no more than 20 remain.
4. Verify Flash returns a scene description using the existing credential.
5. Submit “看看前面有什么” through 9983 and verify natural language plus safe communication-log entries.
6. Do not confirm or execute any motion candidate during acceptance.

## Existing baseline notes

- Development worktree: `/home/nieqingcao/ThirdHand/worktrees/vision-llm-skill`.
- Base commit: `00ad838` (reviewed Language CI baseline).
- Existing unrelated Node baseline failure: `tests/node/web/server.test.js` expects 503 but receives 200.
- Python test dependencies are not fully installed in the production runtime; a worktree-local test dependency directory is permitted and remains untracked.
