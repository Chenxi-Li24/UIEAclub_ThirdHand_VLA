# ThirdHand Research Evidence Hub

This directory is the evidence contract for future SCI work. It organizes
falsifiable hypotheses, recorded datasets, machine-readable results, and figures
generated from those results. It does not turn planned experiments into claims.
Robot control is an experimental platform and supervised safety boundary rather
than the main research contribution.

## Evidence contract

Each claim is traceable through a hypothesis, protocol, dataset split, baseline,
experiment manifest, result records, and generated figure or table. Record every
run with the [experiment manifest schema](schemas/experiment-manifest.schema.json)
and every reported measurement with the
[result record schema](schemas/result-record.schema.json). Populate the linked
templates before a result is cited:

- [Claim-to-evidence matrix](claim_evidence_matrix.md)
- [Dataset datasheet](dataset_datasheet.md)
- [Baseline and ablation matrix](baseline_ablation_matrix.md)
- [Figure manifest](figure_manifest.md)
- [Reproducibility checklist](reproducibility_checklist.md)

The benchmark metrics and acceptance gates originate in
[the existing benchmark and acceptance plan](../vision_research/13_BENCHMARK_AND_ACCEPTANCE_PLAN.md).
Machine-readable JSON/CSV is the source of record; figures and tables are
generated from it, never hand-filled.

## Evidence-status rule / 证据状态规则

Use exactly one evidence status for each claim, result, table, or figure:

- `Planned Evidence / 待补实验证据` means that no result exists yet. It may describe
  a future protocol or artifact requirement, but cannot imply an observed outcome.
- `Evidence Incomplete / 待补充证据` means that partial results exist, but
  `sample_count`, `confidence_interval`, statistical method, or source evidence is
  absent, empty, inadequate, or not traceable. Such material must not support a
  claim, abstract conclusion, or deterministic conclusion in a figure or table.

These states are not interchangeable. A result is not reportable evidence until its
status is neither of the above and its linked manifest, source artifact, sample count,
confidence interval (or explicit justified null), and statistical method are complete.

## Track A — Vision and 3D perception (primary)

| Evidence item | Definition |
| --- | --- |
| Scope | Lumos fisheye RGB as canonical appearance input; D435 metric depth; timestamp, calibration, uncertainty, cross-camera registration, instance segmentation, masked 3D estimation, tracking, persistent identity memory, occlusion/reacquisition, and ambiguity rejection. |
| Candidate contribution | A confidence-aware dual-camera perception and persistent-identity pipeline that carries calibrated visual evidence into actionability decisions. |
| Required evidence | Held-out/replay protocols, calibration and data checksums, run manifests, repeated seeds, detector/identity ablations, uncertainty-aware failures, and generated results. |
| Metrics | Per-class box/mask AP and recall, radial performance, registration P50/P95 and planar mm error, mask coverage/flying-edge rate, 3D error/jitter, HOTA, IDF1, ID switches, fragmentation, reacquisition, false merges, latency, throughput, CPU/GPU/VRAM. |
| Current repository evidence | Design, benchmark definitions, offline unit/replay work, and deployment notes exist; they are not a completed comparative study. |
| Missing gates | Versioned recorded dataset and datasheet, fixed held-out protocol, baseline runs, repeated measurements with intervals, figure generation, and validity review. |
| Templates | [claims](claim_evidence_matrix.md), [dataset](dataset_datasheet.md), [baselines](baseline_ablation_matrix.md), [figures](figure_manifest.md), [reproducibility](reproducibility_checklist.md). |

## Track B — Verifiable VLA decision-making (secondary)

| Evidence item | Definition |
| --- | --- |
| Scope | Grounded multimodal task understanding; structured intent/action candidates; local preview, human confirmation, deterministic validation, refusal, timeout, recovery, and persistent visual state as context. |
| Candidate contribution | Constraining VLA output to an auditable candidate-and-validation interface that can refuse unsupported or unsafe requests before robot authority is considered. |
| Required evidence | Offline task scenarios, unsafe and ambiguous inputs, human-correction protocol, candidate/preview/confirmation logs, validation decisions, and failure/recovery records. |
| Metrics | Task and intent accuracy, unsafe-action interception, human correction rate, unsupported-action rate, calibrated refusal quality, recovery success, and end-to-end latency. |
| Current repository evidence | Interfaces and safety design support candidate generation and Dry Run evaluation; no completed VLA comparison is represented as a result. |
| Missing gates | Frozen scenario set, offline unsafe baseline isolation, registered human-evaluation protocol where applicable, comparative runs, intervals, and generated evidence. |
| Templates | [claims](claim_evidence_matrix.md), [baselines](baseline_ablation_matrix.md), [figures](figure_manifest.md), [reproducibility](reproducibility_checklist.md). |

## Track C — Integrated vision–VLA system (optional / 可选综合路线)

| Evidence item | Definition |
| --- | --- |
| Scope | Persistent object memory as VLA context, perception-uncertainty propagation, long-horizon task completion, closed-loop verification, and failure recovery. |
| Candidate contribution | An integrated evidence-to-decision loop showing when calibrated visual uncertainty changes a grounded candidate, preview, refusal, or recovery outcome. |
| Required evidence | Joined perception and decision manifests, scenario-level traces, actionability/refusal evidence, end-to-end baselines and ablations, and supervised safety records. |
| Metrics | Long-horizon completion, grounded-reference accuracy, uncertainty-conditioned unsafe-action interception, closed-loop recovery success, correction rate, and end-to-end latency/resource use. |
| Current repository evidence | The architecture specifies the integration boundary and supervised robot platform; it does not establish an integrated-paper result. |
| Missing gates | Track A and B evidence gates, synchronized scenario corpus, end-to-end protocol, confound analysis, and generated comparative figures. |
| Templates | [claims](claim_evidence_matrix.md), [dataset](dataset_datasheet.md), [baselines](baseline_ablation_matrix.md), [figures](figure_manifest.md), [reproducibility](reproducibility_checklist.md). |

## Reporting rule

Use `Planned Evidence / 待补实验证据` only for an item with no result. Use
`Evidence Incomplete / 待补充证据` for a partial result whose sample count,
confidence interval, statistical method, or source evidence is missing, empty,
inadequate, or untraceable; never use either status to support a claim, abstract
conclusion, or deterministic figure/table conclusion. A claim may move to reported
evidence only when its matrix row references the dataset checksum, experiment IDs,
source artifacts, sample count, confidence interval or justified null, statistical
method, and generated figure/table.
