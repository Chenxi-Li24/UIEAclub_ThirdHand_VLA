# Windows LAN RGB-D Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the frame-aligned RGB, bottle-algorithm overlay, and depth heatmap to a Windows browser over the local LAN without using SSH or exposing any robot-control endpoint.

**Architecture:** Add a reusable `FrameSource` that composes the existing algorithm and depth MJPEG sources by exact upstream frame ID. Extend the existing preview HTTP boundary with an explicit LAN access policy, then assemble both pieces in a separate read-only `apps.vision_lan` process bound only to the Ubuntu LAN address on port 8770.

**Tech Stack:** Python 3.11, standard-library `http.server`, `ipaddress`, `hmac`, `secrets`, OpenCV, NumPy, pytest, existing ThirdHand preview interfaces. No new dependency and no web frontend.

**Spec:** `docs/superpowers/specs/2026-08-23-lan-rgbd-viewer-design.md`

## Global Constraints

- Bind only the explicit Ubuntu address `192.168.58.68`; reject `0.0.0.0` and `::`.
- Listen on new port 8770; do not stop, reuse, rebind, or modify ports 3000, 8765, or 8766.
- Read only `http://127.0.0.1:3000/camera_lumos_vision` and `http://127.0.0.1:3000/camera_xvisio_depth`.
- Fuse depth only when `X-ThirdHand-Frame-Id` exactly equals the algorithm frame ID.
- Permit only clients in `192.168.58.0/24` and require a generated token with at least 128 bits of entropy.
- Expose only `GET /stream.mjpg` and `GET /health`; do not expose robot, action, selection, files, directories, or a business page.
- Keep the current loopback-only behavior of `PreviewHttpServer` unchanged unless an explicit LAN policy is supplied.
- Work in the existing shared checkout and preserve all unrelated dirty and untracked files.
- Every core module must support hardware-free pytest execution and VS Code Remote-SSH breakpoints.

---

### Task 1: Exact-frame fused preview source

**Files:**
- Create: `src/thirdhand_va/vision/preview/fused_source.py`
- Modify: `src/thirdhand_va/vision/preview/__init__.py`
- Create: `tests/vision/preview/test_fused_source.py`

**Interfaces:**
- Consumes: `Callable[[], FrameSource]`, `Callable[[], TaggedFrameReader]`, `RegisteredDepthCoverage`, `compose_monitor_frame()`, and `render_monitor_notice()`.
- Produces: `SynchronizedCompositeSource(algorithm_source_factory, depth_reader_factory, *, match_timeout_s=0.30, depth_alpha=0.35, depth_coverage=None)` implementing `FrameSource`.
- Produces: `SynchronizedCompositeSource.read() -> SourceFrame` with algorithm provenance preserved on the composed image.

- [ ] **Step 1: Write the failing exact-match and missing-depth tests**

```python
def test_fused_source_composes_only_the_same_frame_id() -> None:
    algorithm = ScriptedSource(tagged(41, np.full((120, 180, 3), 100, np.uint8)))
    depth = RecordingDepthReader(tagged(41, depth_fixture()))
    source = SynchronizedCompositeSource(
        lambda: algorithm,
        lambda: depth,
        match_timeout_s=0,
        depth_coverage=RegisteredDepthCoverage(
            camera_serial="camera",
            reference_size=(180, 120),
            roi_xyxy=(20, 20, 160, 100),
        ),
    )

    source.open()
    frame = source.read()
    source.close()

    assert frame.frame_id == 41
    assert depth.requested_ids == [41]
    assert frame.image_rgb[60, 80].tolist() != [100, 100, 100]
    assert algorithm.close_count == 1
    assert depth.stop_count == 1


def test_fused_source_marks_waiting_instead_of_reusing_wrong_depth() -> None:
    algorithm = ScriptedSource(tagged(42, np.full((120, 180, 3), 100, np.uint8)))
    depth = RecordingDepthReader(tagged(41, depth_fixture()))
    source = SynchronizedCompositeSource(
        lambda: algorithm,
        lambda: depth,
        match_timeout_s=0,
    )

    source.open()
    frame = source.read()
    source.close()

    assert depth.requested_ids == [42]
    assert frame.frame_id == 42
    assert np.any(frame.image_rgb != 100)
    assert np.all(frame.image_rgb[40:80, 60:100] == 100)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/preview/test_fused_source.py -q
```

Expected: collection fails because `thirdhand_va.vision.preview.fused_source` and `SynchronizedCompositeSource` do not exist.

