# Reusable Vision SDK and GPT Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the reusable hardware-free vision SDK, prove an adapter/replay boundary, and add GPT-5.6 Terra text-image target grounding that ends in a browser-only identity preview with zero robot commands.

**Architecture:** The nested Python package at `packages/thirdhand-vision-sdk/` owns reusable perception contracts and algorithms, while `web-control/server/vision_sdk_adapter.py` owns compatibility with the current runtime. A separate CommonJS VLA service snapshots an exactly paired ID-labelled overlay and confirmed candidate list, calls an injected provider out of band, validates the structured decision against current vision state, appends a bounded audit record, and sends only preview state to the requesting browser.

**Tech Stack:** Python 3.10/3.11, NumPy, OpenCV, pytest, setuptools/build; Node.js 22 CommonJS, built-in `fetch`, `AbortController`, `crypto`, `node:assert`; OpenAI Responses API with `gpt-5.6-terra`, image input, and strict JSON Schema Structured Outputs; existing Express/WebSocket/vanilla browser UI.

## Global Constraints

- The first delivery never enables or issues robot, gripper, CAN, active-view, grasp, or trajectory commands; `robotExecutionEnabled` remains `false`.
- GPT runs only after an explicit browser request and never inside `VisionPipeline.process()` or the 15 FPS perception loop.
- Only an exactly paired, fresh ID-labelled overlay and confirmed candidates from the same `detection_result` frame may enter a grounding request.
- The model may return only `select`, `clarify`, or `none`; a selected identity must be in the request-specific integer enum and must pass current-state revalidation.
- GPT never supplies detection IDs, coordinates, poses, depth, trajectories, safety evidence, or motion authorization.
- `VLA_PROVIDER` defaults to `disabled`; CI uses `mock`; `openai` requires a server-side `OPENAI_API_KEY` and never silently falls back.
- Live OpenAI requests use `gpt-5.6-terra`, reasoning effort `low`, one attempt, an 8,000 ms timeout, and the Responses API; model ID remains server-controlled.
- Browser input is the exact object `{cmd: "ground_language_target", query: string}` with a trimmed query of 1–256 Unicode code points.
- Candidate count is at most 256, JPEG size at most 2 MiB, explanation at most 512 Unicode code points, and provider response body at most 64 KiB.
- Audit JSONL contains an explicit allowlist only, uses mode `0600`, stores image hashes but no image bytes, API keys, authorization headers, raw prompts, or unbounded raw responses.
- Default tests are hardware-free and network-free; real RTMDet/DINO installation remains owned by the pinned CUDA 12.8 deployment bootstrap.
- The current online vision implementation remains authoritative; this increment adds an adapter and offline parity harness but does not switch online implementation, run online shadow, or delete duplicate algorithms.
- Preserve unrelated untracked research files and do not push or publish packages unless the user separately authorizes that external action.

---

## File Map

- `packages/thirdhand-vision-sdk/`: corrected import of the reviewed SDK archive, independent tests, release builder, license, manifest, source map, docs, and examples.
- `web-control/server/vision_sdk_adapter.py`: one-way conversion between existing runtime frame/result contracts and SDK contracts; no device or network access.
- `tests/vision_deployment/test_vision_sdk_adapter.py`: deterministic conversion and fail-closed replay parity tests.
- `web-control/server/camera-bridge.js`: exact `detection_result` to next-overlay-JPEG pairing and immutable snapshot cache.
- `web-control/server/vision-status.js`: sanitized, fresh, confirmed candidate snapshot keyed by source frame ID and monotonic timestamp.
- `web-control/server/vla/contracts.js`: exact browser command, snapshot, provider response, and public state validation.
- `web-control/server/vla/prompt.js`: fixed prompt version and request-specific strict JSON schema.
- `web-control/server/vla/openai-provider.js`: bounded Responses API transport with cancellation, timeout, redaction, and usage extraction.
- `web-control/server/vla/mock-provider.js`: deterministic no-network provider for CI and operator preview tests.
- `web-control/server/vla/audit-log.js`: canonical bounded JSONL audit writer.
- `web-control/server/vla/grounding.js`: per-browser job lifecycle, provenance assembly, local revalidation, and advisory state machine.
- `web-control/server/vla/browser-handler.js`: pure preview-command handler used by the proxy and zero-motion tests.
- `web-control/server/config.js`: server-owned VLA environment configuration.
- `web-control/server/proxy.js`: preview-only WebSocket wiring and cancellation; no route from grounding to actuator functions.
- `web-control/web/js/grounding-ui.js`: isolated DOM controller for request submission, status rendering, and identity highlight.
- `web-control/web/js/main.js`, `web-control/web/index.html`, `web-control/web/css/style.css`: integrate the preview panel into the current control page.
- `.github/workflows/ci.yml`: independent nested SDK and no-network VLA preview jobs.
- `README.md`, `packages/thirdhand-vision-sdk/README.md`: install, configuration, safety boundary, and evaluation instructions.

### Task 1: Import and Correct the Reusable Vision SDK Package

**Files:**
- Create: `packages/thirdhand-vision-sdk/**` from the reviewed archive
- Create: `packages/thirdhand-vision-sdk/LICENSE`
- Modify: `packages/thirdhand-vision-sdk/LICENSES.md`
- Modify: `packages/thirdhand-vision-sdk/README.md`
- Modify: `packages/thirdhand-vision-sdk/scripts/build_release.py`
- Modify: `packages/thirdhand-vision-sdk/tests/test_provenance.py`
- Modify: `packages/thirdhand-vision-sdk/tests/test_release_contents.py`

**Interfaces:**
- Consumes: archive `/home/nieqingcao/.codex/attachments/e1417439-f78e-4c57-bcbc-f12a6fbf41b9/thirdhand-vision-sdk-20260806.zip`, verified source commit `1bb7b2e5cf359ded362481413bbf987fad33c9ef`.
- Produces: installable package `thirdhand-vision-sdk==0.1.0`; import root `thirdhand_vision`; standard manifest rows `<sha256><two spaces><relative path>`.

- [ ] **Step 1: Re-verify and import the reviewed archive without touching tracked source files**

```bash
review_dir="$(mktemp -d /tmp/thirdhand-sdk-import.XXXXXX)"
unzip -q /home/nieqingcao/.codex/attachments/e1417439-f78e-4c57-bcbc-f12a6fbf41b9/thirdhand-vision-sdk-20260806.zip -d "$review_dir"
python "$review_dir/thirdhand-vision-sdk/scripts/verify_source_unchanged.py" --source-root /home/nieqingcao/TH-Fanxy
mkdir -p packages
cp -a "$review_dir/thirdhand-vision-sdk" packages/thirdhand-vision-sdk
```

