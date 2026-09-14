# Fixed Pick and Place Automatic Three-Cycle Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate one-click dashboard action that runs exactly three automatic A-to-B-to-A cycles while preserving the existing manual step-by-step mode.

**Architecture:** The dashboard selects an explicit run mode and owns one launcher process. The launcher accepts only a fixed automatic environment tuple, reports the effective mode in preflight, and passes explicit cycle and automatic flags to the Python runner. The runner keeps the existing trajectory, speed, cleanup, and resource safety logic while allowing the approved three-cycle mode to omit per-stage confirmation.

**Tech Stack:** Python 3.10 standard library HTTP server and unittest, Bash, HTML/CSS, browser JavaScript, YAML.

## Global Constraints

- Automatic mode always runs exactly 3 cycles at no more than speed scale 0.30.
- Manual mode remains one cycle with per-stage confirmation.
- Both modes retain CAN/worktree/process conflict checks, the three-second countdown, logging, SIGINT cleanup, and motor disable.
- Each logical movement route remains one continuous SDK path; no point, 0.25 m lift, gripper parameter, or path interpolation bound changes.
- The dashboard never opens `can0` while idle and never signals an unrelated process.
- Software implementation and verification must not start real arm motion.

---

### Task 1: Python runner automatic-mode contract

**Files:**
- Modify: `web-control/scripts/fixed_pick_place.py`
- Test: `tests/web/test_fixed_pick_place.py`

**Interfaces:**
- Consumes: existing `load_config()`, `FixedPickPlaceRunner`, and CLI mode selection.
- Produces: CLI flags `--cycles 3` and `--automatic-three-cycle`; real-mode validation that permits confirmation-free execution only for that exact automatic tuple.

- [ ] **Step 1: Write failing runner contract tests**

Add tests that execute the real point configuration in simulation:

```python
def test_automatic_three_cycle_simulation_runs_60_stages_without_input(self):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--simulate",
            "--config",
            str(ROOT / "configs/tasks/fixed_pick_place.yaml"),
            "--speed-scale",
            "1.0",
            "--cycles",
            "3",
            "--automatic-three-cycle",
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    self.assertEqual(result.returncode, 0, output)
    self.assertIn("CYCLE 3/3 COMPLETE", output)
    self.assertEqual(output.count("AWAITING_CONFIRMATION="), 0)
```

Add parser/validation tests proving `--automatic-three-cycle` rejects cycle
counts other than 3 and that manual real mode still requires confirmation
while validation count is below three. Test validation through a small pure
function rather than constructing hardware.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m unittest \
  tests.web.test_fixed_pick_place.FixedPickPlaceTests.test_automatic_three_cycle_simulation_runs_60_stages_without_input \
  -v
```

Expected: FAIL because `--cycles` and `--automatic-three-cycle` do not exist.

- [ ] **Step 3: Implement minimal runner overrides**

Add parser flags and a pure validator:

```python
def apply_execution_overrides(
    config: dict[str, Any],
    *,
    mode: str,
    cycles: int | None,
    automatic_three_cycle: bool,
    confirm_each_step: bool,
) -> None:
    if cycles is not None:
        if not 1 <= cycles <= 100:
            raise ConfigurationError("--cycles must be between 1 and 100")
        config["demo"]["cycles"] = cycles
    if automatic_three_cycle:
        if config["demo"]["cycles"] != 3:
            raise ConfigurationError(
                "--automatic-three-cycle requires --cycles 3"
            )
        if confirm_each_step:
            raise ConfigurationError(
                "--automatic-three-cycle cannot use --confirm-each-step"
            )
    elif mode == "real" and (
        config["demo"]["validated_real_cycles"] < 3
        or config["demo"]["require_step_confirmation"]
    ) and not confirm_each_step:
        raise ConfigurationError(
            "real mode requires --confirm-each-step until three "
            "validated real cycles are recorded"
        )
```

Call it after loading speed and before constructing the bridge. Preserve the
existing 0.30 real speed hard limit.

- [ ] **Step 4: Run focused and existing runner tests**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m unittest tests.web.test_fixed_pick_place -v
```

