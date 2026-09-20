# 通用瓶子 V+A Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个由上游 L 只传稳定瓶号即可调用、能自动完成普通不透明直立瓶识别、夹取、固定点直立放置和返回 Home 的完整 V+A Skill。

**Architecture:** 保留现有 `common -> vision -> action -> apps` 依赖方向。Lumos/XVisio、Grounding DINO、SAM 2、Norfair、OpenCV hand-eye 和 Startouch 通信均由 adapter 隔离；当前 Skill 自己拥有稳定编号、三维抓取几何、近距离重观察和 Pick-and-Place 状态机，旧 3000 服务只作为低层机器人通信边界。

**Tech Stack:** Ubuntu 20.04、Python 3.11、NumPy 1.26.4、opencv-python 4.11.0.86、PyYAML 6.0.2、Pillow 12.2.0、pytest 8.4.2、PyTorch 2.7.0+cu128、Transformers 4.56.2、Norfair 2.3.0、Node.js 24.18、ws 8.21.3、yaml 2.9.0、CMake 3.16、XVisio SDK。

**Spec:** `docs/superpowers/specs/2026-08-23-generic-bottle-va-skill-design.md`

## Global Constraints

- 正式源码和运行入口只位于 `$HOME/th0814/VA/bottlegrasp`；其他 ThirdHand 目录只读参考或通过 adapter 调用。
- 只使用序列号 `250801DR48FP25002738` 的单台 Lumos Ego STD RGB-D 末端相机；正式路径不得依赖 D435 或双相机变换。
- 第一版只支持不透明、直立、彼此分开且轮廓清楚的普通瓶；同时最多五个。
- 用户编号固定为 `1..5`；编号不随左右顺序变化；选中目标不得自动换成邻近瓶。
- TypeFZ 物理最大开口按 80 mm；正式执行宽度上限固定为 72 mm。
- `start <stable_id>` 一旦被正式入口接受，自动运行完整抓取、固定点放置和 Home；不增加闭合前人工继续步骤。
- 相机运动期间不积累可执行深度；每次预抓取移动后必须停稳并取得 3 至 5 个新运动 epoch 的稳定 RGB-D 结果。
- 库模块导入不得启动模型、相机、网络或机器人；所有真实硬件入口都必须显式授权。
- 在新入口通过离线 preflight、回放和模拟集成前，不重启当前在线桥接进程。
- 当前 Git 工作区含大量用户修改；每次只暂存任务列出的路径，禁止 `git add -A`、`git add .` 和覆盖无关文件。
- 每个任务严格执行 RED -> GREEN -> regression -> commit；测试失败时先用 `superpowers:systematic-debugging` 定位根因。
- 每个核心模块必须有 VS Code Remote-SSH 可直接运行的独立 Debug 入口。
- 跨进程 JSON 一律使用 `snake_case`；Python 内部使用 `snake_case`；JS adapter 在验证 JSON 后只向业务模块暴露 `camelCase`，不得在同一对象中混用两套命名。

---

## File Structure Map

### 新建文件

- `package.json`、`package-lock.json`：目标项目独立 Node 运行时和精确依赖。
- `requirements/vision-cu128.txt`：本机验证过的 Python/CUDA 直接依赖版本。
- `docs/dependencies.md`：外部来源、许可证、版本、采用/拒绝理由和验证命令。
- `scripts/runtime/preflight.py`：不触碰硬件的运行前检查。
- `src/thirdhand_va/vision/tracking/norfair_adapter.py`：Norfair 外部对象隔离层。
- `src/thirdhand_va/vision/tracking/stable_ids.py`：稳定编号、状态和保留/回收规则。
- `src/thirdhand_va/vision/selection/stable_selector.py`：按稳定 ID 选择，不做左右排序。
- `src/thirdhand_va/vision/geometry/grasp_candidates.py`：直立瓶多个侧夹候选和评分。
- `scripts/vision/debug_tracking.py`：稳定编号序列的独立可视化/JSON 调试。
- `src/thirdhand_va/action/calibration/solver.py`：OpenCV eye-in-hand 求解和数值验证。
- `scripts/action/calibrate_handeye.py`：离线标定清单入口。
- `src/thirdhand_va/action/config.js`：严格 Action YAML 加载器。
- `src/thirdhand_va/action/grasp/execution_plan.js`：不可变 Pick-and-Place 路径生成。
- `src/thirdhand_va/action/adapters/robot_ws_client.js`：3000 服务的低层 WS 机器人 adapter。
- `scripts/action/debug_workflow.js`：完整模拟 V+A 状态机入口。
- `scripts/action/validate_pick_place.js`：显式授权的真机整套循环入口。
- `tests/vision/tracking/test_stable_ids.py`、`test_norfair_adapter.py`：稳定轨迹测试。
- `tests/vision/selection/test_stable_selector.py`：稳定 ID 选择测试。
- `tests/vision/geometry/test_grasp_candidates.py`：候选生成和排序测试。
- `tests/fixtures/tracking/reorder.json`：跨帧重排和 detector ID 重置序列。
- `tests/fixtures/action/{alignment.json,approved-plan.json}`：视觉对准和完整动作离线输入。
- `tests/fixtures/integration/full-cycle.json`：端到端 V+A 模拟循环输入。
- `tests/action/calibration/test_solver.py`：合成 hand-eye 测试。
- `tests/action/config.test.js`、`tests/action/grasp/execution_plan.test.js`：Action 配置和计划测试。
- `tests/action/adapters/robot_ws_client.test.js`：机器人 WS adapter 测试。
- `tests/integration/test_runtime_preflight.py`、`va_service.test.js`：运行时和完整服务测试。
- `docs/hardware/generic-bottle-validation.md`：相机、标定和 30 次真机验收流程。

### 重点修改文件

- `pyproject.toml`、`configs/vision.yaml`、`configs/action.yaml`
- `src/thirdhand_va/common/config.py`
- `src/thirdhand_va/common/contracts/{arm_state.py,vision_result.py,vision-result.schema.json}`
- `src/thirdhand_va/vision/perception/{interfaces.py,bottle_filter.py,grounded_sam.py}`
- `src/thirdhand_va/vision/geometry/{pointcloud.py,grasp_pose.py,__init__.py}`
- `src/thirdhand_va/vision/{pipeline.py,tracking/__init__.py,selection/__init__.py}`
- `src/thirdhand_va/vision/adapters/event_publisher.py`
- `src/thirdhand_va/vision/visualization/overlay.py`
- `src/thirdhand_va/action/calibration/{handeye.py,__init__.py}`
- `src/thirdhand_va/action/alignment/visual_align_controller.js`
- `src/thirdhand_va/action/grasp/{grasp_controller.js,workflow.js}`
- `src/thirdhand_va/action/safety/{execution_gate.js,workspace_check.js}`
- `src/thirdhand_va/action/adapters/{camera_bridge.js,vision_client.js,vision_selection_api.js}`
- `src/thirdhand_va/action/operator/controller.js`
- `apps/bottle_pick/{camera_bridge.py,web_server.js,run.js}`
- `scripts/vision/{debug_perception.py,debug_geometry.py,debug_pipeline.py}`
- `scripts/action/{debug_calibration.py,debug_alignment.js,debug_grasp.js}`
- `.vscode/{launch.json,tasks.json}`、`README.md` 和模块/接口文档

---

### Task 1: 可复现依赖、许可证登记和只读 Preflight

**Files:**
- Modify: `pyproject.toml`
- Create: `requirements/vision-cu128.txt`
- Create: `package.json`
- Create: `package-lock.json`
- Create: `docs/dependencies.md`
- Create: `scripts/runtime/preflight.py`
- Create: `tests/integration/test_runtime_preflight.py`
- Modify: `tests/common/test_repository_layout.py`

**Interfaces:**
- Consumes: 当前 Python 3.11 环境、Node 24.18、规范 XVisio 可执行路径。
- Produces: `preflight.collect_report(project_root: Path) -> dict[str, object]`；退出码 0 表示离线运行条件成立，退出码 2 表示存在阻断。

- [ ] **Step 1: 写出失败的依赖与 preflight 测试**

