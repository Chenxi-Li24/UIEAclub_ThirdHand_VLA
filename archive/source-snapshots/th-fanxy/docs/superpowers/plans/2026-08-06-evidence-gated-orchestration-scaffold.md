# Evidence-Gated Orchestration Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable fake-only orchestration scaffold that gates pick-place progress on fresh effect, handoff, and task-goal evidence.

**Architecture:** A small package beside the legacy FSM provides frozen contracts, a YAML Skill registry, replay/fake ports, deterministic monitors, bounded recovery, trace/metrics, and one synchronous supervisor. It has no Startouch/CAN/network adapter and leaves the legacy state machine and vision stack unchanged.

**Tech Stack:** Python 3.10+, Pydantic v2, PyYAML, standard-library JSON/hash/path handling, pytest, Ruff.

## Global Constraints

- The only executor kind is `fake`.
- A completed receipt never proves effect, handoff readiness, or task success.
- `UNKNOWN` never advances the plan.
- `REOBSERVE` obtains newer evidence without dispatching again.
- The final state is `DONE` only after the plan-level task goal passes.
- No runtime file imports or invokes Startouch, CAN, robot, gripper, ROS, subprocess, socket, HTTP, or camera hardware.
- Existing state-machine, web-control, and vision files remain unchanged.

## File Structure

- `src/uiea_thirdhand_vla/orchestration/runtime/models.py`: frozen contracts and enums.
- `src/uiea_thirdhand_vla/orchestration/runtime/registry.py`: exact-version YAML Skill registry.
- `src/uiea_thirdhand_vla/orchestration/runtime/ports.py`: observation/executor protocols and errors.
- `src/uiea_thirdhand_vla/orchestration/runtime/adapters.py`: fake executor and ordered replay source.
- `src/uiea_thirdhand_vla/orchestration/runtime/monitors.py`: required deterministic predicates.
- `src/uiea_thirdhand_vla/orchestration/runtime/recovery.py`: bounded re-observe/retry/stop table.
- `src/uiea_thirdhand_vla/orchestration/runtime/trace.py`: in-memory and JSONL event sinks.
- `src/uiea_thirdhand_vla/orchestration/runtime/metrics.py`: False Advance Rate.
- `src/uiea_thirdhand_vla/orchestration/runtime/supervisor.py`: evidence-gated loop.
- `configs/skills/tabletop_pick.yaml`, `tabletop_place.yaml`: fake-only contracts.
- `scripts/orchestration/run_shadow_replay.py`: local fixture runner.
- `tests/orchestration/runtime/`: focused scaffold tests.
- `tests/fixtures/orchestration/pick_place_success.json`: runnable replay.

---

### Task 1: Contracts and Skill Registry

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/__init__.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/models.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/registry.py`
- Create: `configs/skills/tabletop_pick.yaml`
- Create: `configs/skills/tabletop_place.yaml`
- Create: `tests/orchestration/runtime/test_contracts_registry.py`

**Interfaces:**
- Enums: `Verdict`, `Stage`, `ReceiptStatus`, `RuntimeState`, `PredicateKind`, `RecoveryAction`.
- Models: `EvidenceRef`, `ObjectState`, `RobotState`, `Fact`, `Observation`, `Argument`, `Predicate`, `HandoffRule`, `RecoveryPolicy`, `SkillContract`, `SkillCall`, `Plan`, `CommandRequest`, `CommandReceipt`, `PredicateResult`, `StageResult`, `Budget`, `TraceEvent`, `GroundTruth`, `RunResult`, `RunMetrics`, `ReplayBundle`.
- Functions/classes: `load_skill_contract(path)`, `SkillRegistry.from_paths(paths)`, `resolve(skill_id, version)`, `validate_call(call)`.

- [ ] **Step 1: Write failing strict-contract and registry tests**

```python
def test_checked_in_skills_are_fake_only_and_exact_version():
    registry = SkillRegistry.from_paths((PICK_PATH, PLACE_PATH))
    pick = registry.resolve("tabletop.pick", "0.1.0")
    assert pick.executor_kind == "fake"
    assert pick.handoff_rules[0].next_skill_id == "tabletop.place"
    with pytest.raises(RegistryError, match="version"):
        registry.resolve("tabletop.pick", "0.2.0")