Expected: all runner tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add web-control/scripts/fixed_pick_place.py tests/web/test_fixed_pick_place.py
git commit -m "Add validated automatic three-cycle runner mode"
```

### Task 2: Launcher mode validation and propagation

**Files:**
- Modify: `scripts/demo_fixed_pick_place.sh`
- Test: `tests/web/test_fixed_pick_place.py`

**Interfaces:**
- Consumes: `DEMO_RUN_MODE`, `DEMO_CYCLES`, and
  `DEMO_CONFIRM_EACH_STEP` from the dashboard.
- Produces: either the unchanged manual runner arguments or the exact
  `--cycles 3 --automatic-three-cycle` automatic arguments.

- [ ] **Step 1: Write failing launcher tests**

Add subprocess tests using `DEMO_PREFLIGHT_ONLY=1` and a test-only resource
guard fixture:

```python
def test_launcher_reports_validated_automatic_tuple_in_preflight(self):
    env = os.environ.copy()
    env.update(
        {
            "DEMO_PREFLIGHT_ONLY": "1",
            "DEMO_RUN_MODE": "automatic-three-cycle",
            "DEMO_CYCLES": "3",
            "DEMO_CONFIRM_EACH_STEP": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "demo_fixed_pick_place.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    self.assertEqual(result.returncode, 0, output)
    self.assertIn("RUN_MODE=automatic-three-cycle", output)
    self.assertIn("CYCLES=3", output)
    self.assertIn("REQUIRE_STEP_CONFIRMATION=0", output)
```

Add cases for unknown mode, automatic cycles not equal to 3, confirmation not
equal to 0, and manual overrides. Assert failure occurs before `RUN_COMMAND=`.

- [ ] **Step 2: Run focused tests and verify RED**

Expected: valid automatic preflight still reports the YAML's one-cycle manual
values, and invalid tuples are not rejected.

- [ ] **Step 3: Implement strict shell validation**

At the beginning of launcher preflight, normalize:

```bash
run_mode="${DEMO_RUN_MODE:-manual}"
requested_cycles="${DEMO_CYCLES:-}"
requested_confirmation="${DEMO_CONFIRM_EACH_STEP:-}"
case "$run_mode" in
  manual)
    [[ -z "$requested_cycles" && -z "$requested_confirmation" ]] ||
      fail "MODE_CHECK" "manual mode does not accept automatic overrides"
    ;;
  automatic-three-cycle)
    [[ "$requested_cycles" == "3" ]] ||
      fail "MODE_CHECK" "automatic mode requires DEMO_CYCLES=3"
    [[ "$requested_confirmation" == "0" ]] ||
      fail "MODE_CHECK" "automatic mode requires DEMO_CONFIRM_EACH_STEP=0"
    ;;
  *)
    fail "MODE_CHECK" "unknown DEMO_RUN_MODE=$run_mode"
    ;;
esac
```

After YAML preflight, set effective values for automatic mode, print
`RUN_MODE`, and append `--cycles 3 --automatic-three-cycle` instead of
`--confirm-each-step`.

- [ ] **Step 4: Run launcher and runner tests**

Run:

```bash
bash -n scripts/demo_fixed_pick_place.sh
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m unittest tests.web.test_fixed_pick_place -v
```

Expected: syntax and all focused tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/demo_fixed_pick_place.sh tests/web/test_fixed_pick_place.py
git commit -m "Validate automatic mode in demo launcher"
```

### Task 3: Dashboard endpoint, process ownership, and buttons

**Files:**
- Modify: `web-control/demo/demo_server.py`
- Modify: `web-control/demo/index.html`
- Modify: `web-control/demo/demo.js`
- Modify: `web-control/demo/demo.css`
- Test: `tests/web/test_demo_server.py`

**Interfaces:**
- Consumes: launcher environment tuple defined in Task 2.
- Produces: `DemoController.start(mode: str = "manual") -> bool`,
  `POST /api/start-auto`, status field `run_mode`, and DOM id
  `start-auto-demo`.

- [ ] **Step 1: Write failing controller and HTTP tests**

Assert that:

```python
self.assertTrue(controller.start("automatic-three-cycle"))
kwargs = popen_factory.call_args.kwargs
self.assertEqual(kwargs["env"]["DEMO_RUN_MODE"], "automatic-three-cycle")
self.assertEqual(kwargs["env"]["DEMO_CYCLES"], "3")
self.assertEqual(kwargs["env"]["DEMO_CONFIRM_EACH_STEP"], "0")
self.assertEqual(controller.status()["run_mode"], "automatic-three-cycle")
```

Through the real HTTP test server, assert `POST /api/start-auto` returns 202;
a second `/api/start` or `/api/start-auto` returns 409; `/api/continue`
returns 409 during automatic mode; and `/api/stop` returns 202.

