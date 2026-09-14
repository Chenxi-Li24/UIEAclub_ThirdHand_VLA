# Contained Startouch Runtime Implementation Plan

> Historical plan: the 2026-08-24 approved safety-hardening plan supersedes
> direct host-SDK loading and every claim that vendor `cleanup()` proves motor
> depower.  See `2026-08-24-startouch-safety-hardening.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained, independently debuggable Startouch Action runtime inside `PinZiZhuaQuSkill` that consumes a bottle number, uses the existing VA workflow, and produces a fail-closed full upright pick-and-place plan without touching live hardware during development.

**Architecture:** Keep the existing L-to-VA HTTP contract and Vision workflow unchanged. Add a local Python JSON-Lines bridge around the installed Startouch SDK, a Node process adapter implementing the existing robot-client boundary, explicit flange-frame hand-eye semantics, and a fixed-XY/dynamic-Z placement strategy. Real execution remains locked until both physical hand-eye validation and full path validation artifacts are approved.

**Tech Stack:** Python 3.10+, Node.js 24, Python standard library, NumPy 1.26.4, Node `child_process`, Node test runner, pytest 8.4.2, YAML 2.9.0, installed Startouch SDK.

**Spec:** `docs/superpowers/specs/2026-08-23-contained-startouch-runtime-design.md`

## Global Constraints

- Every created or modified project source, config, test, debug script, derived calibration artifact, and attribution file lives under `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill`.
- `/home/nieqingcao/TH-Fanxy` and `/home/nieqingcao/th0814/TH_MK_D/UIEAclub_ThirdHand_VLA-control-fixed-a-to-b` are read-only references and never runtime import paths.
- Do not copy the complete `TH-Fanxy`; adapt only the minimum MIT-permitted bridge behavior and record its source in `native/startouch/NOTICE.md`.
- The installed Startouch SDK remains an external hardware dependency selected by configuration; simulation and automated tests must not import it.
- Automated tests must not connect to the Lumos camera, `can0`, or any real robot, and must not start, stop, or restart the existing port-3000 service.
- Reuse `/tmp/startouch-web-can0.lock`; lock contention is a hard `robot_resource_locked` failure.
- Keep `configs/action.yaml` at `execution_enabled: false`, imported hand-eye status pending, and path validation inactive.
- All lengths use metres, orientations use radians, joints use degrees, velocities use degrees/second, and gripper feedback uses metres.
- Each production behavior follows RED-GREEN-REFACTOR: write one behavior test, observe the expected failure, add the minimum implementation, rerun the focused test, then run the module suite.
- Preserve all unrelated modified and untracked files already present in the shared worktree; stage only files named by the current task.

## File and Responsibility Map

### New files

- `native/startouch/__init__.py`: package marker only.
- `native/startouch/protocol.py`: strict command/event validation and protocol constants; no SDK import.
- `native/startouch/backends.py`: simulated backend, real SDK backend, CAN preflight, and file-lock ownership.
- `native/startouch/startouch_bridge.py`: JSON-Lines CLI/process lifecycle; no VA business logic.
- `native/startouch/NOTICE.md`: MIT source attribution, adaptations, and SDK non-vendoring statement.
- `src/thirdhand_va/action/adapters/startouch_process_client.js`: Node child-process lifecycle and `RobotClient`-compatible state/events.
- `src/thirdhand_va/action/adapters/robot_client_factory.js`: explicit `startouch_process` or `websocket` backend construction.
- `src/thirdhand_va/action/calibration/import_handeye.py`: deterministic importer from the completed calibration output to the local v3 contract.
- `configs/calibration/lumos-handeye.pending.json`: immutable local pending calibration derivative.
- `tests/action/adapters/test_startouch_protocol.py`: protocol, simulation, lock, completion, and stop tests.
- `tests/action/adapters/startouch_process_client.test.js`: real child-process adapter behavior using the simulator.
- `tests/action/adapters/robot_client_factory.test.js`: explicit backend selection and no-fallback tests.
- `tests/action/calibration/test_import_handeye.py`: source hash and v3 derivative tests.
- `scripts/action/debug_startouch_protocol.js`: standalone simulated bridge debug entry.
- `scripts/action/debug_execution_plan.js`: standalone placement-plan debug entry.

### Modified files

- `src/thirdhand_va/common/contracts/arm_state.py`: rename the observed pose to explicit robot-flange semantics.
- `src/thirdhand_va/action/adapters/camera_bridge.js`: forward explicit flange state to Vision.
- `src/thirdhand_va/action/adapters/robot_ws_client.js`: expose a declared pose frame and stop-proof mode for compatibility.
- `src/thirdhand_va/action/calibration/handeye.py`: load v3 `T_flange_camera`, fail closed on ambiguous v2 semantics, and project from `T_base_flange`.
- `src/thirdhand_va/action/alignment/visual_align_controller.js`: consume explicit flange state and apply the configured base-frame offset exactly once.
- `src/thirdhand_va/action/config.js`: validate robot backend, SDK path, grasp offset, dynamic placement, and range-bound validation artifacts.
- `configs/action.yaml`: add inactive self-contained Startouch backend and fixed-XY/dynamic-Z candidates.
- `src/thirdhand_va/action/evidence/action_evidence.js`: bind sensed bottle point, commanded flange point, and offset into immutable evidence.
- `src/thirdhand_va/action/grasp/execution_plan.js`: derive fixed-XY/dynamic-Z waypoints and export the geometry helper.
- `src/thirdhand_va/action/grasp/workflow.js`: evaluate the derived geometry and support verified depowered-stop acknowledgements.
- `src/thirdhand_va/action/safety/execution_gate.js`: check every derived waypoint and offset/path gates.
- `apps/bottle_pick/web_server.js`: construct the configured backend only after authorization gates pass.
- `scripts/action/debug_calibration.py`: print v3 coordinate semantics and blockers.
- `.vscode/launch.json`: add bridge and placement standalone F5 entries.
- `.vscode/tasks.json`: add focused offline bridge tests.
- `README.md`, `docs/action/modules.md`, `docs/integration/contracts.md`, `docs/dependencies.md`: document module ownership, commands, protocol, sources, and licensing.

### Existing tests updated

- `tests/common/test_arm_state.py`
- `tests/action/adapters/camera_bridge.test.js`
- `tests/action/adapters/robot_ws_client.test.js`
- `tests/action/calibration/test_handeye.py`
- `tests/action/alignment/visual_align_controller.test.js`
- `tests/action/config.test.js`
- `tests/action/evidence/action_evidence.test.js`
- `tests/action/grasp/execution_plan.test.js`
- `tests/action/grasp/workflow.test.js`
- `tests/action/safety/execution_gate.test.js`
- `tests/integration/web_server.test.js`
- `tests/integration/test_debug_entrypoints.py`

---

### Task 1: Strict Startouch protocol and zero-hardware simulator

**Files:**
- Create: `native/startouch/__init__.py`
- Create: `native/startouch/protocol.py`
- Create: `native/startouch/backends.py`
- Create: `native/startouch/startouch_bridge.py`
- Create: `tests/action/adapters/test_startouch_protocol.py`

**Interfaces:**
- Consumes: newline-delimited dictionaries with `cmd` and correlated `request_id`.
- Produces: `validate_command(message: Mapping[str, Any]) -> RobotCommand`, `SimulatedBackend`, `BridgeRuntime.run_line(line: str) -> tuple[dict[str, Any], ...]`, and the `thirdhand-startouch-bridge-v1` ready/state/completion events used by Task 3.

- [ ] **Step 1: Write failing protocol and simulator tests**

Add tests whose independently derived expectations include:

```python
def test_simulator_emits_explicit_flange_state_and_correlated_move_completion():
    runtime = BridgeRuntime(SimulatedBackend(), monotonic_ns=CounterClock(1000))
    events = runtime.run_line(json.dumps({
        "cmd": "move_l",
        "request_id": "move-1",
        "flange_position_m": [0.40, 0.05, 0.18],
        "flange_euler_rad": [0.0, 0.0, 0.0],
        "duration_sec": 3.334,
    }))

    assert events[-1]["request_id"] == "move-1"
    assert events[-1]["command"] == "move_l"
    assert events[-1]["reached"] is True
    assert events[-1]["actual_flange_position_m"] == [0.40, 0.05, 0.18]
    state = runtime.state_event()
    assert state["pose_frame"] == "robot_flange"
    assert state["state_sequence"] > 0
    assert state["producer_monotonic_ns"] > 0
