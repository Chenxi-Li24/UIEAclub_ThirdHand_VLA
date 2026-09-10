# Unified Foundation Baseline

Recorded: 2026-09-10

## Destination

- Ubuntu checkout: `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`
- Branch: `refactor/unified-platform-foundation`
- Clone baseline: `f0b6310` (`Add Ubuntu Startouch web control`)
- `origin`: `Oliveirah007/UIEAclub_ThirdHand_VLA`
- `upstream`: `Chenxi-Li24/UIEAclub_ThirdHand_VLA`

The destination is an independent clone. It is not a linked Git worktree and contains no symlinks back to source projects.

## Read-Only Migration Sources

| Source | Approximate size | Baseline note |
|---|---:|---|
| `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA` | 149 MB | `main` at `6c6b79f`, ahead of its configured upstream by 135 commits, with accepted local changes and untracked grasp/vision files |
| `/home/nieqingcao/Thirdhand_language` | 17 GB | Formal Language Part and only current source for the 9983/3004 delivery |
| `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill` | 78 MB | XVisio, target identity, geometry, supervision, and grasp source subtree |
| `/home/nieqingcao/thirdhand-policy-integration-20260817-01` | 361 MB | ACT contract/checkpoint-loader prototype; not a complete policy delivery |
| `/home/nieqingcao/TH-Fanxy` | 801 MB | Legacy dependency to eliminate during migration |
| `/home/nieqingcao/arm/startouch_sdk` | 32 MB | Startouch SDK with license status currently unknown |
| `/home/nieqingcao/FastUMI_Hardware_SDK` | 196 MB | XVisio native dependency |
| `/home/nieqingcao/calibration` | 7 MB | Calibration records requiring review before promotion |

These directories are migration inputs only. The migration may read and copy from them but must not edit, move, delete, reset, clean, stop, or replace anything in them.

## Accepted Live Entry Points

- Existing Startouch web/robot service: port 3000, currently launched from the accepted old project.
- Existing XVisio service pattern: port 3100.
- Existing Language web gateway and speech service: ports 9983 and 3004.

Foundation tests do not open CAN, initialize the Startouch SDK, access XVisio, load speech models, or occupy those production ports. Simulation uses alternate loopback ports. Production cutover requires a separate user approval after validation.

## Initial Test State

- `python -m pytest tests/test_build_backend.py tests/docs -v` fails during collection because the cloned Python package has not been installed in an isolated project runtime.
- `npm --prefix web-control/server test` fails because commit `f0b6310` has no server `test` script; the accepted old Ubuntu source contains newer tests not yet migrated.

These are pre-existing baseline gaps, not foundation regressions. Later migration steps must copy and reconcile the accepted newer source before its tests can become release gates.

## Rollback

Before cutover, rollback means stopping only processes owned by this new checkout and returning to the already-running old entry points. No source restoration is needed because old projects remain unchanged.
