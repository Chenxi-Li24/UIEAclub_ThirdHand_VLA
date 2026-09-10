# Reusable Vision SDK and GPT Grounding Design

Date: 2026-08-06
Status: Approved design; implementation not started

## 1. Objective

Integrate the delivered `thirdhand-vision-sdk` into the ThirdHand repository as a
reusable, hardware-free vision package, then add an out-of-band GPT text-image
grounding layer that selects an existing visual identity from a natural-language
command such as “夹取可乐”.

The first delivery ends at a validated, visualized target selection. It must not
enable or issue robot, gripper, CAN, active-view, or grasp commands. Existing robot
execution and task-checkpoint gates remain disabled until their independent hardware
acceptance work is complete.

## 2. Verified Input Artifact

The reviewed archive is `thirdhand-vision-sdk-20260806.zip`. It contains 57 entries,
186,678 uncompressed bytes, no absolute or parent-traversal paths, no weights, no
credentials, and no hardware runtime.

The following checks passed in a temporary extraction outside the repository:

- every file matched the archive's manifest values using its current path-first
  manifest layout;
- `scripts/verify_source_unchanged.py` reported that every mapped source file matched
  the current ThirdHand repository;
- the SDK test suite reported `65 passed` under the deployed Python 3.11 vision
  environment;
- the recorded source commit `1bb7b2e5cf359ded362481413bbf987fad33c9ef` exists in
  the repository.

Four release issues must be corrected when the SDK is imported:

1. `MANIFEST.sha256` is path-first although its README instructs users to run
   `sha256sum -c`; the committed manifest must use the standard hash-first layout.
2. `LICENSES.md` says the source repository lacks a top-level license, but the current
   repository has an MIT license. The package must include `LICENSE` and corrected
   redistribution language.
3. `TargetSelection.score` and `TargetSelection.explanation` are discarded when the
   pipeline stores only `selected_identity_id`; the full advisory decision needs an
   auditable application-level envelope.
4. Generic optional dependencies do not encode the deployed MMCV/CUDA compatibility
   constraints. Real model installation remains owned by the pinned CUDA 12.8
   bootstrap and requirements path.

## 3. Alternatives Considered

### 3.1 Monorepo package — selected

Place the SDK at `packages/thirdhand-vision-sdk/` with its own `pyproject.toml`, tests,
examples, docs, build output, version, and license. Use it from the repository through
an editable install in development and a built wheel in release validation.

This retains independent packaging while allowing an incremental migration without
coordinating two repositories.

### 3.2 Separate SDK repository

Publish the SDK independently and consume a pinned wheel or Git tag. This is the
intended later distribution boundary, but adopting it now would add release and
version-coordination work before the public contract is stable.

### 3.3 Merge SDK files into the packaged application

Copy the code into `src/uiea_thirdhand_vla/perception`. This is rejected because it
would create another copy beside `web-control/server/vision`, destroy independent SDK
installation, and make algorithm fixes diverge.

## 4. Repository Boundaries

The target layout is:

```text
TH-Fanxy/
├── packages/
│   └── thirdhand-vision-sdk/
│       ├── pyproject.toml
│       ├── LICENSE
│       ├── README.md
│       ├── src/thirdhand_vision/
│       ├── tests/
│       ├── examples/
│       └── docs/
├── web-control/
│   └── server/
│       ├── camera_bridge.py
│       ├── vision_sdk_adapter.py
│       └── vla/
│           ├── contracts.js
│           ├── prompt.js
│           ├── openai-provider.js
│           ├── grounding.js
│           ├── audit-log.js
│           └── mock-provider.js
├── src/uiea_thirdhand_vla/
└── tests/
```

The SDK becomes the intended single source of truth for hardware-independent vision
algorithms. The existing online path remains authoritative until replay parity,
online shadow, and hardware Dry Run gates pass. Duplicate files are removed only at
the end of migration.