```python
def test_preflight_reports_missing_assets_without_opening_hardware(tmp_path):
    report = preflight.collect_report(tmp_path)
    assert report["hardware_touched"] is False
    assert report["ready"] is False
    assert "xvisio_executable_missing" in report["blockers"]

def test_project_declares_python_and_node_runtime_manifests():
    assert Path("requirements/vision-cu128.txt").is_file()
    assert Path("package-lock.json").is_file()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_runtime_preflight.py tests/common/test_repository_layout.py -v`

Expected: FAIL because `scripts/runtime/preflight.py`、`package.json` 和 requirements 文件尚不存在。

- [ ] **Step 3: 写入精确直接依赖和独立 Node manifest**

```toml
[project.optional-dependencies]
learned = ["torch==2.7.0", "transformers==4.56.2"]
tracking = ["norfair==2.3.0"]
test = ["pytest==8.4.2"]
```

```json
{
  "name": "thirdhand-va-bottle-skill",
  "private": true,
  "engines": {"node": ">=24 <25"},
  "dependencies": {"ws": "8.21.3", "yaml": "2.9.0"},
  "scripts": {
    "test": "find tests/action tests/integration -name '*.js' -type f -print0 | sort -z | xargs -0 -n1 node"
  }
}
```

Run: `npm install --package-lock-only --ignore-scripts`

Expected: `package-lock.json` 固定 `ws` 和 `yaml` 依赖图，不创建或启动服务。

`requirements/vision-cu128.txt` 使用以下直接依赖：

```text
--extra-index-url https://download.pytorch.org/whl/cu128
numpy==1.26.4
PyYAML==6.0.2
opencv-python==4.11.0.86
Pillow==12.2.0
pytest==8.4.2
torch==2.7.0+cu128
transformers==4.56.2
norfair==2.3.0
-e .
```

- [ ] **Step 4: 实现纯只读 preflight 和复用登记**

```python
def collect_report(project_root: Path) -> dict[str, object]:
    blockers: list[str] = []
    executable = project_root / "build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        blockers.append("xvisio_executable_missing")
    for distribution, expected in EXPECTED_DISTRIBUTIONS.items():
        if installed_version(distribution) != expected:
            blockers.append(f"dependency_version_mismatch:{distribution}")
    return {"ready": not blockers, "blockers": blockers, "hardware_touched": False}
```

`docs/dependencies.md` 必须逐项记录 Lumos/XVisio、Grounded-SAM-2、SAM 2、Norfair、OpenCV、MoveIt MTC、Isaac、VGN、GPD、Contact-GraspNet 和 GraspNet baseline 的 URL、版本/提交、许可证、决定和验证命令。

- [ ] **Step 5: 运行模块测试和真实项目 preflight**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pip install -r requirements/vision-cu128.txt`

Run: `npm ci --ignore-scripts`

Run: `bash scripts/vision/build_native.sh`

Expected: 安装固定依赖并生成规范路径 `build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream`；编译不打开相机。

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_runtime_preflight.py tests/common/test_repository_layout.py -v`

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python scripts/runtime/preflight.py --json`

Expected: 测试 PASS；真实报告可因规范二进制或 Norfair 尚未安装而返回退出码 2，但必须准确列出阻断且 `hardware_touched=false`。

- [ ] **Step 6: 提交本任务**

```bash
git add pyproject.toml requirements/vision-cu128.txt package.json package-lock.json docs/dependencies.md scripts/runtime/preflight.py tests/integration/test_runtime_preflight.py tests/common/test_repository_layout.py
git commit -m "build: declare reproducible VA runtime"
```

---

### Task 2: 公共契约、稳定身份字段和严格配置

**Files:**
- Modify: `configs/vision.yaml`
- Modify: `configs/action.yaml`
- Modify: `src/thirdhand_va/common/config.py`
- Modify: `src/thirdhand_va/common/contracts/arm_state.py`
- Modify: `src/thirdhand_va/common/contracts/vision_result.py`
- Modify: `src/thirdhand_va/common/contracts/vision-result.schema.json`
- Modify: `src/thirdhand_va/common/contracts/__init__.py`
- Test: `tests/common/test_config.py`
- Test: `tests/common/test_arm_state.py`
- Test: `tests/common/test_contracts.py`
- Test: `tests/common/test_public_contracts.py`

**Interfaces:**
- Consumes: `RgbdFrame`、现有 `MaskCandidate`、`ArmState`。
- Produces: `TrackState`、`TrackedBottle`、扩展后的 `VisionDecision`；`VisionConfig` 增加稳定跟踪、重检测、几何和 provenance 参数。

- [ ] **Step 1: 写出契约 RED 测试**

```python
def test_tracked_bottle_has_separate_backend_and_user_identity(mask_candidate):
    track = TrackedBottle(
        stable_id=2, backend_track_id=91, state="confirmed",
        candidate=mask_candidate, centroid_xy=(120.0, 80.0),
        depth_supported=True, blockers=(),
    )
    assert track.stable_id == 2
    assert track.backend_track_id == 91

def test_arm_state_preserves_observed_and_received_monotonic_time():
    state = ArmState.from_message(message, received_monotonic_ns=200)
    assert state.observed_monotonic_ns == 150
    assert state.received_monotonic_ns == 200
```

- [ ] **Step 2: 运行测试并确认缺少新类型和字段**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/common/test_config.py tests/common/test_arm_state.py tests/common/test_contracts.py tests/common/test_public_contracts.py -v`

Expected: FAIL importing `TrackedBottle` and accessing `observed_monotonic_ns`。

- [ ] **Step 3: 实现不可变跟踪契约**

```python
TrackState = Literal["tentative", "confirmed", "occluded", "lost", "retired"]

@dataclass(frozen=True, slots=True)
class TrackedBottle:
    stable_id: int | None
    backend_track_id: int
    state: TrackState
    candidate: MaskCandidate
    centroid_xy: tuple[float, float]
    depth_supported: bool
    blockers: tuple[str, ...] = ()
```

为 `MaskCandidate` 增加只读 `descriptor`；为 `VisionDecision` 增加 `request_id`、`selected_stable_id`、`tracks`、`captured_monotonic_ns`、`camera_serial`、`registration_id`、`motion_epoch` 和 `evidence_id`。旧空间序数字段仅保留为不进入 v3 事件的兼容字段。

- [ ] **Step 4: 扩展严格配置并把执行宽度改为 0.072 m**

`configs/vision.yaml` 增加以下精确字段：

```yaml
camera_registration_id: "xvisio-sdk:250801DR48FP25002738"
max_visible_tracks: 5
track_confirmation_hits: 3
track_lost_timeout_ms: 2000
redetect_interval_frames: 15
mask_erosion_px: 2
upright_axis_max_angle_deg: 15.0
table_plane_distance_m: 0.008
min_grasp_clearance_m: 0.010
grasp_band_fractions: [0.35, 0.50, 0.65]
max_grasp_width_m: 0.072
```

`configs/action.yaml` 保持 `execution_enabled: false`，增加 `place.validated: false`、`place.point_m: null`、`place.pre_place_m: null`、`home_preset: home`。配置加载器必须允许未激活的空放置点，但安全门返回 `place_not_validated`。

- [ ] **Step 5: 更新 v3 JSON Schema 并运行契约测试**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/common -v`

Expected: PASS；72 mm 以上配置被拒绝，ArmState 的观测时间晚于接收时间时被拒绝。

- [ ] **Step 6: 提交本任务**

```bash
git add configs/vision.yaml configs/action.yaml src/thirdhand_va/common tests/common
git commit -m "feat: define stable bottle VA contracts"
```

---

### Task 3: 周期性 Grounding DINO 重检测和模型 provenance

**Files:**
- Modify: `src/thirdhand_va/vision/perception/interfaces.py`
- Modify: `src/thirdhand_va/vision/perception/grounded_sam.py`
- Modify: `src/thirdhand_va/vision/perception/bottle_filter.py`
- Test: `tests/vision/perception/test_grounded_sam.py`
- Test: `tests/vision/perception/test_bottle_candidates.py`
- Modify: `scripts/vision/debug_perception.py`

**Interfaces:**
- Consumes: `VisionConfig.redetect_interval_frames`、RGB 帧。
- Produces: `GroundedSamBackend.infer(rgb) -> tuple[RawCandidate, ...]`，每 15 帧重新运行 DINO 并重建 SAM 2 session；`model_provenance() -> dict[str, str]`。

- [ ] **Step 1: 写出新瓶出现和 descriptor 保留的 RED 测试**

```python
def test_backend_redetects_on_interval_and_discovers_new_objects(fake_models):
    backend = GroundedSamBackend(config_with(redetect_interval_frames=3))
    outputs = [backend.infer(frame) for frame in frames(4)]
    assert fake_models.dino_calls == 2
    assert {row.detection_id for row in outputs[-1]} == {10, 11}

