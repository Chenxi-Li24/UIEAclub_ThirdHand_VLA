# Hybrid Verifier and Replanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-cited hybrid verification, deterministic diagnosis, and one-budget bounded replanning to offline/shadow episodes.

**Architecture:** A `StageVerifier` injection keeps the existing rule runtime unchanged by default. Shadow-only model adapters consume bounded evidence bundles and return strict tri-state decisions. An outer adaptive runner may resume only with a registry-validated remaining plan.

**Tech Stack:** Python 3.10+, Pydantic v2, protocols, optional httpx transport, pytest, Ruff.

## Global Constraints

- Hard rule `FAIL` cannot be overridden.
- `UNKNOWN` cannot advance.
- Model outputs must cite evidence IDs already in the bundle.
- Model transports are disabled by default and cannot access executors or files.
- A replan cannot alter completed steps, task goal, contract versions, or budgets.
- Maximum accepted replans per episode is one.

---

### Task 1: Stage Verifier Injection

**Files:**
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/ports.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/monitors.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/supervisor.py`
- Test: `tests/orchestration/runtime/test_verifier_injection.py`

**Interfaces:**
- Produces: `StageVerifier.verify(stage, predicates, call, observation, previous, now_ns) -> StageResult`.
- Produces: `DeterministicStageVerifier` wrapping the current `verify` function.

- [ ] **Step 1: Write failing compatibility and injection tests**

Assert the default produces byte-equivalent stage verdict events, an injected verifier is called at
each gate, hard failure stops, and injected `UNKNOWN` does not advance.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_verifier_injection.py`

Expected: FAIL because `StageVerifier` is absent.

- [ ] **Step 3: Add the optional verifier dependency**

Default to `DeterministicStageVerifier`; replace only the direct call inside `_check`. Do not change
existing state transitions, recovery semantics, constructor call sites, or trace event names.

- [ ] **Step 4: Run all runtime tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/runtime`

Expected: PASS, including all original 21 tests.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime tests/orchestration/runtime
git commit -m "feat(orchestration): allow evidence verifier injection"
```

---

### Task 2: Evidence Bundles, Scripted Model, and Router

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/verification.py`
- Test: `tests/orchestration/shadow/test_verification.py`

**Interfaces:**
- Produces: `VerificationMode`, `RiskClass`, `EvidenceBundle`, `ModelDecision`, `ModelVerifier`.
- Produces: `ScriptedModelVerifier`, `VerifierRouter(StageVerifier)`.

- [ ] **Step 1: Write failing routing tests**

Cover rule-only, always-model, and hybrid modes; hard-fail dominance; model citation subset checks;
invalid/timeout/missing response to `UNKNOWN`; configured semantic stage routing; call and timeout
counters; deterministic response content IDs.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_verification.py`

Expected: FAIL because `verification` is missing.

- [ ] **Step 3: Implement strict bundles and routing**

The router first runs `DeterministicStageVerifier`. It immediately returns hard `FAIL`. It calls the
model only when mode and configured stage require it, and aggregates rule/model verdicts with
`FAIL > UNKNOWN > PASS`. Append a synthetic predicate result whose evidence IDs are a subset of the
bundle and whose reason includes model/prompt version hashes.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_verification.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/verification.py tests/orchestration/shadow/test_verification.py
git commit -m "feat(orchestration): add hybrid evidence verifier"
```

---

### Task 3: Optional Allow-Listed JSON Transport

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/model_transport.py`
- Test: `tests/orchestration/shadow/test_model_transport.py`

**Interfaces:**
- Produces: `ModelTransport.request(payload: dict[str, object]) -> dict[str, object]`.
- Produces: `DisabledTransport`, `InjectedTransport`, `AllowListedHttpTransport`.

- [ ] **Step 1: Write failing transport tests**

Assert disabled-by-default behavior, HTTPS/loopback-only allow-list validation, bounded timeout and
response bytes, no redirect, strict JSON object response, redacted secret trace data, and injected
transport operation without network.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_model_transport.py`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement transport policy**

Import `httpx` only inside the enabled request method. Require `enabled=True`, an exact endpoint in
`allowed_endpoints`, timeout within `(0, 60]`, response cap at 1 MiB, and `follow_redirects=False`.
The transport returns parsed JSON only; schema enforcement remains in `ModelDecision`.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_model_transport.py`

Expected: PASS without performing network access.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/model_transport.py tests/orchestration/shadow/test_model_transport.py
git commit -m "feat(orchestration): add disabled-by-default model transport"
```

---

### Task 4: Failure Diagnosis and Bounded Replanner

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/diagnosis.py`
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/replanning.py`
- Test: `tests/orchestration/shadow/test_diagnosis_replanning.py`

**Interfaces:**
- Produces: `FailureCause`, `Diagnosis`, `FailureDiagnoser.diagnose(result: RunResult) -> Diagnosis`.
- Produces: `ReplanContext`, `ReplanProposal`, `ReplanDecision`, `BoundedReplanner.validate(...)`.

- [ ] **Step 1: Write failing diagnosis/replan tests**

Cover each frozen failure cause, reason-code consistency, evidence citations, exact-version registry
validation, preserved task goal/completed steps, unique step IDs, handoff compatibility, no budget
increase, maximum one accepted proposal, and rejection of loops or unknown Skills.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_diagnosis_replanning.py`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement deterministic diagnosis and validation**

Diagnosis reads trace event types, stop reason, and verdict reasons. Replanning accepts a scripted
proposal but reconstructs every `SkillCall` through `SkillRegistry.validate_call`, checks adjacent
handoff rules, hashes the accepted plan, and decrements an immutable replan budget.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_diagnosis_replanning.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/diagnosis.py src/uiea_thirdhand_vla/orchestration/shadow/replanning.py tests/orchestration/shadow/test_diagnosis_replanning.py
git commit -m "feat(orchestration): add bounded diagnosis and replanning"
```

---

### Task 5: Adaptive Shadow Episode Runner

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/adaptive_runner.py`
- Test: `tests/orchestration/shadow/test_adaptive_runner.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/shadow/__init__.py`

**Interfaces:**
- Produces: `AdaptiveRunResult`, `AdaptiveEpisodeRunner.run(plan: Plan) -> AdaptiveRunResult`.

- [ ] **Step 1: Write failing integration tests**

Assert no-replan compatibility, one accepted remaining-plan replacement, rejected proposal safe
stop, no redispatch of completed steps, monotonic trace sequence, total dispatch/recovery/model-call
counts, and hard termination when replan budget is exhausted.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_adaptive_runner.py`

Expected: FAIL because `AdaptiveEpisodeRunner` is absent.

- [ ] **Step 3: Implement the outer bounded loop**

Run the existing supervisor against persistent observation/executor/trace objects. On `STOPPED`,
diagnose once, validate a scripted proposal, and resume only the accepted remaining plan. Sum counts
and retain completed steps. Never retry a completed step or create a second accepted replan.

- [ ] **Step 4: Verify and commit**

Run:

```bash
.venv/bin/pytest -q tests/orchestration/runtime tests/orchestration/shadow
.venv/bin/ruff check src/uiea_thirdhand_vla/orchestration/runtime src/uiea_thirdhand_vla/orchestration/shadow tests/orchestration
```

Expected: PASS and lint clean.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow tests/orchestration
git commit -m "feat(orchestration): run bounded adaptive shadow episodes"
```
