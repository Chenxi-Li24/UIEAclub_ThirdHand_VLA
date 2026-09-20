# Windows VS Code Fused Camera Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Ubuntu preview relay that keeps the existing fused RGB/depth/mask visualization visible in a Windows VS Code Remote-SSH tab and remains independently runnable and debuggable without owning the camera.

**Architecture:** The existing Vision pipeline remains the only producer of fused images. A new `thirdhand_va.vision.preview` package reads the existing fused MJPEG stream with OpenCV, falls back to raw RGB or an offline frame, stores only the newest encoded frame, and exposes a loopback-only MJPEG endpoint; a thin app and VS Code launch configuration compose these modules.

**Tech Stack:** Python 3.10+, OpenCV/FFmpeg, NumPy, Python `ThreadingHTTPServer`, pytest, VS Code `editor-browser` and Remote-SSH proxy. No new third-party runtime dependency.

**Spec:** `docs/superpowers/specs/2026-08-22-windows-vscode-fused-camera-preview-design.md`

## Global Constraints

- All camera capture, inference, fusion, relay, tests, and debug processes run on Ubuntu; Windows only displays the VS Code tab.
- Do not open or stop the XVisio camera from the preview relay; attach to the existing loopback MJPEG service.
- Keep the existing `render_overlay()` semantics, `depth_alpha=0.30`, mask alpha `0.32`, and robot fail-closed labels unchanged.
- The preview surface is read-only: no camera, bottle-selection, action, or robot-control endpoint.
- Bind only to `127.0.0.1`; do not expose the development server to the LAN.
- Keep only the latest frame. A slow viewer skips old frames and never applies backpressure to Vision.
- Retry the fused source every 2.0 seconds, use raw RGB fallback with a visible warning, and keep an offline frame visible when both sources fail.
- Reuse current OpenCV, `encode_jpeg()`, `FrameProvenance`, and `build_mjpeg_part()`; do not add ROS, WebRTC, X11, `mjpg-streamer`, or a frontend page.
- Every core module needs a deterministic offline test and a direct VS Code breakpoint path.
- Run module tests before interface, integration, optional live-hardware, and full regression tests.

---

## File Structure

```text
src/thirdhand_va/vision/preview/
├── __init__.py          Public preview interfaces only
├── source.py            MJPEG and replay frame-source adapters
├── service.py           Primary/fallback state machine and latest-frame store
└── server.py            Loopback-only read-only HTTP/MJPEG boundary
src/thirdhand_va/vision/visualization/preview_status.py
apps/vision_preview/{__init__.py,main.py}
scripts/vision/preview_smoke.py
tests/vision/preview/{test_source.py,test_service.py,test_server.py}
tests/vision/visualization/test_preview_status.py
tests/integration/{test_vision_preview_entrypoint.py,test_preview_debug_assets.py}
tests/hardware/test_live_vision_preview.py
.vscode/{settings.json,tasks.json,launch.json}
docs/vision/preview.md
README.md
docs/vision/modules.md
```

Do not modify perception, selection, geometry, tracking, Action, robot safety, or the currently running external service.

---

### Task 1: Frame Source Adapters

**Files:**
- Create: `src/thirdhand_va/vision/preview/__init__.py`
- Create: `src/thirdhand_va/vision/preview/source.py`
- Create: `tests/vision/preview/test_source.py`

**Interfaces:**
- Consumes: OpenCV `VideoCapture`, RGB NumPy arrays, a local image path.
- Produces: `SourceFrame`, `FrameSource`, `SourceUnavailable`, `OpenCvMjpegSource`, `ImageReplaySource`.

- [ ] **Step 1: Write failing source tests**

```python
def test_mjpeg_source_opens_ffmpeg_with_timeouts_and_returns_rgb():
    bgr = np.array([[[1, 2, 3]]], dtype=np.uint8)
    factory = CaptureFactoryStub(CaptureStub(opened=True, frames=[(True, bgr)]))
    source = OpenCvMjpegSource(
        "http://127.0.0.1:3000/camera_lumos_vision",
        open_timeout_ms=700, read_timeout_ms=900,
        capture_factory=factory, clock_ns=lambda: 123,
    )
    source.open()
    frame = source.read()
    assert factory.params == (
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 700,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 900,
    )
    assert frame.image_rgb.tolist() == [[[3, 2, 1]]]
    assert frame.received_monotonic_ns == 123


def test_mjpeg_failed_read_raises_source_unavailable():
    source = make_source(CaptureStub(opened=True, frames=[(False, None)]))
    source.open()
    with pytest.raises(SourceUnavailable, match="frame read failed"):
        source.read()


def test_image_replay_returns_independent_rgb_frames(tmp_path):
    path = tmp_path / "frame.jpg"
    cv2.imwrite(str(path), np.full((8, 10, 3), (1, 2, 3), np.uint8))
    source = ImageReplaySource(path, fps=60, sleeper=lambda _: None)
    source.open()
    first, second = source.read(), source.read()
    first.image_rgb[:] = 0
    assert np.any(second.image_rgb != 0)
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/vision/preview/test_source.py -q`.