Expected: source verification exits `0`; `git status --short` shows only `packages/thirdhand-vision-sdk/` plus pre-existing unrelated files.

- [ ] **Step 2: Run the imported 65-test baseline before corrections**

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest packages/thirdhand-vision-sdk/tests -q
```

Expected: `65 passed`.

- [ ] **Step 3: Write failing provenance and release tests**

Add assertions that parse every non-empty `MANIFEST.sha256` line as a 64-character lowercase digest, two spaces, then a relative path; require `LICENSE` in `ALLOWED_ROOT_FILES`, the source distribution, and the deterministic ZIP; require the MIT grant text in `LICENSE`; require `LICENSES.md` to state that ThirdHand code is MIT licensed.

```python
def test_manifest_uses_sha256sum_compatible_layout() -> None:
    for line in (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        assert len(digest) == 64 and digest == digest.lower()
        int(digest, 16)
        assert relative and not Path(relative).is_absolute() and ".." not in Path(relative).parts


def test_package_carries_mit_license() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Permission is hereby granted, free of charge" in license_text
    assert "MIT" in (ROOT / "LICENSES.md").read_text(encoding="utf-8")
```

- [ ] **Step 4: Run the focused tests and verify failure**

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest packages/thirdhand-vision-sdk/tests/test_provenance.py packages/thirdhand-vision-sdk/tests/test_release_contents.py -q
```

Expected: FAIL because the imported manifest is path-first and `LICENSE` is absent from the release allowlist.

- [ ] **Step 5: Correct licensing and standardize the release manifest**

Copy the repository MIT `LICENSE` into the nested package, correct `LICENSES.md` and README verification instructions, add `LICENSE` to `ALLOWED_ROOT_FILES`, and make `_manifest_content()` emit hash-first rows.

```python
ALLOWED_ROOT_FILES = frozenset({
    "LICENSE",
    "LICENSES.md",
    MANIFEST_NAME,
    "README.md",
    "SOURCE_MAP.json",
    "pyproject.toml",
})


def _manifest_content(root: Path, paths: Iterable[Path]) -> str:
    rows = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative != MANIFEST_NAME:
            rows.append(f"{_sha256(path)}  {relative}")
    return "\n".join(sorted(rows, key=lambda row: row.split("  ", 1)[1])) + "\n"
```

- [ ] **Step 6: Regenerate the manifest and run package tests/examples**

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python packages/thirdhand-vision-sdk/scripts/build_release.py --help
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest packages/thirdhand-vision-sdk/tests -q
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python packages/thirdhand-vision-sdk/examples/minimal_mock.py
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python packages/thirdhand-vision-sdk/examples/multimodal_extension.py
```

Expected: all package tests pass; both examples exit `0`; the generated manifest is accepted by `sha256sum -c MANIFEST.sha256` from the package directory.

- [ ] **Step 7: Commit the package import**

```bash
git add packages/thirdhand-vision-sdk
git commit -m "feat(vision): import reusable hardware-free SDK"
```

### Task 2: Build and Inspect Independent SDK Release Artifacts

**Files:**
- Modify: `packages/thirdhand-vision-sdk/pyproject.toml`
- Create: `packages/thirdhand-vision-sdk/tests/test_distribution_artifacts.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: package and release allowlist from Task 1.
- Produces: wheel and sdist containing only package source, docs, config, notices, source map, and license; CI job `vision-sdk` for Python 3.10/3.11.

- [ ] **Step 1: Write the failing distribution-content test**

The test runs `python -m build --outdir <tmp>` and inspects both archives. It requires `thirdhand_vision`, `LICENSE`, `LICENSES.md`, `SOURCE_MAP.json`, and README while rejecting model weights, captures, logs, absolute `/home/` paths, `pyrealsense2`, `startouch`, bearer credentials, symlinks, and files over 1 MiB.

```python
@pytest.mark.parametrize("artifact_kind", ["wheel", "sdist"])
def test_distribution_has_license_and_no_runtime_assets(tmp_path: Path, artifact_kind: str) -> None:
    artifacts = build_distributions(ROOT, tmp_path)
    names, payloads = read_distribution(artifacts[artifact_kind])
    assert any(name.endswith("LICENSE") for name in names)
    assert any("thirdhand_vision/core/types.py" in name for name in names)
    forbidden = (b"/home/", b"pyrealsense2", b"Authorization: Bearer")
    assert all(token not in payload for payload in payloads.values() for token in forbidden)
```

- [ ] **Step 2: Run it and verify the packaging metadata is incomplete**

```bash
python -m pip install build
python -m pytest packages/thirdhand-vision-sdk/tests/test_distribution_artifacts.py -q
```

Expected: FAIL because package data/license inclusion and test helpers are not yet declared.

- [ ] **Step 3: Add exact distribution metadata and helpers**

```toml
[project]
license = {file = "LICENSE"}

[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
thirdhand_vision = ["py.typed"]
```

Add an empty `src/thirdhand_vision/py.typed`, implement archive readers using `zipfile` and `tarfile`, reject symbolic/hard links in sdists, and assert every payload is bounded.

- [ ] **Step 4: Add an isolated CI job**

```yaml
  vision-sdk:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        python-version: ["3.10", "3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install --upgrade pip build
      - run: pip install -e "packages/thirdhand-vision-sdk[test]"
      - run: pytest packages/thirdhand-vision-sdk/tests -q
      - run: python packages/thirdhand-vision-sdk/examples/minimal_mock.py
      - run: python packages/thirdhand-vision-sdk/examples/multimodal_extension.py
      - run: python -m build packages/thirdhand-vision-sdk
```

- [ ] **Step 5: Verify artifacts and commit**

```bash
python -m pytest packages/thirdhand-vision-sdk/tests -q
python -m build packages/thirdhand-vision-sdk
git add packages/thirdhand-vision-sdk .github/workflows/ci.yml
git commit -m "build(vision): validate SDK distributions"
```

Expected: tests pass; wheel and sdist build; artifact inspection finds no hardware runtime, weights, captures, logs, credentials, or machine paths.

### Task 3: Add the Runtime Adapter and Offline Parity Report

**Files:**
- Create: `web-control/server/vision_sdk_adapter.py`
- Create: `tests/vision_deployment/test_vision_sdk_adapter.py`
- Create: `scripts/vision/run_sdk_replay_parity.py`
- Create: `configs/vision/sdk_replay_parity.yaml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: runtime `vision.online_frames.FramePair`, runtime calibration dictionaries, SDK `FrameBundle`, `FusionCalibration`, and `PerceptionResult`.
- Produces: `frame_pair_to_sdk(pair, calibration) -> FrameBundle`, `sdk_result_to_detection_event(result, *, ts_ms) -> dict[str, Any]`, and `compare_replay_frames(legacy, sdk, thresholds) -> dict[str, Any]`.

- [ ] **Step 1: Write failing adapter tests**

Cover immutable RGB/depth conversion, Lumos/D435 camera roles, frame/depth stamps, calibration content ID, mask/bbox, detection/identity IDs, pose/covariance, blockers/reasons, non-finite rejection, mismatched dimensions, and forced `robot_execution_enabled: false`.

```python
def test_sdk_result_serializes_existing_event_without_actionability() -> None:
    event = sdk_result_to_detection_event(make_sdk_result(identity_id=12), ts_ms=1_700_000_000_000)
    assert event["type"] == "detection_result"
    assert event["frame_id"] == 42
    assert event["monotonic_ns"] == 9_000_000
    assert event["targets"][0]["identity_id"] == 12
    assert event["targets"][0]["actionable"] is False
    assert event["robot_execution_enabled"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_adapter_rejects_non_finite_depth(bad: float) -> None:
    pair = make_runtime_pair()
    pair.depth.depth_m[0, 0] = bad
    with pytest.raises(ValueError, match="finite or NaN only"):
        frame_pair_to_sdk(pair, make_calibration())
```

- [ ] **Step 2: Run the focused test and verify import failure**

```bash
PYTHONPATH=packages/thirdhand-vision-sdk/src:web-control/server pytest tests/vision_deployment/test_vision_sdk_adapter.py -q
```

Expected: FAIL with `ModuleNotFoundError: vision_sdk_adapter`.

- [ ] **Step 3: Implement strict conversion functions**

```python
def frame_pair_to_sdk(pair: RuntimeFramePair, calibration: Optional[FusionCalibration]) -> FrameBundle:
    rgb = validated_rgb_image(pair.rgb.image_rgb)
    depth = None if pair.depth is None else validated_depth(pair.depth.depth_m, rgb.shape[:2])
    return FrameBundle(
        rgb=rgb,
        stamp=SdkFrameStamp("lumos_rgb", pair.rgb.stamp.frame_id, pair.rgb.stamp.monotonic_ns),
        depth_m=depth,
        depth_stamp=None if pair.depth is None else SdkFrameStamp(
            "d435_depth", pair.depth.stamp.frame_id, pair.depth.stamp.monotonic_ns
        ),
        calibration=calibration,
    )


def sdk_result_to_detection_event(result: PerceptionResult, *, ts_ms: int) -> dict[str, Any]:
    return {
        "type": "detection_result",
        "ts": require_non_negative_int(ts_ms, "ts_ms"),
        "frame_id": result.frame_id,
        "monotonic_ns": result.monotonic_ns,
        "targets": [serialize_instance(item) for item in result.instances],
        "robot_execution_enabled": False,
        "active_view_execution_enabled": False,
    }
```

The serializer copies no descriptor vector or full mask into the event; it preserves bbox, identity status/memory summary, pose/covariance/frame/calibration ID, detection score, and bounded reason codes.

- [ ] **Step 4: Write and implement the deterministic parity comparator**

Declare thresholds in `sdk_replay_parity.yaml` before comparison: exact detection labels/counts and blockers, `identity_switch_delta_max: 0`, `pose_rmse_m_max: 0.005`, `covariance_abs_max: 0.0001`, `descriptor_cosine_delta_max: 0.02`. The CLI reads two JSONL result streams, compares matching frame IDs, writes a canonical JSON report, and exits `1` when any threshold fails.

```python
def compare_replay_frames(legacy: Sequence[dict], sdk: Sequence[dict], thresholds: Mapping[str, float]) -> dict:
    paired = pair_by_frame_id(legacy, sdk)
    metrics = compute_metrics(paired)
    failures = evaluate_thresholds(metrics, thresholds)
    return {"schema_version": 1, "metrics": metrics, "failures": failures, "passed": not failures}
```

- [ ] **Step 5: Run adapter/parity tests and add them to CI**

```bash
PYTHONPATH=packages/thirdhand-vision-sdk/src:web-control/server pytest tests/vision_deployment/test_vision_sdk_adapter.py -q
```

Add this command to the `vision-sdk` job after the nested package tests. Expected: PASS with no device, network, GPU, model weights, or robot imports.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision_sdk_adapter.py tests/vision_deployment/test_vision_sdk_adapter.py scripts/vision/run_sdk_replay_parity.py configs/vision/sdk_replay_parity.yaml .github/workflows/ci.yml
git commit -m "feat(vision): add SDK adapter and replay parity gate"
```

### Task 4: Capture an Exactly Paired Overlay and Candidate Snapshot

**Files:**
- Modify: `web-control/server/camera-bridge.js`
- Modify: `web-control/server/vision-status.js`
- Create: `web-control/server/test/camera-overlay-snapshot-smoke.js`
- Modify: `web-control/server/test/vision-status-smoke.js`

**Interfaces:**
- Consumes: camera child fd 3 `detection_result` JSON followed by fd 4 MJPEG for the same loop iteration.
- Produces: `CameraBridge.getLatestVisionSnapshot() -> null | {frameId, frameMonotonicNs, observedAtMs, imageSha256, jpeg}` and `VisionStatusStore.groundingSnapshot(nowMs) -> null | {frameId, frameMonotonicNs, observedAtMs, candidates}`.

- [ ] **Step 1: Write failing fragmented-MJPEG and defensive-copy tests**

Use an exported `OverlaySnapshotAssembler` so the test never spawns Python. Feed a detection event, then one JPEG split across several chunks and assert exact pairing; reject overlay-before-event, two pending events, a JPEG over 2 MiB, missing EOI, invalid frame IDs, and mismatched timestamps.

```javascript
const assembler = new OverlaySnapshotAssembler({ maxJpegBytes: 2 * 1024 * 1024 });
assembler.noteDetection({
  type: 'detection_result', frame_id: 42, monotonic_ns: 9000000, ts: 1000,
});
for (const chunk of splitMjpeg(fixtureJpeg, [3, 17, 61])) assembler.push(chunk);
const first = assembler.latest();
assert.equal(first.frameId, 42);
assert.match(first.imageSha256, /^sha256:[0-9a-f]{64}$/);
first.jpeg[0] = 0;
assert.notEqual(assembler.latest().jpeg[0], 0);
```

- [ ] **Step 2: Run tests and verify the APIs are missing**

```bash
node web-control/server/test/camera-overlay-snapshot-smoke.js
node web-control/server/test/vision-status-smoke.js
```

Expected: first command fails because `OverlaySnapshotAssembler` is not exported; second fails because `groundingSnapshot()` is absent.

- [ ] **Step 3: Implement bounded MJPEG pairing**

```javascript
class OverlaySnapshotAssembler {
  noteDetection(event) {
    this.pending = validateDetectionProvenance(event);
  }

  push(chunk) {
    for (const jpeg of this.parser.push(chunk)) {
      if (!this.pending || jpeg.length > this.maxJpegBytes) continue;
      this.snapshot = Object.freeze({
        ...this.pending,
        imageSha256: `sha256:${createHash('sha256').update(jpeg).digest('hex')}`,
        jpeg: Buffer.from(jpeg),
      });
      this.pending = null;
    }
  }

  latest() {
    return this.snapshot ? { ...this.snapshot, jpeg: Buffer.from(this.snapshot.jpeg) } : null;
  }
}
```

Wire `child.stdio[4].on('data', chunk => assembler.push(chunk))`; call `noteDetection()` inside `_handleLine()` immediately before emitting `detection_result`; clear assembler state on child exit/restart/shutdown.

- [ ] **Step 4: Preserve sanitized candidate provenance in VisionStatusStore**

Store validated `frame_id`, `monotonic_ns`, and `ts` during `updateTargets()`. Return only confirmed identities that also have a non-negative safe-integer detection ID, with `{identityId,detectionId,label,identityStatus,detectionScore}`; return `null` when stale, missing provenance, duplicated identity IDs, or no confirmed candidates.

```javascript
groundingSnapshot(nowMs = Date.now()) {
  if (!this._targetsAreFresh(nowMs) || this.targetFrameId === null) return null;
  const candidates = this.targets
    .filter(target => target.identityId !== null && Number.isSafeInteger(target.detectionId) &&
      target.detectionId >= 0 && target.identityStatus === 'confirmed')
    .map(target => Object.freeze({
      identityId: target.identityId,
      detectionId: target.detectionId,
      label: target.label,
      identityStatus: target.identityStatus,
      detectionScore: target.score,
    }));
  return candidates.length ? Object.freeze({
    frameId: this.targetFrameId,
    frameMonotonicNs: this.targetFrameMonotonicNs,
    observedAtMs: this.lastTargetsTs,
    candidates: Object.freeze(candidates),
  }) : null;
}
```

- [ ] **Step 5: Run existing and new bridge/status tests**

```bash
node web-control/server/test/camera-overlay-snapshot-smoke.js
node web-control/server/test/vision-status-smoke.js
PYTHONPATH=web-control/server pytest tests/vision_deployment/test_online_camera_bridge_contract.py -q
```

Expected: PASS; current MJPEG HTTP streams and command allowlists remain unchanged.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/camera-bridge.js web-control/server/vision-status.js web-control/server/test/camera-overlay-snapshot-smoke.js web-control/server/test/vision-status-smoke.js
git commit -m "feat(vla): snapshot paired vision evidence"
```

### Task 5: Define Strict Grounding Contracts and Prompt Schema

**Files:**
- Create: `web-control/server/vla/contracts.js`
- Create: `web-control/server/vla/prompt.js`
- Create: `web-control/server/test/vla-contracts-smoke.js`
- Create: `web-control/server/test/vla-prompt-smoke.js`

**Interfaces:**
- Consumes: exact browser command and paired snapshot outputs from Task 4.
- Produces: `parseGroundingCommand(message)`, `validateEvidence(vision, overlay, nowMs)`, `validateProviderDecision(value, allowedIds)`, `publicGroundingState(value)`, and `buildOpenAIRequest({query,evidence,model})`.

- [ ] **Step 1: Write failing exact-key, bound, and enum tests**

```javascript
assert.deepEqual(
  parseGroundingCommand({ cmd: 'ground_language_target', query: '  夹取可乐  ' }),
  { accepted: true, query: '夹取可乐' }
);
for (const invalid of [
  { cmd: 'ground_language_target', query: '' },
  { cmd: 'ground_language_target', query: 'x'.repeat(257) },
  { cmd: 'ground_language_target', query: '可乐', model: 'attacker-model' },
  { cmd: 'ground_language_target', query: '可乐', identityId: 12 },
]) assert.equal(parseGroundingCommand(invalid).accepted, false);

assert.deepEqual(
  validateProviderDecision({ decision: 'select', identity_id: 12, ambiguous: false,
    explanation: 'ID 12 是可乐瓶。', semantic_score: 0.91 }, new Set([12, 15])).decision,
  'select'
);
assert.throws(
  () => validateProviderDecision({ decision: 'select', identity_id: 99, ambiguous: false,
    explanation: 'x', semantic_score: 0.9 }, new Set([12, 15])),
  /identity_not_allowed/
);
```

- [ ] **Step 2: Run and verify missing modules**

```bash
node web-control/server/test/vla-contracts-smoke.js
node web-control/server/test/vla-prompt-smoke.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement exact local validators**

`validateEvidence()` requires equal frame IDs and timestamps between the sanitized candidate snapshot and overlay, age `0..2000 ms`, JPEG SOI/EOI, size `1..2097152`, `sha256:` digest, unique safe integer identities, and 1–256 candidates. It returns the copied evidence plus a frozen `allowedIdentityIds` array derived only from candidates. `validateProviderDecision()` rejects arrays, extra keys, non-finite score, oversized explanation, `ambiguous: true` on select, non-null IDs for clarify/none, and unknown IDs.

```javascript
const DECISION_KEYS = new Set([
  'decision', 'identity_id', 'ambiguous', 'explanation', 'semantic_score',
]);
const PUBLIC_STATE_KEYS = new Set([
  'type', 'status', 'requestId', 'identityId', 'explanation', 'reason',
  'provider', 'modelId', 'latencyMs',
]);

function parseGroundingCommand(message) {
  if (!exactKeys(message, new Set(['cmd', 'query'])) ||
      message.cmd !== 'ground_language_target') return rejected('browser_command_keys_invalid');
  const query = typeof message.query === 'string' ? message.query.trim() : '';
  if (Array.from(query).length < 1 || Array.from(query).length > 256) {
    return rejected('query_length_invalid');
  }
  return { accepted: true, query };
}
```

- [ ] **Step 4: Build the fixed prompt and strict Responses API schema**

Use prompt version `thirdhand-grounding-v1`. The system text states that visible `ID#N` labels and the enumerated candidate list are authoritative; the model must identify only the requested semantic object and must choose clarify/none when uncertain. The request uses low-detail image input and request-specific identity enum.

```javascript
function buildOpenAIRequest({ query, evidence, model }) {
  const allowedIds = evidence.candidates.map(item => item.identityId);
  return {
    model,
    reasoning: { effort: 'low' },
    input: [{ role: 'user', content: [
      { type: 'input_text', text: renderPrompt(query, evidence.candidates) },
      { type: 'input_image', image_url: `data:image/jpeg;base64,${evidence.jpeg.toString('base64')}`,
        detail: 'low' },
    ] }],
    text: { format: {
      type: 'json_schema', name: 'thirdhand_target_selection', strict: true,
      schema: decisionSchema(allowedIds),
    } },
    max_output_tokens: 300,
  };
}
```

- [ ] **Step 5: Run contract/prompt tests and commit**

```bash
node web-control/server/test/vla-contracts-smoke.js
node web-control/server/test/vla-prompt-smoke.js
git add web-control/server/vla/contracts.js web-control/server/vla/prompt.js web-control/server/test/vla-contracts-smoke.js web-control/server/test/vla-prompt-smoke.js
git commit -m "feat(vla): define strict grounding contracts"
```

### Task 6: Implement OpenAI and Deterministic Mock Providers

**Files:**
- Create: `web-control/server/vla/openai-provider.js`
- Create: `web-control/server/vla/mock-provider.js`
- Create: `web-control/server/test/vla-openai-provider-smoke.js`
- Create: `web-control/server/test/vla-mock-provider-smoke.js`

**Interfaces:**
- Consumes: `buildOpenAIRequest()` and `validateProviderDecision()` from Task 5.
- Produces: `OpenAIProvider.select({query,evidence,signal}) -> Promise<ProviderResult>` and `MockProvider.select({query,evidence,signal}) -> Promise<ProviderResult>` where `ProviderResult` contains validated `decision`, `provider`, `modelId`, `latencyMs`, and bounded token usage.

- [ ] **Step 1: Write fake-transport tests for every failure class**

Cover valid select/clarify/none, absent key, HTTP 401/429/500, quota, timeout, external cancellation, invalid JSON, missing output text, refusal, incomplete response, extra decision keys, unknown identity, body over 64 KiB, and proof that authorization/data URL never appears in returned errors.

```javascript
const requests = [];
const provider = new OpenAIProvider({
  apiKey: 'test-secret', model: 'gpt-5.6-terra', timeoutMs: 8000,
  fetchImpl: async (url, options) => {
    requests.push({ url, options });
    return fakeJsonResponse(makeResponseOutput({ decision: 'select', identity_id: 12,
      ambiguous: false, explanation: 'ID 12 是可乐瓶。', semantic_score: 0.91 }));
  },
  nowMs: sequenceClock([1000, 1120]),
});
const result = await provider.select({ query: '夹取可乐', evidence, signal: new AbortController().signal });
assert.equal(result.decision.identityId, 12);
assert.equal(result.latencyMs, 120);
assert.equal(requests[0].options.headers.Authorization, 'Bearer test-secret');
assert.equal(JSON.stringify(result).includes('test-secret'), false);
```

- [ ] **Step 2: Run and verify missing providers**

```bash
node web-control/server/test/vla-openai-provider-smoke.js
node web-control/server/test/vla-mock-provider-smoke.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement the bounded OpenAI transport**

Use direct built-in `fetch` to avoid a new Node dependency. Combine the caller signal with an 8-second timeout, send only to `https://api.openai.com/v1/responses`, read through a byte-limited stream, parse `output[].content[].type === "output_text"`, and normalize browser/audit errors to stable reason codes.

```javascript
async select({ query, evidence, signal }) {
  if (!this.apiKey) throw providerError('provider_unavailable');
  const timeout = AbortSignal.timeout(this.timeoutMs);
  const combined = AbortSignal.any([signal, timeout]);
  const response = await this.fetchImpl('https://api.openai.com/v1/responses', {
    method: 'POST', signal: combined,
    headers: { Authorization: `Bearer ${this.apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(buildOpenAIRequest({ query, evidence, model: this.model })),
  });
  const payload = JSON.parse(await readBoundedText(response.body, 64 * 1024));
  if (!response.ok) throw classifyHttpFailure(response.status, payload);
  const parsed = JSON.parse(extractOutputText(payload));
  return makeProviderResult(
    payload,
    validateProviderDecision(parsed, new Set(evidence.allowedIdentityIds))
  );
}
```

- [ ] **Step 4: Implement the deterministic mock provider**

The mock accepts an injected selector or a configured identity ID. It performs no fetch, validates the chosen ID against `evidence.allowedIdentityIds`, honors cancellation, and defaults to `none` rather than guessing.

```javascript
async select({ query, evidence, signal }) {
  if (signal.aborted) throw providerError('request_cancelled');
  const identityId = this.selectIdentity({ query, candidates: evidence.candidates });
  const raw = identityId === null
    ? { decision: 'none', identity_id: null, ambiguous: false,
        explanation: 'Mock provider found no configured match.', semantic_score: null }
    : { decision: 'select', identity_id: identityId, ambiguous: false,
        explanation: `Mock provider selected ID ${identityId}.`, semantic_score: 1 };
  return makeMockResult(
    validateProviderDecision(raw, new Set(evidence.allowedIdentityIds))
  );
}
```

- [ ] **Step 5: Run provider tests and commit**

```bash
node web-control/server/test/vla-openai-provider-smoke.js
node web-control/server/test/vla-mock-provider-smoke.js
git add web-control/server/vla/openai-provider.js web-control/server/vla/mock-provider.js web-control/server/test/vla-openai-provider-smoke.js web-control/server/test/vla-mock-provider-smoke.js
git commit -m "feat(vla): add bounded GPT grounding providers"
```

### Task 7: Add Audited Per-Browser Grounding Orchestration

**Files:**
- Create: `web-control/server/vla/audit-log.js`
- Create: `web-control/server/vla/grounding.js`
- Create: `web-control/server/test/vla-audit-log-smoke.js`
- Create: `web-control/server/test/vla-grounding-smoke.js`

**Interfaces:**
- Consumes: provider interface from Task 6, paired overlay/candidate getters from Task 4, validators from Task 5.
- Produces: `GroundingAuditLog.appendDecision(event)`, `GroundingService.submit({operator,query,send})`, `GroundingService.cancel(operator, reason)`, and public states `analyzing|selected|clarify|none|rejected|error`.

- [ ] **Step 1: Write failing audit allowlist and restart-safety tests**

Require contiguous sequence numbers across restart, canonical finite JSON, 64 KiB line limit, file mode `0600`, and explicit rejection of `apiKey`, `authorization`, `jpeg`, `image`, `rawResponse`, `prompt`, and unknown keys.

```javascript
const record = audit.appendDecision({
  requestId: REQUEST_ID, query: '夹取可乐', provider: 'mock', modelId: 'mock-v1',
  promptVersion: 'thirdhand-grounding-v1', schemaVersion: 1, frameId: 42,
  frameMonotonicNs: 9000000, imageSha256: IMAGE_SHA, allowedIdentityIds: [12, 15],
  decision: 'select', selectedIdentityId: 12, ambiguous: false,
  explanation: 'ID 12 是可乐瓶。', semanticScore: 0.91, validation: 'accepted',
  reason: null, latencyMs: 120, usage: { inputTokens: 100, outputTokens: 20, cachedTokens: 0 },
});
assert.equal(record.sequence, 1);
assert.throws(() => audit.appendDecision({ ...valid, apiKey: 'secret' }), /audit_keys_invalid/);
```

- [ ] **Step 2: Write orchestration race and revalidation tests**

Cover valid select, clarify, none, missing/stale/mismatched source evidence, no confirmed candidates, newer request cancels older request, browser close, timeout, provider error, selected identity disappeared, identity became ambiguous, current snapshot older than the source, current snapshot stale, a normal newer frame retaining the identity, and audit failure. Every case asserts only public state events were sent and no actuator callback exists in service dependencies.

```javascript
const service = new GroundingService({
  provider, auditLog, nowMs: clock.now, randomUUID: () => REQUEST_ID,
  getOverlaySnapshot: () => overlay,
  getVisionSnapshot: () => vision,
});
await service.submit({ operator, query: '夹取可乐', send: event => events.push(event) });
assert.deepEqual(events.map(event => event.status), ['analyzing', 'selected']);
assert.equal(events.at(-1).identityId, 12);
assert.equal('position' in events.at(-1), false);
```

- [ ] **Step 3: Run tests and verify missing modules**

```bash
node web-control/server/test/vla-audit-log-smoke.js
node web-control/server/test/vla-grounding-smoke.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 4: Implement the audit allowlist**

