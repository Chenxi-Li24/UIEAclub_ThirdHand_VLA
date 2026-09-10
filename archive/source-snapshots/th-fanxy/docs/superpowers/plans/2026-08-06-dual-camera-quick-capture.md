# 双相机外参快速采集页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Web 服务中提供一个不接触机械臂的双相机外参验证页面，快速收集 10 个通过质量门禁且姿态不同的 ChArUco 样本。

**Architecture:** 浏览器页面通过独立 Node 路由适配器调用现有 Python 双相机验证脚本。Python 继续拥有标定板检测、几何计算、姿态去重和原子证据写入，Node 只限制访问、进程与响应，前端只显示相机流和裁剪后的状态。

**Tech Stack:** Python 3.11、OpenCV、NumPy、Node.js、Express、原生 HTML/CSS/JavaScript、pytest、Node assert、Chrome DevTools Protocol。

## Global Constraints

- 标定目标固定为 12 列、9 行、15 mm 方格、11.25 mm 标记、`DICT_5X5_100`。
- 单样本门禁固定为公共角点不少于 24、D435 RMSE 不高于 1.5 px、Lumos P95 不高于 4 px。
- 新姿态相对每个已选姿态至少平移 15 mm 或旋转 3°。
- 采集页面与 API 不得导入或调用机械臂、CAN、夹爪、运动和抓取模块。
- 浏览器不得控制输出路径、候选外参路径、标定板配置路径、相机 URL 或样本 ID。
- API 不提供删除、重置、覆盖或任意命令执行能力。
- 所有响应保持 `executable: false`；相机外参通过后仍保留手眼与桌面标定 blockers。

---

### Task 1: Python 合格样本与 JSON 协议

**Files:**
- Modify: `web-control/server/vision_models/legacy_dual_camera_validation.py`
- Modify: `scripts/vision/validate_legacy_dual_camera.py`
- Modify: `tests/vision_deployment/test_legacy_dual_camera_validation.py`
- Modify: `tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`

**Interfaces:**
- Produces: `pose_is_distinct(candidate, previous, translation_m=0.015, rotation_deg=3.0) -> bool`
- Produces: CLI `--json`, `--status`, `--require-pass`, `--require-distinct`
- Produces: JSON `{schema_version, ok, action, sample, summary, safety}` or `{schema_version, ok:false, error}`

- [ ] **Step 1: Write failing geometry and append-gate tests**

```python
def test_pose_is_distinct_requires_translation_or_rotation_from_every_selected_pose():
    origin = result_at(x=0.0, yaw_deg=0.0)
    duplicate = result_at(x=0.014, yaw_deg=2.9)
    translated = result_at(x=0.015, yaw_deg=0.0)
    assert pose_is_distinct(duplicate, [origin]) is False
    assert pose_is_distinct(translated, [origin]) is True

def test_required_pass_and_distinct_gates_do_not_append_rejected_observations(tmp_path):
    append_fixture_observation(tmp_path, sample_id="pose-01", result=passing_at(0.0))
    with pytest.raises(CalibrationCaptureError, match="pose is not distinct"):
        append_fixture_observation(
            tmp_path,
            sample_id="pose-02",
            result=passing_at(0.0),
            require_pass=True,
            require_distinct=True,
        )
    assert manifest_samples(tmp_path) == ["pose-01"]
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py -q`

Expected: FAIL because `pose_is_distinct` and append gate parameters do not exist.

- [ ] **Step 3: Implement the public pose predicate and pre-write gates**

```python
def pose_is_distinct(candidate, previous, *, translation_m=0.015, rotation_deg=3.0):
    return all(
        np.linalg.norm(candidate.t_d435_from_board[:3, 3] - item.t_d435_from_board[:3, 3])
        >= translation_m
        or _rotation_delta_rad(candidate.t_d435_from_board, item.t_d435_from_board)
        >= math.radians(rotation_deg)
        for item in previous
    )
```

Call this predicate before any image or manifest write when `require_distinct=True`; reject `passes_pixel_gate=False` before write when `require_pass=True`.

- [ ] **Step 4: Add failing CLI JSON/status behavior tests**

Execute the script namespace with a temporary integrity-valid manifest and assert hand-derived fields:

```python
assert report == {
    "schema_version": 1,
    "ok": True,
    "action": "status",
    "sample": None,
    "summary": {
        "samples": 1,
        "required_samples": 10,
        "passing_pairs": 1,
        "distinct_poses": 1,
        "relative_extrinsic_validated": False,
        "remaining_blockers": [
            "pose_diversity_insufficient",
            "relative_extrinsic_validation_failed",
            "handeye_validation_missing",
            "table_validation_missing",
        ],
    },
    "safety": {"motion_or_robot_access": False, "executable": False},
}
```

Also assert that the classified duplicate error is `pose_not_distinct`, an invisible board is `target_not_visible`, and JSON never contains an absolute output path.

- [ ] **Step 5: Run the new CLI tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/vision_deployment/test_legacy_dual_camera_validation_cli.py -q`

Expected: FAIL because JSON/status mode is absent.

- [ ] **Step 6: Implement stable public reports and CLI modes**

Add pure helpers `public_validation_report(manifest, *, action)` and `classify_capture_error(error)`. `--status` reads and integrity-checks the manifest without opening either camera; capture JSON uses the same report shape after a successful append. Catch expected errors inside `main()` so JSON mode prints one bounded object and exits 2.

- [ ] **Step 7: Verify Task 1 and commit**

Run: `.venv/bin/python -m pytest tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py -q`

Expected: PASS.

```bash
git add web-control/server/vision_models/legacy_dual_camera_validation.py scripts/vision/validate_legacy_dual_camera.py tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py
git commit -m "feat(vision): gate quick calibration samples"
```

### Task 2: 独立 Node 采集 API

**Files:**
- Create: `web-control/server/calibration-capture-api.js`
- Create: `web-control/server/test/calibration-capture-api-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `CalibrationCaptureService.status() -> Promise<PublicReport>`
- Produces: `CalibrationCaptureService.capture() -> Promise<PublicReport>`
- Produces: `createCalibrationCaptureRouter({service, isLoopback}) -> express.Router`

- [ ] **Step 1: Write a failing real-router API smoke test**

Start an ephemeral Express server with an injected deterministic runner that returns the complete Python JSON contract. Assert:

```javascript
assert.equal((await get('/api/calibration/status')).body.summary.samples, 2);
assert.equal((await post('/api/calibration/capture')).body.sample.id, 'pose-03');
assert.equal((await Promise.all([
  post('/api/calibration/capture'), post('/api/calibration/capture')
])).some(item => item.status === 409), true);
assert.equal((await getAsNonLoopback('/api/calibration/status')).status, 403);
```

Verify the runner receives only service-owned paths and flags, and response JSON excludes command, cwd, stderr and absolute paths.

- [ ] **Step 2: Run the Node test and confirm RED**

Run: `node web-control/server/test/calibration-capture-api-smoke.js`

Expected: FAIL with module not found.

- [ ] **Step 3: Implement the service and router**

Use `spawn` without a shell, a 15-second timeout, 1 MiB combined output cap and one in-flight capture. Validate the Python JSON schema and allow-list only report fields. Map expected failures to HTTP 422, concurrent capture to 409, local-access failure to 403, timeout to 504 and internal protocol failure to 502.

```javascript
router.get('/status', requireLoopback, async (_req, res) => {
  await sendServiceResult(res, () => service.status());
});
router.post('/capture', requireLoopback, async (_req, res) => {
  await sendServiceResult(res, () => service.capture());
});
```

- [ ] **Step 4: Verify Task 2 and commit**

Run: `node web-control/server/test/calibration-capture-api-smoke.js`

Expected: PASS.

```bash
git add web-control/server/calibration-capture-api.js web-control/server/test/calibration-capture-api-smoke.js web-control/server/package.json
git commit -m "feat(web): add isolated calibration capture API"
```

### Task 3: 快速采集页面与纯前端状态模块

**Files:**
- Create: `web-control/web/calibration-capture.html`
- Create: `web-control/web/calibration-capture.js`
- Create: `web-control/server/test/calibration-capture-client-smoke.js`
- Modify: `web-control/web/camera-test.html`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `createCalibrationCaptureClient({fetchJson, elements, schedule, cancelSchedule})`
- Consumes: `GET /api/calibration/status`, `POST /api/calibration/capture`

