# bottlegrasp Functional Module Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Reorganize the existing repository into `common`, `vision`, and `action` modules with thin application/debug entry points while preserving current offline behavior and fail-closed execution semantics.

**Architecture:** Keep one installable `thirdhand_va` package. Move reusable implementation under `src/thirdhand_va/common`, `vision`, and `action`; keep only orchestration under `apps/` and argument parsing under `scripts/`. Preserve old Python and Node paths as thin forwarding modules during migration so external consumers are not broken abruptly.

**Tech Stack:** Python 3.10+, NumPy, PyYAML, OpenCV, pytest/unittest, Node.js CommonJS, C++14/CMake/XVisio SDK.

**Spec:** `docs/superpowers/specs/2026-08-21-functional-module-reorganization-design.md`

## Global Constraints

- `vision` must not depend on `action` or execute robot commands.
- `action` may consume only versioned public contracts, never V model/tracker internals.
- Importing a library module must not open hardware, load models, connect sockets, or start processes.
- Default execution must keep `robot_control_enabled=false` and physical execution fail-closed.
- Existing offline behavior and public decision/status semantics must remain unchanged.
- Real-camera and robot tests remain opt-in and are not run during this reorganization.
- No repository-external absolute path may remain as a library default.
- This directory is an untracked subtree inside the parent `$HOME/th0814/VA` Git repository on `main`; the user explicitly requested in-place organization of this folder. Use recorded test checkpoints and do not commit or modify files outside `bottlegrasp`.
- Baseline limitations are preserved as evidence: the active Python environment initially lacks pytest, and stale duplicate tests under `tests/js/` fail while their current counterparts under `tests/node/` pass.

---

### Task 1: Add module-boundary tests and package skeleton

**Files:**
- Create: `tests/common/test_module_boundaries.py`
- Create: `src/thirdhand_va/common/__init__.py`
- Create: `src/thirdhand_va/common/contracts/__init__.py`
- Create: `src/thirdhand_va/vision/__init__.py`
- Create: `src/thirdhand_va/action/__init__.py`

**Interfaces:**
- Consumes: Existing `thirdhand_va` package.
- Produces: Importable `thirdhand_va.common`, `thirdhand_va.vision`, and `thirdhand_va.action` namespaces and a test that rejects cross-domain Python imports.

- [x] **Step 1: Write the failing boundary test**

```python
import ast
from pathlib import Path
import unittest


class ModuleBoundaryTests(unittest.TestCase):
    def test_public_domains_are_importable(self):
        import thirdhand_va.common
        import thirdhand_va.vision
        import thirdhand_va.action

    def test_vision_does_not_import_action(self):
        root = Path("src/thirdhand_va/vision")
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            self.assertFalse(
                any(name.startswith("thirdhand_va.action") for name in imported),
                path,
            )
```

- [x] **Step 2: Run the boundary test and verify it fails before skeleton creation**

Run: `PYTHONPATH=src python -m unittest tests.common.test_module_boundaries -v`

Expected: FAIL because the new domain packages do not exist.

- [x] **Step 3: Create only the namespace initializers**

Each initializer contains a one-line domain docstring and no imports with side effects.

- [x] **Step 4: Run the boundary test**

Run: `PYTHONPATH=src python -m unittest tests.common.test_module_boundaries -v`

Expected: PASS.

- [x] **Step 5: Record checkpoint**

Run: `find src/thirdhand_va/{common,vision,action} -maxdepth 2 -type f | sort`

Expected: Only the new namespace files exist; no existing implementation has moved yet.

### Task 2: Move configuration and immutable data contracts into common

**Files:**
- Create: `src/thirdhand_va/common/config.py`
- Create: `src/thirdhand_va/common/contracts/_validation.py`
- Create: `src/thirdhand_va/common/contracts/rgbd_frame.py`
- Create: `src/thirdhand_va/common/contracts/vision_result.py`
- Create: `src/thirdhand_va/common/contracts/vision-result.schema.json`
- Modify: `src/thirdhand_va/common/contracts/__init__.py`
- Modify: `src/thirdhand_va/config.py`
- Modify: `src/thirdhand_va/contracts.py`
- Create: `tests/common/test_public_contracts.py`
- Move: `tests/test_config.py` -> `tests/common/test_config.py`
- Move: `tests/test_contracts.py` -> `tests/common/test_contracts.py`

