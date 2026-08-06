# Bilingual Tutorial README Design

**Date:** 2026-08-06

**Status:** Approved design

**Audience:** Developers and researchers

**Languages:** Complete Chinese and English documentation

## 1. Objective

Replace the current short repository overview with a bilingual, tutorial-style
documentation set that explains the complete ThirdHand VLA project from first
principles through implementation, deployment, verification, and extension.

The documentation must let a new developer answer five questions without first
reading the implementation:

1. What problem does the project solve, and which hardware and services does it use?
2. Which robotics, perception, VLA, interaction, and safety concepts are involved?
3. How do those concepts map to concrete modules, interfaces, configuration, and data flow?
4. What can be run offline, in simulation, read-only on hardware, or with supervised motion?
5. Which features are implemented, verified, experimental, or only planned?

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

The text must distinguish the packaged perception baseline from the newer
`web-control/server/vision` and `vision_models` pipelines.

### Part 4 — VLA, Voice, and Human Interaction

- optional cloud VLA reasoning and local validation boundary;
- ASR, NLU, TTS, text input, and voice-bridge protocol;
- intent candidates, local preview, human confirmation, and command authorization;
- why model output is a recommendation rather than direct robot authority;
- offline mocks, network failure, and privacy/runtime considerations.

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

## 4. Architecture Presentation

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

## 5. Core Knowledge Chains

The tutorial ties implementation details to five end-to-end knowledge chains:

1. **Robotics:** joint angles → kinematics → end-effector pose → bounds and speed → CAN motion.
2. **Vision geometry:** fisheye and RGB-D cameras → time alignment → depth registration → base-frame SE(3).
3. **Instance perception:** segmentation → appearance descriptor → tracking → object memory → reacquisition.
4. **VLA and voice:** image/audio/text → recommendation or candidate → preview → human confirmation → local validation.
5. **Safety:** freshness + calibration + identity + pose confidence + resource ownership → fail closed.

## 6. Feature Maturity Model

Every substantial capability receives one of four explicit labels:

- **Implemented:** code and public interface exist.
- **Verified:** supported by automated or documented hardware acceptance evidence.
- **Experimental:** runnable but constrained by unresolved gates or incomplete validation.
- **Planned:** represented by research or design documents, not a supported runtime feature.

Labels are based on repository evidence, not aspirational language. In particular,
online dual-camera perception may be observable while vision-triggered robot execution
remains disabled by `robot_execution_enabled: false` until calibration and task-model
acceptance gates pass.

## 7. Reference Tables and Appendices

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

Commands and defaults must be extracted from current code/configuration. Volatile evidence
such as historical test counts or deployment timestamps is linked to result documents rather
than presented as timeless fact unless clearly dated.

## 8. Troubleshooting Pattern

Troubleshooting entries use a consistent structure:

1. observable symptom;
2. likely causes and safe diagnostic checks;
3. required stop/degrade/continue decision;
4. recovery steps;
5. evidence that confirms recovery.

Minimum covered categories are CAN/interface ownership, stale CAN receive data, Lumos/D435
role loss, timestamp skew, invalid calibration/depth, ambiguous identity, port conflicts,
WebSocket/voice-bridge failure, missing model assets, GPU capacity, and latency-limit failure.

## 9. Documentation Quality and Safety Constraints

- Do not include credentials, machine-specific tokens, private paths, logs, PID files, or model weights.
- Do not claim unsupported autonomy or validated grasp execution.
- Do not describe the hardware emergency stop as replaceable by software controls.
- Use relative repository links and commands that work from the documented working directory.
- Mark Linux/Ubuntu, GPU, camera, CAN, or shell-specific requirements explicitly.
- Keep Chinese and English headings, tables, diagrams, links, commands, and status labels aligned.
- Prefer concise explanations in `README.md`; place full teaching material in the language files.
- Link detailed research evidence instead of duplicating long research reports.

## 10. Acceptance Criteria

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
