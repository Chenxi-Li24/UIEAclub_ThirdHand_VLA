# Speech 与 XVisio 运行链路迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在统一项目中恢复 Ubuntu 本地 3004 语音服务和 3100 XVisio 视觉服务，并通过 9983 单一入口提供三档 ASR、TTS、Claude 兼容对话、原始视频、检测框和目标选择。

**Architecture:** Speech 和 Vision 是两个只监听回环地址的独立服务，Web Gateway 代理内部 HTTP/MJPEG/WebSocket；Robot Service 保持唯一 CAN 所有者。Vision 的相机采集与模型推理解耦，模型不可用时原始画面仍在线，所有自动运动继续关闭。

**Tech Stack:** Node.js 24、Python 3.11、`ws`、原生 `http`、`websockets`、PyTorch/FunASR、OpenCV、XVisio SDK/CMake。

**Spec:** `docs/superpowers/specs/2026-09-11-speech-xvisio-runtime-integration-design.md`

## Global Constraints

- 保持分支 `refactor/unified-platform-foundation`，不推送、不合并。
- 不修改、移动或删除 `/home/nieqingcao/Thirdhand_language`、`/home/nieqingcao/th0814` 或其他旧项目。
- 正式运行代码不得从 `migration/sources/*` 或旧项目绝对路径导入。
- 3000 Robot Service 保持唯一 CAN/Startouch SDK 所有者；Speech/Vision 不得打开 CAN。
- SDK、模型、运行时继续位于 ignored `local/`；Git 只跟踪代码、配置、清单、哈希和准备脚本。
- 3004 和 3100 默认只监听 `127.0.0.1`；局域网浏览器只访问 9983。
- 本轮硬件验证只读取 XVisio，不发送关节、夹爪、回零或主动视角命令。
- 兼容期保留正式 Language Part 的 Claude 对话、动作候选和 TTS。
- 测试先于实现，每个任务独立提交。

---

### Task 1: 提升正式 Speech Service 源码

**Files:**
- Create: `services/speech/README.md`
- Create: `services/speech/requirements.txt`
- Create: `services/speech/src/voice_bridge.py`
- Create: `services/speech/src/asr_model_manager.py`
- Create: `services/speech/src/whisper_backend.py`
- Create: `services/speech/src/funasr_backends.py`
- Create: `services/speech/src/voice_agent.py`
- Create: `services/speech/src/tts_bridge.py`
- Create: `tests/python/speech_service/test_source_parity.py`
- Create: `tests/python/speech_service/test_model_paths.py`

**Interfaces:**
- Consumes: project root and environment variables only.
- Produces: `build_model_paths(root: Path) -> dict[str, Path]` and the existing `thirdhand.voice.v1` protocol implementation.

- [ ] **Step 1: Write failing source-boundary and model-path tests**

```python
def test_model_paths_use_project_local_asset_names(repo_root):
    paths = build_model_paths(repo_root)
    assert paths["whisper-small"] == repo_root / "local/models/asr/medium"
    assert paths["paraformer-streaming"] == repo_root / "local/models/asr/realtime"
    assert paths["fun-asr-nano"] == repo_root / "local/models/asr/high"

def test_speech_source_has_no_migration_or_old_project_runtime_dependency():
    forbidden = ("migration/sources", "/home/nieqingcao/Thirdhand_language")
    for path in SPEECH_RUNTIME_FILES:
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden)
```

- [ ] **Step 2: Run tests and confirm the service does not exist**

Run: `local/runtimes/python/bin/python -m pytest tests/python/speech_service/test_source_parity.py tests/python/speech_service/test_model_paths.py -v`

Expected: FAIL because `services.speech` and `build_model_paths` do not exist.

- [ ] **Step 3: Copy the approved Language Part implementation into the formal service**

Copy the listed source files from `migration/sources/language/voice`, preserving protocol behavior and tests. Add a small path resolver:

```python
MODEL_PATHS = {
    "whisper-small": Path("local/models/asr/medium"),
    "paraformer-streaming": Path("local/models/asr/realtime"),
    "fun-asr-nano": Path("local/models/asr/high"),
}

def build_model_paths(repo_root: Path) -> dict[str, Path]:
    return {model_id: (repo_root / relative).resolve()
            for model_id, relative in MODEL_PATHS.items()}
```

Update factories to consume this mapping rather than requiring legacy model directory names.

- [ ] **Step 4: Run source and model-manager tests**

