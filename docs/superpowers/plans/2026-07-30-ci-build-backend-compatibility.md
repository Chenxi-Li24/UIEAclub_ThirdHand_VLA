# CI Build Backend Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make editable installation and the Python 3.10/3.11 GitHub Actions matrix pass with current pip.

**Architecture:** Keep the existing setuptools-based package and change only the invalid PEP 517 backend entry. Verify the exact failing editable-install boundary before and after the change, then run the repository checks and GitHub Actions.

**Tech Stack:** Python 3.10/3.11, pip 26.2, setuptools, pytest, Ruff, Mypy, GitHub Actions

## Global Constraints

- Do not modify robot-control behavior, CAN access, ROS launch behavior, dependencies, or the CI matrix.
- Change `[build-system].build-backend` to `setuptools.build_meta`.
- Apply only Ruff safe fixes plus file-specific `N803` and `N818` compatibility ignores.
- Keep the fix on `fanxy/fixed-pick-place` and the existing draft PR #4.

---

### Task 1: Correct the setuptools build backend

**Files:**
- Modify: `pyproject.toml:3`
- Verify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: PEP 517 `build-backend` string loaded by pip.
- Produces: An importable setuptools backend supporting editable builds.

- [ ] **Step 1: Run the failing editable-install reproduction**

Run in a clean Python virtual environment with pip 26.2:

```powershell
python -m pip install --upgrade pip==26.2
python -m pip install --no-deps -e .
```

Expected before the fix: failure containing
`BackendUnavailable: Cannot import 'setuptools.backends._legacy'`.

- [ ] **Step 2: Apply the minimal configuration change**

Change:

```toml
build-backend = "setuptools.backends._legacy:_Backend"
```

to:

```toml
build-backend = "setuptools.build_meta"
```

- [ ] **Step 3: Re-run the editable-install reproduction**

```powershell
python -m pip install --no-deps -e .
```

Expected after the fix: exit code 0 and an editable wheel for
`uiea-thirdhand-vla` is installed.

- [ ] **Step 4: Run repository verification**

```bash
ruff check src/ tests/ --fix
ruff check src/ tests/
mypy src/
pytest tests/ -v --ignore=tests/e2e/
```

Before the clean Ruff run, add file-specific ignores for `N803` in
`src/uiea_thirdhand_vla/perception/detectors/base.py` and `N818` in
`src/uiea_thirdhand_vla/utils/errors.py`. These names are compatibility
surfaces and must not be renamed. Also run the fixed Pick and Place unittest
suite and Python/Bash syntax checks used during publishing.

- [ ] **Step 5: Commit and push**

```bash
git add pyproject.toml docs/superpowers/
git commit -m "Fix setuptools build backend for CI"
git push upstream fanxy/fixed-pick-place
```

- [ ] **Step 6: Verify GitHub Actions**

Wait for both `test (3.10)` and `test (3.11)` on PR #4. Success requires both
checks to conclude `SUCCESS` and the commit status to show no red cross.
