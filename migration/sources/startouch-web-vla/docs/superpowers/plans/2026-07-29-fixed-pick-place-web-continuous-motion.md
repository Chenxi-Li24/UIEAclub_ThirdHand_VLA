# Fixed Pick and Place Web Control and Continuous Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Ubuntu-local Start/Stop demo page and replace stop-start 12° commands with one continuous SDK trajectory per logical route.

**Architecture:** A small Python HTTP service owns only the demo subprocess and never opens can0 itself. The existing runner generates bounded intermediate joint points and sends them in one bridge command; the bridge validates the complete array and invokes the SDK once.

**Tech Stack:** Python 3.10 standard library, Startouch JSON-lines bridge, Bash, HTML/CSS/JavaScript, `unittest`.

## Global Constraints

- Work only in `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place` on `fanxy/fixed-pick-place`.
- Preserve the existing A/B points, 0.25 m lift, three-cycle workflow, adaptive gripper and normal demo speed 0.15.
- Stop means SIGINT, cleanup, motor disable and remain at the current pose; never auto-return Home.
- Never terminate or interfere with an unowned process; return `RESOURCE_CONFLICT`.
- The web service must not connect to or hold can0 while idle.
- Initial real continuous-motion validation is supervised, step-by-step and limited to 0.03 speed.
- Existing uncommitted changes must be backed up and committed only by exact file paths.

---

### Task 1: Continuous multi-waypoint runner protocol

**Files:**
- Modify: `tests/web/test_fixed_pick_place.py`
- Modify: `web-control/scripts/fixed_pick_place.py`

**Interfaces:**
- Produces: `interpolate_joint_path(start_deg, target_deg, max_step_deg) -> list[list[float]]`
- Produces: `BridgeClient.move_path(waypoints_deg, *, speed_scale, max_speeds_deg_s, min_time_s, timeout_s, target_tolerance_deg, source) -> None`
- Consumes: current `BridgeClient.latest_joints_deg` feedback.

- [ ] **Step 1: Write failing interpolation and one-call tests**

```python
def test_interpolate_joint_path_bounds_every_segment(self):
    path = fixed.interpolate_joint_path([0] * 6, [25, -5, 0, 0, 0, 0], 12)
    self.assertEqual(path[-1], [25, -5, 0, 0, 0, 0])
    self.assertTrue(all(
        max(abs(b - a) for a, b in zip(left, right)) <= 12
        for left, right in zip([[0] * 6, *path[:-1]], path)
    ))

def test_real_closed_loop_submits_one_path_command(self):
    bridge = FakeBridge()
    bridge.latest_joints_deg = [0] * 6
    runner = fixed.FixedPickPlaceRunner(
        bridge, continuous_config(), "real", logging.getLogger("test")
    )
    runner._move_closed_loop("a_up", [25, 0, 0, 0, 0, 0])
    self.assertEqual([call[0] for call in bridge.calls], ["move_path"])
    self.assertEqual(len(bridge.calls[0][1]), 3)
```

- [ ] **Step 2: Run tests and verify RED**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_fixed_pick_place.FixedPickPlaceTests.test_interpolate_joint_path_bounds_every_segment tests.web.test_fixed_pick_place.FixedPickPlaceTests.test_real_closed_loop_submits_one_path_command -v`

Expected: failure because `interpolate_joint_path` and `move_path` do not exist.

- [ ] **Step 3: Implement bounded interpolation and single path submission**

```python
def interpolate_joint_path(start_deg, target_deg, max_step_deg):
    remaining = max(abs(goal - start) for start, goal in zip(start_deg, target_deg))
    segments = max(1, math.ceil(remaining / max_step_deg))
    return [
        [start + (goal - start) * index / segments
         for start, goal in zip(start_deg, target_deg)]
        for index in range(1, segments + 1)
    ]
```

Update `_move_closed_loop` to build this list once, log its point count, call
`bridge.move_path(...)` once and rely on its final feedback check. Keep `move`
as a one-target compatibility wrapper around `move_path([target])`.

- [ ] **Step 4: Run focused and existing runner tests**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_fixed_pick_place -v`

Expected: all tests pass and existing action ordering remains unchanged.

- [ ] **Step 5: Commit exact files**

```bash
git add tests/web/test_fixed_pick_place.py web-control/scripts/fixed_pick_place.py
git commit -m "Use one continuous command per pick place route"
```

### Task 2: Bridge multi-waypoint validation and SDK call

**Files:**
- Modify: `tests/web/test_fixed_pick_place.py`
- Modify: `web-control/server/startouch_bridge.py`

**Interfaces:**
- Consumes JSON: `{"cmd":"move_joint_path","waypoints_rad":[[...],...],"time_sec":float,"request_id":str,"source":str}`
- Produces bridge events with command name `move_joint_path`.
- Calls SDK: `arm.set_joint_waypoints([current, *waypoints], time_sec=time_sec)` exactly once.

- [ ] **Step 1: Write failing bridge tests**

