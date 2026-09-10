# Shadow Observation Bridge Design

Status: approved by delegated user authority on 2026-08-07.

## Purpose

Connect the evidence-gated orchestration runtime to existing ThirdHand vision outputs without
editing, importing through private paths, or controlling the existing vision process. The bridge
supports checked JSON replay and an explicitly enabled read-only latest-event source. It also
defines a lazy, local-files-only Grounding DINO fallback for open-vocabulary target proposals.

## Reuse and Ownership

- Existing RTMDet instance masks remain the primary detector.
- Existing DINO descriptors and REMIND identity memory remain the only source of persistent IDs.
- Existing depth, calibration, actionable-state, active-view, and model-acceptance decisions are
  preserved rather than recomputed by orchestration.
- New code lives under `orchestration/shadow`; existing `web-control`, vision SDK, calibration,
  camera, and model files remain untouched.
- DINOv3 is not substituted for the commissioned DINOv2 model. A descriptor model ID is carried as
  provenance so a separately accepted DINOv3 checkpoint can be evaluated later.

## Canonical Input

The bridge accepts a frozen `VisionEvent` corresponding to the public
`OnlinePerceptionResult.to_event()` boundary:

- `type=detection_result`, source sequence, frame ID, and monotonic timestamp;
- `model_ready`, `task_checkpoint_validated`, `robot_execution_enabled=false`, and blockers;
- target identity, identity status, label, score, actionable flag, pose, grasp preview, reasons,
  registered depth points, and identity-memory statistics;
- model, calibration, camera, and image content IDs when supplied by the producer.

Unknown fields are rejected for checked fixtures and preserved only inside a bounded provenance
record for forward-compatible live events. NaN, infinity, remote file URLs, symlinks, stale frames,
sequence rollback, missing identity, invalid depth, unvalidated calibration, and
`robot_execution_enabled=true` fail closed.

## Components

### Vision event adapter

`VisionEventAdapter(episode_id).to_observation(event, robot_state)` returns the existing runtime
`Observation`. The adapter binds events from a producer that does not carry an orchestration episode
ID to one explicit episode chosen by the caller. A target becomes visible when present,
unambiguous only when its identity status is confirmed and no ambiguity blocker is present, and
actionable only when the upstream actionable flag, accepted checkpoint, valid calibrated pose, and
depth evidence all agree. Evidence IDs are content-addressed from canonical JSON when the producer
does not supply them.

### Sources

- `VisionJsonlReplaySource`: finite, strict JSONL replay.
- `LatestVisionEventSource`: opt-in polling of one explicit local regular file, with bounded wait,
  stable-read verification, no device access, and no network access.
- Both expose the runtime `ObservationSource` protocol and require strictly increasing sequences.

### Grounding DINO fallback

`GroundingDinoCandidateProvider` receives an RGB file, a tuple of text labels, and thresholds. Its
default Hugging Face backend lazily imports Torch, Pillow, and Transformers, requires an explicit
local model directory, and calls `from_pretrained(..., local_files_only=True)`. It never downloads
weights. The output is a tuple of boxes, scores, and normalized phrases with model provenance.

The fallback is invoked only when the primary event has no matching target, an unknown label, or
an explicit ambiguity reason. A proposal never becomes actionable by itself: it must be associated
with a REMIND identity and separately obtain calibrated depth before it can satisfy a Skill
precondition.

This follows the official Grounding DINO implementation and Hugging Face processor contract while
keeping model loading optional and isolated:

- https://github.com/IDEA-Research/GroundingDINO
- https://huggingface.co/docs/transformers/model_doc/grounding-dino

## Data Flow

1. Read and validate an existing detection event.
2. Bind its immutable payload to a content ID.
3. Convert accepted targets and blockers into runtime objects, facts, and evidence references.
4. If the target is missing or ambiguous and fallback is enabled, request Grounding DINO
   candidates.
5. Publish candidates as non-actionable observations until identity and metric depth are confirmed.
6. Give the resulting `Observation` to the unchanged evidence gates.

## Acceptance

1. Checked RTMDet+DINO+REMIND events round-trip deterministically into runtime observations.
2. Stale, rolled-back, unsafe, or unvalidated events cannot pass actionable predicates.
3. Replay and read-only latest-file sources perform no camera, network, or robot access.
4. Grounding DINO works with an injected fake backend in unit tests and has a local-model-only smoke
   command that reports `UNAVAILABLE` when dependencies or weights are absent.
5. The bridge does not modify or import the current uncommitted vision implementation.
