# ThirdHand Vision LLM Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `vision.inspect-scene` tool chain to the 3004 ThirdHand controller using DeepSeek Pro for orchestration and DeepSeek Flash for image understanding.

**Architecture:** Refactor the current `ClaudeAgent` into a backward-compatible `ThirdHandController` that can execute one internal read-only vision tool and feed its structured result back to the text model. The Skill reads one fresh JPEG from the existing 3100 MJPEG stream, retains a bounded debug history, calls Flash through the existing Anthropic-compatible provider, and exposes safe trace events to the 9983 communication log.

**Tech Stack:** Python 3.11, Anthropic Python SDK, stdlib `urllib`, JSON Schema, Node.js 24 frontend tests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-thirdhand-vision-llm-design.md`

## Global Constraints

- Phase A is visual question answering only; no target selection, coordinates, grasping, trajectory generation, or robot execution.
- Never open `/dev/video*`, start/restart XVisio, or modify calibration/detection.
- `TEXT_LLM_MODEL=deepseek-v4-pro`; `VISION_LLM_MODEL=deepseek-flash`; no silent model fallback.
- Read only `http://127.0.0.1:3100/camera/xvisio/raw` by default.
- Fresh visual question budget is 2000 ms and requires an advancing stream sequence.
- Retry a transient capture/provider failure once, then fail explicitly.
- Keep at most 20 JPEGs for at most 24 hours under `skills/vision/inspect-scene/test_pics/`.
- 9983 conversation output is natural language only; safe technical details go to communication logs.
- Motion tools remain candidate-only and confirmation-gated.
- Do not edit, restart, or deploy the active production tree while implementing in the worktree.

## Review Focus

- A stream that returns a repeated sequence must retry once and then fail as frozen, never reuse it as current.
- Provider authentication/model errors must not retry or fall back to Pro.
- A visual tool result must return to the text model without being emitted as a robot action.
- Trace serialization must never include image bytes, Base64, keys, authorization headers, or raw provider payloads.
- Visual context must survive a later motion request while the motion request remains confirmation-gated.

---

### Task 1: Skill contract, MJPEG capture, and bounded image retention

**Files:**
- Create: `skills/vision/inspect-scene/SKILL.md`
- Create: `skills/vision/inspect-scene/manifest.yaml`
- Create: `skills/vision/inspect-scene/schemas/input.json`
- Create: `skills/vision/inspect-scene/schemas/result.json`
- Create: `skills/vision/inspect-scene/src/worker.py`
- Create: `skills/vision/inspect-scene/test_pics/.gitignore`
- Create: `tests/python/speech_service/test_inspect_scene_skill.py`
- Modify: `tests/node/skill_registry/registry.test.js`

**Interfaces:**
- Produces: `CapturedFrame`, `MjpegFrameSource.next_frame(previous_sequence)`, `ImageRetention.save(jpeg, sequence)`, and a discoverable `vision.inspect-scene` manifest.
- Consumes: current 3100 MJPEG part headers, especially `Content-Length` and `X-ThirdHand-Sequence`.

- [ ] **Step 1: Write failing manifest-discovery and Python capture/retention tests**