Expected: collection fails because `thirdhand_va.vision.preview.source` does not exist.

- [ ] **Step 3: Implement minimal source contracts and adapters**

```python
@dataclass(frozen=True, slots=True)
class SourceFrame:
    image_rgb: NDArray[np.uint8]
    received_monotonic_ns: int


class FrameSource(Protocol):
    @property
    def name(self) -> str: ...
    def open(self) -> None: ...
    def read(self) -> SourceFrame: ...
    def close(self) -> None: ...


class SourceUnavailable(RuntimeError):
    pass
```

`OpenCvMjpegSource.open()` calls the injected/default factory with `cv2.CAP_FFMPEG` and the two timeout properties. Reject non-HTTP(S) URLs, timeout values outside `[100, 30_000]`, replay FPS outside `(0, 60]`, unreadable images, non-3-channel frames, and `read()` before `open()`. Convert BGR to RGB, return copies, and make `close()` idempotent.

- [ ] **Step 4: Export and run source tests GREEN**

Run `python -m pytest tests/vision/preview/test_source.py -q`.

Expected: all source tests pass.

- [ ] **Step 5: Commit**

```bash
git add bottlegrasp/src/thirdhand_va/vision/preview bottlegrasp/tests/vision/preview/test_source.py
git commit -m "feat: add independent preview frame sources"
```

---

### Task 2: Preview Status Rendering

**Files:**
- Create: `src/thirdhand_va/vision/visualization/preview_status.py`
- Modify: `src/thirdhand_va/vision/visualization/__init__.py`
- Create: `tests/vision/visualization/test_preview_status.py`

**Interfaces:**
- Consumes: RGB arrays and a short status detail.
- Produces: `render_preview_banner(rgb, title, detail)` and `render_offline_frame(width, height, detail)`.

- [ ] **Step 1: Write failing pure-renderer tests**

```python
def test_preview_banner_is_visible_and_does_not_mutate_input():
    rgb = np.full((120, 240, 3), 80, np.uint8)
    original = rgb.copy()
    rendered = render_preview_banner(
        rgb, title="VISION OFFLINE - RAW CAMERA", detail="retrying fused stream"
    )
    assert np.array_equal(rgb, original)
    assert rendered.shape == rgb.shape
    assert np.any(rendered[:52] != original[:52])
    assert encode_jpeg(rendered).startswith(b"\xff\xd8")


def test_offline_frame_has_requested_shape_and_content():
    rendered = render_offline_frame(320, 240, "no camera stream")
    assert rendered.shape == (240, 320, 3)
    assert rendered.dtype == np.uint8
    assert np.any(rendered != 0)
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/vision/visualization/test_preview_status.py -q`.

Expected: import failure for `preview_status`.

- [ ] **Step 3: Implement deterministic rendering**

`render_preview_banner()` copies its input, draws a dark translucent top panel, a red title, and a light detail line using `cv2.putText`. `render_offline_frame()` creates a dark `uint8` RGB frame and calls the same banner function. Validate image shape and dimensions; keep network and state logic out of this file.

- [ ] **Step 4: Export and run visualization tests GREEN**

Run `python -m pytest tests/vision/visualization/test_preview_status.py tests/vision/visualization/test_visualization.py -q`.