```

Also test that missing/duplicate request IDs, NaN, wrong vector lengths, duration outside `0.001..30.0` seconds, and unknown commands return correlated `error` events; `--simulate` must leave `startouch` absent from `sys.modules`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/adapters/test_startouch_protocol.py -q
```

Expected: collection fails because `native.startouch.protocol`, `backends`, and `startouch_bridge` do not exist.

- [ ] **Step 3: Implement the protocol constants and validation**

Define these exact protocol declarations in `protocol.py`:

```python
PROTOCOL_SCHEMA = "thirdhand-startouch-bridge-v1"
LOW_LEVEL_PROTOCOL = "thirdhand-robot-lowlevel-v1"
COMMANDS = frozenset({
    "connect", "get_state", "move_l", "move_joint",
    "gripper", "software_stop", "disconnect",
})
POSE_FRAME = "robot_flange"
STATE_UNITS = {
    "position": "m", "orientation": "rad", "joints": "deg",
    "joint_velocity": "deg/s", "gripper": "m",
}
```

`validate_command()` returns a frozen `RobotCommand` dataclass and rejects extra keys, non-finite values, unsafe speed, malformed request IDs, and non-flange pose fields.

- [ ] **Step 4: Implement the deterministic simulator and bridge loop**

`SimulatedBackend` starts at flange pose `[0.45, 0.0, 0.25, 0.0, 0.0, 0.0]`, six zero joints, six zero velocities, gripper width `0.080`, healthy/stationary/connected true. A valid move updates the flange pose before emitting `reached: true`; a gripper command maps normalized position `0..1` to width `0..0.080`.