### 4.1 SDK responsibilities

- immutable image, depth, calibration, detection, pose, identity, and result contracts;
- RTMDet and feature-encoder protocols and optional adapters;
- cross-camera depth registration and instance pose estimation;
- persistent identity, ambiguity rejection, and advisory active-view algorithms;
- a caller-driven `VisionPipeline.process()` with no devices, threads, network, UI,
  or robot access.

### 4.2 Runtime responsibilities

- Lumos and D435 device access;
- frame pairing, latest-only scheduling, GPU model lifecycle, and online recovery;
- conversion between runtime and SDK contracts;
- event serialization, MJPEG overlays, browser status, and provenance;
- active-view sessions, robot-state freshness, locks, safety authorization, and robot
  execution.

### 4.3 GPT grounding responsibilities

- receive one bounded natural-language request from the browser;
- use one fresh ID-labelled Lumos overlay and the matching candidate list;
- return `select`, `clarify`, or `none` using a strict schema;
- select only an `identity_id` enumerated in the request;
- log an advisory decision without authorizing motion.

## 5. Vision Runtime Adapter

`web-control/server/vision_sdk_adapter.py` translates without weakening either side's
validation:

```text
runtime FramePair              -> SDK FrameBundle
runtime calibration evidence   -> SDK FusionCalibration
SDK PerceptionResult           -> existing detection_result event contract
```

The adapter owns compatibility with the current browser event schema. The SDK must
not import the Node proxy, camera bridge, Startouch SDK, RealSense device API, network
services, or systemd configuration.

The adapter must preserve at least:

- frame ID and monotonic timestamp;
- camera roles and calibration content ID;
- detection ID, class, score, native mask, and bounding box;
- identity ID, status, ambiguity evidence, and memory statistics;
- three-dimensional pose, covariance, frame, age, and depth evidence;
- frame and target blocker/reason codes;
- the invariant that robot execution remains disabled during migration.

Per-frame fallback between old and SDK identity implementations is forbidden because
the two memories can assign different IDs. Implementation selection occurs only at
service startup. SDK startup or processing failure fails the vision service closed and
publishes no actionable target.

## 6. GPT Text-Image Grounding

### 6.1 Non-blocking execution

Cloud inference must not run inside `VisionPipeline.process()` or the 15 FPS online
perception loop. The existing `TargetSelector` protocol remains appropriate for local,
bounded selectors, but a network selector would block camera processing.

The application therefore maintains the latest immutable perception snapshot and
overlay. A user command creates an independent, capacity-bounded GPT job:

```text
browser command
  -> fresh perception snapshot and ID-labelled overlay
  -> OpenAI Responses API worker
  -> strict advisory selection
  -> current-state revalidation
  -> browser highlight only
```

Only one selection request may be active per browser/operator context. The first
version performs no automatic retry; the operator may submit another request after a
visible failure or clarification.

