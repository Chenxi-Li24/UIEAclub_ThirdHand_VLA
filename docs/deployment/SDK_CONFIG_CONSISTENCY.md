# SDK Configuration Consistency

## Canonical Configuration

`local/sdk/startouch/src/config/robot_kinematics.yaml` is the source of truth.
The generated Python SDK package contains an identical copy at
`local/generated/startouch-python/startouch_sdk/src/config/robot_kinematics.yaml`.
The existing `stage_runtime` build step copies the source configuration into
the package; do not maintain these copies as separate robot configurations.

The trajectory velocity references are 300 degrees/second for J1-J3 and
1000 degrees/second for J4-J6, stored as radians/second. These are SDK planning
references, not a request to move at those speeds. Existing command speed
scales, continuous-follow limits, joint ranges and feedback checks still apply.
This correction changes neither calibration nor TCP values.

## Connection Check

Before importing and constructing `SingleArm`, the Robot bridge validates both
the canonical configuration and the configuration beside its selected Python
module directory. Each must contain the expected six velocity references.
Missing or invalid runtime configuration rejects the connection. The complete
configuration bytes must match the canonical source, including non-speed
parameters. A mismatch must be corrected, not bypassed by disabling validation.

For a configuration-only correction, synchronize the generated configuration
and update its size and SHA-256 entry in `configs/assets/runtime-assets.json`.
Changing Python wrappers, native SDK source or ABI may require rebuilding;
changing this YAML alone does not change the native library binary.

## Offline Verification

Run the complete suites in an independent test checkout if formal services are
online. Do not share the production `runtime/run` directory: launcher ownership
records can conflict, and service-test cleanup can remove production ready
markers. This correction was verified with private simulated runtime state.

- `python -m pytest tests/python/robot_service/test_joint_speed.py -q`
- `python -m pytest -q`
- `npm run test:node`
- `python -m tools.diagnostics.audit_boundaries --json`

The tests use fake SDK constructors and temporary configurations. They reject
generated speed drift, non-speed drift and missing configuration without
constructing a real robot. The delivered configuration equality test also
guards against a stale packaged resource.

## Deployment And Remaining Checks

An already running Python bridge keeps its imported validation code until it is
restarted. Source changes alone are not proof that the live process uses the
new check. Restart and SDK connection require separately coordinated deployment
and hardware precautions; this patch does not perform them.

Resource integrity, runtime readiness and license records are separate checks.
Do not replace unknown license records with approved statuses to pass the
asset verifier. Optional VLA/ACT/DP checkpoint absence and existing incomplete
grasp wiring are not resolved by this configuration correction. Keep the old
deployment branch and integration worktree until formal deployment and physical
validation are complete and cleanup is explicitly authorized.
