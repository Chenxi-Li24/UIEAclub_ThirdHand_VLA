# Repository Release Cleanup Design

## Goal

Prepare the current robotic-arm development branch for a safe, reproducible,
fast-forward update of `origin/main`, while preserving the existing development
history and leaving `upstream` unchanged.

## Scope and repository boundaries

- `origin` (`Oliveirah007/UIEAclub_ThirdHand_VLA`) is the only writable remote
  in this operation.
- `upstream` (`Chenxi-Li24/UIEAclub_ThirdHand_VLA`) is read-only and must not be
  pushed to or otherwise modified.
- The current 42 commits after `origin/main` remain intact. No rebase, squash,
  force push, or history replacement is permitted.
- Existing working-tree changes are preserved and organized into reviewable
  commits. Unrelated behavior is not refactored merely for style.

## Intended project architecture

The cleanup documents and reinforces the existing component boundaries rather
than moving production code during a release preparation:

- `src/uiea_thirdhand_vla/`: packaged Python VLA application, including
  perception, reasoning, orchestration, control, configuration, logging, and
  its FastAPI console.
- `web-control/`: standalone Startouch hardware-control service and browser UI,
  including the vision-safety and Lumos camera integrations used by that UI.
- `configs/`: versioned example and operational configuration that is safe and
  portable across machines.
- `scripts/`: repository-level startup, deployment, calibration, and validation
  entry points.
- `tests/`: offline tests for the packaged application and cross-component
  workflows; component-local tests under `web-control/server/tests/` remain
  beside that standalone service.
- `docs/`: architecture, setup, API, safety, research decisions, and validated
  implementation records.

The README and architecture documentation will state these boundaries, list
the active service ports, and distinguish the packaged FastAPI application from
the standalone Startouch web-control stack.

## Artifact and data policy

The Git repository contains source, portable configuration, small deterministic
test fixtures, and documentation. It must not add:

- downloaded model weights such as `*.pt` and `*.onnx`;
- runtime logs, captured frames, PID files, or generated status files;
- timestamped fixed-point configuration backups;
- secrets, local environment files, or machine-specific credentials.

The local copies of these files are retained on disk. Ignore rules prevent
accidental staging; they do not delete operator data. Documentation supplies a
reproducible model acquisition procedure and identifies where local artifacts
belong.

Existing tracked robot meshes and vendored browser libraries remain tracked
because they are runtime assets already present in `main`, not newly downloaded
model weights.

## Change organization

Uncommitted work is reviewed for secrets, absolute machine paths, temporary
debugging behavior, and duplicated entry points. Valid work is grouped into
reviewable commits along these functional boundaries where the diff permits:

1. packaged VLA core and safety/control integration;
2. vision and Lumos/Startouch service integration;
3. browser UI integration;
4. repository hygiene and portable documentation.

A commit may combine inseparable implementation and tests, but unrelated
subsystems are not bundled solely to reduce the commit count.

## Verification

Verification is offline-first and must not command robot motion. It includes:

- repository status and ignored-artifact checks;
- secret and machine-specific-path scans of the staged content;
- Ruff linting for the configured Python source and tests;
- MyPy checks for the packaged source;
- the CI pytest suite excluding hardware end-to-end tests;
- relevant `web-control` and vision tests not automatically collected by the
  root configuration;
- syntax or startup-contract checks for JavaScript and shell entry points when
  supported locally.

Any failure is reported and resolved or explicitly documented before push. A
test requiring unavailable hardware or proprietary SDK access is skipped only
when the test itself defines that condition; verification must not silently
convert ordinary failures into skips.

## Safe publication procedure

Immediately before publication, fetch `origin` and verify that the current
branch is still a descendant of `origin/main`. Confirm the staged tree contains
no ignored runtime artifacts or credentials and that the working tree is clean.

Publish with a normal fast-forward update from the reviewed `HEAD` to
`origin/main`. Force push is prohibited. If `origin/main` changed during the
cleanup, stop and reconcile the new commits before retrying. After pushing,
verify the remote `main` object ID matches the reviewed local `HEAD` and report
the resulting commit and verification status.

`origin` currently exposes only `main`, so no remote branches or tags are
scheduled for deletion. The remote cleanup consists of publishing a clean,
reproducible `main` without adding temporary release branches.

## Success criteria

- All intended source and documentation changes are committed and reviewable.
- Model weights, logs, PID files, backups, secrets, and machine-local paths are
  absent from the pushed tree.
- Offline verification passes, with any hardware-only limitations clearly
  recorded.
- `origin/main` is updated by fast-forward and matches the reviewed commit.
- `upstream` remains untouched.