def test_contracts_are_frozen_and_reject_unknown_fields():
    observation = valid_observation()
    with pytest.raises(ValidationError):
        observation.sequence = 99
    with pytest.raises(ValidationError):
        Observation.model_validate({**observation.model_dump(), "unexpected": True})
```

- [ ] **Step 2: Run the tests and verify collection fails**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_contracts_registry.py`

Expected: FAIL because the runtime package does not exist.

- [ ] **Step 3: Implement minimal frozen models and tri-state aggregation**

```python
class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class StageResult(FrozenModel):
    stage: Stage
    verdict: Verdict
    results: tuple[PredicateResult, ...]

    @classmethod
    def aggregate(cls, stage: Stage, results: tuple[PredicateResult, ...]) -> "StageResult":
        if not results:
            raise ValueError("verification stage cannot be empty")
        verdict = (
            Verdict.FAIL if any(item.verdict is Verdict.FAIL for item in results)
            else Verdict.PASS if all(item.verdict is Verdict.PASS for item in results)
            else Verdict.UNKNOWN
        )
        return cls(stage=stage, verdict=verdict, results=results)
```

Every float validator rejects NaN/infinity. `EvidenceRef` requires `sha256:` plus 64 lowercase hex digits. Pose-like values carry frame, unit, monotonic timestamp, and calibration ID when present. Facts are tuples of frozen `Fact` records, not mutable dictionaries.

- [ ] **Step 4: Add fake-only pick/place YAML and strict loader**

Pick preconditions: fresh, visible, unambiguous, actionable, valid depth, empty gripper. Pick effects: requested object held and `object_follows_gripper=true`. Pick-to-place handoff: same object held and `place_ready=true`. Place preconditions: object held and `destination_known=true`. Place effects: object inside bound region and gripper empty. Each contract allows two re-observations, one retry, and two logical world changes.

```python
def load_skill_contract(path: Path) -> SkillContract:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryError("skill contract must contain a mapping")
    try:
        contract = SkillContract.model_validate(payload)
    except ValidationError as exc:
        raise RegistryError(f"invalid skill contract: {exc}") from exc
    if contract.executor_kind != "fake":
        raise RegistryError("only fake executor contracts are allowed")
    return contract
```

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_contracts_registry.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime configs/skills tests/orchestration/runtime
git commit -m "feat(orchestration): add runtime contracts and registry"
```

---

### Task 2: Fake/Replay Ports, Monitors, and Recovery

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/ports.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/adapters.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/monitors.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/recovery.py`
- Create: `tests/orchestration/runtime/test_runtime_units.py`

**Interfaces:**
- `ObservationSource.next_observation(after_sequence) -> Observation`.
- `Executor.kind -> str`; `Executor.execute(request) -> CommandReceipt`.
- `ReplayObservationSource`, `FakeExecutor`.
- `evaluate(predicate, call, observation, previous, now_ns) -> PredicateResult`.
- `verify(stage, predicates, call, observation, previous, now_ns) -> StageResult`.
- `RecoveryManager.decide(failure_code, budget, policy) -> tuple[RecoveryAction, Budget, str]`.

- [ ] **Step 1: Write failing unit tests**

