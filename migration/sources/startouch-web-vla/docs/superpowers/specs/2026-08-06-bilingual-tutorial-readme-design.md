# Bilingual Tutorial README Design

**Date:** 2026-08-06

**Status:** Approved design

**Audience:** Developers, researchers, and future SCI authors

**Languages:** Complete Chinese and English documentation

## 1. Objective

Replace the current short repository overview with a bilingual, tutorial-style
documentation set that explains the complete ThirdHand VLA project from first
principles through implementation, deployment, verification, and extension.

The documentation is also the entry point to a reproducible SCI evidence base.
Its primary research axis is robotic vision and 3D perception, its secondary axis
is verifiable VLA decision-making, and its optional system-paper axis combines the
two. Robot control is the supervised experimental platform and safety boundary,
not the principal claimed contribution.

The documentation must let a new developer answer five questions without first
reading the implementation:

1. What problem does the project solve, and which hardware and services does it use?
2. Which robotics, perception, VLA, interaction, and safety concepts are involved?
3. How do those concepts map to concrete modules, interfaces, configuration, and data flow?
4. What can be run offline, in simulation, read-only on hardware, or with supervised motion?
5. Which features are implemented, verified, experimental, or only planned?
6. Which hypotheses, datasets, protocols, metrics, baselines, and artifacts support
   future scientific claims?

## 2. Documentation Set

The repository will expose three top-level README files.

### `README.md`

The bilingual landing page remains concise enough for GitHub visitors. It contains:

- project title, one-sentence purpose, and relevant badges;
- Chinese and English documentation entry points;
- representative capabilities and current maturity;
- a high-level architecture diagram showing both runtime boundaries;
- the shortest safe installation and offline verification route;
- a prominent safety warning and links to the full tutorials;
- a research-track summary and selected evidence/preview gallery;
- the correct `Chenxi-Li24/UIEAclub_ThirdHand_VLA` clone URL.

It is a navigation and project-presentation page, not a third copy of the full tutorial.

### `README_CN.md`

The canonical full Chinese tutorial. It explains concepts before implementation,
uses real repository paths and commands, and links to specialized documents for
research evidence and operational detail.

### `README_EN.md`

The complete English counterpart. Its section numbers, tables, diagrams, commands,
feature-status labels, and links stay aligned with `README_CN.md`. The prose is
translated for technical clarity rather than mechanically mirrored sentence by
sentence.

## 3. Tutorial Information Architecture

Both complete tutorials use the same eight-part teaching sequence.

### Part 1 — Understanding ThirdHand

- project goals, non-goals, and typical tasks;
- Lumos Touch R1, Lumos Ego RGB, Intel RealSense D435, CAN, host, and optional GPU;
- two independently deployable runtime systems;
- feature maturity matrix and safety boundary;
- terminology and suggested reading paths.

### Part 2 — Robotics and Geometry Foundations

- six-degree-of-freedom joint representation;
- joint-space versus Cartesian motion;
- end-effector pose and coordinate-frame notation;
- rotation matrices, RPY conventions, homogeneous transforms, and SE(3);
- camera intrinsics, distortion, extrinsics, and hand-eye calibration;
- workspace bounds, joint limits, speed limits, watchdogs, and emergency stop.

Each concept is paired with the repository module or configuration that implements it.

### Part 3 — Perception Foundations

- Lumos fisheye/SEUCM image model and D435 pinhole/RGB-D model;
- canonical RGB and metric-depth roles;
- frame timestamps, skew limits, freshness, and cross-camera depth registration;
- ArUco, YOLO, RTMDet instance segmentation, and DINOv2 descriptors;
- short-horizon tracking, persistent identity, object memory, occlusion, and reacquisition;
- 3D instance pose estimation, uncertainty, and fail-closed perception gates.
- research hypotheses, baselines, ablations, and metrics for each perception stage.

The text must distinguish the packaged perception baseline from the newer
`web-control/server/vision` and `vision_models` pipelines.

### Part 4 — VLA, Voice, and Human Interaction