- [ ] **Step 3: Implement the minimal source lifecycle and composition**

```python
class SynchronizedCompositeSource:
    def __init__(
        self,
        algorithm_source_factory: Callable[[], FrameSource],
        depth_reader_factory: Callable[[], TaggedFrameReader],
        *,
        match_timeout_s: float = 0.30,
        depth_alpha: float = DEFAULT_MONITOR_DEPTH_ALPHA,
        depth_coverage: RegisteredDepthCoverage | None = None,
    ) -> None:
        if not callable(algorithm_source_factory) or not callable(depth_reader_factory):
            raise TypeError("source factories must be callable")
        if not 0 <= float(match_timeout_s) <= 2.0:
            raise ValueError("match_timeout_s must be within [0, 2]")
        self._algorithm_source_factory = algorithm_source_factory
        self._depth_reader_factory = depth_reader_factory
        self._match_timeout_s = float(match_timeout_s)
        self._depth_alpha = float(depth_alpha)
        self._depth_coverage = depth_coverage
        self._algorithm: FrameSource | None = None
        self._depth_reader: TaggedFrameReader | None = None

    @property
    def name(self) -> str:
        return "rgbd-fused"

    def open(self) -> None:
        if self._algorithm is not None:
            return
        algorithm = self._algorithm_source_factory()
        depth_reader = self._depth_reader_factory()
        try:
            algorithm.open()
            depth_reader.start()
        except Exception:
            algorithm.close()
            depth_reader.stop()
            raise
        self._algorithm = algorithm
        self._depth_reader = depth_reader

    def read(self) -> SourceFrame:
        if self._algorithm is None or self._depth_reader is None:
            raise SourceUnavailable("synchronized composite source is not open")
        algorithm = self._algorithm.read()
        if algorithm.frame_id is None:
            raise SourceUnavailable("algorithm frame is missing frame_id")
        depth = self._depth_reader.take(
            algorithm.frame_id,
            timeout_s=self._match_timeout_s,
        )
        image = self._compose(algorithm, depth)
        return SourceFrame(
            image,
            algorithm.received_monotonic_ns,
            frame_id=algorithm.frame_id,
            source_monotonic_ns=algorithm.source_monotonic_ns,
            observed_at_ms=algorithm.observed_at_ms,
        )

    def close(self) -> None:
        algorithm, self._algorithm = self._algorithm, None
        depth_reader, self._depth_reader = self._depth_reader, None
        if algorithm is not None:
            algorithm.close()
        if depth_reader is not None:
            depth_reader.stop()
```

Implement `_compose()` with existing `compose_monitor_frame()` for equal-size matched frames, `render_monitor_notice(..., detail="DEPTH WAITING")` for no match, and `DEPTH SIZE MISMATCH` for unequal dimensions. Scale `depth_coverage.roi_for_size()` exactly as the Ubuntu monitor does.

- [ ] **Step 4: Run fused-source and existing monitor tests and confirm GREEN**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/preview/test_fused_source.py tests/vision/preview/test_synchronization.py tests/integration/test_vision_monitor_entrypoint.py tests/vision/visualization/test_monitor.py -q
```

Expected: all tests pass and the original native monitor behavior remains unchanged.

- [ ] **Step 5: Commit only the fused-source task**

```bash
git add bottlegrasp/src/thirdhand_va/vision/preview/fused_source.py bottlegrasp/src/thirdhand_va/vision/preview/__init__.py bottlegrasp/tests/vision/preview/test_fused_source.py
git commit -m "feat: add synchronized RGB-D preview source"
```

---

### Task 2: Explicit LAN access policy for the read-only HTTP boundary

**Files:**
- Modify: `src/thirdhand_va/vision/preview/server.py`
- Modify: `src/thirdhand_va/vision/preview/__init__.py`
- Modify: `tests/vision/preview/test_server.py`

**Interfaces:**
- Produces: `PreviewAccessPolicy.lan(access_token: str, allowed_networks: Iterable[str]) -> PreviewAccessPolicy`.
- Produces: `PreviewAccessPolicy.validate_bind(host: str) -> None` and `PreviewAccessPolicy.allows(client_host: str, supplied_token: str | None) -> bool`.
- Extends: `PreviewHttpServer(..., access_policy: PreviewAccessPolicy | None = None)` while preserving loopback-only defaults.

- [ ] **Step 1: Write failing policy and HTTP authorization tests**

```python
def test_lan_policy_requires_token_network_and_specific_bind_address() -> None:
    policy = PreviewAccessPolicy.lan(
        access_token="A" * 32,
        allowed_networks=("192.168.58.0/24",),
    )

    policy.validate_bind("192.168.58.68")
    with pytest.raises(ValueError, match="unspecified"):
        policy.validate_bind("0.0.0.0")
    assert policy.allows("192.168.58.125", "A" * 32) is True
    assert policy.allows("192.168.58.125", "wrong-token-that-is-long") is False
    assert policy.allows("192.168.59.10", "A" * 32) is False