Use the existing active-view canonical JSON rules, but keep a separate VLA record schema. Bound query to 256 code points, explanation to 512, identity list to 256, reason/model/provider strings to 128, and usage to non-negative safe integers or null.

```javascript
const AUDIT_KEYS = Object.freeze([
  'requestId', 'query', 'provider', 'modelId', 'promptVersion', 'schemaVersion',
  'frameId', 'frameMonotonicNs', 'imageSha256', 'allowedIdentityIds', 'decision',
  'selectedIdentityId', 'ambiguous', 'explanation', 'semanticScore', 'validation',
  'reason', 'latencyMs', 'usage',
]);

appendDecision(event) {
  if (!exactKeys(event, new Set(AUDIT_KEYS))) throw new TypeError('audit_keys_invalid');
  return this.log.append(validateAuditEvent(event));
}
```

- [ ] **Step 5: Implement one in-flight request per operator**

Build immutable evidence only when overlay and candidate provenance match. Emit `analyzing`, await the provider, then fetch current vision state again and require the same selected identity to remain confirmed and fresh; a newer camera frame is expected and accepted, while a current snapshot older than the request source is rejected. Superseded/cancelled requests cannot emit a terminal selection. Audit every terminal path; audit failure converts the outcome to `error`.

```javascript
async submit({ operator, query, send }) {
  this.cancel(operator, 'superseded');
  const job = this._createJob(operator);
  this.jobs.set(operator, job);
  send(publicGroundingState({ status: 'analyzing', requestId: job.requestId }));
  try {
    const evidence = this._captureEvidence();
    const result = await this.provider.select({ query, evidence, signal: job.controller.signal });
    const validated = this._revalidate(result.decision, evidence, this.getVisionSnapshot());
    if (this.jobs.get(operator) !== job) return;
    const terminal = this._auditThenPublic(job, query, evidence, result, validated);
    send(terminal);
  } catch (error) {
    if (this.jobs.get(operator) === job) send(this._auditFailure(job, query, error));
  } finally {
    if (this.jobs.get(operator) === job) this.jobs.delete(operator);
  }
}
```