Run: `local/runtimes/python/bin/python -m pytest tests/python/speech_service services/speech/src/test_asr_model_manager.py services/speech/src/test_voice_bridge.py services/speech/src/test_funasr_backends.py services/speech/src/test_whisper_backend.py -v`

Expected: PASS with no network access and no model loading.

- [ ] **Step 5: Commit**

```bash
git add services/speech tests/python/speech_service
git commit -m "feat: promote Ubuntu speech service"
```

### Task 2: Add Speech readiness and launcher-safe startup

**Files:**
- Create: `services/speech/src/runtime.py`
- Create: `services/speech/scripts/ready_probe.py`
- Create: `tests/python/speech_service/test_runtime.py`
- Modify: `services/speech/src/voice_bridge.py`

**Interfaces:**
- Consumes: `THIRDHAND_READY_FILE`, `SPEECH_HOST`, `SPEECH_PORT` and project-local model paths.
- Produces: `write_ready_file(path, model_status)` and WebSocket `ws://127.0.0.1:3004/v1/voice`.

- [ ] **Step 1: Write failing readiness tests**

```python
def test_ready_file_is_written_atomically(tmp_path):
    target = tmp_path / "speech.ready"
    write_ready_file(target, {"state": "ERROR"})
    assert json.loads(target.read_text())["serviceId"] == "speech"

def test_readiness_means_listener_available_even_when_default_model_errors():
    assert readiness_payload({"state": "ERROR"})["ready"] is True
    assert readiness_payload({"state": "ERROR"})["modelReady"] is False
```

- [ ] **Step 2: Run the targeted tests**

Run: `local/runtimes/python/bin/python -m pytest tests/python/speech_service/test_runtime.py -v`

Expected: FAIL because runtime helpers are absent.

- [ ] **Step 3: Implement atomic readiness and environment CLI defaults**

Write readiness only after the WebSocket server has bound. Include `modelReady` and `modelState` so launcher process readiness is distinct from ASR readiness. Remove the ready file on graceful shutdown.

- [ ] **Step 4: Run protocol and readiness tests**

Run: `local/runtimes/python/bin/python -m pytest tests/python/speech_service -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/speech tests/python/speech_service
git commit -m "feat: add speech runtime readiness"
```

### Task 3: Proxy Speech through 9983 and migrate the formal voice UI

**Files:**
- Create: `apps/web/src/websocket-proxy.js`
- Create: `tests/node/web/voice-proxy.test.js`
- Create: `apps/web/public/js/tts-player.js`
- Modify: `apps/web/src/config.js`
- Modify: `apps/web/src/server.js`
- Modify: `apps/web/public/index.html`
- Modify: `apps/web/public/js/voice-control.js`
- Modify: `apps/web/public/js/main.js`
- Modify: `apps/web/public/css/style.css`
- Modify: `apps/web/public/js/runtime-endpoints.js`

**Interfaces:**
- Consumes: `VOICE_WS_URL=ws://127.0.0.1:3004/v1/voice`.
- Produces: same-origin `/voice` WebSocket preserving `thirdhand.voice.v1` and `GET /api/runtime-config` returning `voice.endpoint`.

- [ ] **Step 1: Write failing WebSocket proxy and runtime-config tests**

```javascript
test('voice proxy preserves subprotocol and messages', async () => {
  const browser = new WebSocket(gatewayUrl('/voice'), 'thirdhand.voice.v1');
  await once(browser, 'open');
  assert.equal(browser.protocol, 'thirdhand.voice.v1');
  browser.send(JSON.stringify({ type: 'model.list', protocolVersion: 1 }));
  assert.equal((await nextJson(browser)).type, 'model.catalog');
});

test('runtime config advertises same-origin voice path', async () => {
  const body = await fetch(origin + '/api/runtime-config').then(r => r.json());
  assert.equal(body.voice.endpoint, '/voice');
});
```

- [ ] **Step 2: Run tests and confirm /voice is rejected**

Run: `local/runtimes/node/bin/node --test tests/node/web/voice-proxy.test.js`

Expected: FAIL because only `/ws` upgrades are accepted.

- [ ] **Step 3: Implement the generic upstream WebSocket proxy**

Validate upgrade path exactly, pass only the expected voice subprotocol, bound queued bytes, close both sides together, and never forward voice traffic to RobotProxy.

- [ ] **Step 4: Migrate only the Language Part voice surface**

Use `migration/sources/language/app/web` as the source of truth for voice markup, `voice-control.js`, `tts-player.js` and CSS. Preserve the current robot and XVisio page areas. Replace old Jetson buttons with Medium, Real-time and High controls, force the versioned endpoint migration to same-origin `/voice`, and keep operator confirmation before robot execution.