def test_filter_preserves_masked_appearance_descriptor(raw_bottle, rgb):
    candidate = BottleCandidateFilter(config).filter(rgb, (raw_bottle,))[0]
    np.testing.assert_array_equal(candidate.descriptor, raw_bottle.descriptor)
```

- [ ] **Step 2: 运行感知测试并确认 RED**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/perception/test_grounded_sam.py tests/vision/perception/test_bottle_candidates.py -v`

Expected: FAIL because当前 backend 只在第一帧检测且 `MaskCandidate` 未接收 descriptor。

- [ ] **Step 3: 抽取检测/播种与传播路径**

```python
def infer(self, rgb):
    self._frame_count += 1
    detect_due = self._video_session is None or (
        (self._frame_count - 1) % self.config.redetect_interval_frames == 0
    )
    if detect_due:
        return self._detect_and_seed(rgb)
    return self._track_frame_image(rgb)
```

重检测时关闭旧 session、重新用 DINO 发现所有瓶子并用 SAM 2 播种；稳定用户编号由 Task 4 保留，不能依赖新的 detection ID。

- [ ] **Step 4: 增加模型来源和本地缓存检查**

```python
def model_provenance(self) -> dict[str, str]:
    return {
        "grounding_model": self.config.grounding_model,
        "sam_model": self.config.sam_model,
        "transformers_version": importlib.metadata.version("transformers"),
    }
```

`debug_perception.py` 输出候选数、掩膜像素、descriptor 维度、DINO/SAM 延迟和 provenance，不启动机器人。

- [ ] **Step 5: 运行感知回归**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/perception -v`

Expected: PASS；测试 fake 不下载模型、不访问相机。

- [ ] **Step 6: 提交本任务**

```bash
git add src/thirdhand_va/vision/perception scripts/vision/debug_perception.py tests/vision/perception
git commit -m "feat: periodically rediscover bottle instances"
```

---

### Task 4: Norfair 稳定编号、轨迹生命周期和稳定 ID 选择

**Files:**
- Create: `src/thirdhand_va/vision/tracking/norfair_adapter.py`
- Create: `src/thirdhand_va/vision/tracking/stable_ids.py`
- Modify: `src/thirdhand_va/vision/tracking/__init__.py`
- Create: `src/thirdhand_va/vision/selection/stable_selector.py`
- Modify: `src/thirdhand_va/vision/selection/__init__.py`
- Create: `scripts/vision/debug_tracking.py`
- Create: `tests/vision/tracking/test_norfair_adapter.py`
- Create: `tests/vision/tracking/test_stable_ids.py`
- Create: `tests/vision/selection/test_stable_selector.py`
- Create: `tests/fixtures/tracking/reorder.json`

**Interfaces:**
- Consumes: `tuple[MaskCandidate, ...]`、可选 detection->camera/world 三维点、`now_ns`、`camera_moving`。
- Produces: `StableTrackManager.update(candidates, now_ns, camera_moving, camera_points, world_points) -> tuple[TrackedBottle, ...]`、`reserve(stable_id, request_id) -> bool`、`release(request_id) -> None`、`available_ids -> tuple[int, ...]`；`StableSelectionRequest(stable_id, request_id)`。

- [ ] **Step 1: 写出编号不随左右顺序和 backend ID 改变的 RED 测试**

```python
def test_stable_ids_survive_reorder_and_backend_reseed(manager, frames):
    first = manager.update(frames.left_to_right, now_ns=1, camera_moving=False)
    second = manager.update(frames.right_to_left_new_detection_ids,
                            now_ns=2, camera_moving=False)
    assert physical_to_stable(first) == physical_to_stable(second)

def test_reserved_id_is_not_recycled_until_request_finishes(manager):
    manager.reserve(2, "req-2")
    manager.update((), now_ns=3_000_000_000, camera_moving=False)
    assert manager.available_ids == (1, 3, 4, 5)
    manager.release("req-2")
    assert 2 in manager.available_ids
```

- [ ] **Step 2: 运行测试并确认模块尚不存在**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/tracking/test_norfair_adapter.py tests/vision/tracking/test_stable_ids.py tests/vision/selection/test_stable_selector.py -v`

Expected: FAIL importing new modules。

- [ ] **Step 3: 实现 Norfair 外部对象隔离层**

```python
@dataclass(frozen=True, slots=True)
class Association:
    backend_track_id: int
    candidate: MaskCandidate

class NorfairTrackerAdapter:
    def update(self, candidates: tuple[MaskCandidate, ...]) -> tuple[Association, ...]:
        detections = [Detection(points=np.asarray([tracking_centroid(c.mask)]),
                                scores=np.asarray([c.score]), data=c,
                                embedding=c.descriptor, label="bottle")
                      for c in candidates]
        return self._associate(self._tracker.update(detections=detections))
```

`tracking_centroid()` 定义在本 adapter 内，不从旧 ordinal selector 导入。自定义距离同时使用 mask IoU、归一化中心距离和 descriptor 余弦距离；相机移动时关闭纯中心距离强匹配，三维强冲突直接拒绝关联。

- [ ] **Step 4: 实现用户编号和确定性生命周期**

```python
class StableTrackManager:
    def update(self, candidates, *, now_ns, camera_moving,
               camera_points=None, world_points=None) -> tuple[TrackedBottle, ...]:
        associations = self._adapter.update(candidates)
        self._apply_associations(associations, now_ns, camera_moving,
                                 camera_points or {}, world_points or {})
        self._expire_unreserved(now_ns)
        return self._snapshots()

    def reserve(self, stable_id: int, request_id: str) -> bool:
        track = self._track_by_stable_id(stable_id)
        if track is None or track.state != "confirmed" or self._reservation:
            return False
        self._reservation = (stable_id, request_id)
        return True

    def release(self, request_id: str) -> None:
        if self._reservation is not None and self._reservation[1] == request_id:
            self._reservation = None
```

`_apply_associations`、`_expire_unreserved`、`_snapshots` 和 `_track_by_stable_id` 都在同一文件内实现并由私有单元测试间接覆盖。连续 3 次命中才从 `tentative` 进入 `confirmed`；新确认轨迹取得最小可用 ID；未选轨迹丢失 2 秒退休；选中 ID 保留到 request 终止；容量超过五个时输出无编号且 blocker 为 `unnumbered_capacity_exceeded`。

- [ ] **Step 5: 实现稳定 ID selector 和调试入口**

```python
@dataclass(frozen=True, slots=True)
class StableSelectionRequest:
    stable_id: int
    request_id: str

class StableBottleSelector:
    def select(self, tracks, request):
        matches = [t for t in tracks if t.stable_id == request.stable_id]
        if not matches:
            return StableSelectionResult(None, ("target_id_not_found",))
        if matches[0].state != "confirmed":
            return StableSelectionResult(None, (f"target_{matches[0].state}",))
        return StableSelectionResult(matches[0], ())
```

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python scripts/vision/debug_tracking.py --fixture tests/fixtures/tracking/reorder.json`

Expected: JSON/可视化中同一物理瓶跨重排保持同一编号。

- [ ] **Step 6: 运行跟踪和选择测试**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/tracking tests/vision/selection -v`

Expected: PASS；旧左右 selector 测试可以保留为 legacy 单元测试，但正式稳定 selector 不导入它。

- [ ] **Step 7: 提交本任务**

```bash
git add src/thirdhand_va/vision/tracking src/thirdhand_va/vision/selection scripts/vision/debug_tracking.py tests/vision/tracking tests/vision/selection tests/fixtures/tracking
git commit -m "feat: assign stable bottle identities"
```

