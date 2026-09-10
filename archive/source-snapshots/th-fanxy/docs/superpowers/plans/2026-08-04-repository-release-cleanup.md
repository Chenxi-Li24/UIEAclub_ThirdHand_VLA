# Repository Release Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the current reviewed robotic-arm worktree into a clean, reproducible commit series and fast-forward it to `origin/main`.

**Architecture:** Preserve the existing split between the packaged Python application in `src/uiea_thirdhand_vla/` and the standalone Startouch stack in `web-control/`. Review and commit the current implementation by subsystem, then add repository hygiene and portable documentation without moving production modules during release preparation.

**Tech Stack:** Python 3.10+, pytest, Ruff, MyPy, FastAPI, Node.js/WebSocket, browser JavaScript, Bash, Git, GitHub HTTPS remote.

## Global Constraints

- Write only to `origin`; never push to or modify `upstream`.
- Preserve all existing commits after `origin/main`; do not rebase, squash, force push, or replace history.
- Do not delete local model weights, logs, PID files, captured data, or fixed-point backups.
- Do not stage `*.pt`, `*.onnx`, runtime logs, generated status files, timestamped fixed-point backups, secrets, or machine credentials.
- Verification must not command robot motion.
- Update `origin/main` only when the reviewed `HEAD` is a descendant of the freshly fetched `origin/main`.

---

### Task 1: Audit and protect machine-local artifacts

**Files:**
- Modify: `.gitignore`
- Inspect: all modified and untracked files reported by `git status`

**Interfaces:**
- Consumes: artifact policy from `docs/superpowers/specs/2026-08-04-repository-release-cleanup-design.md`
- Produces: ignore rules that keep downloaded weights and runtime artifacts outside Git without deleting local files

- [ ] **Step 1: Record the initial state and test current ignore behavior**

Run:

```bash
git status --short --branch
git check-ignore -v yolov8n.pt yolov8n.onnx web-control/server/yolov8n.pt \
  logs/fixed_pick_place/demo-ui.log \
  configs/tasks/.fixed_pick_place_backups/fixed_pick_place-20260729-184024-971179.yaml
```

Expected: the status lists the current source changes; at least the three model
weights and fixed-point backup are not yet covered by an explicit matching rule.

- [ ] **Step 2: Add exact artifact classes to `.gitignore`**

Add these repository-scoped rules:

```gitignore
# Downloaded ML model weights
*.pt
*.onnx

# Robot runtime state and operator backups
logs/**
!logs/.gitkeep
*.pid
configs/tasks/.fixed_pick_place_backups/
```

- [ ] **Step 3: Verify ignored files remain on disk and disappear from status**

Run:

```bash
test -f yolov8n.pt
test -f yolov8n.onnx
test -f web-control/server/yolov8n.pt
git check-ignore -v yolov8n.pt yolov8n.onnx web-control/server/yolov8n.pt \
  logs/fixed_pick_place/demo-ui.log \
  configs/tasks/.fixed_pick_place_backups/fixed_pick_place-20260729-184024-971179.yaml
git status --short
```

Expected: each artifact is ignored, the three weights still exist, and source
files remain visible for review.

- [ ] **Step 4: Scan candidate content for credentials and machine paths**

Run:

```bash
git diff -- . ':!docs/superpowers/plans/2026-08-04-repository-release-cleanup.md'
git ls-files -co --exclude-standard -z | xargs -0 rg -n \
  '/home/|/Users/|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|api[_-]?key\s*[:=]|token\s*[:=]' || true
```

Expected: no private key or credential value is present. Every absolute path is
either removed, converted to a portable example, or explicitly justified as a
test fixture before it can be staged.

### Task 2: Review and commit the packaged VLA core

**Files:**
- Modify: `src/uiea_thirdhand_vla/__main__.py`
- Modify: `src/uiea_thirdhand_vla/config/loader.py`
- Modify: `src/uiea_thirdhand_vla/control/gripper.py`
- Modify: `src/uiea_thirdhand_vla/control/robot.py`
- Modify: `src/uiea_thirdhand_vla/control/safety.py`
- Modify: `src/uiea_thirdhand_vla/logging/run_logger.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/central_control.py`
- Modify: `src/uiea_thirdhand_vla/orchestration/state_machine.py`
- Modify: `src/uiea_thirdhand_vla/perception/calibration.py`
- Modify: `src/uiea_thirdhand_vla/perception/camera.py`
- Modify: `src/uiea_thirdhand_vla/perception/detectors/aruco_detector.py`
- Modify: `src/uiea_thirdhand_vla/perception/detectors/base.py`
- Modify: `src/uiea_thirdhand_vla/perception/detectors/yolo_detector.py`
- Modify: `src/uiea_thirdhand_vla/perception/transforms.py`
- Modify: `src/uiea_thirdhand_vla/reasoning/vla_client.py`
- Modify: `src/uiea_thirdhand_vla/reasoning/vla_session.py`
- Test: existing `tests/` suite selected by `pyproject.toml`