`BridgeRuntime` owns a strictly increasing uint53 sequence and `time.monotonic_ns()` timestamp. The CLI emits one ready event, processes stdin one line at a time, flushes every JSON event, and supports:

The ready event includes `bridge_content_id` computed from the project-local bridge source set and `runtime_config_id` computed from canonical non-secret runtime settings. Both use `sha256:<64 lowercase hex>` so Node can bind runtime evidence to the exact implementation and configuration.

```bash
python native/startouch/startouch_bridge.py --simulate
```

- [ ] **Step 5: Run focused and Python Action tests**

Run:

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/adapters/test_startouch_protocol.py tests/action -q
```

Expected: all selected tests pass; no camera or robot hardware tests are collected.

- [ ] **Step 6: Commit Task 1**

```bash
git add native/startouch/__init__.py native/startouch/protocol.py \
  native/startouch/backends.py native/startouch/startouch_bridge.py \
  tests/action/adapters/test_startouch_protocol.py
git commit -m "feat: add simulated Startouch bridge protocol"
```

---

### Task 2: Real SDK backend, resource ownership, and truthful stop

**Files:**
- Modify: `native/startouch/backends.py`
- Modify: `native/startouch/startouch_bridge.py`
- Modify: `tests/action/adapters/test_startouch_protocol.py`
- Create: `native/startouch/NOTICE.md`

**Interfaces:**
- Consumes: `SdkBackendConfig(sdk_path, can_interface, lock_file, gripper_max_width_m)` and the installed SDK methods `connect()`, `get_ee_pose_euler()`, `get_joint_positions()`, `get_joint_velocities()`, `move_l()`, gripper APIs, and `cleanup()`.
- Produces: the same backend protocol as `SimulatedBackend`; `ResourceLockedError("robot_resource_locked")`; software-stop completion only when SDK cleanup succeeds.

- [ ] **Step 1: Write failing safety tests with a complete fake SDK arm**

The fake mirrors every SDK method the backend consumes. Add these behavior tests:

```python
def test_cleanup_failure_never_claims_depowered(tmp_path):
    arm = FakeSdkArm(cleanup_error=RuntimeError("cleanup failed"))
    backend = SdkBackend(config(tmp_path), arm_factory=lambda **kwargs: arm)
    backend.connect()

    with pytest.raises(StopNotConfirmedError, match="software_stop_not_confirmed"):
        backend.software_stop()

    assert backend.depowered is False


def test_same_can_lock_rejects_second_owner(tmp_path):
    first = CanOwner(tmp_path / "startouch-web-can0.lock")
    second = CanOwner(tmp_path / "startouch-web-can0.lock")
    first.acquire()
    with pytest.raises(ResourceLockedError, match="robot_resource_locked"):
        second.acquire()
```

Add a move test where SDK returns a pose outside tolerance and assert `reached` is false with literal position/orientation errors.

- [ ] **Step 2: Run and verify RED**

Run the same focused pytest command from Task 1.

Expected: failures name missing `SdkBackend`, `CanOwner`, and `StopNotConfirmedError` behaviors.

- [ ] **Step 3: Implement real-backend boundaries without importing SDK at module load**

The backend constructor receives an `arm_factory` for tests. Production factory inserts the configured SDK path only inside `connect()` and imports the verified Startouch class there. `get_ee_pose_euler()` is declared and emitted as flange pose because the installed SDK documents its end-effector state as flange state.

Use nonblocking `fcntl.flock(LOCK_EX | LOCK_NB)` on the exact configured lock path. Always release the lock on a successful cleanup or failed connection attempt. Never remove another process's lock file.

- [ ] **Step 4: Implement completion evidence and truthful software stop**

After `move_l`, read actual flange pose and return:

```python
{
    "reached": position_error_m <= 0.005 and orientation_error_rad <= 0.035,
    "actual_flange_position_m": actual_position,
    "actual_flange_euler_rad": actual_euler,
    "position_error_m": position_error_m,
    "orientation_error_rad": orientation_error_rad,
}
```

Call `cleanup()` for `software_stop`. Only a successful call returns `stopped: true`, `depowered: true`, `applied_state_sequence`, and `applied_producer_monotonic_ns`; exceptions become an error and leave depowered false.

- [ ] **Step 5: Add attribution and licensing record**

`NOTICE.md` records the two local read-only source paths, the upstream MIT repository URL, the specific behaviors adapted, the date, and that the vendor SDK is linked/imported externally and not redistributed.

- [ ] **Step 6: Run focused tests and commit Task 2**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/adapters/test_startouch_protocol.py -q
git add native/startouch/backends.py native/startouch/startouch_bridge.py \
  native/startouch/NOTICE.md tests/action/adapters/test_startouch_protocol.py
git commit -m "feat: add fail-closed Startouch SDK backend"
```