- [ ] **Step 6: Run tests and commit**

```bash
node web-control/server/test/vla-audit-log-smoke.js
node web-control/server/test/vla-grounding-smoke.js
git add web-control/server/vla/audit-log.js web-control/server/vla/grounding.js web-control/server/test/vla-audit-log-smoke.js web-control/server/test/vla-grounding-smoke.js
git commit -m "feat(vla): orchestrate audited preview selections"
```

### Task 8: Wire Preview-Only Grounding into the WebSocket Server

**Files:**
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/proxy.js`
- Create: `web-control/server/vla/browser-handler.js`
- Create: `web-control/server/test/vla-proxy-wiring-smoke.js`

**Interfaces:**
- Consumes: `GroundingService`, providers, audit log, `CameraBridge.getLatestVisionSnapshot()`, `VisionStatusStore.groundingSnapshot()`.
- Produces: accepted command `{cmd:"ground_language_target",query}` and requester-only `grounding_state` events; config `vla.{provider,model,timeoutMs,auditLog}`.

- [ ] **Step 1: Write a static and injected-boundary test**

The test loads `createGroundingBrowserHandler()` with a fake service, submits a grounding command, and asserts one `GroundingService.submit()` call. It rejects extra keys and verifies the handler has no robot, camera, gripper, grasp, active-view, or broadcast dependency. It also checks disconnect/software-stop cancel the operator job.

```javascript
assert.deepEqual(config.vla, {
  provider: 'disabled', model: 'gpt-5.6-terra', timeoutMs: 8000,
  auditLog: path.resolve(__dirname, '../../artifacts/vision/vla-grounding/events.jsonl'),
});
await handler({ cmd: 'ground_language_target', query: '夹取可乐' }, ws);
assert.deepEqual(calls.submit, [{ operator: ws, query: '夹取可乐' }]);
assert.deepEqual(calls.robot, []);
assert.deepEqual(calls.gripper, []);
assert.deepEqual(calls.activeView, []);
```

- [ ] **Step 2: Run and verify no wiring exists**

```bash
node web-control/server/test/vla-proxy-wiring-smoke.js
```

Expected: FAIL because `config.vla` and `browser-handler.js` are absent.

- [ ] **Step 3: Add server-owned configuration and fail-closed provider factory**

```javascript
vla: {
  provider: process.env.VLA_PROVIDER || 'disabled',
  model: process.env.VLA_MODEL || 'gpt-5.6-terra',
  timeoutMs: Math.max(1000, Math.min(30000, Number(process.env.VLA_TIMEOUT_MS || 8000))),
  auditLog: process.env.VLA_AUDIT_LOG ||
    path.resolve(__dirname, '../../artifacts/vision/vla-grounding/events.jsonl'),
},
```

`createGroundingProvider()` accepts only `disabled`, `mock`, or `openai`. `disabled` returns a stable `provider_unavailable`; `mock` is selected only explicitly; `openai` receives `process.env.OPENAI_API_KEY` but never logs or exposes it.

- [ ] **Step 4: Implement the pure preview handler and wire request-local submission**

```javascript
function createGroundingBrowserHandler({ grounding, send }) {
  return async function handleGroundingBrowserCommand(message, operator) {
    const parsed = parseGroundingCommand(message);
    if (!parsed.accepted) {
      send(operator, rejectedPublicState(parsed.reason));
      return { handled: true, accepted: false };
    }
    void grounding.submit({
      operator,
      query: parsed.query,
      send: event => send(operator, event),
    });
    return { handled: true, accepted: true };
  };
}
```

The factory signature intentionally has no actuator, camera-command, grasp, active-view, or broadcast argument. In `proxy.js`, call this handler only from the language-grounding case:

```javascript
case 'ground_language_target': {
  void handleGroundingBrowserCommand(message, ws);
  return;
}
```

Call `grounding.cancel(ws, 'browser_disconnected')` on `close`; call cancellation for all clients before software stop, camera stop, and vision-fatal paths. Do not alter the existing `grasp_object` or active-view cases.

- [ ] **Step 5: Run server protocol tests and commit**

```bash
node web-control/server/test/vla-proxy-wiring-smoke.js
node web-control/server/test/vla-contracts-smoke.js
node web-control/server/test/vla-grounding-smoke.js
git add web-control/server/config.js web-control/server/proxy.js web-control/server/vla/browser-handler.js web-control/server/test/vla-proxy-wiring-smoke.js
git commit -m "feat(web): expose preview-only language grounding"
```

### Task 9: Add the Browser Grounding Preview and Identity Highlight

**Files:**
- Create: `web-control/web/js/grounding-ui.js`
- Create: `web-control/server/test/vla-browser-ui-smoke.js`
- Modify: `web-control/web/index.html`
- Modify: `web-control/web/css/style.css`
- Modify: `web-control/web/js/main.js`

**Interfaces:**
- Consumes: `WSClient.send()` and requester-only `grounding_state` events.
- Produces: `createGroundingUI({root,send})` with `handleState(event)`, `handleDetections(targets)`, `invalidate(reason)`, and `destroy()`.

- [ ] **Step 1: Write a no-browser fake-DOM interaction test**

Assert submit sends only `{cmd:'ground_language_target',query}`, button/input are disabled while analyzing, selected ID receives class `grounding-selected`, clarify/none/rejected/error render bounded safe text, and new detections without the ID clear the highlight. Verify all text uses `textContent`, not `innerHTML`.

```javascript
const sent = [];
const ui = createGroundingUI({ root: fixtureDocument(), send: value => sent.push(value) });
ui.elements.input.value = '夹取可乐';
ui.elements.form.dispatchEvent(new Event('submit'));
assert.deepEqual(sent, [{ cmd: 'ground_language_target', query: '夹取可乐' }]);
ui.handleState({ type: 'grounding_state', status: 'selected', requestId: REQUEST_ID,
  identityId: 12, explanation: 'ID 12 是可乐瓶。', reason: null,
  provider: 'mock', modelId: 'mock-v1', latencyMs: 3 });