```python
def test_bridge_path_calls_sdk_once(self):
    bridge = bridge_module.RobotBridge()
    arm = RecordingArm()
    bridge.connected = True
    bridge.state_ready = True
    bridge.arm = arm
    bridge.last_valid_joints = [0.0] * 6
    bridge.enqueue_motion({
        "cmd": "move_joint_path",
        "waypoints_rad": [[0.1] * 6, [0.2] * 6],
        "time_sec": 1.0,
        "request_id": "path-1",
        "source": "test",
    })
    command = bridge.motion_queue.get_nowait()
    bridge._execute_motion(command)
    self.assertEqual(len(arm.trajectory_calls), 1)
    self.assertEqual(arm.trajectory_calls[0], [[0.0] * 6, [0.1] * 6, [0.2] * 6])
```

Also add cases rejecting an empty path, non-six-axis points, NaN, all-zero
target and joint-limit violations.

- [ ] **Step 2: Run bridge tests and verify RED**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_fixed_pick_place -v`

Expected: path protocol is unknown or `waypoints_rad` is not validated.

- [ ] **Step 3: Implement path validation and one SDK call**

Store `waypoints_rad` on the motion queue item, validate every point with
`_finite_values`, joint limits and final all-zero protection, and execute:

```python
duration = arm.set_joint_waypoints(
    [command["start_joints_rad"], *command["waypoints_rad"]],
    time_sec=command["time_sec"],
)
```

The simulator must traverse every waypoint without stopping its API call.
`software_stop` must continue to call the existing concurrent cleanup path.

- [ ] **Step 4: Run tests and compile checks**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_fixed_pick_place -v`

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m py_compile web-control/server/startouch_bridge.py web-control/scripts/fixed_pick_place.py`

Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit exact files**

```bash
git add tests/web/test_fixed_pick_place.py web-control/server/startouch_bridge.py
git commit -m "Add validated continuous waypoint bridge command"
```

### Task 3: Demo process controller and API

**Files:**
- Create: `web-control/demo/demo_server.py`
- Create: `tests/web/test_demo_server.py`

**Interfaces:**
- Produces HTTP: `GET /api/status`, `POST /api/start`, `POST /api/stop`.
- Produces status JSON: `state`, `stage`, `message`, `pid`, `owned`, `log_tail`, `last_log`.
- Launches only: `bash scripts/demo_fixed_pick_place.sh`.

- [ ] **Step 1: Write failing ownership and lifecycle tests**

```python
def test_idle_status_does_not_spawn_or_open_can(self):
    controller = DemoController(root=ROOT, popen=fake_popen)
    self.assertEqual(controller.status()["state"], "IDLE")
    self.assertEqual(fake_popen.calls, [])

def test_stop_signals_only_owned_process_group(self):
    controller = DemoController(root=ROOT, popen=fake_popen, killpg=fake_killpg)
    controller.start()
    controller.stop()
    self.assertEqual(fake_killpg.calls, [(controller.pid, signal.SIGINT)])

def test_resource_conflict_is_not_terminated(self):
    controller = DemoController(root=ROOT, popen=conflict_popen, killpg=fake_killpg)
    controller.start()
    wait_until_finished(controller)
    self.assertEqual(controller.status()["state"], "FAILED")
    self.assertIn("RESOURCE_CONFLICT", controller.status()["message"])
    self.assertEqual(fake_killpg.calls, [])
```

- [ ] **Step 2: Run tests and verify RED**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_demo_server -v`

Expected: import/file failure.

- [ ] **Step 3: Implement the minimal controller and HTTP server**

Use `subprocess.Popen(..., start_new_session=True, stdout=PIPE,
stderr=STDOUT, text=True)`. Keep the owned `Popen` object under a lock.
Stream output into a bounded `deque(maxlen=500)`, map known markers to
states, and expose JSON from a `ThreadingHTTPServer`.

Stop behavior:

```python
with self._lock:
    process = self._process
if process is None or process.poll() is not None:
    return False
os.killpg(process.pid, signal.SIGINT)
return True
```

Never search for, signal or kill an external PID.

- [ ] **Step 4: Run controller tests**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_demo_server -v`

Expected: PASS.

- [ ] **Step 5: Commit exact files**

```bash
git add web-control/demo/demo_server.py tests/web/test_demo_server.py
git commit -m "Add owned-process demo control API"
```

### Task 4: Ubuntu-local Start/Stop page and launcher

**Files:**
- Create: `web-control/demo/index.html`
- Create: `web-control/demo/demo.js`
- Create: `web-control/demo/demo.css`
- Create: `scripts/open_fixed_pick_place_control.sh`
- Modify: `tests/web/test_demo_server.py`

**Interfaces:**
- Consumes the Task 3 HTTP API.
- Launcher serves only on `127.0.0.1:8766` and opens `http://127.0.0.1:8766/`.

- [ ] **Step 1: Write failing static/API contract tests**

```python
def test_page_has_start_stop_status_and_log(self):
    html = (ROOT / "web-control/demo/index.html").read_text()
    self.assertIn('id="start-demo"', html)
    self.assertIn('id="stop-demo"', html)
    self.assertIn('id="demo-status"', html)
    self.assertIn('id="demo-log"', html)
```