---

### Task 3: Node Startouch process client

**Files:**
- Create: `src/thirdhand_va/action/adapters/startouch_process_client.js`
- Create: `tests/action/adapters/startouch_process_client.test.js`
- Create: `scripts/action/debug_startouch_protocol.js`

**Interfaces:**
- Consumes: a spawned bridge that emits `thirdhand-startouch-bridge-v1` JSON Lines and named preset definitions supplied by the validated Action config.
- Produces: `StartouchProcessClient extends EventEmitter` with `connect(): boolean`, `send(command): boolean`, `getRobotState(): object | null`, `shutdown(): void`, `connected`, `protocolReady`, and `stopProofMode === "depowered_ack"`.

- [ ] **Step 1: Write failing process-client tests against the real simulator process**

Use Node's real `child_process.spawn` and the local Python simulator. Assert the public behavior:

```javascript
test('process client completes handshake and exposes fresh flange state', async t => {
  const client = new StartouchProcessClient({
    pythonExecutable: PYTHON,
    bridgePath: path.resolve('native/startouch/startouch_bridge.py'),
    bridgeArgs: ['--simulate'],
  });
  t.after(() => client.shutdown());

  assert.equal(client.connect(), true);
  await onceReady(client);
  const state = client.getRobotState();
  assert.equal(state.poseFrame, 'robot_flange');
  assert.equal(state.connected, true);
  assert.equal(state.stateFresh, true);
  assert.deepEqual(state.flangePositionM, [0.45, 0.0, 0.25]);
});
```

Add separate tests for correlated `move_l`, wrong protocol version, malformed stdout, child exit, stale state, concurrent commands, and a software-stop response with `depowered: false`.

- [ ] **Step 2: Run and verify RED**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/startouch_process_client.test.js
```

Expected: module-not-found failure for `startouch_process_client.js`.

- [ ] **Step 3: Implement child lifecycle and strict ready handshake**

Validate exact schema, low-level version, complete command set, units, `pose_frame: robot_flange`, correlated completions, sequence type, producer clock type, `bridge_content_id`, and `runtime_config_id`. Buffer partial stdout chunks and split only on newline. Parse failures emit `robot_message_invalid` and close the client fail-closed.

- [ ] **Step 4: Implement command mapping and state normalization**

Map the existing Action commands exactly:

```javascript
{
  cmd: 'move_l',
  request_id: command.request_id,
  flange_position_m: command.position,
  flange_euler_rad: command.euler,
  duration_sec: command.time_sec,
}
```

For `{cmd: 'preset', name: 'home'}`, resolve the validated six-element degree vector from `presets`, send a wire-level `move_joint`, and translate its correlated completion back to public command `preset` so the existing GraspController contract stays unchanged. Map Python `robot_state` to immutable camel-case fields, retaining sequence/timestamp freshness checks. `software_stop` completion is emitted only with `stopped: true` and `depowered: true`; process exit alone never creates a stop completion.

- [ ] **Step 5: Add standalone simulation debug entry**

`debug_startouch_protocol.js --simulate` connects, prints ready/state, sends one bounded simulated move and gripper cycle, sends simulated stop, prints correlated events, and exits nonzero on any failed invariant. It must reject execution without `--simulate` so pressing F5 cannot connect hardware.

- [ ] **Step 6: Run focused tests and commit Task 3**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/startouch_process_client.test.js
git add src/thirdhand_va/action/adapters/startouch_process_client.js \
  tests/action/adapters/startouch_process_client.test.js \
  scripts/action/debug_startouch_protocol.js
git commit -m "feat: add Startouch process robot client"
```

---

### Task 4: Explicit flange-state contract and v3 hand-eye import

**Files:**
- Modify: `src/thirdhand_va/common/contracts/arm_state.py`
- Modify: `tests/common/test_arm_state.py`
- Modify: `src/thirdhand_va/action/adapters/camera_bridge.js`
- Modify: `tests/action/adapters/camera_bridge.test.js`
- Modify: `src/thirdhand_va/action/adapters/robot_ws_client.js`
- Modify: `tests/action/adapters/robot_ws_client.test.js`
- Modify: `src/thirdhand_va/action/alignment/visual_align_controller.js`
- Modify: `tests/action/alignment/visual_align_controller.test.js`
- Modify: `src/thirdhand_va/action/grasp/workflow.js`
- Create: `src/thirdhand_va/action/calibration/import_handeye.py`
- Modify: `src/thirdhand_va/action/calibration/handeye.py`
- Create: `tests/action/calibration/test_import_handeye.py`
- Modify: `tests/action/calibration/test_handeye.py`
- Create: `configs/calibration/lumos-handeye.pending.json`
- Modify: `scripts/action/debug_calibration.py`