- [ ] **Step 5: Run Web Gateway and static contract tests**

Run: `local/runtimes/node/bin/node --test tests/node/web/*.test.js`

Expected: PASS; no test opens CAN.

- [ ] **Step 6: Commit**

```bash
git add apps/web tests/node/web
git commit -m "feat: connect formal voice UI through web gateway"
```

### Task 4: Promote and build the XVisio driver

**Files:**
- Create: `drivers/xvisio/README.md`
- Create: `drivers/xvisio/native/CMakeLists.txt`
- Create: `drivers/xvisio/native/xvisio_rgbd_stream.cpp`
- Create: `drivers/xvisio/scripts/build.sh`
- Create: `drivers/xvisio/src/xvisio_stream.py`
- Create: `tests/python/vision_service/test_xvisio_packet.py`
- Create: `tests/python/vision_service/test_driver_paths.py`

**Interfaces:**
- Consumes: installed `xvsdk` and OpenCV; XVisio USB serial from `configs/vision.yaml`.
- Produces: `XVisioStream(executable, expected_serial)` yielding RGB, metric depth, XYZ, sequence and monotonic timestamp.

- [ ] **Step 1: Write failing packet and path tests**

```python
def test_packet_parser_rejects_wrong_magic():
    with pytest.raises(StreamProtocolError):
        parse_header(b"BADHDR00" + bytes(80))

def test_default_executable_is_project_local(repo_root):
    assert default_executable(repo_root) == (
        repo_root / "runtime/build/xvisio/xvisio_rgbd_stream"
    )
```

- [ ] **Step 2: Run driver tests**

Run: `local/runtimes/python/bin/python -m pytest tests/python/vision_service/test_xvisio_packet.py tests/python/vision_service/test_driver_paths.py -v`

Expected: FAIL because the formal driver is absent.

- [ ] **Step 3: Promote native and Python driver code**

Copy the reviewed native source and stream parser from `migration/sources/vision-grasp`. Build into ignored `runtime/build/xvisio`, validate serial and packet lengths before allocation, and retain bounded read timeouts.

- [ ] **Step 4: Run tests and a build-only check**

Run: `local/runtimes/python/bin/python -m pytest tests/python/vision_service/test_xvisio_packet.py tests/python/vision_service/test_driver_paths.py -v`

Run: `drivers/xvisio/scripts/build.sh`

Expected: tests PASS and the executable exists; the build step does not open the camera.

- [ ] **Step 5: Commit**

```bash
git add drivers/xvisio tests/python/vision_service
git commit -m "feat: promote XVisio RGB-D driver"
```

### Task 5: Build the 3100 Vision Service with raw-stream fallback

**Files:**
- Create: `services/vision/package.json`
- Create: `services/vision/src/config.js`
- Create: `services/vision/src/server.js`
- Create: `services/vision/src/camera-process.js`
- Create: `services/vision/python/camera_bridge.py`
- Create: `services/vision/python/thirdhand_va/`
- Create: `services/vision/README.md`
- Create: `tests/node/vision_service/server.test.js`
- Create: `tests/python/vision_service/test_camera_fallback.py`

**Interfaces:**
- Consumes: the Task 4 driver, project-local Grounded-SAM model configuration, and read-only `arm_state` messages.
- Produces: `GET /health`, `GET /camera/xvisio/raw`, `GET /camera/xvisio/vision`, `GET /camera/xvisio/depth` and a bounded vision command/event WebSocket.

- [ ] **Step 1: Write failing service contract tests**

```javascript
test('raw MJPEG stays available when inference reports model_error', async () => {
  const service = await startVisionWithFakeCamera({ modelError: 'checkpoint missing' });
  const health = await json(service.url('/health'));
  assert.equal(health.camera.status, 'ready');
  assert.equal(health.inference.status, 'error');
  assert.equal((await fetch(service.url('/camera/xvisio/raw'))).status, 200);
  assert.equal((await fetch(service.url('/camera/xvisio/vision'))).status, 503);
});
```

```python
def test_capture_worker_keeps_publishing_after_model_load_failure():
    runtime = CameraRuntime(fake_frames(), model_factory=raising_model_factory)
    assert runtime.next_raw_frame(timeout=1).sequence == 1
    assert runtime.status()["inference"]["status"] == "error"
```

- [ ] **Step 2: Run the service tests**

