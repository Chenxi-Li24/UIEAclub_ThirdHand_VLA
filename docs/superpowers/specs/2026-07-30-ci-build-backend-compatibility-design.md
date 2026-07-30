# CI build backend compatibility design

Date: 2026-07-30
Status: user approved

## Problem

GitHub Actions fails during `pip install -e ".[core,dev]"` on Python 3.11
after upgrading to pip 26.2. The configured backend
`setuptools.backends._legacy:_Backend` cannot be imported. The Python 3.10
matrix job is then cancelled by fail-fast.

After reproducing and correcting that boundary, the next CI command exposes
32 pre-existing Ruff findings that were previously hidden by the install
failure. Repository history confirms every `main` CI run has stopped at the
same invalid backend before reaching lint.

Once Ruff is clean, Mypy strict mode exposes 106 missing-annotation errors in
29 unfinished framework skeleton files. The fixed Pick and Place workflow is
outside that legacy `src/` skeleton. Keeping Mypy enabled with its normal
checks, while disabling strict mode until the skeleton is fully annotated,
provides a truthful baseline without a risky unrelated rewrite.

## Considered approaches

1. Pin pip below 26.2 in CI. This hides the invalid backend configuration and
   leaves local installations vulnerable to the same failure.
2. Replace the backend with `setuptools.build_meta`. This is the standard
   PEP 517 setuptools backend and preserves the existing `pyproject.toml`
   package metadata. This is the selected approach.
3. Replace the project packaging configuration. This is unnecessary and would
   expand the change beyond the observed failure.

For the newly exposed lint layer, apply Ruff's safe mechanical fixes for
imports, unused imports, and Python 3.10 union annotations. Preserve public
exception class names and the camera-matrix compatibility parameter by adding
file-specific ignores for `N818` and `N803`; renaming those symbols would risk
breaking callers.

For Mypy, keep `mypy src/` in CI and `ignore_missing_imports = true`, change
`strict` to `false`, and correct the explicit nullable `Intent.params` type.

## Change

Change only `[build-system].build-backend` in `pyproject.toml` to
`setuptools.build_meta`. Apply only behavior-preserving Ruff fixes and the two
file-specific compatibility ignores. Do not change project dependencies, CI
versions, robot-control behavior, or hardware behavior. Keep Mypy enabled in
non-strict mode for the unfinished framework skeleton.

## Verification

1. Reproduce the existing failure with pip 26.2 and an editable no-dependency
   install.
2. Apply the one-line backend correction and repeat the same install.
3. Verify Ruff fails on the pre-existing findings, apply the safe fixes and
   compatibility ignores, and verify Ruff is clean.
4. Run the repository's complete test suite, Mypy, and syntax checks.
5. Push to the existing PR and wait for both Python 3.10 and 3.11 GitHub
   Actions jobs to complete successfully.
