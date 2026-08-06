# Figure Manifest

Every entry below is `Planned Evidence`. It defines a future generated artifact,
not a measured result. A figure can be released only after its source data,
experiment manifest(s), and generation command are all linked and reproducible.

`Planned Evidence / 待补实验证据` means no result exists; every registry entry below
has this status. `Evidence Incomplete / 待补充证据` is reserved for a partial result
whose sample count, confidence interval, statistical method, or source evidence is
absent, empty, inadequate, or untraceable. The labels are not interchangeable, and
neither status may support a claim, abstract conclusion, or deterministic conclusion
in a figure or table.

A missing preregistration protocol, threshold, or statistical-analysis plan is a
separate readiness gap. It does not change a figure with no measurements from
`Planned Evidence / 待补实验证据` to `Evidence Incomplete / 待补充证据`.

| ID | Intended content | Status | Required source data | Required generation command | Release gate |
| --- | --- | --- | --- | --- | --- |
| V1 | Lumos instance mask, D435 depth, and robot-base 3D result. | Planned Evidence | Timestamped Lumos RGB, D435 depth, calibration ID/hash, instance masks, registered 3D points, experiment manifest. | Versioned script/command that joins frames by manifest, applies the recorded calibration, and renders the selected samples. | Source manifest and command reproduce the panel without manual image editing. |
| V2 | Identity before occlusion, during occlusion, and after reacquisition. | Planned Evidence | Ordered replay frames, detections/masks, track IDs, association scores, memory state, occlusion annotations, experiment manifest. | Versioned script/command that selects declared clips and renders the three states from result records. | Clip split is held out and identity labels/selection rule are recorded. |
| V3 | Depth-registration error, radial calibration residuals, and uncertainty view. | Planned Evidence | Calibration targets, correspondence/residual records, radial-bin metadata, registration errors, covariance/uncertainty records, manifest. | Versioned script/command that aggregates source JSON/CSV into residual, error, and uncertainty panels. | Units, aggregation, calibration ID, and excluded samples are reported. |
| L1 | VLA instruction, visual context, candidate, preview, confirmation, and refusal reason. | Planned Evidence | De-identified scenario input, visual-context reference, structured candidate, preview output, confirmation event, validator/refusal log, manifest. | Versioned script/command that renders the complete auditable decision trace from logs. | No secret, personal, or misleading actuator-success claim appears in the trace. |
| E1 | Baseline comparison and confidence intervals. | Planned Evidence | Result records for all preregistered baselines, sample counts, intervals, slices, source CSV/JSON, manifests. | Versioned script/command that reads result records and computes/plots declared aggregate and confidence intervals. | Baselines, split, interval method, and exclusions match the matrix. |
| E2 | Ablation table/curve. | Planned Evidence | Controlled-variant result records, variant configuration, seeds, slices, source CSV/JSON, manifests. | Versioned script/command that groups variants and produces the declared table or curve. | One-delta ablation rule and all controls are documented. |
| E3 | Accuracy-latency-resource trade-off. | Planned Evidence | Accuracy, P50/P95 latency, FPS, CPU/GPU/VRAM records, hardware/environment manifests, source CSV/JSON. | Versioned script/command that joins metrics by experiment ID and renders trade-off points/error bars. | Hardware, batch/input settings, and aggregation window are comparable. |
| F1 | Representative success and failure cases. | Planned Evidence | Declared case-selection rule, scenario/clip IDs, input/output traces, failure taxonomy, manifests. | Versioned script/command that applies the selection rule and renders paired success/failure cases. | Selection is not cherry-picked; limitations and refusal/failure context are visible. |

## Source-data conventions

- Source data must be machine-readable JSON/CSV conforming to the
  [experiment manifest](schemas/experiment-manifest.schema.json) and
  [result record](schemas/result-record.schema.json) contracts where applicable.
- A generation command must include the script version or Git commit, input paths
  relative to the repository/artifact store, and all filters/seeds needed to recreate
  the output.
- Keep generated outputs separate from templates. Do not substitute illustrative
  screenshots, invented metrics, or handwritten conclusions for source evidence.