**Interfaces:**
- Consumes: bridge state `pose_frame=robot_flange`, `flange_position_m`, `flange_euler_rad`; calibration source SHA-256 `05e5c8680193dad6bb72370e7ba29c8afafee885f4f139250ca1b9d76303be7c`.
- Produces: `ArmState.flange_position_m`, `ArmState.flange_euler_rad`, `HandEyeCalibration.t_flange_camera`, and `import_handeye(source_path, expected_sha256) -> dict[str, Any]`.

- [ ] **Step 1: Write failing flange-contract and importer tests**

The ArmState test must reject a message that omits `pose_frame` or uses `configured_tool_tcp`. The calibration importer test uses a minimal source fixture with the real matrix and asserts the v3 coordinate declaration and pending gates:

```python
artifact = import_handeye(source, expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
assert artifact["schema"] == "thirdhand-handeye-calibration-v3"
assert artifact["robot_state_semantics"] == "T_base_flange"
assert artifact["extrinsic_semantics"] == "T_flange_camera"
assert artifact["physical_validation"]["status"] == "pending"
assert artifact["approved_for_bottle_grasp"] is False
```

Add a hand-checked matrix-chain test where flange translation, camera translation, and camera point produce a literal base point. Add a v2 artifact test proving ambiguous `configured_tool_tcp` can load for diagnosis but cannot become approved.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/common/test_arm_state.py tests/action/calibration/test_import_handeye.py \
  tests/action/calibration/test_handeye.py -q
```

Expected: missing importer and old TCP-field assertions fail.

- [ ] **Step 3: Migrate the shared state contract to flange semantics**

Require the incoming message shape:

```python
{
    "type": "arm_state",
    "pose_frame": "robot_flange",
    "flange_position_m": [0.4, 0.1, 0.2],
    "flange_euler_rad": [0.0, 0.0, 0.0],
    "stationary": True,
}
```

Update CameraBridge forwarding, workflow arm-state forwarding, and VisualAlignController robot-state reads to use `flangePositionM`/`flangeEulerRad`. The WebSocket compatibility adapter declares `poseFrame` only if its capability response explicitly declares `robot_flange`; otherwise it cannot make `robotReady()` true for v3 calibration.

- [ ] **Step 4: Implement deterministic v3 import and loading**

The importer verifies the exact source bytes, copies the source matrix unchanged, captures source path/hash, camera identity, numerical metrics, and writes no approval. `HandEyeCalibration.load()` accepts v3 explicitly; v2 remains diagnostic-only unless its semantics are explicitly `robot_flange`.

The runtime projection becomes exactly:

```python
t_base_camera = rpy_xyz_transform(
    arm_state.flange_position_m, arm_state.flange_euler_rad
) @ calibration.t_flange_camera
```

- [ ] **Step 5: Generate and verify the local pending artifact**

Run the project-local importer against the named source and write only into the project:

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m thirdhand_va.action.calibration.import_handeye \
  --source /home/nieqingcao/th0814/相机手眼标定/2026-08-17_250801DR48FP25002738_eye_in_hand/final/solution_85a58f8a28ac/derived/luming_eye_in_hand_calibration.json \
  --expected-sha256 05e5c8680193dad6bb72370e7ba29c8afafee885f4f139250ca1b9d76303be7c \
  --output configs/calibration/lumos-handeye.pending.json
```

Run `debug_calibration.py` and verify it prints `T_base_flange`, `T_flange_camera`, `handeye_physical_validation_pending`, and `handeye_activation_locked`.

- [ ] **Step 6: Run affected tests and commit Task 4**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/common tests/action/calibration tests/integration/test_camera_bridge_script.py -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/camera_bridge.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/robot_ws_client.test.js
git add src/thirdhand_va/common/contracts/arm_state.py tests/common/test_arm_state.py \
  src/thirdhand_va/action/adapters/camera_bridge.js \
  tests/action/adapters/camera_bridge.test.js \
  src/thirdhand_va/action/adapters/robot_ws_client.js \
  tests/action/adapters/robot_ws_client.test.js \
  src/thirdhand_va/action/alignment/visual_align_controller.js \
  tests/action/alignment/visual_align_controller.test.js \
  src/thirdhand_va/action/grasp/workflow.js \
  src/thirdhand_va/action/calibration/import_handeye.py \
  src/thirdhand_va/action/calibration/handeye.py \
  tests/action/calibration/test_import_handeye.py \
  tests/action/calibration/test_handeye.py \
  configs/calibration/lumos-handeye.pending.json scripts/action/debug_calibration.py