### 6.2 Selection request

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "query": "夹取可乐",
  "frame_id": 1842,
  "frame_monotonic_ns": 987654321,
  "image_sha256": "sha256:<64 lowercase hex characters>",
  "candidates": [
    {
      "identity_id": 12,
      "detection_id": 3,
      "label": "bottle",
      "identity_status": "confirmed",
      "detection_score": 0.94
    }
  ]
}
```

The candidate array is derived exclusively from the same bounded vision snapshot as
the overlay. Only confirmed identities are offered. User-controlled URLs, model names,
candidate IDs, schemas, and system prompts are not accepted by this endpoint.

### 6.3 Model response

```json
{
  "decision": "select",
  "identity_id": 12,
  "ambiguous": false,
  "explanation": "ID 12 is the Coca-Cola bottle."
}
```

The schema permits three decisions:

- `select`: exactly one allowed identity is selected;
- `clarify`: the image or language is ambiguous and a bounded explanation is returned;
- `none`: no allowed candidate matches the request.

For `select`, `identity_id` is constrained with a request-specific integer enum. For
the other decisions it is null. A model-provided semantic score may be recorded for
research but is never safety evidence or authorization.

### 6.4 Validated decision envelope

The application preserves the SDK selection fields rather than storing only an ID:

```text
request_id
query
provider
model_id
prompt_version
schema_version
source frame_id and monotonic_ns
image_sha256
allowed candidate IDs
decision
selected identity_id
model explanation
local validation result and reason
request latency
input/output/cached tokens
estimated cost inputs
```

The raw API response may be retained only after removing credentials and bounded to a
configured maximum size. Full images are not retained by default; explicitly enabled
dataset capture records consent, manifest membership, and the image content hash.

## 7. Local Revalidation and Safety

After an API response, the application discards the source snapshot for execution
purposes and checks the current trusted vision state. A selected target is displayable
only if:

- the response passes the strict schema;
- the selected ID was in the request-specific enum;
- that identity still exists and remains `confirmed`;
- the current observation is fresh and not ambiguous or occluded;
- frame and image provenance match the recorded request;
- the request has not expired, been superseded, or been cancelled.

The first release then stops at a browser highlight. It never invokes
`authorizeGrasp()`, `startGrasp()`, active-view motion, the Startouch bridge, or any
gripper or motion command.

Future physical execution still requires a separate approved design and all existing
checks for current identity, depth, calibration, covariance, pose age, stationary arm,
workspace bounds, resource locks, software state, and hardware emergency stop. GPT
cannot supply or override robot coordinates.

## 8. Failure Policy

All GPT and integration failures produce no selection and no motion:

- absent server-side `OPENAI_API_KEY`;
- authentication, quota, billing, rate-limit, network, or timeout error;
- stale, missing, mismatched, or oversized image and candidate snapshot;
- no confirmed candidate;
- invalid JSON, schema violation, extra fields, or response size violation;
- an identity outside the allowed enum;
- `clarify`, `none`, or an ambiguous result;
- selected identity missing, stale, occluded, or ambiguous on revalidation;
- SDK, adapter, model, calibration, depth, or vision service unavailable.

There is no fallback to the first candidate, the highest detector score, a previous
GPT result, or an alternate unvalidated model. Errors are sanitized for the browser
and audit log; API keys and authorization headers are never logged or sent to the
browser.

## 9. Browser Experience

The current hardware control page gains a bounded text field and a “识别目标” action.
The page shows:

- request state: idle, analyzing, selected, clarify, none, rejected, or error;
- provider/model and latency;
- selected identity and explanation;
- a highlight synchronized with the current target list;
- an explicit “预览，不会执行抓取” label.

The browser cannot submit model IDs, API keys, image URLs, target coordinates, or
arbitrary candidate lists. Refresh, disconnect, software stop, vision failure, or a
newer language request invalidates the displayed selection.

## 10. Migration and Acceptance Gates

### Gate 1 — package import

- place the corrected SDK under `packages/thirdhand-vision-sdk/`;
- include MIT `LICENSE`, third-party notices, standard manifest, and source map;
- run the SDK unit suite and examples;
- build and inspect the wheel and source distribution;
- verify that artifacts contain no weights, captures, logs, credentials, absolute
  machine paths, symlinks, CAN, or hardware runtime.

### Gate 2 — replay parity

Run the old core and SDK against identical immutable replay inputs. Compare detection
count/classes, masks, descriptor distances, identity assignments and switches, blocker
codes, ambiguity refusal, three-dimensional pose/covariance, and failure behavior.
Thresholds and paired differences are declared in the result manifest before review.

### Gate 3 — online shadow

Run the SDK beside the current online result path on real Lumos and D435 streams with
`robot_execution_enabled: false`. Record latency, GPU memory, target/identity parity,
pose differences, errors, and all would-be-actionable disagreements. The old path
remains the displayed authority during this gate.

### Gate 4 — SDK primary runtime

Select the SDK implementation at service startup after replay and shadow approval.
Keep robot execution disabled. Startup, model, adapter, or processing failure produces
a visible fail-closed vision error and zero candidates for grasp execution.

### Gate 5 — duplicate removal

Convert remaining runtime imports to SDK or thin compatibility adapters. Remove a
duplicate algorithm file only after its source-map record, unit tests, replay tests,
online shadow tests, and all downstream contracts have moved to the package.

## 11. Verification Strategy

### 11.1 SDK tests

- retain the existing 65-test baseline;
- add standard-manifest, MIT-license, wheel/sdist content, source-map, and public API
  tests;
- keep all default tests hardware-free and network-free;
- retain explicit fake-based contracts for optional RTMDet and DINO adapters.

### 11.2 Runtime adapter tests

- exact timestamp, calibration ID, camera-role, mask, pose, covariance, and reason
  conversion;
- rejection of invalid, non-finite, stale, or mismatched inputs;
- deterministic event serialization with no arrays or credentials accidentally
  embedded;
- fail-closed startup and processing errors;
- replay parity reports generated from declared fixtures.

### 11.3 GPT provider and grounding tests

Use a fake transport and fixture JPEGs; CI never calls the live API. Cover:

- valid `select`, `clarify`, and `none` results;
- request-specific ID enums and rejection of unknown IDs;
- missing key, authentication, quota, timeout, rate limit, malformed response, extra
  keys, oversized response, and cancellation;
- stale source frame and stale or disappeared identity on revalidation;
- bounded prompt, request, response, and explanation sizes;
- redaction of keys and authorization headers;
- mock provider behavior without network access.

### 11.4 End-to-end Dry Run

A deterministic browser/API test submits “夹取可乐” against a fixture containing
IDs 12 and 15. A fake provider selects 12, the UI highlights 12, and the audit record
links the command, image hash, candidates, response, and validation result.

The following assertions are mandatory for successful, ambiguous, malformed, stale,
cancelled, and API-error cases:

```text
robot motion commands = 0
gripper commands = 0
active-view motion commands = 0
grasp starts = 0
```

## 12. CI and Release

The repository CI gains an independent SDK job for Python 3.10 and 3.11. It installs
the nested package without GPU extras, runs SDK tests and examples, builds release
artifacts, and inspects contents. The existing packaged-application job remains
unchanged until explicit integration work needs it.

The deployed vision environment installs the local package with no dependency
resolution after the pinned CUDA 12.8 bootstrap has installed compatible Torch, MMCV,
MMDetection, Transformers, NumPy, SciPy, and OpenCV versions. Model checkpoints and
Hugging Face caches remain external runtime assets.

SDK releases use semantic versions and include a source map, standard manifest,
license, verification report, artifact hash sidecar, and declared compatibility with
the repository commit and vision environment.

## 13. Explicit Non-goals

This implementation does not:

- enable physical grasp, active-view motion, or robot execution;
- let GPT create detections, identities, poses, trajectories, or coordinates;
- call cloud APIs on every camera frame;
- train or fine-tune a detector, descriptor, VLM, or grasp policy;
- publish the SDK to a public package index or create a separate repository;
- distribute model weights, captured research data, or calibration evidence;
- remove the existing vision implementation before all migration gates pass;
- treat model explanations or self-reported confidence as safety evidence.

## 14. Implementation Sequence

After this specification is reviewed, the implementation plan will split work into
four independently verifiable increments:

1. correct and import the SDK package with package-only CI and release guards;
2. implement the runtime adapter and offline replay parity harness;
3. implement the server-side GPT grounding worker, contracts, audit, and fake provider;
4. add the preview-only browser flow and end-to-end zero-motion tests.

Online shadow and SDK-primary runtime conversion remain subsequent gated increments,
because they require replay evidence and operator review produced by the initial work.