Run: `local/runtimes/node/bin/node --test tests/node/vision_service/server.test.js`

Run: `local/runtimes/python/bin/python -m pytest tests/python/vision_service/test_camera_fallback.py -v`

Expected: FAIL because Vision Service is absent.

- [ ] **Step 3: Promote the minimum complete vision package**

Copy the required `thirdhand_va.common`, `thirdhand_va.vision` and calibration read-only modules from `migration/sources/vision-grasp` into `services/vision/python`. Do not copy its Startouch action adapter or executable robot workflow.

- [ ] **Step 4: Separate capture lifecycle from inference lifecycle**

Start the XVisio capture worker first. Publish one-slot raw/depth buffers immediately. Load Grounded-SAM in a separate inference worker; on load failure, record the error and keep capture alive. Clear selections and stable target references after camera restart.

- [ ] **Step 5: Implement the loopback HTTP/MJPEG service**

Use the Node camera-process wrapper to own one Python child and fan out MJPEG to multiple clients without buffering stale frames. Enforce exact methods and paths, bounded JSON bodies, no arbitrary proxy target, and atomic `vision.ready` creation after port 3100 binds.

- [ ] **Step 6: Run replay and service tests**

Run: `local/runtimes/python/bin/python -m pytest tests/python/vision_service -v`

Run: `local/runtimes/node/bin/node --test tests/node/vision_service/*.test.js`

Expected: PASS in replay/fake-camera mode without hardware or network.

- [ ] **Step 7: Commit**

```bash
git add services/vision tests/python/vision_service tests/node/vision_service
git commit -m "feat: add resilient XVisio vision service"
```

### Task 6: Proxy Vision through 9983 and wire target selection

**Files:**
- Create: `apps/web/src/http-proxy.js`
- Create: `apps/web/src/vision-proxy.js`
- Create: `tests/node/web/vision-proxy.test.js`
- Modify: `apps/web/src/config.js`
- Modify: `apps/web/src/server.js`
- Modify: `apps/web/public/js/main.js`

**Interfaces:**
- Consumes: `VISION_HTTP_URL=http://127.0.0.1:3100` and Vision command/events.
- Produces: same-origin `/camera/xvisio/{raw,vision,depth}`, `/api/vision/status` and browser vision events.

- [ ] **Step 1: Replace the old 503 assertion with failing proxy tests**

```javascript
test('vision MJPEG is streamed without buffering the body', async () => {
  const response = await fetch(origin + '/camera/xvisio/raw');
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /boundary=frame/);
});

test('vision failure remains structured', async () => {
  visionStub.close();
  const response = await fetch(origin + '/api/vision/status');
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'vision_upstream_unavailable');
});
```

- [ ] **Step 2: Run Web Gateway tests**

Run: `local/runtimes/node/bin/node --test tests/node/web/server.test.js tests/node/web/vision-proxy.test.js`

Expected: FAIL because vision paths still return the migration placeholder.

- [ ] **Step 3: Implement allowlisted streaming proxy routes**

Proxy only configured vision paths and methods, pass MJPEG backpressure through Node streams, abort upstream requests when the browser disconnects, and translate connection failures to structured 503 responses.

- [ ] **Step 4: Wire raw/识别 tabs and stable target events**

Keep `识别` mapped to the overlay route and `原始` mapped to raw. On inference error, select raw automatically and show the specific model error. Forward target selection to Vision only; movement commands continue through Robot and remain authorization-gated.

- [ ] **Step 5: Run all Web tests**

Run: `local/runtimes/node/bin/node --test tests/node/web/*.test.js`

Expected: PASS, including robot command isolation.

- [ ] **Step 6: Commit**

```bash
git add apps/web tests/node/web
git commit -m "feat: expose XVisio streams through web gateway"
```

### Task 7: Integrate lifecycle, documentation and no-motion acceptance

**Files:**
- Modify: `package.json`
- Modify: `configs/runtime/manual-control.json`
- Modify: `configs/runtime/default.json`
- Modify: `apps/launcher/src/service-supervisor.js`
- Modify: `tests/node/launcher/runtime-profiles.test.js`
- Modify: `tests/integration/test_simulated_lifecycle.py`
- Modify: `docs/RUN_GUIDE.md`
- Modify: `docs/DIRECTORY_MAP.md`
- Modify: `docs/OPERATIONS.md`

**Interfaces:**
- Consumes: formal Speech, Vision, Robot and Web entrypoints.
- Produces: idempotent `./thirdhand start|status|stop` lifecycle with ordered readiness.