**Interfaces:**
- Consumes: YAML configuration models and existing hardware SDK adapters
- Produces: packaged camera-to-reasoning-to-safety orchestration invoked through `python -m uiea_thirdhand_vla`

- [ ] **Step 1: Review the core diff for debug and hardware-motion entry points**

Run:

```bash
git diff -- src/uiea_thirdhand_vla
rg -n 'breakpoint\(|pdb\.|print\(|/home/|TEMPORARY_DEBUG|XXX' src/uiea_thirdhand_vla
```

Expected: no debugger remains, machine paths are absent, and every print is an
intentional CLI message rather than temporary tracing.

- [ ] **Step 2: Run focused static and offline tests before staging**

Run:

```bash
ruff check src/uiea_thirdhand_vla tests
mypy src/uiea_thirdhand_vla
pytest tests/ -q --ignore=tests/e2e
```

Expected: all commands exit zero; no command starts a robot-control process.

- [ ] **Step 3: Stage only the packaged core and inspect the index**

Run:

```bash
git add src/uiea_thirdhand_vla
git diff --cached --stat
git diff --cached --check
```

Expected: the staged list contains only `src/uiea_thirdhand_vla/**` files and
has no whitespace errors.

- [ ] **Step 4: Commit the packaged core**

Run:

```bash
git commit -m "feat(core): integrate vision-aware control pipeline"
```

Expected: one commit containing the reviewed packaged Python core changes.

### Task 3: Review and commit vision and Startouch service integration