Expected: new renderer and existing overlay/depth tests pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add bottlegrasp/src/thirdhand_va/vision/visualization bottlegrasp/tests/vision/visualization
git commit -m "feat: render preview fallback status"
```

---

### Task 3: Latest-Frame Preview Service and Recovery State Machine

**Files:**
- Create: `src/thirdhand_va/vision/preview/service.py`
- Modify: `src/thirdhand_va/vision/preview/__init__.py`
- Create: `tests/vision/preview/test_service.py`

**Interfaces:**
- Consumes: `Callable[[], FrameSource]` factories, `encode_jpeg()`, status renderer, monotonic and wall clocks.
- Produces: `PreviewMode`, `PreviewFrame`, `PreviewStatus`, `PreviewService`.

- [ ] **Step 1: Write failing state-machine and latest-value tests**

```python
def test_service_prefers_fused_then_falls_back_and_recovers():
    clock = FakeClock()
    primary = SequenceFactory([
        ScriptedSource("fused", [SourceUnavailable("down")]),
        ScriptedSource("fused", [frame(30)]),
    ])
    fallback = SequenceFactory([ScriptedSource("raw", [frame(10), frame(20)])])
    service = PreviewService(
        primary, fallback, reconnect_interval_s=2.0,
        clock_ns=clock.monotonic_ns, wall_time_ms=clock.wall_time_ms,
    )
    service.run_once()
    assert service.status().mode == PreviewMode.RAW_FALLBACK
    assert service.wait_for_frame(-1, 0).mode == PreviewMode.RAW_FALLBACK
    clock.advance(2.0)
    service.run_once()
    assert service.status().mode == PreviewMode.FUSED
    assert service.wait_for_frame(-1, 0).source_name == "fused"


def test_latest_store_skips_frames_older_than_requested_sequence():
    service = service_with_primary_frames(frame(1), frame(2), frame(3))
    service.run_once(); service.run_once(); service.run_once()
    assert service.wait_for_frame(after_sequence=0, timeout_s=0).sequence == 2


def test_service_publishes_offline_frame_and_stop_is_idempotent():
    service = service_with_broken_sources()
    service.run_once()
    assert service.status().mode == PreviewMode.OFFLINE
    assert service.wait_for_frame(-1, 0).jpeg.startswith(b"\xff\xd8")
    service.stop(); service.stop()
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/vision/preview/test_service.py -q`.

Expected: import failure for `PreviewService`.

- [ ] **Step 3: Implement immutable outputs and one-slot storage**

```python
class PreviewMode(str, Enum):
    STARTING = "starting"
    FUSED = "fused"
    RAW_FALLBACK = "raw_fallback"
    OFFLINE = "offline"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    sequence: int
    jpeg: bytes
    mode: PreviewMode
    source_name: str
    source_received_monotonic_ns: int
    published_monotonic_ns: int
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class PreviewStatus:
    mode: PreviewMode
    source_name: str | None
    last_sequence: int | None
    last_frame_at_ms: int | None
    relay_frame_age_ms: float | None
    reconnect_count: int
```

Store one `PreviewFrame` behind `threading.Condition`. `wait_for_frame(after_sequence, timeout_s)` returns immediately for a newer frame, returns `None` on timeout/stopped, and never creates a per-client frame queue.

- [ ] **Step 4: Implement deterministic `run_once()` and lifecycle**

`run_once()` performs this exact order:

1. When due, create/open primary.
2. Read one primary frame; on success close fallback, encode and publish `FUSED`.
3. On primary failure, close it, increment `reconnect_count`, and schedule `now + 2.0 s`.
4. Create/open/read fallback; on success draw the warning and publish `RAW_FALLBACK`.
5. If neither source yields a frame, publish/throttle an encoded offline frame.

`start()` owns one daemon worker repeatedly calling `run_once()`. `stop()` sets the event, closes owned sources, notifies waiters, and joins within the configured read timeout plus one second. Factories, clocks, encoder, and status renderers stay injectable.

- [ ] **Step 5: Run service tests GREEN**

Run `python -m pytest tests/vision/preview/test_service.py tests/vision/preview/test_source.py tests/vision/visualization/test_preview_status.py -q`.

Expected: all tests pass without live network or camera access.

- [ ] **Step 6: Commit**

```bash
git add bottlegrasp/src/thirdhand_va/vision/preview bottlegrasp/tests/vision/preview/test_service.py
git commit -m "feat: add latest-frame preview recovery service"
```

---

### Task 4: Loopback-Only MJPEG and Health Server

**Files:**
- Create: `src/thirdhand_va/vision/preview/server.py`
- Modify: `src/thirdhand_va/vision/preview/__init__.py`
- Create: `tests/vision/preview/test_server.py`

**Interfaces:**
- Consumes: `PreviewService.status()`, `PreviewService.wait_for_frame()`, existing `FrameProvenance` and `build_mjpeg_part()`.
- Produces: `PreviewHttpServer.start() -> tuple[str, int]`, `PreviewHttpServer.stop()`, `/stream.mjpg`, `/health`.

- [ ] **Step 1: Write failing server contract tests**

```python
def test_server_rejects_non_loopback_binding():
    with pytest.raises(ValueError, match="loopback"):
        PreviewHttpServer(FakeService(), host="0.0.0.0", port=0)