git commit -m "feat: import explicit flange hand-eye calibration"
```

---

### Task 5: Fixed-XY/dynamic-Z placement and provenance-bound offset

**Files:**
- Modify: `configs/action.yaml`
- Modify: `src/thirdhand_va/action/config.js`
- Modify: `tests/action/config.test.js`
- Modify: `src/thirdhand_va/action/evidence/action_evidence.js`
- Modify: `tests/action/evidence/action_evidence.test.js`
- Modify: `src/thirdhand_va/action/alignment/visual_align_controller.js`
- Modify: `tests/action/alignment/visual_align_controller.test.js`
- Modify: `src/thirdhand_va/action/grasp/execution_plan.js`
- Modify: `tests/action/grasp/execution_plan.test.js`
- Modify: `src/thirdhand_va/action/grasp/workflow.js`
- Modify: `src/thirdhand_va/action/safety/execution_gate.js`
- Modify: `tests/action/safety/execution_gate.test.js`
- Create: `scripts/action/debug_execution_plan.js`

**Interfaces:**
- Consumes: detected bottle center `target.detectedGraspPointM`, independently derived `target.commandedFlangeGraspM`, fixed XY `[0.26783482212847776, 0.010668622392713049]`, candidate base-frame flange offset `[0.0475, 0.0100, 0.0]`, and vertical clearance `0.10`.
- Produces: `deriveExecutionGeometry(target, config)` with distinct `detectedGraspM`, `commandedFlangeGraspM`, `pregraspM`, `liftM`, `prePlaceM`, `placeM`, `retreatM`; action evidence binds all geometry and validation IDs.

- [ ] **Step 1: Write failing dynamic placement tests**

Use two target fixtures whose Z values differ and assert literal waypoints:

```javascript
const low = deriveExecutionGeometry(target({
  detectedGraspPointM: [0.40, 0.05, 0.18],
  commandedFlangeGraspM: [0.4475, 0.06, 0.18],
}), config);
const high = deriveExecutionGeometry(target({
  detectedGraspPointM: [0.40, 0.05, 0.26],
  commandedFlangeGraspM: [0.4475, 0.06, 0.26],
}), config);

assert.deepEqual(low.commandedFlangeGraspM, [0.4475, 0.06, 0.18]);
assert.deepEqual(low.placeM, [0.267834822128, 0.010668622393, 0.18]);
assert.deepEqual(low.prePlaceM, [0.267834822128, 0.010668622393, 0.28]);
assert.equal(high.placeM[2], 0.26);
assert.equal(high.prePlaceM[2], 0.36);
```

Add separate tests proving an unvalidated offset, Z outside the artifact range, changed XY, changed clearance, changed speed, or changed home preset blocks execution.

- [ ] **Step 2: Run and verify RED**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/grasp/execution_plan.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/config.test.js
```

Expected: `deriveExecutionGeometry` is missing and the current fixed-XYZ assertions fail.

- [ ] **Step 3: Upgrade Action configuration and validation artifact contract**

Use this inactive project config shape:

```yaml
schema: "thirdhand-action-config-v2"
execution_enabled: false
robot:
  backend: "startouch_process"
  python_executable: "python3"
  bridge_path: "../native/startouch/startouch_bridge.py"
  sdk_path: "/home/nieqingcao/arm/startouch_sdk"
  can_interface: "can0"
  lock_file: "/tmp/startouch-web-can0.lock"
  ws_url: "ws://127.0.0.1:3000/ws"
  joint_limits_deg:
    - [-162, 162]
    - [-12, 201]
    - [-183, 0]
    - [-98, 98]
    - [-98, 98]
    - [-164, 164]
  joint_max_speeds_deg_s: [300, 300, 300, 1000, 1000, 1000]
  speed_scale: 0.05
  presets:
    home: [0, 0, 0, 0, 0, 0]
grasp:
  flange_offset_base_m: [0.0475, 0.0100, 0.0]
  offset_validated: false
place:
  strategy: "fixed_xy_keep_grasp_z"
  validated: false
  fixed_xy_m: [0.26783482212847776, 0.010668622392713049]
  grasp_z_range_m: null
  vertical_clearance_m: 0.10
  source_observation_path_validation_id: "sha256:c4b3d7a05a274e0527ca582db0157b19c7e0cb3d4e9c946690be23a882b4dce4"
  home_preset: "home"
  path_validation_file: null
  path_validation_sha256: null
```

The activated artifact schema is `thirdhand-pick-place-path-validation-v2`; it must bind fixed XY, allowed grasp-Z range, vertical clearance, flange offset, Euler orientation, linear speed, home preset, source observation path validation ID, physical validation, and execution approval. `execution_enabled: true` requires both `place.validated` and `grasp.offset_validated`.

- [ ] **Step 4: Implement geometry and bind it into evidence**

VisualAlignController receives `config.grasp.flange_offset_base_m`, aligns the flange to the offset pregrasp, and hands off both the untouched detected bottle point and the corrected commanded flange point. `deriveExecutionGeometry()` independently recomputes the correction and rejects a handoff mismatch, which prevents both missing and double-applied offsets:

```javascript
const commandedFlangeGraspM = add(
  target.detectedGraspPointM,
  config.grasp.flange_offset_base_m,
);
if (!sameVector(commandedFlangeGraspM, target.commandedFlangeGraspM)) {
  throw new TypeError('commanded_flange_grasp_mismatch');
}
const placeM = [config.place.fixed_xy_m[0], config.place.fixed_xy_m[1], commandedFlangeGraspM[2]];
const safePlaceZ = Number((placeM[2] + config.place.vertical_clearance_m).toFixed(12));
const prePlaceM = [placeM[0], placeM[1], safePlaceZ];
const retreatM = [...prePlaceM];
```