```python
def test_replay_requires_strictly_newer_observation():
    source = ReplayObservationSource((observation(1), observation(2)))
    assert source.next_observation(None).sequence == 1
    assert source.next_observation(1).sequence == 2
    with pytest.raises(ObservationUnavailable):
        source.next_observation(2)


def test_missing_world_fact_is_unknown_not_pass():
    result = evaluate(
        Predicate(predicate_id="held", kind="robot_holds_object", object_arg="target_id"),
        pick_call(),
        observation_without_robot(),
        None,
        100,
    )
    assert result.verdict is Verdict.UNKNOWN


def test_reobserve_consumes_only_reobserve_budget():
    action, after, _ = RecoveryManager().decide(
        "effect_unknown",
        Budget(reobservations=1, retries=1, world_changes=1),
        recovery_policy(),
    )
    assert action is RecoveryAction.REOBSERVE
    assert after == Budget(reobservations=0, retries=1, world_changes=1)
```

- [ ] **Step 2: Run tests and verify missing modules fail**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_runtime_units.py`

Expected: FAIL.

- [ ] **Step 3: Implement finite replay and scripted fake execution**

```python
class FakeExecutor:
    kind = "fake"

    def __init__(self, statuses: tuple[ReceiptStatus, ...]) -> None:
        self._statuses = iter(statuses)
        self.dispatch_count = 0

    def execute(self, request: CommandRequest) -> CommandReceipt:
        try:
            status = next(self._statuses)
        except StopIteration as exc:
            raise ExecutorUnavailable("fake receipt script exhausted") from exc
        self.dispatch_count += 1
        return CommandReceipt.from_request(request, status)
```

- [ ] **Step 4: Implement only the predicates needed by pick/place**

Support `observation_fresh`, `object_visible`, `object_unambiguous`, `object_actionable`, `object_depth_valid`, `robot_holds_object`, `robot_holds_nothing`, `object_in_region`, and `fact_equals`. Explicit false returns `FAIL`; unavailable data returns `UNKNOWN`; every result includes snapshot/evidence references.

- [ ] **Step 5: Implement bounded recovery table**

`*_unknown` chooses `REOBSERVE` while available. `execution_failed`, `execution_timeout`, and `effect_fail` choose `RETRY_SAME_FAKE` only when listed in the Skill policy and both retry/world-change budget remain. Everything else chooses `STOP`. Inputs remain immutable.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_runtime_units.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime tests/orchestration/runtime
git commit -m "feat(orchestration): add offline ports and evidence checks"
```

---

### Task 3: Trace, Metrics, and Evidence-Gated Supervisor

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/trace.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/metrics.py`
- Create: `src/uiea_thirdhand_vla/orchestration/runtime/supervisor.py`
- Create: `tests/orchestration/runtime/test_supervisor.py`

**Interfaces:**
- `MemoryTrace`, `JsonlTrace`, `canonical_json`, `content_id`.
- `compute_metrics(events, ground_truth) -> RunMetrics`.
- `EvidenceGatedSupervisor.run(plan) -> RunResult`.

- [ ] **Step 1: Write failing core behavior tests**

```python
def test_success_requires_effect_handoff_and_task_goal(runtime):
    result = runtime(success_observations(), completed_executor()).run(pick_place_plan())
    assert result.final_state is RuntimeState.DONE
    kinds = [event.event_type for event in result.events]
    assert kinds.index("effect_result") < kinds.index("handoff_result")
    assert kinds.index("handoff_result") < kinds.index("step_advanced")
    assert kinds.index("task_goal_result") < kinds.index("episode_done")


def test_completed_receipt_with_failed_effect_never_advances(runtime):
    executor = completed_executor()
    result = runtime(effect_failure_observations(), executor).run(pick_place_plan())
    assert result.final_state is RuntimeState.STOPPED
    assert result.completed_steps == ()
    assert executor.dispatch_count == 1


def test_unknown_reobserves_without_redispatch(runtime):
    executor = completed_executor()
    result = runtime(unknown_then_pass_observations(), executor).run(single_pick_plan())
    assert result.final_state is RuntimeState.DONE
    assert executor.dispatch_count == 1
    assert result.recovery_count == 1
```

Add one handoff-failure test asserting Pick does not advance to Place.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_supervisor.py`