Add a server construction test asserting the default bind host equals
`127.0.0.1` and port equals `8766`.

- [ ] **Step 2: Run tests and verify RED**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_demo_server -v`

Expected: missing page/launcher contract.

- [ ] **Step 3: Implement page and safe launcher**

The page polls `/api/status` once per second. Start requires a confirmation
dialog containing the fixed-A placement and clear-workspace warning. Stop
requires confirmation and posts `/api/stop`. Buttons follow the state and
the page renders `RESOURCE_CONFLICT`, failure stage, error reason and logs
without hiding them.

Launcher:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
exec /home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  web-control/demo/demo_server.py --host 127.0.0.1 --port 8766 --open-browser
```

The browser-open helper may call `xdg-open`; it must not start the existing
manual `proxy.js` or `startouch_bridge.py`.

- [ ] **Step 4: Run static tests and simulated HTTP smoke test**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_demo_server -v`

Run server in simulate-test mode, request `/api/status`, verify JSON `IDLE`,
then terminate only that test server.

- [ ] **Step 5: Commit exact files**

```bash
git add web-control/demo/index.html web-control/demo/demo.js \
  web-control/demo/demo.css scripts/open_fixed_pick_place_control.sh \
  tests/web/test_demo_server.py
git commit -m "Add local fixed pick place start stop page"
```

### Task 5: Documentation, backup and non-hardware verification

**Files:**
- Modify: `README.md`
- Modify: `web-control/FIXED_PICK_PLACE.md`
- Modify: `docs/fixed_pick_place_audit.md`
- Modify: `scripts/demo_fixed_pick_place.sh`

**Interfaces:**
- Documents both required CLI launch commands and the new page launcher.
- Keeps success marker `PICK AND PLACE COMPLETE` and failure marker `PICK AND PLACE FAILED`.

- [ ] **Step 1: Add a preflight test for continuous mode and exact commands**

Add assertions that README/report contain:

```text
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/demo_fixed_pick_place.sh
ssh -t robot-ubuntu "cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place && bash scripts/demo_fixed_pick_place.sh"
bash scripts/open_fixed_pick_place_control.sh
```

and that preflight accepts the continuous trajectory configuration while
enforcing speed `<= 0.20`.

- [ ] **Step 2: Run the new test and verify RED**

Run:
`/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest tests.web.test_fixed_pick_place -v`

Expected: documentation/continuous-mode assertion fails.

- [ ] **Step 3: Update documentation and preflight**

Document UI states, stop semantics, resource conflict behavior, 15% normal
speed and the 3% first continuous-motion validation gate. Make the demo
script trap INT/TERM/EXIT and forward INT to its owned runner so both normal
and abnormal paths reach runner cleanup.

- [ ] **Step 4: Run the full non-hardware verification**

Run:

```bash
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m unittest discover -s tests -v
/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m py_compile \
  web-control/scripts/fixed_pick_place.py \
  web-control/server/startouch_bridge.py \
  web-control/demo/demo_server.py
DEMO_PREFLIGHT_ONLY=1 bash scripts/demo_fixed_pick_place.sh
```

Expected: all tests PASS, compile succeeds and output contains
`DEMO_PREFLIGHT_OK`. Verify afterward that no `startouch_bridge.py`,
`fixed_pick_place.py` or `proxy.js` process exists.

- [ ] **Step 5: Commit exact files**

```bash
git add README.md web-control/FIXED_PICK_PLACE.md \
  docs/fixed_pick_place_audit.md scripts/demo_fixed_pick_place.sh \
  tests/web/test_fixed_pick_place.py
git commit -m "Document continuous web-controlled pick place demo"
```

### Task 6: Ubuntu desktop and supervised hardware validation

**Files:**
- Append generated logs under: `logs/fixed_pick_place/`
- Modify after evidence only: `configs/tasks/fixed_pick_place.yaml`
- Modify after evidence only: `docs/fixed_pick_place_audit.md`

**Interfaces:**
- Uses `bash scripts/open_fixed_pick_place_control.sh`.
- Real run remains gated by on-site operator and functional emergency stop.

- [ ] **Step 1: Open the page without connecting can0**

Start the control service, open `http://127.0.0.1:8766/` on Ubuntu and verify
the page reports IDLE. Verify no robot-control process exists.

- [ ] **Step 2: Get explicit现场 confirmation**

Require confirmation that a person is present, the physical emergency stop
is available, the workspace is clear and the test is empty-load.

- [ ] **Step 3: Run 3% step-by-step empty-load validation**

Create a timestamped backup of the YAML, temporarily set speed to `0.03`,
cycles to `1` and step confirmation to true. Execute one continuous empty
trajectory and confirm each logical stage. Stop on any unexpected motion.

- [ ] **Step 4: Restore and verify 15% bottle demo only after success**

Restore the backed-up normal configuration, verify exact diff, place the
bottle at A and execute the agreed three-cycle sequence at `0.15`. Record
logs and results; do not increase beyond 0.15.

- [ ] **Step 5: Record evidence and commit only verified configuration/report**

Update validation counts only for cycles actually observed. Commit exact
configuration and report files without adding generated logs or unrelated
dirty files.
