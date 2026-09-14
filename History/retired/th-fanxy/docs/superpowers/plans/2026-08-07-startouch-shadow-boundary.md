# Startouch Shadow Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce Startouch-shaped command previews while making physical execution structurally unavailable.

**Architecture:** Frozen preview contracts and a content-addressed local artifact writer implement the runtime executor protocol with `kind="shadow"` and `can_execute_world=False`. The package mirrors only documented field names and never imports the existing bridge or SDK.

**Tech Stack:** Python 3.10+, Pydantic v2, standard-library JSON/hash/path, pytest, Ruff, AST isolation checks.

## Global Constraints

- Never import, launch, connect to, or edit Startouch, CAN, robot, gripper, camera, or web-control code.
- No subprocess, socket, HTTP, device path, or environment-variable real-mode escape hatch.
- `robot_execution_enabled` is a literal false and `can_execute_world` is a literal false.
- A completed shadow receipt proves serialization only, never world change.

---

### Task 1: Executor Capability Contract

**Files:**
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/models.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/ports.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/adapters.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/registry.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/runtime/supervisor.py`
- Test: `tests/orchestration/runtime/test_executor_capabilities.py`

**Interfaces:**
- Produces: `ExecutorKind` with `FAKE` and `SHADOW`.
- Extends: `Executor.kind -> ExecutorKind`, `Executor.can_execute_world -> Literal[False]`.
- Extends: `SkillRegistry(..., allowed_executor_kinds=(ExecutorKind.FAKE,))`.

- [ ] **Step 1: Write failing capability tests**

Assert current fake behavior is unchanged; real/unknown executor kinds cannot validate; a shadow
executor is accepted only by an explicitly shadow-enabled registry; and any
`can_execute_world=True` executor stops before dispatch.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/runtime/test_executor_capabilities.py`

Expected: FAIL because the capability contract is absent.

- [ ] **Step 3: Implement fake/shadow-only capabilities**

Replace string literals with the enum, default the registry to fake-only for backward
compatibility, add `can_execute_world=False` to `FakeExecutor`, and make the supervisor reject an
executor whose kind is not permitted by every contract or whose capability is world-changing.

- [ ] **Step 4: Run regression tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/runtime`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/runtime tests/orchestration/runtime
git commit -m "feat(orchestration): define non-world-changing executors"
```

---

### Task 2: Frozen Startouch Preview Models

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/startouch_preview.py`
- Create: `configs/orchestration/startouch_shadow.yaml`
- Test: `tests/orchestration/shadow/test_startouch_preview.py`

**Interfaces:**
- Produces: `JointWaypointPreview`, `LinearPosePreview`, `GripperPreview`, `StartouchCommandPreview`.
- Produces: `ShadowLimits`, `load_shadow_limits(path: Path) -> ShadowLimits`.

- [ ] **Step 1: Write failing schema and safety tests**

Cover exactly six finite joint radians, finite xyz metres/Euler radians, explicit frame and
calibration ID, duration/speed/tolerance bounds, mutually exclusive gripper units, strict unknown
field rejection, and literal false execution flags.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_startouch_preview.py`

Expected: FAIL because preview models are absent.

- [ ] **Step 3: Implement models and checked bounds**

Copy representative limits from the existing bridge into the new YAML with a source path and
source commit field. Validate all numeric values as finite and fail closed on absent units, frame,
calibration, policy version, or contract version.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_startouch_preview.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/startouch_preview.py configs/orchestration/startouch_shadow.yaml tests/orchestration/shadow/test_startouch_preview.py
git commit -m "feat(orchestration): model Startouch shadow previews"
```

---

### Task 3: Content-Addressed Shadow Executor

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/shadow/execution.py`
- Create: `configs/skills/tabletop_pick_shadow.yaml`
- Create: `configs/skills/tabletop_place_shadow.yaml`
- Test: `tests/orchestration/shadow/test_shadow_executor.py`

**Interfaces:**
- Produces: `ExecutionCapability.shadow() -> ExecutionCapability`.
- Produces: `PreviewResolver.resolve(request: CommandRequest) -> StartouchCommandPreview`.
- Produces: `StartouchShadowExecutor.execute(request: CommandRequest) -> CommandReceipt`.

- [ ] **Step 1: Write failing executor tests**

Assert canonical preview creation, content-addressed filename, no partial artifact on invalid input,
receipt evidence kind/ID, duplicate request idempotency, fake/shadow contract mismatch rejection,
and inability to construct a real capability.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_shadow_executor.py`

Expected: FAIL because the shadow executor is absent.

- [ ] **Step 3: Implement atomic preview writing**

Resolve through an injected exact-version `PreviewResolver`; absence of a mapping is a rejection,
never an invented default pose. Validate and serialize in memory, compute the content ID, create the
explicit parent directory, write to a same-directory temporary regular file with exclusive
creation, `fsync`, and atomically rename to `<content-id>.json`. A repeated identical request
returns the same receipt. No SDK or bridge code is imported.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_shadow_executor.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/shadow/execution.py configs/skills/tabletop_pick_shadow.yaml configs/skills/tabletop_place_shadow.yaml tests/orchestration/shadow/test_shadow_executor.py
git commit -m "feat(orchestration): add Startouch shadow executor"
```

---

### Task 4: Isolation and End-to-End Shadow Replay

**Files:**
- Create: `tests/fixtures/orchestration/pick_place_shadow_success.json`
- Create: `tests/fixtures/orchestration/startouch_preview_policy.json`
- Create: `scripts/orchestration/run_startouch_shadow.py`
- Test: `tests/orchestration/shadow/test_shadow_isolation.py`
- Test: `tests/orchestration/shadow/test_shadow_cli.py`

**Interfaces:**
- CLI: `--bundle`, repeated `--skill`, `--limits`, `--preview-dir`, `--trace`, `--metrics`.

- [ ] **Step 1: Write failing AST isolation and CLI tests**

Scan runtime/shadow imports for `startouchclass`, `can`, `socket`, `subprocess`, ROS and camera
libraries. Assert a successful replay writes two previews, reaches `DONE` only after newer evidence,
and reports `robot_execution_enabled=false` and `can_execute_world=false`.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/shadow/test_shadow_isolation.py tests/orchestration/shadow/test_shadow_cli.py`

Expected: FAIL because the fixture and CLI are absent.

- [ ] **Step 3: Add fixture and CLI**

Use the existing fake replay observations but shadow contract versions and a checked fixture that
maps the two exact Skill requests to simulated preview commands. Reject absent request mappings,
existing non-file outputs, symlinks, unsafe limits, and any attempt to pass a real-execution option.

- [ ] **Step 4: Verify and commit**

Run:

```bash
.venv/bin/pytest -q tests/orchestration/runtime tests/orchestration/shadow
.venv/bin/ruff check src/uiea_thirdhand_vla/orchestration/runtime src/uiea_thirdhand_vla/orchestration/shadow scripts/orchestration tests/orchestration
```

Expected: PASS and lint clean.

```bash
git add configs/orchestration configs/skills src/uiea_thirdhand_vla/orchestration/shadow scripts/orchestration/run_startouch_shadow.py tests/orchestration/shadow tests/fixtures/orchestration/pick_place_shadow_success.json tests/fixtures/orchestration/startouch_preview_policy.json
git commit -m "feat(orchestration): complete non-executing Startouch boundary"
```