ui.handleDetections([{ identity_id: 12 }, { identity_id: 15 }]);
assert.equal(ui.targetElement(12).classList.contains('grounding-selected'), true);
assert.match(ui.elements.safety.textContent, /预览，不会执行抓取/);
```

- [ ] **Step 2: Run and verify missing UI module**

```bash
node web-control/server/test/vla-browser-ui-smoke.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement the isolated UMD DOM controller**

Keep the module importable by Node tests and expose `window.ThirdHandGroundingUI`. It owns only its panel and selected CSS class. It never constructs grasp, gripper, servo, preset, active-view, model, URL, key, identity, or coordinate commands.

```javascript
function submit(event) {
  event.preventDefault();
  const query = elements.input.value.trim();
  if (Array.from(query).length < 1 || Array.from(query).length > 256) {
    renderLocalError('请输入 1–256 个字符的目标描述');
    return;
  }
  send({ cmd: 'ground_language_target', query });
}
```

- [ ] **Step 4: Add the visible preview panel and integrate it**

Add an accessible form near the camera/detection list with IDs `grounding-form`, `grounding-query`, `grounding-submit`, `grounding-status`, `grounding-result`, and `grounding-safety`. The persistent safety line is `GPT 仅选择已有视觉 ID：预览，不会执行抓取。` Import `grounding-ui.js` before `main.js`; instantiate it in `UIControls`; pass each `detection_result.targets` to `handleDetections()`; subscribe to `grounding_state`; invalidate on WebSocket disconnect, software stop, camera/vision error, and page unload.

