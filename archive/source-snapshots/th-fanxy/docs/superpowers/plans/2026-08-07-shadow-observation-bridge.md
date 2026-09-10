# Shadow Observation Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert existing checked ThirdHand vision events into immutable runtime observations and provide an optional local-files-only Grounding DINO proposal adapter.

**Architecture:** New code lives in `orchestration/shadow` and imports only public runtime contracts. Vision producers remain untouched. Strict JSON/JSONL sources feed a canonical adapter; open-vocabulary proposals are optional and never actionable without REMIND identity plus calibrated depth.

**Tech Stack:** Python 3.10+, Pydantic v2, standard-library JSON/path/hash/time, optional Pillow/Torch/Transformers, pytest, Ruff.

## Global Constraints

- Do not modify `web-control`, `packages/thirdhand-vision-sdk`, vision configs, calibration, or data files.
- No camera, robot, CAN, subprocess, or network access.
- Grounding DINO loads only an explicit local model directory with `local_files_only=True`.
- `robot_execution_enabled` must be exactly `false`.
- An open-vocabulary proposal cannot set `ObjectState.actionable=True`.

---

### Task 1: Strict Vision Event Models and Adapter

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/__init__.py`
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/vision_events.py`
- Test: `tests/orchestration/shadow/test_vision_events.py`

**Interfaces:**
- Produces: `VisionEvent`, `VisionTarget`, `VisionPose`, `VisionIdentityMemory`.
- Produces: `VisionEventAdapter(episode_id: str).to_observation(event: VisionEvent, robot: RobotState | None = None) -> Observation`.

- [ ] **Step 1: Write failing strict-schema and conversion tests**

```python
def test_checked_event_becomes_actionable_runtime_object():
    event = accepted_bottle_event(sequence=7)
    observation = VisionEventAdapter("episode-vision-1").to_observation(event)
    target = observation.objects[0]
    assert target.identity_id == 2
    assert target.actionable is True
    assert target.depth_valid is True
    model_ready = next(item for item in observation.facts if item.name == "vision_model_ready")
    assert model_ready.value is True


def test_unsafe_or_unvalidated_event_fails_closed():
    event = accepted_bottle_event(robot_execution_enabled=True)
    with pytest.raises(ValidationError):
        VisionEvent.model_validate(event)
```

- [ ] **Step 2: Run tests and confirm missing module failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_vision_events.py`

Expected: FAIL because `orchestration.shadow` does not exist.

- [ ] **Step 3: Implement frozen event models and deterministic evidence IDs**

Use `ConfigDict(frozen=True, extra="forbid")`, finite-number validators, exact
`type="detection_result"`, `robot_execution_enabled: Literal[False]`, nonnegative sequences, and
`sha256:` content IDs generated from canonical JSON when absent. Map upstream blockers and reasons
to facts; require confirmed identity, accepted task checkpoint, actionable upstream state, valid
pose calibration ID, and positive registered depth points before the runtime object is actionable.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_vision_events.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow tests/orchestration/shadow
git commit -m "feat(orchestration): bridge checked vision events"
```

---

### Task 2: Finite Replay and Read-Only Latest-File Sources

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/vision_sources.py`
- Test: `tests/orchestration/shadow/test_vision_sources.py`

**Interfaces:**
- Consumes: `VisionEventAdapter`.
- Produces: `VisionJsonlReplaySource(path: Path, adapter: VisionEventAdapter)`.
- Produces: `LatestVisionEventSource(path: Path, adapter: VisionEventAdapter, timeout_s: float, poll_s: float)`.

- [ ] **Step 1: Write failing source tests**

Test strict sequence increase, malformed JSON rejection, remote/symlink/directory rejection,
stable-read behavior, timeout, and conversion to the runtime `ObservationSource` protocol.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_vision_sources.py`

Expected: FAIL because `vision_sources` is missing.

- [ ] **Step 3: Implement bounded local sources**

Replay reads a finite JSONL file once. Latest-file source reads the same regular file twice and
accepts it only when size, mtime, and bytes are stable; it uses `time.monotonic()` with a bounded
timeout and never opens a device or URL. Both reject a sequence not strictly newer than
`after_sequence`.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_vision_sources.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/vision_sources.py tests/orchestration/shadow/test_vision_sources.py
git commit -m "feat(orchestration): add read-only vision sources"
```

---

### Task 3: Local-Only Grounding DINO Candidate Provider

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/grounding_dino.py`
- Create: `scripts/orchestration/check_grounding_dino.py`
- Test: `tests/orchestration/shadow/test_grounding_dino.py`

**Interfaces:**
- Produces: `OpenVocabCandidate`, `GroundingDinoConfig`, `GroundingDinoBackend` protocol.
- Produces: `GroundingDinoCandidateProvider.propose(image_path: Path, labels: tuple[str, ...]) -> tuple[OpenVocabCandidate, ...]`.

- [ ] **Step 1: Write failing provider tests**

Test normalized labels, finite boxes/scores, threshold filtering, local regular image checks,
dependency-unavailable errors, and the invariant `actionable=False` for every proposal. Inject a
fake backend so CI performs no model load.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_grounding_dino.py`

Expected: FAIL because `grounding_dino` is missing.

- [ ] **Step 3: Implement the provider and lazy Hugging Face backend**

The default backend imports dependencies only inside `load()`, rejects non-local model paths, calls
`AutoProcessor.from_pretrained(path, local_files_only=True)` and
`AutoModelForZeroShotObjectDetection.from_pretrained(path, local_files_only=True)`, sets eval mode,
and uses `post_process_grounded_object_detection`. The smoke CLI emits canonical JSON with
`AVAILABLE` or `UNAVAILABLE` and exits without downloading.

- [ ] **Step 4: Run tests, isolation check, and commit**

Run:

```bash
.venv/bin/pytest -q tests/orchestration/shadow/test_grounding_dino.py
.venv/bin/ruff check src/uiea_thirdhand_vla/orchestration/shadow scripts/orchestration tests/orchestration/shadow
```

Expected: PASS and no lint errors.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/grounding_dino.py scripts/orchestration/check_grounding_dino.py tests/orchestration/shadow/test_grounding_dino.py
git commit -m "feat(orchestration): add local open-vocabulary fallback"
```

---

### Task 4: Bridge Fixture and CLI

**Files:**
- Create: `tests/fixtures/orchestration/vision/accepted_bottle.jsonl`
- Create: `scripts/orchestration/replay_vision_events.py`
- Test: `tests/orchestration/shadow/test_vision_bridge_cli.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/shadow/__init__.py`

**Interfaces:**
- CLI: `--events`, `--output`, `--episode-id`.

- [ ] **Step 1: Write a failing end-to-end CLI test**

Assert the checked fixture produces ordered runtime observations, content-addressed evidence,
`robot_execution_enabled=false`, and no world-changing output.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_vision_bridge_cli.py`

Expected: FAIL because the fixture and CLI are absent.

- [ ] **Step 3: Add the fixture and local conversion CLI**

The CLI reads only the provided JSONL file, writes canonical JSONL observations, refuses an output
directory or symlink, and prints a summary containing count, first/last sequence, actionable count,
and `robot_execution_enabled=false`.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow scripts/orchestration/replay_vision_events.py tests/orchestration/shadow tests/fixtures/orchestration/vision
git commit -m "feat(orchestration): complete shadow observation bridge"
```