`buildActionEvidence()` emits `thirdhand-action-evidence-v2` and stores `detected_grasp_point_m`, `commanded_flange_grasp_point_m`, and `flange_offset_base_m`. `buildExecutionPlan()` rejects any evidence mismatch rather than recomputing and silently accepting it.

- [ ] **Step 5: Gate every derived waypoint and add the dry-run entry**

Evaluate workspace for pregrasp, commanded grasp, lift, pre-place, place, and retreat. `debug_execution_plan.js` loads an inactive fixture config with a test-only approved artifact object in memory, prints the sensed point, applied offset, all waypoints, units, and blockers, and never creates a robot client.

- [ ] **Step 6: Run Action module tests and commit Task 5**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node tests/action/config.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/evidence/action_evidence.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/grasp/execution_plan.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/safety/execution_gate.test.js
git add configs/action.yaml src/thirdhand_va/action/config.js \
  tests/action/config.test.js src/thirdhand_va/action/evidence/action_evidence.js \
  tests/action/evidence/action_evidence.test.js \
  src/thirdhand_va/action/alignment/visual_align_controller.js \
  tests/action/alignment/visual_align_controller.test.js \
  src/thirdhand_va/action/grasp/execution_plan.js \
  tests/action/grasp/execution_plan.test.js \
  src/thirdhand_va/action/grasp/workflow.js \
  src/thirdhand_va/action/safety/execution_gate.js \
  tests/action/safety/execution_gate.test.js scripts/action/debug_execution_plan.js
git commit -m "feat: plan fixed-xy dynamic-z bottle placement"
```

---

### Task 6: Runtime backend selection and backend-specific stop proof

**Files:**
- Create: `src/thirdhand_va/action/adapters/robot_client_factory.js`
- Create: `tests/action/adapters/robot_client_factory.test.js`
- Modify: `src/thirdhand_va/action/grasp/workflow.js`
- Modify: `tests/action/grasp/workflow.test.js`
- Modify: `apps/bottle_pick/web_server.js`
- Modify: `tests/integration/web_server.test.js`

**Interfaces:**
- Consumes: `config.robot.backend`, authorization result, and optional injected `spawn`/`WebSocketImpl` dependencies.
- Produces: `createRobotClient(config, dependencies)` and workflow stop modes `depowered_ack` or `fresh_state_boundary`.

- [ ] **Step 1: Write failing factory and stop-proof tests**

Factory behavior:

```javascript
assert.equal(createRobotClient(startouchConfig, deps).constructor.name, 'StartouchProcessClient');
assert.equal(createRobotClient(websocketConfig, deps).constructor.name, 'RobotWebSocketClient');
assert.throws(() => createRobotClient(unknownConfig, deps), /robot_backend_unsupported/);
```

Workflow behavior: for `stopProofMode: 'depowered_ack'`, a correlated completion with `stopped: true` and `depowered: true` finishes the cancelled workflow without waiting for a post-disconnect state. A completion with `depowered: false`, an uncorrelated completion, or process exit never finishes as confirmed. Existing WebSocket fresh-state-boundary tests remain unchanged.

- [ ] **Step 2: Run and verify RED**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/robot_client_factory.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/grasp/workflow.test.js
```

Expected: missing factory and unsupported depowered-ack behavior fail.

- [ ] **Step 3: Implement explicit factory with no real-backend fallback**

For `startouch_process`, resolve `bridge_path` relative to the Action config file, pass SDK/CAN/lock arguments, and do not append `--simulate`. For `websocket`, construct the existing client. A start failure is returned as `robot_resource_locked`, `robot_protocol_not_ready`, or `robot_start_failed`; never try the other backend automatically.

- [ ] **Step 4: Implement backend-specific stop proof**

Add `stopProofMode` to both robot clients. In `WorkflowClient.onRobotEvent()`, accept terminal depower only when:

```javascript
this.robotClient.stopProofMode === 'depowered_ack' &&
event.type === 'command_complete' &&
event.command === 'software_stop' &&
event.request_id === this.stopPending.requestId &&
event.stopped === true &&
event.depowered === true
```

Otherwise keep the existing fresh-state boundary or fail `software_stop_not_confirmed`.

- [ ] **Step 5: Wire the web server after all authorization gates**

`main()` must call the factory only inside the existing `robotEnabled` branch and after `execution_enabled`, exact acknowledgement, hand-eye path, and runtime evidence checks. `robotReady()` requires protocol readiness, explicit `robot_flange` pose frame, fresh healthy stationary state, camera approval, and matching artifacts.