---

### Task 5: 直立瓶三维候选、桌面约束和 72 mm 安全门

**Files:**
- Modify: `src/thirdhand_va/vision/geometry/pointcloud.py`
- Create: `src/thirdhand_va/vision/geometry/grasp_candidates.py`
- Modify: `src/thirdhand_va/vision/geometry/grasp_pose.py`
- Modify: `src/thirdhand_va/vision/geometry/__init__.py`
- Create: `tests/vision/geometry/test_grasp_candidates.py`
- Modify: `tests/vision/geometry/test_grasp_pose.py`
- Modify: `tests/vision/geometry/test_pointcloud.py`
- Modify: `scripts/vision/debug_geometry.py`

**Interfaces:**
- Consumes: 注册 XYZ、实例 mask、`VisionConfig`。
- Produces: `GraspCandidate3D(pose, quality, height_fraction, clearance_m, blockers)`；`estimate_grasp_candidates(frame: RgbdFrame, candidate: MaskCandidate, config: VisionConfig) -> tuple[GraspCandidate3D, ...]`；兼容 `estimate_grasp_pose` 返回最高质量 pose。

- [ ] **Step 1: 写出几何 RED 测试**

```python
def test_upright_bottle_generates_ranked_middle_body_candidates(scene):
    candidates = estimate_grasp_candidates(*scene)
    assert len(candidates) >= 2
    assert candidates[0].quality >= candidates[-1].quality
    assert 0.35 <= candidates[0].height_fraction <= 0.65

def test_73mm_bottle_is_displayable_but_not_graspable(scene_73mm):
    with pytest.raises(GeometryRejected, match="grasp_width_exceeded"):
        estimate_grasp_pose(*scene_73mm)

def test_non_upright_axis_is_rejected(scene_tilted_25deg):
    with pytest.raises(GeometryRejected, match="bottle_not_upright"):
        estimate_grasp_pose(*scene_tilted_25deg)
```

- [ ] **Step 2: 运行几何测试并确认 RED**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/geometry -v`

Expected: FAIL because当前只产生一个 pose、未检查桌面法向和 72 mm blocker。

- [ ] **Step 3: 实现稳健桌面平面和瓶身安全带**

```python
def fit_table_plane(xyz, object_mask, *, distance_m):
    background = finite_points_outside(erode_mask(object_mask, radius=2), xyz)
    normal, offset = deterministic_ransac_plane(background, threshold=distance_m)
    return orient_normal_toward_camera(normal), offset

BODY_FRACTIONS = (0.35, 0.50, 0.65)
```

RANSAC 使用固定 seed 和 NumPy 线性代数，避免引入 Open3D 大依赖；算法来源和为何不引入重依赖记录到 `docs/dependencies.md`。

- [ ] **Step 4: 生成并排序多个侧夹候选**

```python
@dataclass(frozen=True, slots=True)
class GraspCandidate3D:
    pose: GraspPoseCamera
    quality: float
    height_fraction: float
    clearance_m: float
    blockers: tuple[str, ...] = ()

def estimate_grasp_candidates(frame, candidate, config):
    # mask erosion -> near coherent surface -> axis/table check -> body bands
    # -> width/clearance/depth/covariance score -> descending quality
    return tuple(sorted(accepted, key=lambda item: item.quality, reverse=True))
```

质量分量固定包含 depth ratio、点数饱和值、位置协方差、宽度余量和桌面间隙；没有候选时抛出最具体的结构化 `GeometryRejected`。

- [ ] **Step 5: 扩展独立几何调试输出**

`debug_geometry.py` 增加 `--output-json` 和 `--output-image`，输出所有候选、评分分量、轴线、桌面法向和阻断原因；不导入 pipeline 或 Action。

- [ ] **Step 6: 运行几何回归**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/geometry -v`

Expected: PASS；原有 mask XYZ、空洞和离群点测试继续通过。

- [ ] **Step 7: 提交本任务**

```bash
git add src/thirdhand_va/vision/geometry scripts/vision/debug_geometry.py tests/vision/geometry
git commit -m "feat: rank upright bottle grasp candidates"
```

---

### Task 6: VisionPipeline 使用稳定 ID、运动 epoch 和 v3 evidence

**Files:**
- Modify: `src/thirdhand_va/vision/pipeline.py`
- Modify: `src/thirdhand_va/vision/tracking/stability.py`
- Modify: `tests/vision/test_pipeline.py`
- Modify: `tests/vision/tracking/test_stability.py`
- Modify: `scripts/vision/debug_pipeline.py`

**Interfaces:**
- Consumes: `StableTrackManager`、`StableSelectionRequest`、Task 5 候选。
- Produces: `VisionPipeline.select(stable_id: int, request_id: str, force: bool = False) -> bool`、`release(request_id: str) -> None`、`begin_motion_epoch(epoch: int) -> None`、`process(frame: RgbdFrame, *, now_ns: int | None = None) -> VisionDecision`。

- [ ] **Step 1: 用稳定编号重写 pipeline RED 测试**

```python
def test_pipeline_selects_stable_id_after_left_right_reorder(scene_sequence):
    pipeline = VisionPipeline(config, backend)
    confirmed = process_until_confirmed(pipeline, scene_sequence.initial)
    chosen = confirmed.tracks[1].stable_id
    assert pipeline.select(chosen, "req-2") is True
    result = pipeline.process(
        scene_sequence.reordered,
        now_ns=scene_sequence.reordered.monotonic_ns + 1_000_000,
    )
    assert result.selected_stable_id == chosen
    assert physical_name(result.target) == "middle-bottle"

def test_motion_epoch_discards_old_stability_hits(pipeline, stable_scene):
    ready = process_until_ready(pipeline, stable_scene)
    pipeline.begin_motion_epoch(2)
    next_frame = stable_scene.next()
    moving = pipeline.process(next_frame, now_ns=next_frame.monotonic_ns + 1_000_000)
    assert moving.status == "uncertain"
    assert moving.reasons == ("camera_motion_active",)
    assert moving.stable_hits == 0
```

- [ ] **Step 2: 运行 pipeline 测试并确认旧 ordinal API 失败**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/test_pipeline.py tests/vision/tracking/test_stability.py -v`

Expected: FAIL because constructor仍要求 `SelectionRequest(side, ordinal)`。

- [ ] **Step 3: 改为所有瓶先跟踪、选中 ID 后授权**

```python
class VisionPipeline:
    def __init__(self, config, backend, *, tracker=None):
        self.config = config
        self.backend = backend
        self.tracker = tracker or StableTrackManager.from_config(config)
        self.selection = None
        self.motion_epoch = 0
        self.camera_moving = False
        self.stability = StabilityWindow(config)

    def select(self, stable_id: int, request_id: str, *, force=False) -> bool:
        request = StableSelectionRequest(stable_id, request_id)
        if self.selection == request and not force:
            return False
        if not self.tracker.reserve(stable_id, request_id):
            return False
        self.selection = request
        self.stability = StabilityWindow(self.config)
        return True

    def release(self, request_id: str) -> None:
        self.tracker.release(request_id)
        if self.selection is not None and self.selection.request_id == request_id:
            self.selection = None

    def begin_motion_epoch(self, epoch: int) -> None:
        if epoch <= self.motion_epoch:
            raise ValueError("motion epoch must strictly increase")
        self.motion_epoch = epoch
        self.stability = StabilityWindow(self.config)