Expected: FAIL.

- [ ] **Step 3: Implement canonical trace and False Advance Rate**

```python
def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()
```

Only `step_advanced` and `episode_done` are eligible advances. Missing or non-pass ground truth for a required gate counts as false advance. Zero eligible transitions reports rate `0.0` and count `0`.

- [ ] **Step 4: Implement the synchronous supervisor loop**

```text
LOAD_PLAN → OBSERVE_PRE → PRECHECK → DISPATCH → RECEIPT
→ OBSERVE_POST → VERIFY_EFFECT
→ VERIFY_HANDOFF → NEXT
→ VERIFY_TASK_GOAL → DONE
```

Before every dispatch, validate the exact Skill and preconditions. After a completed receipt, require a strictly newer observation. `REOBSERVE` resumes the blocked verifier with a newer snapshot and no dispatch. `RETRY_SAME_FAKE` starts a new attempt and precheck. Any failed/unknown gate after budget exhaustion returns `STOPPED`.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_supervisor.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime tests/orchestration/runtime
git commit -m "feat(orchestration): add evidence-gated supervisor"
```

---

### Task 4: Runnable Replay and Boundary Verification

**Files:**
- Create: `scripts/orchestration/run_shadow_replay.py`
- Create: `tests/fixtures/orchestration/pick_place_success.json`
- Create: `tests/orchestration/runtime/test_replay_cli.py`
- Create: `tests/orchestration/runtime/test_isolation.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/__init__.py`

**Interfaces:**
- CLI: `--bundle`, repeated `--skill`, `--trace`, `--metrics`.
- Output summary includes final state, dispatch count, recovery count, False Advance Rate, and `robot_execution_enabled:false`.

- [ ] **Step 1: Write failing CLI and isolation tests**

```python
def test_success_fixture_runs_to_done(tmp_path):
    result = run_cli(tmp_path)
    assert result["final_state"] == "DONE"
    assert result["false_advance_rate"] == 0.0
    assert result["robot_execution_enabled"] is False


def test_runtime_contains_no_hardware_or_network_imports():
    source = "\n".join(path.read_text() for path in runtime_python_files())
    for forbidden in ("startouch", "can.interface", "socket", "subprocess", "requests", "httpx"):
        assert forbidden not in source.lower()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_replay_cli.py tests/orchestration/runtime/test_isolation.py`

Expected: FAIL.

- [ ] **Step 3: Add one deterministic JSON bundle and local-only CLI**

The bundle contains a two-step plan, four observations, two completed fake receipts, and ground-truth labels. The CLI validates regular local input files, runs the supervisor, writes canonical JSONL/metrics, and never performs network or device access.

- [ ] **Step 4: Run focused and regression verification**

```bash
.venv/bin/pytest -q tests/orchestration/runtime
.venv/bin/ruff check src/uiea_thirdhand_vla/orchestration/runtime scripts/orchestration tests/orchestration/runtime
.venv/bin/pytest -q tests/orchestration tests/vision_deployment
git diff --check
```

Expected: runtime and relevant regression tests pass; Ruff and diff checks print no errors. Unrelated concurrent web-control changes are not modified.

- [ ] **Step 5: Run the replay and commit**

```bash
.venv/bin/python scripts/orchestration/run_shadow_replay.py \
  --bundle tests/fixtures/orchestration/pick_place_success.json \
  --skill configs/skills/tabletop_pick.yaml \
  --skill configs/skills/tabletop_place.yaml \
  --trace /tmp/thirdhand-orchestration/events.jsonl \
  --metrics /tmp/thirdhand-orchestration/metrics.json
```

Expected: `DONE`, two fake dispatches, zero false advances, and execution disabled.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime scripts/orchestration configs/skills tests/orchestration/runtime tests/fixtures/orchestration
git commit -m "feat(orchestration): complete offline runtime scaffold"
```