- [ ] **Step 6: Run focused suites and commit Task 6**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/adapters/robot_client_factory.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  tests/action/grasp/workflow.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node tests/integration/web_server.test.js
git add src/thirdhand_va/action/adapters/robot_client_factory.js \
  tests/action/adapters/robot_client_factory.test.js \
  src/thirdhand_va/action/grasp/workflow.js tests/action/grasp/workflow.test.js \
  apps/bottle_pick/web_server.js tests/integration/web_server.test.js
git commit -m "feat: wire contained Startouch runtime backend"
```

---

### Task 7: Independent debugging, documentation, and full offline verification

**Files:**
- Modify: `.vscode/launch.json`
- Modify: `.vscode/tasks.json`
- Modify: `tests/integration/test_debug_entrypoints.py`
- Modify: `README.md`
- Modify: `docs/action/modules.md`
- Modify: `docs/integration/contracts.md`
- Modify: `docs/dependencies.md`

**Interfaces:**
- Consumes: standalone commands delivered by Tasks 3–5.
- Produces: user-facing F5 entries, exact test commands, source/license map, and evidence-backed offline completion report.

- [ ] **Step 1: Write failing debug-entrypoint integration tests**

Run each real script in simulation/dry-run mode and assert behavior, not source text:

```python
bridge = subprocess.run(
    [NODE, "scripts/action/debug_startouch_protocol.js", "--simulate"],
    cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=15,
)
assert bridge.returncode == 0
payload = json.loads(bridge.stdout.strip().splitlines()[-1])
assert payload["ok"] is True
assert payload["hardware_connected"] is False
assert payload["stop_confirmed"] is True
```

Add an equivalent `debug_execution_plan.js --fixture tests/fixtures/integration/full-cycle.json` assertion that verifies fixed XY and dynamic Z output.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/integration/test_debug_entrypoints.py -q
```

Expected: new output contract assertions fail until the scripts and fixtures are aligned.

- [ ] **Step 3: Add VS Code launch and task entries**

Add:

- `Action: Debug Startouch Protocol (Simulated)` running Node with `--simulate`.
- `Action: Debug Fixed Placement Plan` running Node with the integration fixture.
- `Action: Startouch Offline Tests` running the focused Python and Node bridge suites.

Neither launch configuration carries robot-enable environment variables.

- [ ] **Step 4: Update module and integration documentation**

Document:

- which files own bridge protocol, SDK lifecycle, Node lifecycle, calibration, planning, and workflow;
- the stable L request `POST /api/va/start` with `target_id`;
- exact standalone commands and observable output;
- the pending hand-eye and path gates;
- OpenCV, Lumos, local MIT source paths, adaptations, licenses, and the decision not to add ROS/MoveIt;
- migration steps that copy only `PinZiZhuaQuSkill` plus reinstall the external SDK.

- [ ] **Step 5: Run all module and integration tests**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/common tests/vision tests/action tests/integration -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/npm test
```

Expected: all offline tests pass; hardware tests are not selected.

- [ ] **Step 6: Run independent debug commands**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  scripts/action/debug_startouch_protocol.js --simulate
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/debug_calibration.py configs/calibration/lumos-handeye.pending.json
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  scripts/action/debug_execution_plan.js \
  --fixture tests/fixtures/integration/full-cycle.json
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  scripts/action/debug_workflow.js --target-id 2 \
  --fixture tests/fixtures/integration/full-cycle.json
```

Expected: bridge reports simulation and confirmed simulated stop; calibration reports pending blockers; plan reports fixed XY/dynamic Z; workflow reports the full simulated action sequence with `robot_control_enabled=false`.

- [ ] **Step 7: Verify repository boundaries and commit Task 7**

```bash
git diff --check
git status --short
```

Confirm no file outside `PinZiZhuaQuSkill` was added or modified by this implementation and no unrelated pre-existing worktree file is staged. From the `PinZiZhuaQuSkill` working directory, inspect this feature with:

```bash
git diff --name-only HEAD -- .
```

```bash
git add .vscode/launch.json .vscode/tasks.json \
  tests/integration/test_debug_entrypoints.py README.md docs/action/modules.md \
  docs/integration/contracts.md docs/dependencies.md
git commit -m "docs: add standalone Startouch VA debugging"
```

## Completion Criteria

- Every new function with behavior has a test that was observed failing before implementation.
- The Python simulator and Node process client complete a full offline command cycle.
- A failed SDK cleanup cannot produce a depowered confirmation in Python, Node, or Workflow.
- Robot state and hand-eye math use explicit `robot_flange`, `T_base_flange`, and `T_flange_camera` semantics.
- The local calibration derivative matches the exact source hash and remains pending/locked.
- Fixed placement uses the selected XY and the current commanded grasp Z; the path artifact binds the permitted Z envelope and offset.
- The app selects the contained Startouch process backend without depending on `TH-Fanxy`.
- `configs/action.yaml` still has real execution disabled and no approved path artifact.
- All offline Python and JavaScript tests pass, and every documented standalone debug command runs without hardware.
- The final handoff names changed modules, reused sources/licenses, VS Code files, test commands, and the remaining real-hardware validation gates.