def test_health_is_read_only_and_reports_client_count(running_server):
    status, body, headers = request(running_server, "GET", "/health")
    assert status == 200
    assert headers["cache-control"] == "no-store"
    assert json.loads(body) == {
        "status": "ok", "mode": "fused", "source": "fixture",
        "last_sequence": 7, "last_frame_at_ms": 1000,
        "relay_frame_age_ms": 5.0, "reconnect_count": 0,
        "clients": 0, "read_only": True,
    }
    assert request(running_server, "POST", "/health")[0] == 405


def test_stream_is_multipart_mjpeg_with_provenance(running_server):
    connection = http.client.HTTPConnection(*running_server)
    connection.request("GET", "/stream.mjpg")
    stream = connection.getresponse()
    payload = stream.read(expected_part_length)
    assert stream.status == 200
    assert stream.headers["content-type"] == "multipart/x-mixed-replace; boundary=frame"
    assert b"X-ThirdHand-Frame-Id: 7" in payload
    assert payload.endswith(fixture_jpeg + b"\r\n")


def test_slow_client_never_builds_a_historical_frame_queue():
    service = FakeService(frames=[preview_frame(1), preview_frame(2), preview_frame(3)])
    server = PreviewHttpServer(service, host="127.0.0.1", port=0)
    address = server.start()
    try:
        slow = open_stream(address, read=False)
        fast = open_stream(address, read=True)
        assert read_frame_id(fast) == 3
        assert service.per_client_queue_count == 0
        slow.close(); fast.close()
    finally:
        server.stop()
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/vision/preview/test_server.py -q`.

Expected: import failure for `PreviewHttpServer`.

- [ ] **Step 3: Implement the server boundary**

Use `ThreadingHTTPServer` with a handler factory closing over service/server state. Validate `ipaddress.ip_address(host).is_loopback`; allow `port=0` for tests. `GET /stream.mjpg` sends:

```python
self.send_response(HTTPStatus.OK)
self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
self.send_header("Pragma", "no-cache")
self.end_headers()
```

For every newer frame, call existing `build_mjpeg_part(frame.jpeg, FrameProvenance(...))`, write/flush, and exit on disconnect or server stop. Track client count under a lock in `try/finally`. Return JSON for health, 404 for unknown paths, and 405 for POST/PUT/PATCH/DELETE.

- [ ] **Step 4: Run preview module tests GREEN**

Run `python -m pytest tests/vision/preview -q`.

Expected: source, service, and server tests pass without hardware.

- [ ] **Step 5: Commit**

```bash
git add bottlegrasp/src/thirdhand_va/vision/preview bottlegrasp/tests/vision/preview/test_server.py
git commit -m "feat: expose loopback-only preview stream"
```

---

### Task 5: Thin CLI Application and Offline Integration Test

**Files:**
- Create: `apps/vision_preview/__init__.py`
- Create: `apps/vision_preview/main.py`
- Create: `tests/integration/test_vision_preview_entrypoint.py`

**Interfaces:**
- Consumes: source factories, `PreviewService`, `PreviewHttpServer`.
- Produces: `build_parser()`, `run(args, stop_event=None) -> int`, `main(argv=None) -> int`, and `python -m apps.vision_preview.main`.

- [ ] **Step 1: Write failing CLI and subprocess tests**

```python
def test_parser_defaults_are_safe_and_attach_only():
    args = build_parser().parse_args([])
    assert args.primary_url == "http://127.0.0.1:3000/camera_lumos_vision"
    assert args.fallback_url == "http://127.0.0.1:3000/camera_xvisio_raw"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.reconnect_seconds == 2.0