- optional cloud VLA reasoning and local validation boundary;
- ASR, NLU, TTS, text input, and voice-bridge protocol;
- intent candidates, local preview, human confirmation, and command authorization;
- why model output is a recommendation rather than direct robot authority;
- offline mocks, network failure, and privacy/runtime considerations.
- VLA evaluation protocols covering intent accuracy, unsafe-action interception,
  human correction, latency, hallucination, refusal quality, and recovery.

### Part 5 — Control, Orchestration, and Safety

- deterministic task state machine and pick-and-place stages;
- robot and gripper adapters;
- Startouch SDK bridge, CAN ownership, process locks, and resource guards;
- software stop versus independent hardware emergency stop;
- fixed A/B point teaching and supervised execution;
- safety invariants and fail-closed behavior.

### Part 6 — Mapping Concepts to the Repository

- a curated directory tree;
- responsibilities, inputs, outputs, dependencies, safety boundary, and deep links for
  every major module;
- configuration hierarchy and important YAML files;
- service/API/WebSocket boundaries;
- model assets and runtime artifacts;
- scripts grouped by installation, calibration, deployment, demonstration, and verification.

The tutorial documents meaningful modules rather than describing every source file line by line.

### Part 7 — Hands-on Operation

The operating tutorial follows a risk ladder:

| Level | Scope | Hardware authority |
| --- | --- | --- |
| L0 | Read, install, prepare configuration and model assets | None |
| L1 | Lint, type checking, unit tests, synthetic geometry, deterministic replay | None |
| L2 | Simulation, dry run, browser UI, voice mocks, command preview | No real CAN motion |
| L3 | Camera frames, timing, CAN receive health, online vision status | Read-only |
| L4 | Supervised, exclusive, low-speed robot operation | Explicit human gate |

Instructions must never imply that completing a lower level authorizes a higher one.
Every real-hardware section begins with prerequisites, stop conditions, and expected evidence.

### Part 8 — Verification, Troubleshooting, and Extension

- Ruff and MyPy checks across supported Python versions;
- core, web security, orchestration, and control tests;
- geometry, registration, tracking, identity, memory, and safety tests;
- Lumos HTTP, dual-camera, online inference, Node protocol, and browser smoke tests;
- hardware preflight, soak testing, logs, and acceptance evidence;
- symptom-to-diagnosis-to-safe-response troubleshooting;
- extension interfaces, contribution workflow, research roadmap, and documentation index.
- SCI evidence manifests, dataset documentation, reproducibility checklists, quantitative
  result generation, effect previews, baselines, ablations, failure cases, and limitations.

## 4. Scientific Research Tracks

The documentation prepares three compatible publication directions without claiming
that uncompleted experiments already support them.

### Track A — Robotic Vision and 3D Perception (primary)

The primary research story covers:

- Lumos fisheye RGB as the canonical appearance source;
- D435 metric depth and cross-camera registration;
- explicit timestamp, calibration, and uncertainty handling;
- instance segmentation and masked 3D estimation;
- DINOv2 appearance descriptors, tracking, persistent object memory, occlusion,
  reacquisition, and ambiguity rejection;
- propagation of perception confidence into actionability.

Candidate evaluation includes mask AP/recall, radial performance, depth registration
error, 3D position error and jitter, HOTA, IDF1, ID switches, fragmentation,
reacquisition rate, false identity merges, latency, throughput, and GPU memory.

### Track B — Verifiable VLA Decision-Making (secondary)

The VLA research story covers:

- grounded multimodal task understanding;
- structured intent/action candidates instead of direct actuator calls;
- local simulation/preview, human confirmation, and deterministic validation;
- uncertainty, invalid intent, hallucination, timeout, refusal, and recovery behavior;
- use of persistent visual object state as grounded VLA context.

Candidate evaluation includes task and intent accuracy, unsafe-action interception,
human correction rate, unsupported-action rate, calibrated refusal quality, recovery
success, and end-to-end latency.

### Track C — Integrated Vision–VLA System (optional)