```javascript
this.grounding = window.ThirdHandGroundingUI.createGroundingUI({
  root: document,
  send: command => this.ws.send(command),
});
this.ws.on('grounding_state', event => this.grounding.handleState(event));
```

- [ ] **Step 5: Run UI and existing web smoke tests**

```bash
node web-control/server/test/vla-browser-ui-smoke.js
node web-control/server/test/vla-proxy-wiring-smoke.js
node web-control/server/test/active-view-demo-smoke.js
```

Expected: PASS; the current active-view preview UI is unchanged; no execution button is added.

- [ ] **Step 6: Commit**

```bash
git add web-control/web/js/grounding-ui.js web-control/web/index.html web-control/web/css/style.css web-control/web/js/main.js web-control/server/test/vla-browser-ui-smoke.js
git commit -m "feat(web): preview GPT-selected vision identities"
```

### Task 10: Prove Zero Motion End to End, Document Operation, and Complete CI

**Files:**
- Create: `web-control/server/test/vla-preview-e2e-smoke.js`
- Create: `tests/fixtures/vla/coke-selection.json`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `packages/thirdhand-vision-sdk/README.md`

**Interfaces:**
- Consumes: all preceding package, provider, service, proxy, and UI interfaces.
- Produces: deterministic “夹取可乐” preview evidence for IDs 12/15, CI job `vla-preview`, and operator/research documentation.

