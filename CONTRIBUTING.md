# Contributing to ThirdHand VLA

## Supported Source Boundaries

Runtime changes belong in `apps/`, `services/`, `drivers/`, `platform/`, or
`skills/`. Do not import or execute code from `History/`. SDKs, models, generated
bindings, logs, and credentials remain under ignored `local/` or `runtime/` paths.

Only `services/robot` may own `can0`. Vision, speech, models, and Skills must use
the documented service contracts instead of sending CAN frames.

## Setup

Use Node.js 24 and the project-local Python runtime described in
`docs/RUN_GUIDE.md`. Install JavaScript dependencies with `npm ci`.

## Verification

```bash
npm run test:node
npm run test:python
python tools/diagnostics/audit_boundaries.py --root .
./thirdhand start --profile simulation
./thirdhand status --profile simulation
./thirdhand stop --profile simulation
```

Hardware verification requires a separate test plan, an accessible independent
hardware emergency stop, and explicit operator authorization. Automated tests
must use simulation and must not initialize the Startouch SDK.

## Change Scope

Keep changes within the owning module, update its tests and protocol docs, and
record local binary assets through `configs/assets` rather than committing them.