Add markup assertions for `手动逐步演示`, `一键自动循环 3 次`, and
`start-auto-demo`.

- [ ] **Step 2: Run dashboard tests and verify RED**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m unittest tests.web.test_demo_server -v
```

Expected: failures for the missing method argument, endpoint, status field,
and button.

- [ ] **Step 3: Implement process mode ownership**

Change the controller signature to:

```python
def start(self, mode: str = "manual") -> bool:
```

Accept only `manual` and `automatic-three-cycle`. Copy `os.environ` and add
the three automatic values only for automatic mode. Store `_run_mode`, expose
it in `status()`, and clear it to `None` after the owned process exits.
`continue_step()` must return `False` unless `_run_mode == "manual"`.

Add:

```python
if path == "/api/start-auto":
    started = self.controller.start("automatic-three-cycle")
```

Keep `/api/start` calling `start("manual")`.

- [ ] **Step 4: Implement the page controls**

Add `<button id="start-auto-demo" class="auto-start">一键自动循环 3 次</button>`.
In JavaScript, disable both Start buttons while `data.owned`, bind the new
button to `/api/start-auto`, and show an explicit confirmation mentioning
three cycles, 30% speed, onsite presence, clear workspace, and E-stop.

Use existing button styling, adding only the `.auto-start` color needed to
distinguish automatic mode. Preserve the responsive layout.

- [ ] **Step 5: Run dashboard tests**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -m unittest tests.web.test_demo_server -v
```

Expected: all dashboard tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add web-control/demo tests/web/test_demo_server.py
git commit -m "Add one-click automatic dashboard control"
```

### Task 4: End-to-end simulation, documentation, and handoff

**Files:**
- Modify: `README.md`
- Modify: `web-control/FIXED_PICK_PLACE.md`
- Modify: `docs/fixed_pick_place_audit.md`
- Test: `tests/web/test_demo_server.py`

**Interfaces:**
- Consumes: all automatic mode interfaces from Tasks 1-3.
- Produces: dashboard-driven 60-stage automatic simulation evidence and final
  operating documentation.

- [ ] **Step 1: Write the failing end-to-end dashboard test**

Use `DemoController` with the launcher in a software-only test environment,
start `automatic-three-cycle`, poll until terminal state, and assert:

```python
self.assertEqual(status["state"], "COMPLETE", status)
self.assertIn("CYCLE 3/3 COMPLETE", "\n".join(status["log_tail"]))
self.assertNotIn(
    "AWAITING_CONFIRMATION=", "\n".join(status["log_tail"])
)
```

- [ ] **Step 2: Run the end-to-end test and verify RED if integration is incomplete**

Expected: the test fails until the complete dashboard-to-launcher-to-runner
automatic path is connected.

- [ ] **Step 3: Complete only the missing integration and update docs**

Document both buttons, exact three-cycle behavior, 30% hard limit, 25 cm lift,
resource conflict behavior, Stop/cleanup behavior, and that opening the page
does not start motion. Preserve the exact Ubuntu and Windows launch commands.

- [ ] **Step 4: Run all verification**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  -W error::ResourceWarning -m unittest discover -s tests -v
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m py_compile \
  web-control/scripts/fixed_pick_place.py \
  web-control/server/startouch_bridge.py \
  web-control/demo/demo_server.py
bash -n scripts/demo_fixed_pick_place.sh \
  scripts/open_fixed_pick_place_control.sh \
  scripts/fixed_pick_place_resource_guard.sh
git diff --check
```

Then run the current real point configuration in software simulation with
`--cycles 3 --automatic-three-cycle`, and run both manual and automatic
`DEMO_PREFLIGHT_ONLY=1` checks after stopping only the dashboard process owned
by this task. Do not start real mode.

- [ ] **Step 5: Commit Task 4**

```bash
git add README.md web-control/FIXED_PICK_PLACE.md \
  docs/fixed_pick_place_audit.md tests/web/test_demo_server.py
git commit -m "Document and verify automatic three-cycle demo"
```

- [ ] **Step 6: Restart the Ubuntu-local dashboard safely**

Start only `web-control/demo/demo_server.py` on `127.0.0.1:8766`, open it on
the Ubuntu desktop, and verify `/api/status` reports `IDLE`, `owned: false`,
and no runner PID. Do not press either Start button.