def test_lan_server_requires_token_for_health_and_stream(running_lan_preview) -> None:
    _, _, address, token = running_lan_preview

    assert request(address, "GET", "/health")[0] == 403
    assert request(address, "GET", f"/health?token={token}")[0] == 200
    assert request(address, "GET", f"/?token={token}")[0] == 404
    assert request(address, "POST", f"/health?token={token}")[0] == 405
```

The LAN fixture binds to `127.0.0.1:0` with an allowed test network of `127.0.0.0/8`; production validation is separately tested against `192.168.58.68` without opening a real LAN listener.

- [ ] **Step 2: Run the server test and confirm RED**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/preview/test_server.py -q
```

Expected: import or constructor failures because `PreviewAccessPolicy` and `access_policy` do not exist.

- [ ] **Step 3: Implement the policy and authorize before routing**

```python
@dataclass(frozen=True, slots=True)
class PreviewAccessPolicy:
    access_token: str | None = None
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @classmethod
    def loopback_only(cls) -> "PreviewAccessPolicy":
        return cls()

    @classmethod
    def lan(
        cls,
        *,
        access_token: str,
        allowed_networks: Iterable[str],
    ) -> "PreviewAccessPolicy":
        if len(access_token.encode("utf-8")) < 22:
            raise ValueError("LAN preview token must contain at least 128 bits")
        networks = tuple(ipaddress.ip_network(value, strict=False) for value in allowed_networks)
        if not networks:
            raise ValueError("LAN preview requires at least one allowed network")
        return cls(access_token=access_token, allowed_networks=networks)

    def validate_bind(self, host: str) -> None:
        address = ipaddress.ip_address(host)
        if address.is_unspecified:
            raise ValueError("preview host must not be an unspecified address")
        if self.access_token is None and not address.is_loopback:
            raise ValueError("preview host must be a loopback IP address")

    def allows(self, client_host: str, supplied_token: str | None) -> bool:
        address = ipaddress.ip_address(client_host)
        if self.access_token is None:
            return address.is_loopback
        in_network = any(address in network for network in self.allowed_networks)
        return in_network and supplied_token is not None and hmac.compare_digest(
            self.access_token,
            supplied_token,
        )
```

Parse the request with `urlsplit(self.path)` and `parse_qs(..., keep_blank_values=True)`. For token-protected policies, accept exactly one `token` value and no additional query parameters. Return `403` with `{"status": "forbidden", "read_only": true}` before serving health or video. Keep all existing loopback requests and tests valid without query parameters.

- [ ] **Step 4: Run server, service, and source tests and confirm GREEN**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/vision/preview/test_server.py tests/vision/preview/test_service.py tests/vision/preview/test_source.py -q
```

Expected: all tests pass, including the original non-loopback rejection when no policy is supplied.

- [ ] **Step 5: Commit only the access-policy task**

```bash
git add bottlegrasp/src/thirdhand_va/vision/preview/server.py bottlegrasp/src/thirdhand_va/vision/preview/__init__.py bottlegrasp/tests/vision/preview/test_server.py
git commit -m "feat: secure LAN access to read-only preview"
```

---

### Task 3: Standalone LAN viewer application and VS Code debug entry

**Files:**
- Create: `apps/vision_lan/__init__.py`
- Create: `apps/vision_lan/main.py`
- Create: `tests/integration/test_vision_lan_entrypoint.py`
- Modify: `.vscode/launch.json`

**Interfaces:**
- Produces: `python -m apps.vision_lan.main`.
- Produces: CLI options `--host`, `--allowed-network`, `--port`, `--access-token`, `--algorithm-url`, `--depth-url`, `--depth-alpha`, `--match-timeout-seconds`, `--reconnect-seconds`, `--open-timeout-ms`, and `--read-timeout-ms`.
- Produces: `run(args, stop_event, *, service_factory=PreviewService, server_factory=PreviewHttpServer) -> int` for injected integration tests.

- [ ] **Step 1: Write failing CLI, lifecycle, and no-control tests**

```python
def test_lan_entrypoint_defaults_are_read_only_and_use_new_port() -> None:
    args = build_parser().parse_args([
        "--host", "192.168.58.68",
        "--allowed-network", "192.168.58.0/24",
    ])

    assert args.port == 8770
    assert args.algorithm_url == "http://127.0.0.1:3000/camera_lumos_vision"
    assert args.depth_url == "http://127.0.0.1:3000/camera_xvisio_depth"
    assert not any("robot" in action.dest or "control" in action.dest
                   for action in build_parser()._actions)