- [ ] **Step 1: Write failing client state tests**

Exercise the real client module with simple DOM-like elements and complete response fixtures. Assert that 2/10 renders two passed cells, a capture disables the button until completion, `pose_not_distinct` gives a move/tilt instruction, and 10/10 with validation true reports that handeye/table remain blocked.

- [ ] **Step 2: Run the client test and confirm RED**

Run: `node web-control/server/test/calibration-capture-client-smoke.js`

Expected: FAIL with module not found.

- [ ] **Step 3: Implement the pure client state module**

Keep network/state transitions in `calibration-capture.js`; update text via `textContent` and progress nodes via `replaceChildren`. Poll status every 1500 ms only while the page is visible, coalesce overlapping polls, and never construct a WebSocket or robot command.

- [ ] **Step 4: Add the page shell**

Create responsive side-by-side `<img>` streams using `/camera_lumos` and `/camera_d435_raw`, a 10-cell progress strip, latest metrics, safety banner and one capture button. Add a navigation link from `camera-test.html`; do not add capture logic to that page.

- [ ] **Step 5: Verify Task 3 and commit**

Run: `node web-control/server/test/calibration-capture-client-smoke.js`

Expected: PASS.

```bash
git add web-control/web/calibration-capture.html web-control/web/calibration-capture.js web-control/web/camera-test.html web-control/server/test/calibration-capture-client-smoke.js web-control/server/package.json
git commit -m "feat(web): add dual-camera quick capture page"
```

### Task 4: 挂载、浏览器验证与真实服务检查

**Files:**
- Modify: `web-control/server/proxy.js`
- Create: `web-control/server/test/calibration-capture-browser-smoke.js`
- Modify: `web-control/server/package.json`
- Modify: `tests/web/test_web_ui_security.py`
- Modify: `web-control/README.md`

**Interfaces:**
- Consumes: `createCalibrationCaptureRouter`
- Produces: `/api/calibration/status`, `/api/calibration/capture`, `/calibration-capture.html`

- [ ] **Step 1: Write failing browser and security tests**

Start a controlled HTTP server exposing two SVG camera fixtures and deterministic calibration API responses. In headless Chrome assert both images are visible, the current sample/progress render, one click sends exactly one POST, duplicate-pose rejection is actionable, and the page source contains none of `move_joint`, `move_l`, `gripper`, `/ws`, `innerHTML` or arbitrary path inputs.

- [ ] **Step 2: Run tests and confirm RED**

Run: `node web-control/server/test/calibration-capture-browser-smoke.js && .venv/bin/python -m pytest tests/web/test_web_ui_security.py -q`

Expected: FAIL because routes are not mounted and final security contracts are absent.

- [ ] **Step 3: Mount the router and document operator flow**

Instantiate the service with repo-owned defaults in `proxy.js`, mount its router under `/api/calibration`, and add the page URL plus the 10-pose board movement instructions to `web-control/README.md`. Do not alter robot initialization or shutdown.

- [ ] **Step 4: Run focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py tests/web/test_web_ui_security.py -q
cd web-control/server && npm test
```

Expected: all focused Python and Node tests PASS.

- [ ] **Step 5: Restart only the simulated/read-only port 3100 service and verify runtime**

Do not touch the real port 3000 controller. Restart the known port 3100 simulated process, then run:

```bash
curl --fail --silent http://127.0.0.1:3100/api/calibration/status
curl --fail --silent http://127.0.0.1:3100/calibration-capture.html
curl --fail --silent http://127.0.0.1:3100/api/vision/status
```

Open the page and confirm both real camera streams render. If the board is not in both views, a capture must return `target_not_visible` without increasing the sample count; once the board is placed, use the page for pose 1.

- [ ] **Step 6: Final diff check and commit**

Run: `git diff --check && git status --short`

```bash
git add web-control/server/proxy.js web-control/server/test/calibration-capture-browser-smoke.js web-control/server/package.json tests/web/test_web_ui_security.py web-control/README.md
git commit -m "feat(vision): serve quick calibration workflow"
```
