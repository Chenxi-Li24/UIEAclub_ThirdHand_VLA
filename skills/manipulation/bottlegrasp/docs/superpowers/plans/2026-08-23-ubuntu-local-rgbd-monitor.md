# Ubuntu Local RGB-D Vision Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the existing camera image, algorithm overlay, and a clearly visible synchronized depth heatmap in one native Ubuntu window viewed through ToDesk.

**Architecture:** Extend the read-only preview source boundary with a multipart reader that preserves upstream frame identity. Pair the algorithm and depth streams by exact frame ID, compose them in a pure visualization function, and keep X11/OpenCV window lifecycle in a thin independently runnable app.

**Tech Stack:** Python 3.10+, Python `urllib`, OpenCV Qt5, NumPy, pytest, VS Code Remote-SSH. No new dependency and no new listening port.

**Spec:** `docs/superpowers/specs/2026-08-23-ubuntu-local-rgbd-monitor-design.md`

## Global Constraints

- The window appears on Ubuntu X11 display `:1` and is viewed with ToDesk.
- Do not open, close, restart, or modify the camera producer or listeners on ports 3000, 8765, and 8766.
- Read only `/camera_lumos_vision` and `/camera_xvisio_depth` from the existing loopback service.
- Fuse only equal `X-ThirdHand-Frame-Id` values; never blend stale depth into a newer algorithm frame.
- Preserve registered geometry; do not resize a mismatched depth image.
- Keep networking, pure visualization, synchronization, and app lifecycle as separate responsibilities.
- Every core behavior has an offline unit test and the app has a VS Code debug entry.

---

### Task 1: Tagged multipart MJPEG source

**Files:**
- Modify: `src/thirdhand_va/vision/preview/source.py`
- Modify: `src/thirdhand_va/vision/preview/__init__.py`
- Modify: `tests/vision/preview/test_source.py`

**Interfaces:**
- Produces: optional provenance fields on `SourceFrame` and `MultipartMjpegSource.read() -> SourceFrame`.
- Consumes: an injected `urlopen`-compatible opener for deterministic tests.

- [x] Add a test containing two real multipart byte parts and assert JPEG decoding, frame IDs, timestamps, SHA validation, and sequential reads.
- [x] Run `python -m pytest tests/vision/preview/test_source.py -q` and confirm it fails because `MultipartMjpegSource` is absent.
- [x] Implement bounded header parsing, exact content reads, provenance validation, OpenCV JPEG decode, and idempotent close.
- [x] Run the source tests and confirm they pass.

### Task 2: Synchronized depth buffering and pure fusion

**Files:**
- Create: `src/thirdhand_va/vision/preview/synchronization.py`
- Create: `src/thirdhand_va/vision/visualization/monitor.py`
- Modify: `src/thirdhand_va/vision/visualization/__init__.py`
- Create: `tests/vision/preview/test_synchronization.py`
- Create: `tests/vision/visualization/test_monitor.py`

**Interfaces:**
- Produces: `FrameIdBuffer.put(frame)`, `FrameIdBuffer.take(frame_id)`, and `compose_monitor_frame(algorithm_rgb, depth_heatmap_rgb, ...)`.
- Consumes: provenance-bearing `SourceFrame` values and same-size RGB images.

- [x] Add failing tests showing exact-ID matching, bounded stale-frame eviction, valid-pixel-only depth blending, visible legend/status, and input immutability.
- [x] Run the two focused test files and confirm failures are caused by missing modules.
- [x] Implement the minimal thread-safe frame buffer and pure compositor with default alpha 0.35 and black-pixel validity threshold.
- [x] Run both focused test files and confirm they pass.

### Task 3: Native Ubuntu monitor application

**Files:**
- Create: `apps/vision_monitor/__init__.py`
- Create: `apps/vision_monitor/main.py`
- Create: `tests/integration/test_vision_monitor_entrypoint.py`
- Modify: `.vscode/launch.json`

**Interfaces:**
- Produces: `python -m apps.vision_monitor.main` and VS Code launch `Vision Monitor: Ubuntu Desktop Window`.
- Consumes: live multipart sources by default or `--algorithm-image` plus `--depth-image` offline inputs.

- [x] Add failing tests for no-port defaults, paired offline arguments, and an injected one-frame window loop that closes only owned resources.
- [x] Run the integration test and confirm it fails because the app does not exist.
- [x] Implement CLI validation, live reconnection, the background depth reader, OpenCV window keys, structured status output, and offline-image mode.
- [x] Add the VS Code debug configuration using the deployment Python, `DISPLAY=:1`, and the current Xauthority path.
- [x] Run the integration test and all preview/visualization tests.

### Task 4: Documentation and live verification

**Files:**
- Modify: `docs/vision/preview.md`
- Modify: `docs/vision/modules.md`
- Modify: `README.md`

**Interfaces:**
- Documents: one-command launch, VS Code breakpoint files, keyboard controls, offline inputs, and proof that no listener is created.

- [x] Document the Ubuntu-window workflow and explicitly separate it from the existing Windows relay workflow.
- [x] Run module tests, integration tests, then the complete Python suite.
- [x] Record listeners before/after, start the monitor on X11 display `:1`, verify its process/window, and confirm ports 3000, 8765, and 8766 remain owned by the same processes.