The integrated paper route studies persistent object memory as VLA context,
perception-uncertainty propagation into decisions, long-horizon task completion,
closed-loop verification, and failure recovery. Robot hardware demonstrates the
method under supervised safety constraints; low-level arm control is not presented
as the main novelty.

## 5. Scientific Evidence Unit

Every research-relevant method section follows one repeatable evidence structure:

1. **Problem:** research question, scope, and falsifiable hypothesis.
2. **Method:** notation, mathematical definition, algorithm, assumptions, and complexity.
3. **Protocol:** hardware, software, dataset split, scenario, seed, baseline, and procedure.
4. **Metrics:** exact definition, aggregation, uncertainty, and statistical test where useful.
5. **Evidence:** machine-readable results, generated figures, model/calibration/data versions,
   commit, command, and environment manifest.
6. **Limits:** failure cases, threats to validity, safety limits, and unverified claims.

Results must be generated from machine-readable JSON/CSV rather than copied by hand.
The evidence contract records at least the Git commit, model identifier and checksum,
calibration identifier, dataset manifest/checksum, hardware/software environment,
command, seed, timestamp, and schema version.

## 6. Effect Preview and Planned-Evidence Policy

The README set provides visual preview positions that can later be populated with
real experimental artifacts:

- **V1:** Lumos instance mask, D435 depth, and robot-base 3D result;
- **V2:** identity before occlusion, during occlusion, and after reacquisition;
- **V3:** depth-registration error, radial calibration residuals, and uncertainty view;
- **L1:** VLA instruction, visual context, candidate, preview, confirmation, and refusal reason;
- **E1:** baseline comparison and confidence intervals;
- **E2:** ablation table/curve;
- **E3:** accuracy-latency-resource trade-off;
- **F1:** representative success and failure cases.

Until real evidence exists, each position is visibly labeled **Planned Evidence /
待补实验证据** and contains only the expected artifact type, required fields,
and generation path. It must not contain invented screenshots, numbers, curves, or
conclusions. A preview becomes a result only after its source manifest and generation
command are linked.

## 7. Research Support Files

The implementation plan may add a focused research evidence area under `docs/research/`
with the following templates or indexes:

- contribution and claim-to-evidence matrix;
- dataset datasheet and recording manifest;
- experiment manifest and result schema;
- baseline and ablation matrix;
- metric definitions and statistical reporting rules;
- figure manifest with source-data and generation-command fields;
- reproducibility checklist;
- known limitations and threats-to-validity register;
- paper-writing index mapping methods, experiments, figures, and tables to evidence.

These are support structures, not empty claims. The README links them and summarizes
their current completion state.

## 8. Architecture Presentation

The tutorials explicitly show two cooperating but independent runtime boundaries.

### Packaged Python VLA application

```text
Lumos camera
  -> ArUco / YOLO perception
  -> deterministic state machine
  -> local safety checks
  -> robot and gripper adapters

optional VLA -> recommendation ------^
optional voice -> intent candidate --^
FastAPI console :8000 -> status/operator commands
```

The VLA and voice paths cannot bypass state-machine or safety validation.

### Startouch Web control stack

```text
Browser :3000
  -> Node proxy
     -> Startouch Python bridge -> SDK -> can0 -> Lumos Touch R1
     -> D435 bridge -> MJPEG / guarded detections
     -> online dual-camera vision -> read-only safety status

Lumos RGB HTTP :3001 -> snapshot / MJPEG
Voice bridge -> candidate / preview / explicit confirmation
Fixed A/B demo :8766 -> separate process and CAN ownership lock
```

The diagrams must show control authority separately from observational data flow.

## 9. Core Knowledge Chains

The tutorial ties implementation details to five end-to-end knowledge chains:

1. **Robotics:** joint angles → kinematics → end-effector pose → bounds and speed → CAN motion.
2. **Vision geometry:** fisheye and RGB-D cameras → time alignment → depth registration → base-frame SE(3).
3. **Instance perception:** segmentation → appearance descriptor → tracking → object memory → reacquisition.
4. **VLA and voice:** image/audio/text → recommendation or candidate → preview → human confirmation → local validation.
5. **Safety:** freshness + calibration + identity + pose confidence + resource ownership → fail closed.