```

每帧对所有瓶子建立 tracks 和几何摘要；只有选中 stable ID 进入 `StabilityWindow`。深度无效候选仍保留编号和 blockers，不因过滤重新编号。

- [ ] **Step 4: 构造可追溯 evidence ID**

```python
def evidence_id(decision_fields) -> str:
    encoded = json.dumps(decision_fields, sort_keys=True,
                         separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
```

哈希输入包含 frame、monotonic time、registration ID、motion epoch、stable ID、pose、宽度和 blockers；mask 图像不进入跨进程契约。

- [ ] **Step 5: 更新独立 pipeline 调试入口**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python scripts/vision/debug_pipeline.py --target-id 2 BUNDLE_DIR`

Expected: 终端逐帧输出所有 stable tracks、选中 ID、motion epoch、evidence ID 和状态。

- [ ] **Step 6: 运行 Vision pipeline 回归**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/test_pipeline.py tests/vision/tracking -v`

Expected: PASS；不再存在“无深度候选被移除导致编号前移”的行为。

- [ ] **Step 7: 提交本任务**

```bash
git add src/thirdhand_va/vision/pipeline.py src/thirdhand_va/vision/tracking/stability.py scripts/vision/debug_pipeline.py tests/vision/test_pipeline.py tests/vision/tracking
git commit -m "feat: drive vision by stable bottle id"
```

---

### Task 7: v3 视觉事件、稳定编号可视化和单 Lumos CameraBridge

**Files:**
- Modify: `src/thirdhand_va/vision/adapters/event_publisher.py`
- Modify: `src/thirdhand_va/vision/visualization/overlay.py`
- Modify: `src/thirdhand_va/action/adapters/vision_client.js`
- Modify: `src/thirdhand_va/action/adapters/camera_bridge.js`
- Modify: `apps/bottle_pick/camera_bridge.py`
- Modify: `tests/vision/adapters/test_bridge.py`
- Modify: `tests/vision/visualization/test_visualization.py`
- Modify: `tests/action/adapters/clients.test.js`
- Modify: `tests/action/adapters/camera_bridge.test.js`
- Modify: `tests/integration/test_camera_bridge_script.py`

**Interfaces:**
- Consumes: Task 6 `VisionDecision`。
- Produces: `thirdhand-va-detection-v3`、命令 `{type:"select_bottle",stable_id,request_id}`、只读 MJPEG/JSON。

- [ ] **Step 1: 写出 v3 事件和 overlay RED 测试**

```python
def test_v3_event_exposes_stable_ids_and_no_d435_fields(decision, provenance):
    event = build_detection_event(decision, provenance, b"jpeg")
    assert event["schema"] == "thirdhand-va-detection-v3"
    assert [item["stable_id"] for item in event["targets"]] == [1, 2, 3]
    assert "d435_sequence" not in json.dumps(event)

def test_overlay_marks_blocked_tracks_without_renumbering(
    rgb, decision_with_blocked_depth, render_metrics
):
    rendered = render_overlay(rgb, decision_with_blocked_depth, render_metrics)
    assert {"1", "2", "3", "2 BLOCKED depth_insufficient"} <= rendered.labels
```

- [ ] **Step 2: 运行事件、可视化和 bridge 测试并确认 RED**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/adapters tests/vision/visualization tests/integration/test_camera_bridge_script.py -v`

Run: `node tests/action/adapters/clients.test.js && node tests/action/adapters/camera_bridge.test.js`

Expected: FAIL because当前 schema 为 v2、命令仍为 side/ordinal、存在 D435 alias 和电源 hack。

- [ ] **Step 3: 实现 v3 serializer 和客户端深校验**

```python
target = {
    "stable_id": track.stable_id,
    "track_state": track.state,
    "detection_id": track.candidate.detection_id,
    "selected": track.stable_id == decision.selected_stable_id,
    "depth_valid": track.depth_supported,
    "blockers": list(track.blockers),
}
```

JS `VisionClient.accept()` 必须验证 schema、frame、monotonic time、registration ID、motion epoch、evidence ID、stable ID 唯一性、track state、pose 和 blockers 后才 emit。

- [ ] **Step 4: 重写 CameraBridge 为单 Lumos 稳定 ID 协议**

删除 D435 USB 电源循环、D435 命名和不存在的 active-view 配置默认值。允许命令精确键改为：

```javascript
select_bottle: ['type', 'stable_id', 'request_id'],
reset_target_pose_reference: ['type', 'request_id', 'motion_epoch'],
```

Python `consume_commands()` 调用 `pipeline.select(stable_id, request_id)`；机器人移动完成时调用 `begin_motion_epoch()`，不再构造左右 `SelectionRequest`。

- [ ] **Step 5: 更新 overlay 和编码错误恢复**

所有 confirmed track 都显示稳定 ID；红色显示 blocker、绿色显示可夹取、选中目标加粗。JPEG 编码异常由 capture worker 转换为 `preview_encode_failed` 事件并继续读取后续帧，不静默终止线程。

- [ ] **Step 6: 运行跨语言回归**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/adapters tests/vision/visualization tests/integration/test_camera_bridge_script.py -v`

Run: `node tests/action/adapters/clients.test.js && node tests/action/adapters/camera_bridge.test.js`

Expected: PASS；`rg -n "d435|selection_side|requested_ordinal" apps/bottle_pick src/thirdhand_va/vision src/thirdhand_va/action/adapters` 只允许命中明确标记的 legacy 文档或兼容声明，不命中正式事件和启动配置。

- [ ] **Step 7: 提交本任务**

```bash
git add src/thirdhand_va/vision/adapters src/thirdhand_va/vision/visualization src/thirdhand_va/action/adapters/vision_client.js src/thirdhand_va/action/adapters/camera_bridge.js apps/bottle_pick/camera_bridge.py tests/vision/adapters tests/vision/visualization tests/action/adapters tests/integration/test_camera_bridge_script.py
git commit -m "feat: publish stable-id Lumos vision events"
```

---

### Task 8: OpenCV eye-in-hand 求解、数值验证和单 Lumos 标定契约

**Files:**
- Create: `src/thirdhand_va/action/calibration/solver.py`
- Modify: `src/thirdhand_va/action/calibration/handeye.py`
- Modify: `src/thirdhand_va/action/calibration/__init__.py`
- Create: `scripts/action/calibrate_handeye.py`
- Modify: `scripts/action/debug_calibration.py`
- Create: `tests/action/calibration/test_solver.py`
- Modify: `tests/action/calibration/test_handeye.py`

**Interfaces:**
- Consumes: `thirdhand-handeye-samples-v1` JSON，至少 12 个 fit 样本和 3 个独立 validation 样本，每个包含 `T_base_tool` 与 `T_camera_target`。
- Produces: `solve_handeye(manifest) -> HandEyeSolveReport`；标定文件使用 `T_tool_camera`、相机序列号、TCP 语义、样本哈希和误差。

- [ ] **Step 1: 写出合成 hand-eye RED 测试**

```python
def test_solver_recovers_known_tool_camera_transform(synthetic_manifest):
    report = solve_handeye(synthetic_manifest)
    np.testing.assert_allclose(report.t_tool_camera[:3, 3],
                               synthetic_manifest.truth[:3, 3], atol=0.002)
    assert report.validation_translation_rmse_m < 0.003

def test_solver_requires_pose_diversity_and_held_out_validation(one_axis_manifest):
    with pytest.raises(HandEyeSolveError, match="rotation_axis_diversity"):
        solve_handeye(one_axis_manifest)
```

- [ ] **Step 2: 运行标定测试并确认 solver 缺失**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/action/calibration -v`

Expected: FAIL importing `solver`。

- [ ] **Step 3: 使用 OpenCV 官方实现求解**

```python
r_cam2tool, t_cam2tool = cv2.calibrateHandEye(
    r_tool2base, t_tool2base, r_target2cam, t_target2cam,
    method=cv2.CALIB_HAND_EYE_DANIILIDIS,
)
t_tool_camera = homogeneous(r_cam2tool, t_cam2tool)
```

验证阶段计算每个 `T_base_target = T_base_tool @ T_tool_camera @ T_camera_target`，报告相对中值的平移 RMSE/P95 和旋转 geodesic RMSE/P95；不使用 D435 中间变换。

- [ ] **Step 4: 更新 loader 的语义和激活门**

`HandEyeCalibration` 正式字段改为 `t_tool_camera`；只读兼容 property 可读取旧 `T_flange_camera`，但 `approved_for_bottle_grasp` 只有 camera serial、mount activation、数值验证和独立物理验证全部通过才为 true。

- [ ] **Step 5: 完成独立 CLI**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python scripts/action/calibrate_handeye.py samples.json --output calibration.json`

Expected: 对合成/录制清单输出内容哈希、样本数、旋转轴多样性、fit/validation 误差和 `approved_for_bottle_grasp=false`；该 CLI 不移动机器人。

- [ ] **Step 6: 运行标定回归并提交**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/action/calibration -v`

Expected: PASS。

```bash
git add src/thirdhand_va/action/calibration scripts/action/calibrate_handeye.py scripts/action/debug_calibration.py tests/action/calibration
git commit -m "feat: solve and validate Lumos hand-eye calibration"
```

---

### Task 9: 严格 Action 配置、执行计划和 fail-closed 安全门

**Files:**
- Create: `src/thirdhand_va/action/config.js`
- Create: `src/thirdhand_va/action/grasp/execution_plan.js`
- Modify: `src/thirdhand_va/action/safety/execution_gate.js`
- Modify: `src/thirdhand_va/action/safety/workspace_check.js`
- Create: `tests/action/config.test.js`
- Create: `tests/action/grasp/execution_plan.test.js`
- Modify: `tests/action/safety/execution_gate.test.js`

**Interfaces:**
- Consumes: `configs/action.yaml`、v3 actionable target、robot state。
- Produces: `loadActionConfig(path) -> frozen ActionConfig`；`buildExecutionPlan(target, config) -> frozen plan`；`evaluateExecutionGate(context) -> ActionDecision`。

- [ ] **Step 1: 写出配置、宽度和固定点 RED 测试**

```javascript
test('inactive real config blocks place while simulation fixture can plan', () => {
  const blocked = evaluateExecutionGate(validContext({ placeValidated: false }));
  assert.deepEqual(blocked.blockers, ['place_not_validated']);
});

test('execution plan rejects width above 72mm', () => {
  assert.throws(() => buildExecutionPlan(target({ widthM: 0.073 }), config),
                /grasp_width_exceeded/);
});
```

- [ ] **Step 2: 运行 Action 配置和安全测试并确认 RED**

Run: `node tests/action/config.test.js && node tests/action/grasp/execution_plan.test.js && node tests/action/safety/execution_gate.test.js`

Expected: FAIL because loader/plan 不存在且 gate 不检查 place、identity、evidence、width。

- [ ] **Step 3: 实现严格 YAML loader**

```javascript
function loadActionConfig(filePath) {
  const raw = YAML.parse(fs.readFileSync(filePath, 'utf8'));
  assertExactKeys(raw, ['schema', 'execution_enabled', 'ws_url', 'workflow_timeout_ms',
    'home_timeout_ms', 'workspace_m', 'status_file', 'motion', 'gripper', 'place']);
  return deepFreeze(normalize(raw));
}
```

未知键、非有限数、72 mm 以上最大宽度、未验证却含激活标志、验证为 true 却缺坐标均直接抛错。

- [ ] **Step 4: 从 TH-Fanxy 已验证控制器抽取不可变执行计划**

```javascript
function buildExecutionPlan(target, config) {
  return deepFreeze({
    stableId: target.stableId,
    evidenceId: target.evidenceId,
    finalApproachM: target.graspPointM,
    liftM: [target.graspPointM[0], target.graspPointM[1],
            target.graspPointM[2] + config.motion.lift_height_m],
    prePlaceM: config.place.pre_place_m,
    placeM: config.place.point_m,
    homePreset: config.place.home_preset,
    widthM: target.widthM,
  });
}
```

移植时保留内部来源说明；不复制浏览器、Express 或全局状态代码。

- [ ] **Step 5: 扩展安全门精确 blocker**

检查 execution、stable ID 一致、confirmed、evidence age、motion epoch、depth、pose spread、calibration、arm stationary、gripper、place、72 mm、grasp/pre-place/place 工作区。blocker 顺序固定，便于测试和 UI。

- [ ] **Step 6: 运行 Action 纯模块测试并提交**

Run: `node tests/action/config.test.js && node tests/action/grasp/execution_plan.test.js && node tests/action/safety/execution_gate.test.js`

Expected: PASS。

```bash
git add src/thirdhand_va/action/config.js src/thirdhand_va/action/grasp/execution_plan.js src/thirdhand_va/action/safety configs/action.yaml tests/action/config.test.js tests/action/grasp/execution_plan.test.js tests/action/safety
git commit -m "feat: gate immutable pick-place plans"
```

---

### Task 10: 稳定 ID 视觉对准和强制近距离重观察

**Files:**
- Modify: `src/thirdhand_va/action/alignment/visual_align_controller.js`
- Modify: `src/thirdhand_va/action/observation/base_target_lock.js`
- Modify: `src/thirdhand_va/action/observation/depth_filter.js`
- Modify: `tests/action/alignment/visual_align_controller.test.js`
- Modify: `tests/action/observation/base_target_lock.test.js`
- Modify: `tests/action/observation/depth_filter.test.js`
- Modify: `scripts/action/debug_alignment.js`
- Create: `tests/fixtures/action/alignment.json`

**Interfaces:**
- Consumes: `start({targetId, requestId})`、v3 targets、机器人状态/完成事件。
- Produces: 预抓取移动、递增 motion epoch、3 至 5 帧新深度证据、最多 5 mm 微调和 evidence-bound handoff。

- [ ] **Step 1: 写出不重复左右排序且必须新深度的 RED 测试**

```javascript
const started = controller.start({ targetId: 2, requestId: 'req-2' });
assert.equal(selections[0].stable_id, 2);

controller.onRobotEvent(moveComplete(firstMove));
const blocked = controller.onVisionTargets([target({ stableId: 2, depthValid: false })]);
assert.equal(blocked.reason, 'fresh_depth_required');
assert.equal(grasps.length, 0);

const handedOff = feedStableFreshEpoch(controller, { stableId: 2, motionEpoch: 2 });
assert.equal(handedOff.phase, 'handed_off');
```

- [ ] **Step 2: 运行 alignment 测试并确认旧语义失败**

Run: `node tests/action/alignment/visual_align_controller.test.js && node tests/action/observation/base_target_lock.test.js && node tests/action/observation/depth_filter.test.js`

Expected: FAIL because当前 `start` 使用 targetIndex/left ordinal，且允许近距离无深度沿用旧点。

- [ ] **Step 3: 改为 stable ID 和 request-bound lock**

```javascript
start({ targetId, requestId }) {
  if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5) {
    return { accepted: false, reason: 'target_id_invalid' };
  }
  this.selectBottle({ stable_id: targetId, request_id: requestId });
}
```

BaseFrameTargetLock 强制 stable ID、request ID、calibration ID 一致；视觉冲突返回 `target_identity_conflict`，不重新绑定。

- [ ] **Step 4: 每次移动完成后开启新 epoch 并清空深度证据**

```javascript
this.session.motionEpoch += 1;
this.targetLock.resetEvidence();
this.resetTargetPoseReference({
  request_id: this.session.requestId,
  motion_epoch: this.session.motionEpoch,
});
```

只有相同 epoch 的 3 至 5 个 fresh、stationary、depth-valid 结果进入 refine；每次修正向量范数不超过 0.005 m。

- [ ] **Step 5: 更新独立 alignment 模拟入口**

Run: `node scripts/action/debug_alignment.js --target-id 2 --fixture tests/fixtures/action/alignment.json`

Expected: 输出 `MOVING_TO_PREGRASP -> SETTLING -> REOBSERVING -> HANDED_OFF`，所有机器人命令只进入内存 fake adapter。

- [ ] **Step 6: 运行 Action observation/alignment 回归并提交**

Run: `node tests/action/alignment/visual_align_controller.test.js && find tests/action/observation -name '*.js' -print0 | sort -z | xargs -0 -n1 node`

Expected: PASS。

```bash
git add src/thirdhand_va/action/alignment src/thirdhand_va/action/observation scripts/action/debug_alignment.js tests/action/alignment tests/action/observation tests/fixtures/action
git commit -m "feat: reobserve stable target after wrist motion"
```

---

### Task 11: 完整夹取、固定点放置、Home 状态机和阶段化失败

**Files:**
- Modify: `src/thirdhand_va/action/grasp/grasp_controller.js`
- Modify: `tests/action/grasp/grasp_controller.test.js`
- Modify: `scripts/action/debug_grasp.js`
- Create: `tests/fixtures/action/approved-plan.json`

**Interfaces:**
- Consumes: Task 9 immutable execution plan、`robotClient.send(command)`、机器人完成/错误事件。
- Produces: `GraspController.start(plan) -> Result`、`onRobotEvent(event) -> Result`、`snapshot()`、`cancel(reason)`；完整 phase status。

- [ ] **Step 1: 写出完整阶段顺序 RED 测试**

```javascript
test('one accepted plan completes grasp place retreat and home', () => {
  const controller = makeController();
  assert.equal(controller.start(plan).accepted, true);
  completeAllCommands(controller);
  assert.deepEqual(sent.map(command => command.source), [
    'grasp:open', 'grasp:final_approach', 'grasp:close', 'grasp:lift',
    'grasp:transfer', 'grasp:lower', 'grasp:release', 'grasp:retreat',
    'grasp:return_home',
  ]);
  assert.equal(controller.snapshot().phase, 'complete');
});

test('post-close failure never opens or returns home automatically', () => {
  failAt(controller, 'lift');
  assert.equal(controller.snapshot().reason, 'manual_recovery_required');
  assert.equal(sent.some(c => c.source === 'grasp:release'), false);
});
```

- [ ] **Step 2: 运行 grasp 测试并确认当前单命令实现失败**

Run: `node tests/action/grasp/grasp_controller.test.js`

Expected: FAIL because当前只发送一条 `execute_grasp`。

- [ ] **Step 3: 移植成熟阶段推进器并适配本项目接口**

```javascript
const NEXT_PHASE = Object.freeze({
  open: 'final_approach', final_approach: 'close', close: 'lift',
  lift: 'transfer', transfer: 'lower', lower: 'release',
  release: 'retreat', retreat: 'return_home', return_home: 'complete',
});
```

`open/close/release` 发送 gripper；位姿阶段发送 `move_l`；Home 发送 `preset`。close 只有实际位置位于配置接触区间才判定抓到瓶子。

- [ ] **Step 4: 实现设计规定的失败策略**

final approach 前失败不闭夹爪；final approach 失败保持；close 到 lower 失败保持夹爪与机械臂并返回 `manual_recovery_required`；release 无法证明成功时保持；release 后只有机器人健康且剩余路径已验证才继续 retreat/Home。

- [ ] **Step 5: 更新独立 grasp 模拟入口**

Run: `node scripts/action/debug_grasp.js --fixture tests/fixtures/action/approved-plan.json`

Expected: 输出完整九阶段命令、状态和 `robot_control_enabled=false`，不连接网络。

- [ ] **Step 6: 运行 grasp 测试和提交**

Run: `node tests/action/grasp/grasp_controller.test.js && node scripts/action/debug_grasp.js --fixture tests/fixtures/action/approved-plan.json`

Expected: PASS/完整模拟输出。

```bash
git add src/thirdhand_va/action/grasp/grasp_controller.js scripts/action/debug_grasp.js tests/action/grasp/grasp_controller.test.js tests/fixtures/action/approved-plan.json
git commit -m "feat: execute complete upright pick and place"
```

---

### Task 12: 低层机器人 WS adapter、V+A Workflow 和 L 调用服务

**Files:**
- Create: `src/thirdhand_va/action/adapters/robot_ws_client.js`
- Modify: `src/thirdhand_va/action/grasp/workflow.js`
- Modify: `src/thirdhand_va/action/operator/controller.js`
- Modify: `src/thirdhand_va/action/operator/status_store.js`
- Modify: `apps/bottle_pick/web_server.js`
- Modify: `apps/bottle_pick/run.js`
- Create: `scripts/action/debug_workflow.js`
- Create: `tests/action/adapters/robot_ws_client.test.js`
- Modify: `tests/action/grasp/workflow.test.js`
- Modify: `tests/action/operator/controller.test.js`
- Create: `tests/integration/va_service.test.js`
- Modify: `tests/integration/app_run.test.js`
- Modify: `tests/integration/web_server.test.js`
- Create: `tests/fixtures/integration/full-cycle.json`

**Interfaces:**
- Consumes: CameraBridge v3 events、3000 WS 的低层 robot state/command status、Task 10/11 controllers。
- Produces: 回环 VA 服务 `POST /api/va/start`、`POST /api/va/stop`、`GET /api/va/status`、MJPEG routes；CLI `run.js start <1..5>`。

- [ ] **Step 1: 写出服务边界和不再委托 closed_loop_pick 的 RED 测试**

```javascript
test('L start request creates local VA workflow with stable id', async () => {
  const result = await post('/api/va/start', {
    schema: 'thirdhand.va.command.v1', cmd: 'start', target_id: 2,
    request_id: 'req-2',
  });
  assert.equal(result.status, 202);
  assert.equal(result.body.target_id, 2);
  assert.equal(robotMessages.some(m => m.cmd === 'closed_loop_pick'), false);
});

test('same request id is idempotent and another request is rejected', async () => {
  const command = {schema: 'thirdhand.va.command.v1', cmd: 'start',
    target_id: 2, request_id: 'req-2'};
  const first = await post('/api/va/start', command);
  const duplicate = await post('/api/va/start', command);
  const conflict = await post('/api/va/start', {...command, request_id: 'req-3'});
  assert.equal(first.status, 202);
  assert.equal(duplicate.status, 202);
  assert.equal(conflict.status, 409);
});
```

- [ ] **Step 2: 运行 adapter/workflow/service 测试并确认 RED**

Run: `node tests/action/adapters/robot_ws_client.test.js && node tests/action/grasp/workflow.test.js && node tests/integration/va_service.test.js && node tests/integration/app_run.test.js`

Expected: FAIL because robot adapter/service 不存在且 workflow 仍发送 `closed_loop_pick`。

- [ ] **Step 3: 实现只允许低层命令的 RobotWebSocketClient**

```javascript
const ALLOWED = new Set(['move_l', 'move_joint', 'gripper', 'preset', 'software_stop', 'get_state']);

class RobotWebSocketClient extends EventEmitter {
  send(command) {
    if (!ALLOWED.has(command?.cmd)) return false;
    this.ws.send(JSON.stringify(command));
    return true;
  }
}
```

adapter 规范化 `robot_state`、`command_status accepted/complete`、`error`、`software_stop`；不包含识别、目标选择或抓取编排。

- [ ] **Step 4: 重写 WorkflowClient 为本地 V+A orchestration**

`WorkflowClient` 监听 CameraBridge detection events 与 RobotWebSocketClient events，依次驱动 VisualAlignController 和 GraspController；机器人状态同步发送到 Python camera bridge；同一 request ID 幂等；最终结果包含 target ID、evidence ID、完成/失败 phase 和 reason。

```javascript
workflow.start({ targetId: 2, requestId: 'req-2' });
workflow.onVisionResult(v3Result);
workflow.onRobotEvent(normalizedRobotEvent);
```

- [ ] **Step 5: 把 web_server.js 变成目标项目唯一 V+A 服务**

默认绑定 `127.0.0.1:8766`，避免占用机器人 3000。相机只在 `THIRDHAND_VA_ENABLE_CAMERA=1` 时启动；机器人只在 `THIRDHAND_VA_ENABLE_ROBOT=1` 且 Action 配置激活时连接。暴露 `/camera_lumos_vision`、`/camera_xvisio_raw`、`/camera_xvisio_depth` 和三条 VA API。

- [ ] **Step 6: 把 run.js 改为 L 的薄客户端**

```javascript
await fetch(`${baseUrl}/api/va/start`, {
  method: 'POST', headers: {'content-type': 'application/json'},
  body: JSON.stringify({schema: 'thirdhand.va.command.v1', cmd: 'start',
                        target_id: targetId, request_id: randomUUID()}),
});
```

Node 24 自带 fetch，不引入 HTTP 客户端依赖。`stop` 调 `/api/va/stop`。

- [ ] **Step 7: 完成模拟 V+A 独立入口**

Run: `node scripts/action/debug_workflow.js --target-id 2 --fixture tests/fixtures/integration/full-cycle.json`

Expected: 不连接相机/机器人，输出从 stable selection 到 complete 的全状态轨迹和所有低层命令。

- [ ] **Step 8: 运行完整 JS 回归并提交**

Run: `npm test`

Expected: 所有 JS 测试 PASS；没有测试监听 3000、打开相机或发送真实机器人命令。

```bash
git add src/thirdhand_va/action/adapters/robot_ws_client.js src/thirdhand_va/action/grasp/workflow.js src/thirdhand_va/action/operator apps/bottle_pick scripts/action/debug_workflow.js tests/action tests/integration tests/fixtures/integration
git commit -m "feat: own complete VA workflow behind L API"
```

---

### Task 13: VS Code 独立 Debug、操作文档和离线全回归

**Files:**
- Modify: `.vscode/launch.json`
- Modify: `.vscode/tasks.json`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/vision/modules.md`
- Modify: `docs/action/modules.md`
- Modify: `docs/integration/contracts.md`
- Modify: `docs/vision/preview.md`
- Modify: `tests/integration/test_debug_entrypoints.py`
- Modify: `tests/integration/test_preview_debug_assets.py`
- Modify: `tests/common/test_module_boundaries.py`
- Modify: `tests/common/test_repository_layout.py`

**Interfaces:**
- Consumes: Tasks 1-12 的正式和 Debug 入口。
- Produces: 每个核心模块的 VS Code 配置、精确命令、输入格式、断点建议和预期输出。

- [ ] **Step 1: 写出 Debug 资产 RED 测试**

```python
EXPECTED = {
    "Vision: Debug Perception", "Vision: Debug Stable IDs",
    "Vision: Debug Geometry", "Vision: Debug Pipeline",
    "Action: Debug Calibration", "Action: Debug Alignment",
    "Action: Debug Grasp", "VA: Debug Simulated Workflow",
}
assert EXPECTED <= launch_names()
```

- [ ] **Step 2: 运行文档/入口测试并确认缺少新入口**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_debug_entrypoints.py tests/integration/test_preview_debug_assets.py tests/common/test_module_boundaries.py tests/common/test_repository_layout.py -v`

Expected: FAIL because tracking/workflow launch config 和文档尚未登记。

- [ ] **Step 3: 增加八个独立 launch 配置**

每个配置固定 `cwd` 为项目根、Python 为专用环境、`PYTHONPATH=${workspaceFolder}/src`；真实相机配置包含 `--allow-camera` 但不设为默认；真实机器人配置不放进一键 F5，必须从硬件验证脚本显式执行。

- [ ] **Step 4: 更新 README 和模块文档**

每个模块说明必须回答：职责、输入、输出、依赖、独立命令、预期终端/JSON/图像、常用断点和失败定位。正式接口只描述 stable ID 和 v3 schema；固定可乐、左右 ordinal、D435 路径标注为非正式 legacy，不出现在快速开始。

- [ ] **Step 5: 运行所有离线 Python/JS/语法测试**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/common tests/vision tests/action tests/integration -q`

Run: `npm test`

Run: `find src apps scripts tests -name '*.py' -type f -print0 | sort -z | xargs -0 $HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m py_compile`

Run: `find src apps scripts tests -name '*.js' -type f -print0 | sort -z | xargs -0 -n1 node --check`

Expected: 全部 PASS；hardware tests 保持显式跳过。

- [ ] **Step 6: 提交本任务**

```bash
git add .vscode README.md docs/architecture.md docs/vision docs/action docs/integration tests/integration/test_debug_entrypoints.py tests/integration/test_preview_debug_assets.py tests/common/test_module_boundaries.py tests/common/test_repository_layout.py
git commit -m "docs: make every VA module independently debuggable"
```

---

### Task 14: 硬件验收工具、部署切换门和最终证据

**Files:**
- Create: `scripts/action/validate_pick_place.js`
- Create: `docs/hardware/generic-bottle-validation.md`
- Modify: `tests/hardware/test_live_depth_endpoint.py`
- Modify: `tests/hardware/test_live_vision_preview.py`
- Create: `tests/hardware/test_live_va_skill.py`
- Modify: `scripts/vision/camera_smoke.py`
- Modify: `scripts/vision/record_rgbd.py`
- Modify: `scripts/vision/validate_camera_alignment.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 已通过全部离线测试的 VA service、Lumos、hand-eye 产物、低层机器人 3000 服务。
- Produces: `artifacts/validation/generic-bottle/<run-id>/report.json`，包含环境、配置/模型/标定哈希、30 个 trial 和成功/失败分布。

- [ ] **Step 1: 写出硬件入口必须显式授权的 RED 测试**

```javascript
test('hardware validator refuses without exact allow flag', async () => {
  const code = await main(['--trials', '1'], fakeDeps);
  assert.equal(code, 2);
  assert.equal(fakeDeps.robotCommands.length, 0);
});
```

```python
pytestmark = pytest.mark.skipif(
    os.environ.get("THIRDHAND_LIVE_TEST") != "1",
    reason="requires explicit live hardware authorization",
)

def test_live_va_skill_completes_one_requested_id(live_client):
    result = live_client.run(target_id=1)
    assert result["phase"] == "complete"
```

- [ ] **Step 2: 运行 hardware tests 并确认默认只跳过/拒绝**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/hardware -q`

Run: `node scripts/action/validate_pick_place.js --trials 1`

Expected: pytest 全部 SKIPPED；validator 返回 2 且没有网络/硬件调用。

- [ ] **Step 3: 实现可追溯真机验收入口**

`validate_pick_place.js` 同时要求 `--allow-robot`、`THIRDHAND_LIVE_TEST=1`、Action `execution_enabled=true`、已验证 place 和 calibration；每个 trial 调用正式 `/api/va/start` 并等待最终结果，不直接发送机械臂命令。

- [ ] **Step 4: 写明分阶段现场命令，但不在无授权会话执行**

```bash
bash scripts/vision/build_native.sh
python scripts/vision/camera_smoke.py --frames 30 --allow-camera
python scripts/vision/record_rgbd.py --output artifacts/vision/recordings --allow-camera
python scripts/action/calibrate_handeye.py artifacts/calibration/samples.json --output artifacts/calibration/lumos-tool.json
THIRDHAND_LIVE_TEST=1 node scripts/action/validate_pick_place.js --allow-robot --trials 30
```

文档要求先相机、再配准、再 hand-eye、再空载固定点、再完整低速循环；任何阶段不通过不得进入下一阶段。

- [ ] **Step 5: 在获得用户当次硬件授权后执行验证并生成报告**

Expected acceptance:

- 五种普通不透明瓶、30 个随机允许位置；
- 错抓编号 0；
- 身份交换 0；
- 无效证据执行授权 0；
- 完整成功率至少 90%；
- 成功 trial 全部直立放置并回 Home；
- 失败 trial 全部具有 phase、reason、evidence ID。

若未授权或任一硬件门未通过，本任务状态保持未完成，报告阻断而不宣称真机完成。

- [ ] **Step 6: 运行最终回归和工作区检查**

Run: `$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/common tests/vision tests/action tests/integration -q`

Run: `npm test`

Run: `git diff --check`

Run: `git status --short`

Expected: 离线测试全绿；status 中只出现本计划明确修改和用户原有变更，不包含模型、原始 RGB-D 或运行日志。

- [ ] **Step 7: 提交硬件工具和文档，不提交原始证据大文件**

```bash
git add scripts/action/validate_pick_place.js docs/hardware/generic-bottle-validation.md tests/hardware scripts/vision/camera_smoke.py scripts/vision/record_rgbd.py scripts/vision/validate_camera_alignment.py .gitignore
git commit -m "test: add supervised bottle skill acceptance"
```

---

## Final Handoff Checklist

- [ ] 运行 `scripts/runtime/preflight.py --json` 并保存结果摘要。
- [ ] 运行全部 Python、JS、Python compile 和 JS syntax 检查。
- [ ] 逐个执行八个独立 Debug 入口并保存预期输出示例。
- [ ] 确认正式代码不含左右 ordinal、D435 运行依赖或旧删除脚本路径。
- [ ] 确认 L 只需 `start <1..5>`，相同 request ID 幂等。
- [ ] 确认 `start` 的成功结果只有完整放置并回 Home 后产生。
- [ ] 确认未经过现场验证时 execution/place/calibration 门保持关闭。
- [ ] 交付修改模块、复用来源/许可证、测试证据、VS Code 文件与命令、剩余风险。
