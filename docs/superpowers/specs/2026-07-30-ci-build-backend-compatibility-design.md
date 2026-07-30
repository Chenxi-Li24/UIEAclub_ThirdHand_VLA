# CI build backend compatibility design

Date: 2026-07-30
Status: user approved

## Problem

GitHub Actions fails during `pip install -e ".[core,dev]"` on Python 3.11
after upgrading to pip 26.2. The configured backend
`setuptools.backends._legacy:_Backend` cannot be imported. The Python 3.10
matrix job is then cancelled by fail-fast.

## Considered approaches

1. Pin pip below 26.2 in CI. This hides the invalid backend configuration and
   leaves local installations vulnerable to the same failure.
2. Replace the backend with `setuptools.build_meta`. This is the standard
   PEP 517 setuptools backend and preserves the existing `pyproject.toml`
   package metadata. This is the selected approach.
3. Replace the project packaging configuration. This is unnecessary and would
   expand the change beyond the observed failure.

## Change

Change only `[build-system].build-backend` in `pyproject.toml` to
`setuptools.build_meta`. Do not change project dependencies, CI versions,
robot-control code, or hardware behavior.

## Verification

1. Reproduce the existing failure with pip 26.2 and an editable no-dependency
   install.
2. Apply the one-line backend correction and repeat the same install.
3. Run the repository's complete test suite, Ruff, Mypy, and syntax checks.
4. Push to the existing PR and wait for both Python 3.10 and 3.11 GitHub
   Actions jobs to complete successfully.