- [ ] **Step 1: Create the deterministic fixture and failing zero-motion E2E test**

The fixture contains a tiny valid JPEG, matching frame ID 1842/monotonic timestamp, confirmed candidates 12 and 15, and mock decision 12. The test drives browser command parsing, service submission, server send, and UI state handling. Instrument fake robot, gripper, active-view, camera-command, and grasp-start transports and assert every count is zero for select, clarify, malformed, stale, cancelled, and provider-error cases.

```javascript
assert.deepEqual(outcome.terminal, {
  status: 'selected', identityId: 12, explanation: 'ID 12 是可乐瓶。',
});
assert.equal(outcome.ui.highlightedIdentityId, 12);
assert.deepEqual(outcome.motionCounts, {
  robot: 0, gripper: 0, activeView: 0, cameraCommand: 0, graspStart: 0,
});
assert.equal(outcome.audit.imageSha256, fixture.imageSha256);
assert.deepEqual(outcome.audit.allowedIdentityIds, [12, 15]);
```

- [ ] **Step 2: Run and verify the E2E harness is absent**

```bash
node web-control/server/test/vla-preview-e2e-smoke.js
```

Expected: FAIL because the fixture/harness is not yet complete.

- [ ] **Step 3: Complete the harness and add a dedicated no-network CI job**