**Interfaces:**
- Consumes: Existing `VisionConfig`, `RgbdFrame`, `MaskCandidate`, `GraspPoseCamera`, `SpatialRank`, and `VisionDecision` behavior.
- Produces: `thirdhand_va.common.VisionConfig`; `thirdhand_va.common.contracts.{RgbdFrame, MaskCandidate, GraspPoseCamera, SpatialRank, VisionDecision}`; old modules re-export the same class objects.

- [x] **Step 1: Write identity-preserving compatibility tests**

```python
import unittest

from thirdhand_va.common.config import VisionConfig as NewVisionConfig
from thirdhand_va.common.contracts import RgbdFrame as NewRgbdFrame
from thirdhand_va.config import VisionConfig as OldVisionConfig
from thirdhand_va.contracts import RgbdFrame as OldRgbdFrame


class PublicContractTests(unittest.TestCase):
    def test_old_config_path_is_a_reexport(self):
        self.assertIs(OldVisionConfig, NewVisionConfig)

    def test_old_frame_path_is_a_reexport(self):
        self.assertIs(OldRgbdFrame, NewRgbdFrame)
```

- [x] **Step 2: Run the new test and verify it fails**

Run: `PYTHONPATH=src python -m unittest tests.common.test_public_contracts -v`

Expected: FAIL because the common implementations are absent.

- [x] **Step 3: Move implementations and replace old files with re-exports**

`src/thirdhand_va/config.py` must contain only:

```python
"""Compatibility imports for the pre-module-layout config path."""
from thirdhand_va.common.config import VisionConfig

__all__ = ["VisionConfig"]
```

`src/thirdhand_va/contracts.py` must import and export the five existing public contract classes plus `DecisionStatus` from `thirdhand_va.common.contracts`. The dataclass implementations must exist only in common contracts.

- [x] **Step 4: Add a cross-language VisionResult schema**

The schema must require `schema`, `robot_control_enabled`, `status`, `frame_id`, `reasons`, `stable_hits`, and `window_size`; `robot_control_enabled` must be constrained to `false`, and `status` must allow only `searching`, `rejected`, `uncertain`, `unstable`, and `ready`.

- [x] **Step 5: Run common tests**

Run: `PYTHONPATH=src python -m unittest tests.common.test_module_boundaries tests.common.test_public_contracts -v`

Expected: PASS.

- [x] **Step 6: Record checkpoint**

Run: `PYTHONPATH=src python -c "from thirdhand_va.config import VisionConfig as A; from thirdhand_va.common.config import VisionConfig as B; assert A is B"`

Expected: exit 0.

### Task 3: Move reusable Vision leaf modules

**Files:**
- Move: `src/thirdhand_va/camera/*` -> `src/thirdhand_va/vision/camera/*`
- Move: `src/thirdhand_va/geometry/*` -> `src/thirdhand_va/vision/geometry/*`
- Move: `src/thirdhand_va/perception/*` -> `src/thirdhand_va/vision/perception/*`
- Move: `src/thirdhand_va/tracking/*` -> `src/thirdhand_va/vision/tracking/*`
- Create compatibility packages at the four old paths.
- Move tests into `tests/vision/camera`, `tests/vision/geometry`, `tests/vision/perception`, and `tests/vision/tracking`.
- Create: `tests/vision/test_vision_public_imports.py`

**Interfaces:**
- Consumes: Common configuration and contracts from Task 2.
- Produces: Public leaf APIs under `thirdhand_va.vision.camera`, `.geometry`, `.perception`, and `.tracking`; old leaf paths forward to identical objects.

- [x] **Step 1: Write public import identity tests**