def test_lan_entrypoint_generates_token_and_closes_only_owned_resources(capsys) -> None:
    service = RecordingService()
    server = RecordingServer(("192.168.58.68", 8770))
    stop = threading.Event()
    stop.set()

    exit_code = run(
        validate_args(build_parser().parse_args([
            "--host", "192.168.58.68",
            "--allowed-network", "192.168.58.0/24",
        ])),
        stop,
        service_factory=lambda *_args, **_kwargs: service,
        server_factory=lambda *_args, **_kwargs: server,
    )

    event = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert event["type"] == "vision_lan_ready"
    assert event["stream_url"].startswith("http://192.168.58.68:8770/stream.mjpg?token=")
    assert service.start_count == service.stop_count == 1
    assert server.start_count == server.stop_count == 1
    assert event["robot_control_enabled"] is False
```

- [ ] **Step 2: Run the entrypoint test and confirm RED**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_vision_lan_entrypoint.py -q
```

Expected: collection fails because `apps.vision_lan.main` does not exist.

- [ ] **Step 3: Implement the thin application assembly**

```python
DEFAULT_ALGORITHM_URL = "http://127.0.0.1:3000/camera_lumos_vision"
DEFAULT_DEPTH_URL = "http://127.0.0.1:3000/camera_xvisio_depth"
DEFAULT_PORT = 8770


def resolve_token(value: str | None) -> str:
    token = value or secrets.token_urlsafe(24)
    if len(token.encode("utf-8")) < 22:
        raise ValueError("--access-token must contain at least 128 bits")
    return token


def run(args, stop_event, *, service_factory=PreviewService, server_factory=PreviewHttpServer) -> int:
    token = resolve_token(args.access_token)
    coverage = RegisteredDepthCoverage(
        camera_serial="250801DR48FP25002738",
        reference_size=(640, 480),
        roi_xyxy=(203, 149, 428, 319),
    )
    fused_factory = lambda: SynchronizedCompositeSource(
        lambda: MultipartMjpegSource(
            args.algorithm_url,
            name="algorithm",
            open_timeout_ms=args.open_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
        ),
        lambda: TaggedFrameReader(
            lambda: MultipartMjpegSource(
                args.depth_url,
                name="depth",
                open_timeout_ms=args.open_timeout_ms,
                read_timeout_ms=args.read_timeout_ms,
            ),
            reconnect_interval_s=args.reconnect_seconds,
        ),
        match_timeout_s=args.match_timeout_seconds,
        depth_alpha=args.depth_alpha,
        depth_coverage=coverage,
    )
    service = service_factory(fused_factory, fallback_factory=None)
    policy = PreviewAccessPolicy.lan(
        access_token=token,
        allowed_networks=(args.allowed_network,),
    )
    server = server_factory(
        service,
        host=args.host,
        port=args.port,
        access_policy=policy,
    )
    service.start()
    try:
        host, port = server.start()
        query = urlencode({"token": token})
        print(json.dumps({
            "type": "vision_lan_ready",
            "stream_url": f"http://{host}:{port}/stream.mjpg?{query}",
            "health_url": f"http://{host}:{port}/health?{query}",
            "read_only": True,
            "robot_control_enabled": False,
        }, ensure_ascii=False, sort_keys=True), flush=True)
        while not stop_event.wait(0.25):
            pass
        return 0
    finally:
        server.stop()
        service.stop()
```

Install SIGINT/SIGTERM handlers exactly like `apps.vision_monitor.main`. Reject an unspecified host, a loopback host, a host outside `--allowed-network`, invalid port, invalid alpha, and non-loopback upstream URLs; the two upstream URLs must remain `127.0.0.1` HTTP endpoints so the LAN process cannot become an arbitrary proxy.

- [ ] **Step 4: Add the VS Code debug configuration**

```json
{
  "name": "Vision LAN: Debug Windows Viewer",
  "type": "debugpy",
  "request": "launch",
  "module": "apps.vision_lan.main",
  "python": "$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python",
  "args": [
    "--host", "192.168.58.68",
    "--allowed-network", "192.168.58.0/24",
    "--port", "8770"
  ],
  "cwd": "${workspaceFolder}",
  "console": "integratedTerminal",
  "justMyCode": true,
  "env": {"PYTHONUNBUFFERED": "1"}
}
```