def test_replay_entrypoint_serves_decodable_mjpeg_without_camera(tmp_path):
    image = write_fixture_image(tmp_path / "preview.jpg")
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "apps.vision_preview.main",
         "--replay-image", str(image), "--port", "0", "--replay-fps", "8"],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    ready = json.loads(read_line_with_timeout(process.stdout, 5.0))
    assert ready["type"] == "preview_ready"
    frame = read_one_mjpeg_frame(ready["stream_url"])
    assert cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR) is not None
    process.send_signal(signal.SIGINT)
    assert process.wait(timeout=5) == 0
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/integration/test_vision_preview_entrypoint.py -q`.

Expected: import failure for `apps.vision_preview`.

- [ ] **Step 3: Implement parser and dependency assembly**

Use these defaults exactly:

```text
--primary-url       http://127.0.0.1:3000/camera_lumos_vision
--fallback-url      http://127.0.0.1:3000/camera_xvisio_raw
--replay-image      None
--replay-fps        5.0
--host              127.0.0.1
--port              8765
--open-timeout-ms   1500
--read-timeout-ms   1500
--reconnect-seconds 2.0
--jpeg-quality      85
```

With `--replay-image`, construct `ImageReplaySource` as primary and omit fallback. Otherwise each factory invocation creates a new `OpenCvMjpegSource`. Start service/server, print one flushed JSON line containing `type`, bound address, `stream_url`, `health_url`, `source_mode`, and `read_only: true`, then wait on the supplied stop event. Install SIGINT/SIGTERM handlers only in `main()`. In `finally`, stop server before service.

- [ ] **Step 4: Run all preview and entrypoint tests GREEN**

Run `python -m pytest tests/vision/preview tests/vision/visualization/test_preview_status.py tests/integration/test_vision_preview_entrypoint.py -q`.

Expected: all module and offline integration tests pass.

- [ ] **Step 5: Commit**

```bash
git add bottlegrasp/apps/vision_preview bottlegrasp/tests/integration/test_vision_preview_entrypoint.py
git commit -m "feat: add standalone vision preview app"
```

---

### Task 6: VS Code One-Action Window, Debug Profiles, and Documentation

**Files:**
- Create: `.vscode/settings.json`
- Create: `.vscode/tasks.json`
- Create: `.vscode/launch.json`
- Create: `scripts/vision/preview_smoke.py`
- Create: `docs/vision/preview.md`
- Modify: `README.md`
- Modify: `docs/vision/modules.md`
- Create: `tests/integration/test_preview_debug_assets.py`

**Interfaces:**
- Consumes: CLI app and loopback stream URL.
- Produces: normal F5 viewer, live/replay Python debug profiles, independent smoke command, exact operator instructions.

- [ ] **Step 1: Write failing configuration and smoke-entry tests**

```python
def test_vscode_preview_launches_integrated_remote_browser():
    launch = json.loads((PROJECT_ROOT / ".vscode/launch.json").read_text())
    window = named(launch["configurations"], "Vision Preview: Open Window")
    assert window["type"] == "editor-browser"
    assert window["url"] == "http://127.0.0.1:8765/stream.mjpg"
    assert window["preLaunchTask"] == "Vision Preview: Start Relay"
    settings = json.loads((PROJECT_ROOT / ".vscode/settings.json").read_text())
    assert settings["workbench.browser.enableRemoteProxy"] is True