## 10. Feature Maturity Model

Every substantial capability receives one of four explicit labels:

- **Implemented:** code and public interface exist.
- **Verified:** supported by automated or documented hardware acceptance evidence.
- **Experimental:** runnable but constrained by unresolved gates or incomplete validation.
- **Planned:** represented by research or design documents, not a supported runtime feature.

Labels are based on repository evidence, not aspirational language. In particular,
online dual-camera perception may be observable while vision-triggered robot execution
remains disabled by `robot_execution_enabled: false` until calibration and task-model
acceptance gates pass.

## 11. Reference Tables and Appendices

The complete tutorials include synchronized Chinese and English versions of:

- hardware and software prerequisites;
- curated repository directory tree;
- module responsibility and interface table;
- service ports and bind-address table;
- configuration file index;
- important environment-variable index;
- command quick reference;
- API and WebSocket link index;
- model asset and runtime-artifact policy;
- test and verification command matrix;
- glossary;
- research, architecture, setup, API, safety, and contribution document index.
- research-track, experiment, metric, figure, and claim-to-evidence indexes.

Commands and defaults must be extracted from current code/configuration. Volatile evidence
such as historical test counts or deployment timestamps is linked to result documents rather
than presented as timeless fact unless clearly dated.

## 12. Troubleshooting Pattern

Troubleshooting entries use a consistent structure:

1. observable symptom;
2. likely causes and safe diagnostic checks;
3. required stop/degrade/continue decision;
4. recovery steps;
5. evidence that confirms recovery.

Minimum covered categories are CAN/interface ownership, stale CAN receive data, Lumos/D435
role loss, timestamp skew, invalid calibration/depth, ambiguous identity, port conflicts,
WebSocket/voice-bridge failure, missing model assets, GPU capacity, and latency-limit failure.

## 13. Documentation Quality and Safety Constraints

- Do not include credentials, machine-specific tokens, private paths, logs, PID files, or model weights.
- Do not claim unsupported autonomy or validated grasp execution.
- Do not describe the hardware emergency stop as replaceable by software controls.
- Use relative repository links and commands that work from the documented working directory.
- Mark Linux/Ubuntu, GPU, camera, CAN, or shell-specific requirements explicitly.
- Keep Chinese and English headings, tables, diagrams, links, commands, and status labels aligned.
- Prefer concise explanations in `README.md`; place full teaching material in the language files.
- Link detailed research evidence instead of duplicating long research reports.
- Separate measured results, dated deployment evidence, hypotheses, and future work.
- Never use a visual placeholder or expected threshold as evidence of achieved performance.
- Describe dataset licensing, consent/privacy, leakage prevention, and train/validation/test
  separation before presenting quantitative results.
- Include failure cases and threats to validity alongside positive qualitative previews.

## 14. Acceptance Criteria

The README redesign is complete when:

1. all three README files render correctly on GitHub;
2. all internal links and documented paths resolve;
3. the clone URL and service defaults match the target repository and current configuration;
4. the two runtime boundaries and five knowledge chains are unambiguous;
5. major modules, configs, scripts, services, tests, and research documents are discoverable;
6. all real-hardware commands carry the appropriate prerequisites and warnings;
7. maturity labels match repository evidence;
8. Chinese and English documents have aligned structure and technical meaning;
9. Markdown lint/link checks and the repository's relevant verification commands pass;
10. no local artifacts, secrets, or unverified capability claims are introduced.
11. the vision-primary, VLA-secondary, and optional integrated research tracks are explicit;
12. every displayed scientific result is traceable to machine-readable data and a manifest;
13. planned previews are clearly distinguishable from measured evidence;
14. the documentation provides reusable experiment, metric, figure, and reproducibility
    structures sufficient to support later SCI writing without retroactive data reconstruction.