**Files:**
- Modify: `configs/vision/remind3d.yaml`
- Modify: `scripts/vision/bootstrap_remind3d_env.sh`
- Modify: `scripts/vision/smoke_remind3d_models.py`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/startouch_bridge.py`
- Create: `web-control/server/camera-bridge.js`
- Create: `web-control/server/camera_bridge.py`
- Create: `web-control/server/lumos_http_server.py`
- Create: `web-control/server/lumos_stream.py`
- Modify/Create: `web-control/server/tests/**`
- Modify: `web-control/server/vision/**`
- Modify: `web-control/server/vision_models/**`
- Test: `tests/vision_deployment/test_bootstrap_contract.py`

**Interfaces:**
- Consumes: Lumos camera streams, Startouch SDK bridge, REMIND-3D model configuration, local model files ignored by Git
- Produces: ports `3000` (proxy/UI), `3001` (Lumos HTTP service), and vision safety observations for the Startouch service

- [ ] **Step 1: Review service and vision diffs**

Run:

```bash
git diff -- configs/vision scripts/vision web-control/server tests/vision_deployment
rg -n 'breakpoint\(|pdb\.|/home/|TEMPORARY_DEBUG|XXX|0\.0\.0\.0|127\.0\.0\.1|3000|3001|8766' \
  configs/vision scripts/vision web-control/server tests/vision_deployment
```

Expected: binding addresses and ports are intentional configuration or documented
defaults; local paths and debugger statements are absent.

- [ ] **Step 2: Run service syntax and vision tests**

Run:

```bash
node --check web-control/server/proxy.js
node --check web-control/server/config.js
node --check web-control/server/camera-bridge.js
python -m py_compile web-control/server/startouch_bridge.py \
  web-control/server/camera_bridge.py web-control/server/lumos_http_server.py \
  web-control/server/lumos_stream.py scripts/vision/smoke_remind3d_models.py
pytest -q tests/vision_deployment web-control/server/tests
```

Expected: syntax checks and offline tests exit zero without moving hardware.

- [ ] **Step 3: Stage only service implementation, configuration, and tests**

Run:

```bash
git add configs/vision scripts/vision tests/vision_deployment web-control/server
git diff --cached --stat
git diff --cached --check
git diff --cached --name-only | rg '\.(pt|onnx|log)$' && exit 1 || true
```

Expected: source, configuration, and tests are staged; downloaded weights and
logs are absent.

- [ ] **Step 4: Commit service integration**

Run:

```bash
git commit -m "feat(vision): integrate Lumos camera services"
```

Expected: one commit containing the reviewed server and vision integration.

### Task 4: Review and commit the browser UI

**Files:**
- Modify: `web-control/web/css/style.css`
- Modify: `web-control/web/index.html`
- Modify: `web-control/web/js/main.js`
- Create: `web-control/web/camera-test.html`

**Interfaces:**
- Consumes: proxy and Lumos HTTP endpoints from Task 3
- Produces: operator UI for camera state and robot-control status

- [ ] **Step 1: Review browser changes and endpoint references**

Run:

```bash
git diff -- web-control/web
rg -n '/home/|TEMPORARY_DEBUG|XXX|localhost|127\.0\.0\.1|3000|3001|8766' web-control/web
```

Expected: browser URLs are portable relative endpoints or documented diagnostic
defaults, with no developer-machine path.

- [ ] **Step 2: Run available JavaScript syntax checks**

Run:

```bash
node --check web-control/web/js/main.js
```

Expected: command exits zero.

- [ ] **Step 3: Stage and commit browser changes**

Run:

```bash
git add web-control/web/css/style.css web-control/web/index.html \
  web-control/web/js/main.js web-control/web/camera-test.html
git diff --cached --check
git commit -m "feat(web): expose Lumos camera controls"
```

Expected: one commit containing only the reviewed browser UI changes.

### Task 5: Document architecture and repository hygiene

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/architecture.md`
- Create: `docs/model_assets.md`
- Modify if needed: `.env.example`

**Interfaces:**
- Consumes: final service boundaries and ports validated in Tasks 2–4
- Produces: portable onboarding, architecture, model acquisition, and artifact policy documentation

- [ ] **Step 1: Update documentation with exact supported entry points**

Document all of the following:

```text
Packaged VLA console: python -m uiea_thirdhand_vla, default port 8000
Startouch proxy and browser UI: web-control/server/proxy.js, default port 3000
Lumos HTTP service: web-control/server/lumos_http_server.py, default port 3001
Fixed-point demo UI: web-control/demo/demo_server.py, loopback port 8766
Downloaded model files are local artifacts and are not committed
```

Remove workstation-specific clone and worktree paths from user-facing examples.

- [ ] **Step 2: Add reproducible model asset instructions**

Create `docs/model_assets.md` with exact commands already supported by the
repository or upstream package tooling to obtain each required model. State the
expected local destination, configuration key, and that `*.pt` and `*.onnx` are
ignored. Do not publish a checksum unless it is computed from an authoritative
artifact used by the repository.

- [ ] **Step 3: Validate links, paths, and whitespace**

Run:

```bash
rg -n '/home/nieqingcao|UIEAclub_ThirdHand_VLA-fixed-pick-place' \
  README.md README_CN.md docs/architecture.md docs/model_assets.md
git diff --check -- .gitignore README.md README_CN.md docs/architecture.md docs/model_assets.md
```

Expected: no machine-specific path is found and no whitespace error is reported.

- [ ] **Step 4: Stage and commit repository hygiene**

Run:

```bash
git add .gitignore README.md README_CN.md docs/architecture.md docs/model_assets.md .env.example
git diff --cached --stat
git diff --cached --check
git commit -m "docs: prepare repository for reproducible release"
```

Expected: one commit containing ignore rules and portable release documentation.

### Task 6: Run final verification and publish `origin/main`

**Files:**
- Inspect: complete Git tree at `HEAD`
- Update: remote reference `origin/main`

**Interfaces:**
- Consumes: clean commits from Tasks 1–5
- Produces: verified fast-forward `origin/main` matching local `HEAD`

- [ ] **Step 1: Verify the complete local tree**

Run:

```bash
git status --short --branch
git diff --check origin/main...HEAD
ruff check src/ tests/
mypy src/
pytest tests/ -q --ignore=tests/e2e/
pytest -q web-control/server/tests
node --check web-control/server/proxy.js
node --check web-control/server/camera-bridge.js
node --check web-control/web/js/main.js
bash -n scripts/demo_fixed_pick_place.sh scripts/fixed_pick_place_resource_guard.sh \
  scripts/open_fixed_pick_place_control.sh scripts/vision/bootstrap_remind3d_env.sh
```

Expected: working tree is clean except ignored local artifacts and every command
exits zero.

- [ ] **Step 2: Prove forbidden artifacts and likely credentials are absent from `HEAD`**

Run:

```bash
git ls-tree -r --name-only HEAD | rg '\.(pt|onnx|log|pid)$|\.fixed_pick_place_backups/' && exit 1 || true
git grep -n -E 'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|api[_-]?key[[:space:]]*[:=][[:space:]]*[A-Za-z0-9_-]{16,}' HEAD -- ':!docs/**' ':!.env.example' && exit 1 || true
```

Expected: neither command reports a forbidden tracked file or credential value.

- [ ] **Step 3: Fetch and verify fast-forward eligibility**

Run:

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git rev-list --left-right --count origin/main...HEAD
```

Expected: the ancestor check exits zero and the left count is `0`. If not, stop
without pushing and reconcile the newly fetched commits.

- [ ] **Step 4: Fast-forward the reviewed commit to `origin/main`**

Run:

```bash
git push origin HEAD:main
```

Expected: a normal fast-forward push succeeds; no `--force` option is used.

- [ ] **Step 5: Verify remote state and report the release**

Run:

```bash
local_head=$(git rev-parse HEAD)
remote_head=$(git ls-remote origin refs/heads/main | cut -f1)
test "$local_head" = "$remote_head"
git ls-remote --heads --tags origin
git status --short --branch
```

Expected: local and remote object IDs match; `origin` still exposes only the
intended `main` branch and no temporary release branch.