- [ ] **Step 1: Write failing runtime-profile tests**

```javascript
test('manual-control starts internal services before web', () => {
  const profile = loadProfile('manual-control');
  assert.deepEqual(profile.services.filter(s => s.enabled).map(s => s.id),
    ['robot', 'speech', 'vision', 'web']);
  assert.equal(profile.services.find(s => s.id === 'speech').port, 3004);
  assert.equal(profile.services.find(s => s.id === 'vision').port, 3100);
});
```

- [ ] **Step 2: Run launcher and lifecycle tests**

Run: `local/runtimes/node/bin/node --test tests/node/launcher/*.test.js`

Run: `local/runtimes/python/bin/python -m pytest tests/integration/test_simulated_lifecycle.py -v`

Expected: FAIL because profiles do not enable Speech/Vision.

- [ ] **Step 3: Add service definitions and longer model startup timeouts**

Configure Speech with project Python and model paths, Vision with project Node/Python and XVisio executable, and Web with internal upstream URLs. Make readiness timeout configurable per service so Medium model warm-up does not cause false failure.

- [ ] **Step 4: Update operator documentation**

Document:
- `sudo ip link set can0 up type can bitrate 1000000` remains separate hardware setup.
- `./thirdhand start --profile manual-control` is the normal one-command startup.
- 9983 is the only browser URL.
- 3004/3100 are loopback-only diagnostics.
- raw-video fallback and log locations.
- software stop is not a physical emergency stop.

- [ ] **Step 5: Run the complete no-hardware regression**

Run: `local/runtimes/node/bin/node --test tests/node/**/*.test.js`

Run: `local/runtimes/python/bin/python -m pytest tests/python tests/integration -v`

Expected: PASS without opening CAN or XVisio.

- [ ] **Step 6: Perform bounded XVisio-only acceptance**

Keep PID 82925 Robot Service running and do not send it commands. Build the driver, start Vision on 3100, and read a bounded number of frames. Verify:
- USB serial matches configuration.
- frame sequence increases.
- JPEG bytes are non-empty.
- `/health` reports camera ready.
- no process other than Robot owns `can0`.

- [ ] **Step 7: Start Speech and verify the formal model catalog**

Start Speech on 3004, connect with `thirdhand.voice.v1`, request `model.list`, and verify all three model IDs. Send a text-only request to exercise Claude compatibility without microphone recording or robot execution.

- [ ] **Step 8: Controlled Web Gateway cutover**

Stop only the currently owned 9983 Web Gateway process, leave Robot running, start the updated Web Gateway, and verify:
- `http://192.168.58.68:9983/health` reports robot, speech and vision dependencies.
- `/camera/xvisio/raw` returns MJPEG.
- `/camera/xvisio/vision` returns overlay or an explicit model error.
- `/voice` negotiates the expected subprotocol.
- Robot state continues to update and no connect/home/move command was sent automatically.

- [ ] **Step 9: Commit**

```bash
git add package.json configs/runtime apps/launcher tests docs
git commit -m "feat: run speech and vision in unified platform"
```

### Task 8: Final verification and evidence

**Files:**
- Create: `docs/validation/SPEECH_XVISIO_ACCEPTANCE_2026-09-11.md`

**Interfaces:**
- Consumes: test output, service health, frame metadata and process/port inspection.
- Produces: a reproducible acceptance record without secrets, model files or captured private audio.

- [ ] **Step 1: Record versions and health without credentials**

Record Git commit, Ubuntu version, Node/Python versions, XVisio USB ID, XVisio SDK package version, service PIDs, bind addresses and health JSON. Do not include API keys, bearer tokens, audio content or model weights.

- [ ] **Step 2: Run tracked-file and boundary audits**

Run: `git status --short`

Run: `local/runtimes/python/bin/python tools/diagnostics/audit_boundaries.py`

Run: `git ls-files local runtime`

Expected: no tracked SDK/model/runtime payload and no formal runtime import from migration/archive/old absolute paths.

- [ ] **Step 3: Re-run focused regression**

Run: `local/runtimes/node/bin/node --test tests/node/web/*.test.js tests/node/vision_service/*.test.js tests/node/launcher/*.test.js`

Run: `local/runtimes/python/bin/python -m pytest tests/python/speech_service tests/python/vision_service tests/integration/test_simulated_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 4: Commit the acceptance record**

```bash
git add docs/validation/SPEECH_XVISIO_ACCEPTANCE_2026-09-11.md
git commit -m "docs: record speech and XVisio acceptance"
```