```yaml
  vla-preview:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: |
          node web-control/server/test/camera-overlay-snapshot-smoke.js
          node web-control/server/test/vla-contracts-smoke.js
          node web-control/server/test/vla-prompt-smoke.js
          node web-control/server/test/vla-openai-provider-smoke.js
          node web-control/server/test/vla-mock-provider-smoke.js
          node web-control/server/test/vla-audit-log-smoke.js
          node web-control/server/test/vla-grounding-smoke.js
          node web-control/server/test/vla-proxy-wiring-smoke.js
          node web-control/server/test/vla-browser-ui-smoke.js
          node web-control/server/test/vla-preview-e2e-smoke.js
```

The fake OpenAI transport must assert request shape but never open a socket. Run CI with no `OPENAI_API_KEY` secret.

- [ ] **Step 4: Document install, safe configuration, and research outputs**

Add exact commands for editable SDK install in the pinned vision environment, package-only tests/build, offline parity, disabled/mock/OpenAI provider modes, and server-side key placement. Document that a ChatGPT subscription is separate from API billing, keys must never be pasted into chat/browser/Git, and live API availability depends on supported-region access. Include the expected browser preview and JSONL research fields; state that semantic score is analysis data, not safety confidence.

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pip install --no-deps -e packages/thirdhand-vision-sdk
VLA_PROVIDER=mock node web-control/server/proxy.js
VLA_PROVIDER=openai node web-control/server/proxy.js
```

The OpenAI command requires `OPENAI_API_KEY` to have already been injected into the server process environment by a secret manager; no real key is stored in a shell history, file, screenshot, log, or test fixture.

- [ ] **Step 5: Run the complete verification matrix**

```bash
python -m pytest tests/ -q --ignore=tests/e2e/
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest packages/thirdhand-vision-sdk/tests -q
PYTHONPATH=packages/thirdhand-vision-sdk/src:web-control/server pytest tests/vision_deployment/test_vision_sdk_adapter.py tests/vision_deployment/test_online_camera_bridge_contract.py -q
for test_file in \
  web-control/server/test/camera-overlay-snapshot-smoke.js \
  web-control/server/test/vision-status-smoke.js \
  web-control/server/test/vla-contracts-smoke.js \
  web-control/server/test/vla-prompt-smoke.js \
  web-control/server/test/vla-openai-provider-smoke.js \
  web-control/server/test/vla-mock-provider-smoke.js \
  web-control/server/test/vla-audit-log-smoke.js \
  web-control/server/test/vla-grounding-smoke.js \
  web-control/server/test/vla-proxy-wiring-smoke.js \
  web-control/server/test/vla-browser-ui-smoke.js \
  web-control/server/test/vla-preview-e2e-smoke.js; do node "$test_file"; done
python -m build packages/thirdhand-vision-sdk
```

Expected: all commands pass; no live API, camera, GPU, CAN, Startouch, gripper, or robot is required.

- [ ] **Step 6: Scan for secrets, forbidden actuator paths, and accidental placeholders**

```bash
rg -n "ghp_[A-Za-z0-9]+|sk-[A-Za-z0-9_-]+|Authorization: Bearer [A-Za-z0-9]" packages/thirdhand-vision-sdk web-control/server/vla web-control/web README.md
rg -n "authorizeGrasp|startGrasp|sendActiveViewRobotCommand|cmd: 'gripper'|cmd: 'servo'" web-control/server/vla web-control/web/js/grounding-ui.js
forbidden_pattern='TB''D|TO''DO|FIX''ME|implement ''later|fill ''in'
rg -n "$forbidden_pattern" packages/thirdhand-vision-sdk web-control/server/vla web-control/web/js/grounding-ui.js README.md
```

Expected: all three searches return no matches and exit `1` because no matching lines exist.

- [ ] **Step 7: Inspect the final diff and commit documentation/E2E/CI**

```bash
git diff --check
git status --short
git diff --stat HEAD
git add web-control/server/test/vla-preview-e2e-smoke.js tests/fixtures/vla/coke-selection.json .github/workflows/ci.yml README.md packages/thirdhand-vision-sdk/README.md
git commit -m "test(vla): prove preview grounding cannot move robot"
```

- [ ] **Step 8: Final verification before reporting completion**

Re-run Step 5 from the committed tree, then run:

```bash
git status --short --branch
git log --oneline --decorate -12
```

Expected: only the three pre-existing unrelated untracked research artifacts remain; all implementation commits are present locally; no push or package publication has occurred.

## Deferred Acceptance Gates

The following work starts only after this plan's replay report and preview evidence are reviewed: real-camera online shadow, SDK-primary startup selection, duplicate algorithm removal, dataset capture with consent/manifest controls, and any physical execution design. Each requires its own approved plan; none is implicitly authorized by completing this implementation.