```python
import unittest

from thirdhand_va.camera.recording import read_frame_bundle as old_read
from thirdhand_va.geometry.grasp_pose import estimate_grasp_pose as old_estimate
from thirdhand_va.vision.camera.recording import read_frame_bundle as new_read
from thirdhand_va.vision.geometry.grasp_pose import estimate_grasp_pose as new_estimate


class VisionPublicImportTests(unittest.TestCase):
    def test_camera_compatibility_import(self):
        self.assertIs(old_read, new_read)

    def test_geometry_compatibility_import(self):
        self.assertIs(old_estimate, new_estimate)
```

- [x] **Step 2: Run and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.vision.test_vision_public_imports -v`

Expected: FAIL because new paths are absent.

- [x] **Step 3: Move leaf implementations and update internal imports**

All moved Python modules import `VisionConfig` from `thirdhand_va.common.config`, contracts from `thirdhand_va.common.contracts`, and neighboring V modules from `thirdhand_va.vision.*`.

- [x] **Step 4: Add old-path forwarding modules**

Each old file contains only a compatibility docstring, explicit imports from the new module, and `__all__`. No implementation is copied.

- [x] **Step 5: Move tests without changing assertions**

Update test imports to canonical `thirdhand_va.vision.*` paths. Keep a small compatibility test for each old package.

- [x] **Step 6: Run leaf-module tests**

Run: `PYTHONPATH=src python -m pytest tests/common tests/vision/camera tests/vision/geometry tests/vision/perception tests/vision/tracking -q`

Expected: PASS once pytest is available; if not, record the environment failure and run `python -m compileall -q src/thirdhand_va` plus the unittest compatibility suite.

### Task 4: Split selection and visualization, then move the Vision pipeline

**Files:**
- Create: `src/thirdhand_va/vision/selection/ordinal_selector.py`
- Create: `src/thirdhand_va/vision/selection/target_lock.py`
- Create: `src/thirdhand_va/vision/selection/__init__.py`
- Create: `src/thirdhand_va/vision/visualization/overlay.py`
- Create: `src/thirdhand_va/vision/visualization/depth_heatmap.py`
- Create: `src/thirdhand_va/vision/visualization/__init__.py`
- Move: `src/thirdhand_va/pipeline.py` -> `src/thirdhand_va/vision/pipeline.py`
- Move: `src/thirdhand_va/evaluation.py` -> `src/thirdhand_va/vision/evaluation.py`
- Replace old modules with compatibility re-exports.
- Move: `tests/test_selection.py` -> `tests/vision/selection/test_selection.py`
- Move: `tests/test_visualization.py` -> `tests/vision/visualization/test_visualization.py`
- Move: `tests/test_pipeline.py` -> `tests/vision/test_pipeline.py`
- Move: `tests/test_evaluation.py` -> `tests/vision/test_evaluation.py`

**Interfaces:**
- Consumes: `MaskCandidate`, `GraspPoseCamera`, common configuration, and V leaf APIs.
- Produces: `SelectionRequest`, `SpatialBottleSelector`, `TargetLock`, `RenderMetrics`, `render_overlay`, `render_depth_heatmap`, `VisionPipeline`, and `aggregate_metrics` at canonical V paths.

- [x] **Step 1: Add compatibility identity assertions to Vision public tests**

```python
from thirdhand_va.pipeline import VisionPipeline as OldPipeline
from thirdhand_va.selection import SpatialBottleSelector as OldSelector
from thirdhand_va.vision.pipeline import VisionPipeline as NewPipeline
from thirdhand_va.vision.selection import SpatialBottleSelector as NewSelector

self.assertIs(OldPipeline, NewPipeline)
self.assertIs(OldSelector, NewSelector)
```

- [x] **Step 2: Run and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.vision.test_vision_public_imports -v`

Expected: FAIL because canonical paths are absent.

- [x] **Step 3: Split selection without behavior changes**

Move `SelectionRequest`, `SelectionResult`, `mask_centroid`, and `SpatialBottleSelector` to `ordinal_selector.py`; move `TargetLock` and mask-IoU matching to `target_lock.py`. Export both groups from `vision.selection`.

- [x] **Step 4: Split visualization without behavior changes**