Tests must assert valid discovery, JPEG extraction, positive/advancing sequence, repeated-sequence failure, timeout sanitization, 20-file limit, and 24-hour expiry.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
NODE_PATH=/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/node_modules node --test tests/node/skill_registry/registry.test.js
PYTHONPATH=.testdeps:services/speech/src python -m pytest -q tests/python/speech_service/test_inspect_scene_skill.py
```

Expected: failures because the Skill manifest and worker do not exist.

- [ ] **Step 3: Add the manifest, schemas, frame source, and retention implementation**

`worker.py` must use stdlib networking, cap accepted JPEG size, sanitize exceptions, require a positive sequence, support optional acquisition timestamp headers, and mark delivery-time fallback explicitly.

- [ ] **Step 4: Run Task 1 tests and verify GREEN**

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit exact Task 1 paths**

```bash
git add skills/vision/inspect-scene tests/python/speech_service/test_inspect_scene_skill.py tests/node/skill_registry/registry.test.js
git commit -m "feat: add read-only scene inspection skill"
```

### Task 2: Flash image analysis, retry policy, and safe result contract

**Files:**
- Modify: `skills/vision/inspect-scene/src/worker.py`
- Modify: `tests/python/speech_service/test_inspect_scene_skill.py`

**Interfaces:**
- Consumes: `CapturedFrame` and the resolved Anthropic-compatible client.
- Produces: `InspectSceneSkill.invoke(question, prior_visual_summary, language) -> dict` and `InspectSceneError(code, user_message, retryable)`.

- [ ] **Step 1: Add failing tests for Anthropic image blocks and retry classification**

Assert model `deepseek-flash`, JPEG Base64 source block, question/prior summary only, one retry for transient capture/provider errors, zero retry for auth/model errors, no Pro fallback, and sanitized trace output.

- [ ] **Step 2: Run the focused test and verify RED**

Expected: `InspectSceneSkill` is missing.

- [ ] **Step 3: Implement the minimal Flash client flow**

Use the existing client object; do not create or log a second key. Save the captured JPEG, clean retention, call `messages.create`, extract text, and return the structured result and safe trace list.

- [ ] **Step 4: Run Task 2 tests and verify GREEN**

Expected: all Skill tests pass.

- [ ] **Step 5: Commit exact Task 2 paths**

```bash
git add skills/vision/inspect-scene/src/worker.py tests/python/speech_service/test_inspect_scene_skill.py
git commit -m "feat: analyze fresh scene frames with DeepSeek Flash"
```

### Task 3: ThirdHand controller and internal tool loop

**Files:**
- Modify: `services/speech/src/voice_agent.py`
- Create: `tests/python/speech_service/test_thirdhand_controller.py`
- Modify: `services/speech/src/test_language_contract.py`

**Interfaces:**
- Consumes: `InspectSceneSkill.invoke(...)`.
- Produces: `ThirdHandController.chat(user_text) -> {text, actions, trace}` and compatibility alias `ClaudeAgent`.

- [ ] **Step 1: Write failing controller tests**

Cover model defaults, ordinary one-call answers, visual tool call -> Skill -> tool_result -> final answer, one-visual-call limit, explicit Skill failure, visual-summary persistence across motion turns, and motion tools staying in `actions` without execution.

- [ ] **Step 2: Run focused controller tests and verify RED**

Expected: `ThirdHandController` and `vision_inspect_scene` are absent.

- [ ] **Step 3: Implement controller refactor and loader**

Load the Python worker from the manifest directory, share the resolved Anthropic client, read `TEXT_LLM_MODEL` and `VISION_LLM_MODEL`, add the visual tool schema and prompt rules, and perform at most one tool-result continuation call.

- [ ] **Step 4: Run controller and Language contract tests and verify GREEN**

Expected: focused tests pass; existing candidate semantics remain unchanged.

- [ ] **Step 5: Commit exact Task 3 paths**

```bash
git add services/speech/src/voice_agent.py services/speech/src/test_language_contract.py tests/python/speech_service/test_thirdhand_controller.py
git commit -m "refactor: add ThirdHand controller skill loop"
```

### Task 4: VoiceBridge trace protocol and 9983 communication log

**Files:**
- Modify: `services/speech/src/voice_bridge.py`
- Modify: `services/speech/src/test_voice_bridge.py`
- Modify: `apps/web/public/js/voice-control.js`
- Modify: `apps/web/public/js/main.js`
- Create: `tests/node/web/agent-trace.test.js`

**Interfaces:**
- Consumes: `chat()` result `trace` list.
- Produces: `agent.trace` Voice Protocol event and `VoiceControl.onAgentTrace(payload)` callback into `ui._log(...)`.

- [ ] **Step 1: Write failing Python and Node tests**

Assert traces are sent before `session.completed`, chat still receives only natural language, log callback displays safe fields, and unsafe fields are rejected or omitted.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: no `agent.trace` event handling exists.

- [ ] **Step 3: Implement sanitized trace propagation and UI logging**

Use a strict allow-list. Do not serialize request bodies, exception reprs, image data, or credentials.

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: Python protocol and Node UI trace tests pass.

- [ ] **Step 5: Commit exact Task 4 paths**

```bash
git add services/speech/src/voice_bridge.py services/speech/src/test_voice_bridge.py apps/web/public/js/voice-control.js apps/web/public/js/main.js tests/node/web/agent-trace.test.js
git commit -m "feat: show safe agent traces in communication log"
```

### Task 5: Runtime configuration, documentation, and integration verification

**Files:**
- Modify: `.env.example`
- Modify: `configs/runtime/default.json`
- Modify: `configs/runtime/manual-control.json`
- Modify: `services/speech/README.md`
- Modify: `tests/node/launcher/runtime-profiles.test.js`

**Interfaces:**
- Consumes: controller/Skill environment variables.
- Produces: launcher defaults and operator documentation.

- [ ] **Step 1: Add failing configuration tests**

Assert both profiles configure `TEXT_LLM_MODEL=deepseek-v4-pro`, `VISION_LLM_MODEL=deepseek-flash`, loopback raw stream URL, and `VISION_QA_MAX_FRAME_AGE_MS=2000`.

- [ ] **Step 2: Run config tests and verify RED**

Expected: required variables are absent.

- [ ] **Step 3: Add configuration and operator documentation**

Document shared credential behavior, no silent fallback, the read-only camera boundary, retention, and safe live acceptance.

- [ ] **Step 4: Run focused suites**

```bash
node --test tests/node/skill_registry/registry.test.js tests/node/launcher/runtime-profiles.test.js tests/node/web/agent-trace.test.js
python -m pytest -q tests/python/speech_service/test_inspect_scene_skill.py tests/python/speech_service/test_thirdhand_controller.py services/speech/src/test_language_contract.py services/speech/src/test_voice_bridge.py
```

Expected: all feature-focused tests pass.

- [ ] **Step 5: Run broader regression suites and record the known baseline**

Run the project Node and Python suites. Expected: feature tests pass; any remaining `tests/node/web/server.test.js` 200-vs-503 failure must match the recorded pre-feature baseline exactly.

- [ ] **Step 6: Perform read-only live checks without restarting services**

Check active PID ownership, 3100 raw-frame delivery, current credential/model support, and a direct Skill invocation. If the current credential is rejected specifically for `deepseek-flash`, stop and request a new API key from the user.

- [ ] **Step 7: Commit exact Task 5 paths**

```bash
git add .env.example configs/runtime/default.json configs/runtime/manual-control.json services/speech/README.md tests/node/launcher/runtime-profiles.test.js
git commit -m "docs: configure ThirdHand text and vision models"
```
