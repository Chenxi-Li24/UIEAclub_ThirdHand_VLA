# PART D test report

- Date: 2026-08-17 (Asia/Shanghai)
- Implementation commit: `dfa5dd3765267d56322f2a3a8d874bc556af4969`
- Modes exercised: `simulate`, local no-motion `dry-run`; `real` was not run
- Hardware access: none
- Bridge/SDK/CAN/SSH access: none
- Motion/gripper commands: none
- Focused tests: 44 passed, 0 failed
- Ruff: passed

## Commands and results

```text
PYTHONPATH=src .venv-control/bin/python -m pytest -q -p no:cacheprovider tests/control/test_startouch_fixed_waypoint_adapter.py tests/control/test_startouch_execution_service.py tests/control/test_part_d_handoff.py
............................................                             [100%]
44 passed in 4.52s
```

```text
RUFF_CACHE_DIR=/private/tmp/thirdhand-ruff-cache .venv-control/bin/python -m ruff check web-control/scripts/startouch_fixed_waypoint_adapter.py web-control/server/startouch_execution_service.py tests/control/test_startouch_fixed_waypoint_adapter.py tests/control/test_startouch_execution_service.py tests/control/test_part_d_handoff.py
All checks passed!
```

Coverage includes positive simulate and local dry-run, no-hardware guards,
confirmation/safety/schema rejection, optional identity mismatch, unsupported
adapter/ACT, speed limits, real-mode refusal, concurrency, JSON protocol errors,
route truncation, strict JSON parsing, and handoff replay validation.

Bridge connection failure, CAN fault, stale state, and timeout cases are
synthetic fault injections. They verify fail-closed result mapping only and are
not hardware evidence. Neither read-only Bridge status nor motion commands were
used: the Bridge process was never started.