- [ ] **Step 5: Run entrypoint and complete focused tests and confirm GREEN**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_vision_lan_entrypoint.py tests/vision/preview tests/vision/visualization/test_monitor.py tests/integration/test_vision_monitor_entrypoint.py -q
```

Expected: all tests pass without opening a production listener.

- [ ] **Step 6: Commit only the LAN application task**

```bash
git add bottlegrasp/apps/vision_lan bottlegrasp/tests/integration/test_vision_lan_entrypoint.py bottlegrasp/.vscode/launch.json
git commit -m "feat: add standalone LAN RGB-D viewer"
```

---

### Task 4: Operator documentation and live LAN verification

**Files:**
- Modify: `docs/vision/preview.md`
- Modify: `README.md`
- Test: `tests/integration/test_preview_debug_assets.py`

**Interfaces:**
- Documents: one foreground start command, the exact Windows URL, `Ctrl+C` shutdown, VS Code debug entry, health check, firewall diagnosis, and proof that existing ports are unchanged.

- [ ] **Step 1: Add a failing documentation contract test**

```python
def test_lan_viewer_documentation_has_safe_start_and_stop_contract() -> None:
    preview = (PROJECT_ROOT / "docs/vision/preview.md").read_text()
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "apps.vision_lan.main" in preview
    assert "192.168.58.68:8770" in preview
    assert "Ctrl+C" in preview
    assert "不经过 SSH" in preview
    assert "Vision LAN: Debug Windows Viewer" in preview
    assert "局域网" in readme and "8770" in readme
```

- [ ] **Step 2: Run the documentation test and confirm RED**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest tests/integration/test_preview_debug_assets.py -q
```

Expected: failure because the LAN viewer command and port are not documented.

- [ ] **Step 3: Document exact commands and Windows operation**

Document this foreground command:

```bash
cd $HOME/th0814/VA/bottlegrasp
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -u -m apps.vision_lan.main \
  --host 192.168.58.68 \
  --allowed-network 192.168.58.0/24 \
  --port 8770
```

State that the terminal prints the full tokenized URL, Windows opens that URL in Edge/Chrome/VLC, `Ctrl+C` closes only port 8770, and the VS Code Ports panel must not be used because that would route through SSH. Include these diagnostics:

```bash
ss -ltnp '( sport = :3000 or sport = :8765 or sport = :8766 or sport = :8770 )'
curl --fail 'http://192.168.58.68:8770/health?token=TOKEN_FROM_STARTUP'
```

- [ ] **Step 4: Run focused and full non-hardware test suites**

Run:

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest -q tests/vision/preview tests/vision/visualization tests/integration/test_vision_lan_entrypoint.py tests/integration/test_vision_monitor_entrypoint.py tests/integration/test_preview_debug_assets.py
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest -q
```

Expected: all tests pass; any pre-existing unrelated failure is recorded before proceeding to live verification.

- [ ] **Step 5: Record existing listener ownership and start the LAN viewer**

Run before startup:

```bash
ss -ltnp '( sport = :3000 or sport = :8765 or sport = :8766 or sport = :8770 )'
```

Start the foreground process with the documented command, retain its session, and copy the printed stream URL. Do not kill or restart any existing listener.

- [ ] **Step 6: Verify the live fused stream and unchanged ports**

Read `/health` and one MJPEG part through `192.168.58.68:8770` using the generated token. Decode the JPEG with OpenCV and assert it is a 640x480 RGB image containing the depth legend/overlay. Re-run the listener command and confirm the owners of 3000, 8765, and 8766 have the same PIDs while 8770 is owned only by `apps.vision_lan.main`.

Ask the user to open the printed URL on Windows with the VS Code port forward closed. If Windows cannot connect but the Ubuntu LAN-address curl succeeds, report that the Ubuntu firewall or Wi-Fi client isolation requires local administrator/network action; do not bind `0.0.0.0` or expose port 3000 as a workaround.

- [ ] **Step 7: Commit documentation and test changes**

```bash
git add bottlegrasp/docs/vision/preview.md bottlegrasp/README.md bottlegrasp/tests/integration/test_preview_debug_assets.py bottlegrasp/docs/superpowers/plans/2026-08-23-lan-rgbd-viewer.md
git commit -m "docs: add LAN RGB-D viewer workflow"
```