Move `blend_registered_depth` and `render_depth_heatmap` to `depth_heatmap.py`; keep `RenderMetrics`, `OverlayResult`, `render_overlay`, and `encode_jpeg` in `overlay.py`. `overlay.py` imports depth helpers from its sibling module.

- [x] **Step 5: Move pipeline and evaluation and update imports**

`vision.pipeline` imports only common and V modules. Old `selection.py`, `visualization.py`, `pipeline.py`, and `evaluation.py` become re-export shims.

- [x] **Step 6: Move tests and run the Vision suite**

Run: `PYTHONPATH=src python -m pytest tests/vision -q`

Expected: All offline Vision tests pass; hardware test remains outside this directory.

### Task 5: Move Action calibration and Node controllers with old-path wrappers

**Files:**
- Move: `src/thirdhand_va/handeye.py` -> `src/thirdhand_va/action/calibration/handeye.py`
- Create: `src/thirdhand_va/action/calibration/__init__.py`
- Replace: `src/thirdhand_va/handeye.py` with a re-export shim.
- Move available Node modules from `integration/web-control/` into `src/thirdhand_va/action/observation`, `alignment`, and `adapters`.
- Move reusable operator modules into `src/thirdhand_va/action/grasp`, `safety`, and `operator`.
- Leave thin CommonJS wrappers at all old paths.
- Move current Node smoke tests to `tests/action/` and remove stale duplicate smoke tests only after comparison.
- Move: `tests/test_handeye.py` -> `tests/action/calibration/test_handeye.py`

**Interfaces:**
- Consumes: Common VisionDecision/VisionResult contracts and existing Node controller APIs.
- Produces: Canonical Action modules while preserving `require()` and Python import compatibility at old paths.

- [x] **Step 1: Write Python and Node compatibility tests**

```python
from thirdhand_va.action.calibration.handeye import HandEyeCalibration as NewCalibration
from thirdhand_va.handeye import HandEyeCalibration as OldCalibration
assert NewCalibration is OldCalibration
```

```javascript
const assert = require('assert/strict');
const oldModule = require('../../integration/web-control/base-target-lock');
const newModule = require('../../src/thirdhand_va/action/observation/base-target-lock');
assert.equal(oldModule.BaseFrameTargetLock, newModule.BaseFrameTargetLock);
```