def test_preview_smoke_has_no_camera_or_model_dependency():
    result = subprocess.run(
        [sys.executable, "scripts/vision/preview_smoke.py", "--help"],
        cwd=PROJECT_ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0
    assert "--url" in result.stdout and "--frames" in result.stdout
```

- [ ] **Step 2: Run tests and verify RED**

Run `python -m pytest tests/integration/test_preview_debug_assets.py -q`.

Expected: `.vscode` files and smoke script are absent.

- [ ] **Step 3: Add VS Code configuration**

Create workspace settings:

```json
{
  "workbench.browser.enableRemoteProxy": true,
  "remote.restoreForwardedPorts": true
}
```

Create background task `Vision Preview: Start Relay` running `python -u -m apps.vision_preview.main`; its background problem matcher becomes ready on the JSON `"type": "preview_ready"` line. Add:

- `Vision Preview: Open Window`: `editor-browser`, `/stream.mjpg`, prelaunch relay task.
- `Vision Preview: Debug Live Attach`: `debugpy`, module `apps.vision_preview.main`.
- `Vision Preview: Debug Replay`: same module with `--replay-image artifacts/vision/validation/spatial/three-left-2-overlay.jpg`.

Do not add HTML, JavaScript UI, external browser commands, or Windows executables.

- [ ] **Step 4: Implement independent smoke consumer**

`scripts/vision/preview_smoke.py` imports `OpenCvMjpegSource`, reads a configurable number of frames, and prints JSON with URL, frame count, width, height, elapsed seconds, measured FPS, and last receive time. Defaults: URL `http://127.0.0.1:8765/stream.mjpg`, `--frames 5`, 1500 ms timeouts. Return `0` on success and `2` with concise stderr JSON on source failure.

- [ ] **Step 5: Document exact workflows**

`docs/vision/preview.md` documents:

1. Remote-SSH normal viewing: select `Vision Preview: Open Window`, press `F5`.
2. Replay Debug with breakpoints in `source.py`, `service.py`, or `server.py`.
3. Terminal replay and live-attach commands.
4. Health and smoke commands.
5. Stop/restart and port-in-use diagnosis.
6. Port 3000 owns the camera; stopping preview never stops it.

Link the page from `README.md`; add `preview` to the Vision module table with input, output, and independent debug entry.

- [ ] **Step 6: Run tests GREEN**

Run `python -m pytest tests/integration/test_preview_debug_assets.py -q` and `python scripts/vision/preview_smoke.py --help`.

Expected: configuration assertions pass and smoke help exits zero.

- [ ] **Step 7: Commit**

```bash
git add bottlegrasp/.vscode bottlegrasp/scripts/vision/preview_smoke.py bottlegrasp/docs/vision bottlegrasp/README.md bottlegrasp/tests/integration/test_preview_debug_assets.py
git commit -m "docs: add VS Code vision preview workflow"
```

---

### Task 7: Optional Live Test and Full Verification

**Files:**
- Create: `tests/hardware/test_live_vision_preview.py`
- Modify only if evidence requires a fix: files introduced in Tasks 1--6.

**Interfaces:**
- Consumes: current loopback endpoints on port 3000 and all preview components.
- Produces: opt-in live evidence without mutating or restarting the camera service.

- [ ] **Step 1: Write opt-in live test**

```python
@pytest.mark.skipif(
    os.environ.get("THIRDHAND_LIVE_TEST") != "1",
    reason="set THIRDHAND_LIVE_TEST=1 to use the existing read-only stream",
)
def test_live_fused_preview_reads_three_fresh_frames():
    source = OpenCvMjpegSource(
        "http://127.0.0.1:3000/camera_lumos_vision",
        open_timeout_ms=1500, read_timeout_ms=1500,
    )
    source.open()
    try:
        frames = [source.read() for _ in range(3)]
    finally:
        source.close()
    assert all(frame.image_rgb.shape == (480, 640, 3) for frame in frames)
    assert frames[0].received_monotonic_ns < frames[-1].received_monotonic_ns
```

- [ ] **Step 2: Run module tests first**

Run `python -m pytest tests/vision/preview tests/vision/visualization/test_preview_status.py -q`.

Expected: all preview module tests pass.

- [ ] **Step 3: Run interface and offline integration tests**

Run `python -m pytest tests/integration/test_vision_preview_entrypoint.py tests/integration/test_preview_debug_assets.py -q`.

Expected: subprocess replay, MJPEG readback, VS Code config, and smoke contracts pass.

- [ ] **Step 4: Run opt-in read-only live test**

```bash
curl --fail --max-time 2 http://127.0.0.1:3000/camera_lumos_vision --output /dev/null
THIRDHAND_LIVE_TEST=1 python -m pytest tests/hardware/test_live_vision_preview.py -q
```

Expected: MJPEG bytes arrive and three `640x480` frames decode. Do not kill, restart, or reconfigure port 3000.

- [ ] **Step 5: Run live relay and measure it**

Terminal 1: `python -u -m apps.vision_preview.main`.

Terminal 2:

```bash
python scripts/vision/preview_smoke.py --frames 10
curl --fail http://127.0.0.1:8765/health
```

Expected: ten decodable frames, `fused`, `read_only: true`, and relay frame age that does not grow continuously. Stop only the preview app with `Ctrl+C`.

- [ ] **Step 6: Run existing non-hardware regressions**

```bash
python -m pytest tests/common tests/vision tests/action tests/integration -q
find tests/action tests/integration -name '*.js' -type f -print0 | sort -z | xargs -0 -n1 node
```

Expected: all existing Python and Node tests pass.

- [ ] **Step 7: Check scope**

Run `git diff --check` and `git status --short` from `/home/nieqingcao/th0814/VA`.

Expected: no whitespace errors; changes stay within this plan and approved documents.

- [ ] **Step 8: Commit live test or evidence-driven fixes**

```bash
git add bottlegrasp/tests/hardware/test_live_vision_preview.py
git commit -m "test: verify live fused preview attachment"
```

Do not commit runtime PIDs, logs, caches, captured private images, or temporary MJPEG data.
