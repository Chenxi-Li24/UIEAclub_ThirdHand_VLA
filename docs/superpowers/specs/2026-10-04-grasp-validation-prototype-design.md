# Grasp Validation Prototype Design

## Purpose

Create an independent grasp-validation prototype based on the current
`fanxy/bottle_grasp` implementation. The prototype exists to exercise and inspect
the core grasp sequence before the production approval gates and validation
artifact path are integrated.

The prototype must remain separate from the production bottle-pick workflow. It
must not weaken, replace, or silently bypass the existing production safety
path.

## Branch and baseline

- Branch: `Xavier/grasp-validation-prototype`
- Base: `origin/fanxy/bottle_grasp` at `7b8dc5813a2ce9dcc360d026325bd86d88641072`
- The existing production workflow and configuration remain unchanged.
- The prototype is simulation-only in this phase and must not open CAN, start
  the Startouch SDK, or send commands to the production Robot Service.

## Scope

The prototype implements this sequence:

1. Accept a target position, grasp orientation, and bottle width.
2. Derive a flange target from an explicitly supplied flange-to-grip transform.
3. Construct a pregrasp waypoint above the target.
4. Approach the target.
5. Close the simulated gripper.
6. Lift vertically by a configured distance.
7. Stop after the lift and report the generated commands and final state.

The prototype does not implement transfer, placement, retreat, or return Home.

## Deliberately omitted in this phase

The prototype does not depend on:

- `execution_gate`;
- hand-eye approval state;
- calibration approval hashes;
- grasp-offset approval;
- placement or path-validation artifacts;
- production runtime evidence;
- target-selection authorization;
- the production nine-stage pick-and-place controller.

These omissions apply only to the isolated prototype. The existing production
workflow continues to enforce all of its current gates.

## Required structural checks

Although approval gates are omitted, the prototype still rejects malformed
data that cannot produce a meaningful plan:

- positions and Euler angles must be finite three-element vectors;
- bottle width, speed, pregrasp offset, and lift distance must be finite and
  positive;
- the flange-to-grip value must be a finite rigid 4x4 transform;
- generated command values must remain finite.

These are input-contract checks, not commissioning or approval gates.

## Components

### Prototype plan builder

Add a focused module under
`skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/` that converts
plain geometric inputs into an immutable command plan. It may reuse pure rigid
transform helpers, but it must not import the production execution gate or
production workflow.

The output contains exactly four operator-visible phases:

- `pregrasp` — move above the target;
- `approach` — descend to the grasp pose;
- `grip` — close the simulated gripper;
- `lift` — move vertically upward.

### Simulation executor

Add a small executor in the same prototype directory. It consumes the plan,
emits one command at a time, records acknowledgements, and finishes after the
lift. The only adapter accepted in this phase is an injected simulator adapter.
There is no Startouch, WebSocket Robot Service, CAN, or hardware adapter factory
in the prototype module.

### CLI

Add `scripts/action/prototype_grasp_validation.js`. It reads a JSON fixture,
builds the plan, executes it through the simulator, and prints one JSON report.
It must not accept an `--execute`, `--real`, backend, socket, or CAN option.

### Fixtures and tests

Add a deterministic synthetic fixture containing a target pose, an example
flange-to-grip transform, bottle width, and motion settings. The fixture is
prototype input only and is not an approval artifact.

Tests cover:

- exact pregrasp, approach, grip, and lift ordering;
- correct flange target calculation;
- immutability of the generated plan;
- rejection of malformed or non-finite inputs;
- simulation completion and command correlation;
- proof that the CLI exposes no hardware execution option;
- proof that the prototype source does not import production robot adapters or
  the production execution gate.

## Isolation from production

No production route, web button, runtime profile, action configuration, or
service startup path references the prototype. Running the prototype requires
an explicit CLI invocation with a fixture. Later work may place approval gates
around the prototype core or connect a separately reviewed adapter, but that is
outside this phase.

## Verification

The implementation is complete when:

1. the new prototype tests pass;
2. the existing root Node suite still passes;
3. focused existing bottle-grasp planning and transform tests still pass;
4. a source scan confirms that the prototype has no hardware adapter imports;
5. the CLI produces a deterministic simulated four-phase report.

The existing Startouch process-client baseline currently has seven timeout
failures on this macOS environment. Those failures predate the prototype and
will be reported separately from prototype verification.