- [x] **Step 2: Run and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.action.calibration.test_calibration_public_imports -v`

Run: `node tests/action/module-compatibility-smoke.js`

Expected: FAIL because canonical Action paths are absent.

- [x] **Step 3: Move hand-eye implementation and add shim**

Update its contract import to `thirdhand_va.common.contracts`. Do not change calibration validation, transform math, evidence IDs, blocker names, or `robot_control_enabled` behavior.

- [x] **Step 4: Move Node observation and alignment modules**

Place `visual-target-lock.js`, `depth-observation-filter.js`, `locked-target-memory.js`, and `base-target-lock.js` under `action/observation`; place `visual-align-controller.js` under `action/alignment` and change only its relative import path to `../observation/base-target-lock`.

- [x] **Step 5: Move operator modules**

Place `workflow-client.js` under `action/grasp`, `status-store.js` under `action/operator`, and `stop.js` logic under `action/safety/software-stop.js`. Keep `operator/run.js` and `operator/operator-control.sh` as thin application wrappers.

- [x] **Step 6: Consolidate duplicate Node smoke tests**

Keep the passing `tests/node/` expectations as the current behavior baseline, move them to `tests/action/`, and delete stale `tests/js/base-target-lock-smoke.js` and `tests/js/visual-align-controller-smoke.js`. Preserve the unique depth-filter and visual-target-lock tests by moving them to `tests/action/`.

- [x] **Step 7: Run Action tests**

Run: `for f in tests/action/*.js; do node "$f"; done`

Expected: Every Action smoke test prints PASS and exits 0.

### Task 6: Separate reusable bridge adapters from application orchestration

**Files:**
- Create: `src/thirdhand_va/vision/adapters/__init__.py`
- Move/split: `src/thirdhand_va/bridge.py` -> `vision/adapters/mjpeg_publisher.py` and `event_publisher.py`
- Replace: `src/thirdhand_va/bridge.py` with a re-export shim.
- Move: `scripts/camera_bridge_va.py` -> `apps/bottle_pick/camera_bridge.py`
- Replace: `scripts/camera_bridge_va.py` with a thin wrapper importing `apps.bottle_pick.camera_bridge.main`.
- Move: `integration/web-control/camera-bridge.js` -> `src/thirdhand_va/action/adapters/camera-bridge.js`
- Move: `integration/web-control/vision-selection-api.js` -> `src/thirdhand_va/action/adapters/vision-selection-api.js`
- Move: `integration/web-control/proxy.js` -> `apps/bottle_pick/web-server.js`
- Create thin CommonJS wrappers at the three old integration paths.
- Move bridge tests to `tests/vision/adapters` and `tests/integration`.

**Interfaces:**
- Consumes: VisionDecision, frame provenance, rendered JPEG bytes, arm state, and calibration.
- Produces: Pure MJPEG/event encoding adapters and a composition-only camera bridge application.

- [x] **Step 1: Write adapter compatibility tests**

```python
from thirdhand_va.bridge import build_mjpeg_part as old_build
from thirdhand_va.vision.adapters import build_mjpeg_part as new_build
assert old_build is new_build
```

- [x] **Step 2: Run and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.vision.adapters.test_adapter_public_imports -v`

Expected: FAIL because canonical adapters are absent.

- [x] **Step 3: Split pure bridge functions**

Keep `FrameProvenance` and `build_mjpeg_part` in `mjpeg_publisher.py`. Keep `build_detection_event` and `LatestFramePublisher` in `event_publisher.py`, importing the MJPEG helper from its sibling.

- [x] **Step 4: Move camera bridge application**

The app may parse arguments, own file descriptors/threads, initialize models, and compose V/A modules. Reusable frame iteration, mailbox, and publisher code must be imported from domain modules when it has no application-specific fd contract.

- [x] **Step 5: Preserve old script execution**

The old script wrapper must add the repository `src` directory only when running from a source checkout, then call `apps.bottle_pick.camera_bridge.main()`. It must contain no perception, geometry, or action logic.

- [x] **Step 6: Move the Node bridge adapters and web application**

`action/adapters/camera-bridge.js` keeps process spawning, stream parsing, and validated message transport. `action/adapters/vision-selection-api.js` keeps only HTTP-body validation and forwarding. `apps/bottle_pick/web-server.js` remains the application composition root; change its three local imports to canonical Action paths:

```javascript
const { CameraBridge } = require('../../src/thirdhand_va/action/adapters/camera-bridge');
const { createVisionSelectionHandler } = require(
  '../../src/thirdhand_va/action/adapters/vision-selection-api'
);
const { VisualAlignController } = require(
  '../../src/thirdhand_va/action/alignment/visual-align-controller'
);
```

The old `integration/web-control/proxy.js` contains only `require('../../apps/bottle_pick/web-server')`. The old adapter files explicitly export the canonical module. Dependencies that were already absent from this repository remain documented external integration requirements; do not fabricate their implementations during this reorganization.

- [x] **Step 7: Run bridge and script tests**

Run: `PYTHONPATH=src python -m pytest tests/vision/adapters tests/integration/test_camera_bridge_script.py -q`

Run: `node tests/integration/vision-selection-api.test.js`

Expected: PASS without opening hardware.

### Task 7: Reorganize scripts, native source, tests, artifacts, and documentation

**Files:**
- Move Vision scripts into `scripts/vision/` and Action scripts into `scripts/action/`.
- Keep thin wrappers only for externally documented old paths.
- Move `native/xvisio_rgbd_stream` -> `native/vision/xvisio_rgbd_stream`.
- Update: `scripts/vision/build_native.sh`, default executable paths, docs, and config references.
- Move tests into final `common`, `vision`, `action`, `integration`, and `hardware` layout.
- Move artifacts into `artifacts/vision`, `artifacts/action`, and `artifacts/integration` without deleting evidence.
- Create: `README.md`
- Create: `docs/architecture.md`
- Remove confirmed obsolete `*.py..bak` files and the unused duplicate `src/thirdhand_va/grounded_sam.py`.

**Interfaces:**
- Consumes: Canonical module paths produced by Tasks 1-6.
- Produces: Discoverable debug commands, mirrored tests, preserved evidence, and no ambiguous duplicate sources.

- [x] **Step 1: Add a repository layout test**

```python
from pathlib import Path
import unittest


class RepositoryLayoutTests(unittest.TestCase):
    def test_no_backup_or_duplicate_python_sources_remain(self):
        root = Path('.')
        self.assertEqual([], list(root.rglob('*.py..bak')))
        self.assertFalse(Path('src/thirdhand_va/grounded_sam.py').exists())
```

- [x] **Step 2: Run and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.common.test_repository_layout -v`

Expected: FAIL while backup and duplicate files still exist.

- [x] **Step 3: Move scripts and native source and update paths**

Every moved script imports canonical modules. Old wrappers are retained only for `run_live.py`, `camera_bridge_va.py`, and other paths explicitly referenced by current docs or external bridge configuration.

- [x] **Step 4: Move artifacts without changing contents**

Reference manifests and camera/vision reports go to `artifacts/vision`; operator status/logs go to `artifacts/action`; combined server logs go to `artifacts/integration`. Existing evidence files keep their bytes and timestamps where the move mechanism permits.

- [x] **Step 5: Remove confirmed obsolete sources**

Before removal, run `diff` against the active files and verify the backup contributes no behavior absent from the active implementation. Remove only the two `..bak` files and the unused top-level Grounded SAM duplicate.

- [x] **Step 6: Write module documentation**

`README.md` must list V/A responsibilities, public imports, per-module debug commands, offline test commands, hardware-test opt-in rules, and the V-to-A contract. `docs/architecture.md` must document dependency direction and application/adapters boundaries.

- [x] **Step 7: Run layout and import verification**

Run: `PYTHONPATH=src python -m unittest tests.common.test_module_boundaries tests.common.test_repository_layout -v`

Run: `PYTHONPATH=src python -m compileall -q src apps scripts`

Expected: PASS and no compile errors.

### Task 8: Full offline verification and final inventory

**Files:**
- Modify only files required by verified migration regressions.
- Create: `artifacts/integration/reorganization-verification.json`

**Interfaces:**
- Consumes: Final reorganized repository.
- Produces: Machine-readable verification evidence and a human-readable final module inventory.

- [x] **Step 1: Install the project test extra if pytest remains unavailable**

Run: `python -m pip install -e '.[test]'`

Expected: Editable `thirdhand-va` installation and `python -m pytest --version` exit 0. This installation does not authorize model downloads or hardware access.

- [x] **Step 2: Run all Python offline tests**

Run: `python -m pytest tests/common tests/vision tests/action tests/integration -q`

Expected: PASS, with hardware tests excluded.

- [x] **Step 3: Run all Node Action tests**

Run: `for f in tests/action/*.js; do node "$f"; done`

Expected: Every file exits 0.

- [x] **Step 4: Run offline spatial validation**

Run: `python scripts/vision/validate_spatial_vision_offline.py --output artifacts/vision/validation/spatial`

Expected: Report has `passed=true`, `camera_opened=false`, and `robot_control_enabled=false`.

- [x] **Step 5: Verify no forbidden dependency or hard-coded path remains**

Run: `if rg -n 'thirdhand_va\.action' src/thirdhand_va/vision; then exit 1; fi`

Run: `rg -n '/home/[^/]+|TH-Fanxy' src scripts apps configs`

Expected: First command finds nothing; second finds no library/default dependency paths. Documentation may mention migration history separately.

- [x] **Step 6: Write verification evidence**

The JSON file records Python test totals, Node test files, offline validation status, hardware tests not run, `robot_control_enabled=false`, and any baseline limitations that remain external to this repository.

- [x] **Step 7: Print final inventory**

Run: `find src/thirdhand_va -maxdepth 4 -type f -not -path '*/__pycache__/*' | sort`

Expected: All reusable code is under common, vision, or action; old paths contain only documented compatibility wrappers.
