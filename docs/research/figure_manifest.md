# Figure Manifest

Every entry below is `Planned Evidence`. It defines a future generated artifact,
not a measured result. A figure can be released only after its source data,
experiment manifest(s), and generation command are all linked and reproducible.
This is the canonical preview registry: the README tables preserve each row's intended
content, status, source-data requirement, generation-command requirement, and release gate.
Each non-status field carries one exact machine-readable `<code>` contract key; translated
README rows duplicate those keys verbatim while retaining their natural-language descriptions.

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
| V1 | Lumos instance mask, D435 depth, and robot-base 3D view. <code>content:v1:mask-depth-base3d</code> | Planned Evidence | Timestamped Lumos RGB, D435 depth, calibration ID/hash, instance masks, registered 3D points, experiment manifest. <code>source:v1:rgb-depth-calibration-mask-points</code> | Versioned script/command that joins frames by manifest, applies the recorded calibration, and renders the selected samples. <code>generator:v1:manifest-calibrated-panel</code> | Source manifest and command reproduce the panel without manual image editing. <code>gate:v1:reproducible-no-manual-edit</code> |
| V2 | Identity before occlusion, during occlusion, and after reacquisition. <code>content:v2:occlusion-reacquisition-identity</code> | Planned Evidence | Ordered replay frames, detections/masks, track IDs, association scores, memory state, occlusion annotations, experiment manifest. <code>source:v2:replay-tracks-memory-annotations</code> | Versioned script/command that selects declared clips and renders the three states from result records. <code>generator:v2:declared-clips-three-states</code> | Clip split is held out and identity labels/selection rule are recorded. <code>gate:v2:heldout-identity-selection</code> |
| V3 | Depth-registration error, radial calibration residuals, and uncertainty view. <code>content:v3:registration-residual-uncertainty</code> | Planned Evidence | Calibration targets, correspondence/residual records, radial-bin metadata, registration errors, covariance/uncertainty records, manifest. <code>source:v3:calibration-correspondence-covariance</code> | Versioned script/command that aggregates source JSON/CSV into residual, error, and uncertainty panels. <code>generator:v3:aggregate-residual-error-uncertainty</code> | Units, aggregation, calibration ID, and excluded samples are reported. <code>gate:v3:units-aggregation-calibration-exclusions</code> |
| L1 | VLA instruction, visual context, candidate, preview, confirmation, and refusal reason. <code>content:l1:instruction-candidate-preview-refusal</code> | Planned Evidence | De-identified scenario input, visual-context reference, structured candidate, preview output, confirmation event, validator/refusal log, manifest. <code>source:l1:scenario-context-candidate-validator-log</code> | Versioned script/command that renders the complete auditable decision trace from logs. <code>generator:l1:auditable-decision-trace</code> | No secret, personal, or misleading actuator-success claim appears in the trace. <code>gate:l1:no-secrets-or-actuator-success-claim</code> |
| E1 | Baseline comparison and confidence intervals. <code>content:e1:baseline-confidence-intervals</code> | Planned Evidence | Result records for all preregistered baselines, sample counts, intervals, slices, source CSV/JSON, manifests. <code>source:e1:preregistered-results-intervals-slices</code> | Versioned script/command that reads result records and computes/plots declared aggregate and confidence intervals. <code>generator:e1:aggregate-confidence-interval-plot</code> | Baselines, split, interval method, and exclusions match the matrix. <code>gate:e1:baseline-split-interval-exclusions</code> |
| E2 | Ablation table/curve. <code>content:e2:ablation-table-curve</code> | Planned Evidence | Controlled-variant result records, variant configuration, seeds, slices, source CSV/JSON, manifests. <code>source:e2:controlled-variants-seeds-results</code> | Versioned script/command that groups variants and produces the declared table or curve. <code>generator:e2:grouped-variant-table-curve</code> | One-delta ablation rule and all controls are documented. <code>gate:e2:one-delta-controls</code> |
| E3 | Accuracy-latency-resource trade-off. <code>content:e3:accuracy-latency-resource</code> | Planned Evidence | Accuracy, P50/P95 latency, FPS, CPU/GPU/VRAM records, hardware/environment manifests, source CSV/JSON. <code>source:e3:metrics-environment-manifest</code> | Versioned script/command that joins metrics by experiment ID and renders trade-off points/error bars. <code>generator:e3:experiment-metric-tradeoff</code> | Hardware, batch/input settings, and aggregation window are comparable. <code>gate:e3:comparable-hardware-window</code> |
| F1 | Representative success and failure cases. <code>content:f1:representative-success-failure</code> | Planned Evidence | Declared case-selection rule, scenario/clip IDs, input/output traces, failure taxonomy, manifests. <code>source:f1:selection-traces-failure-taxonomy</code> | Versioned script/command that applies the selection rule and renders paired success/failure cases. <code>generator:f1:selection-rule-paired-cases</code> | Selection is not cherry-picked; limitations and refusal/failure context are visible. <code>gate:f1:no-cherry-pick-limitations-visible</code> |

## Source-data conventions

- Source data must be machine-readable JSON/CSV conforming to the
  [experiment manifest](schemas/experiment-manifest.schema.json) and
  [result record](schemas/result-record.schema.json) contracts where applicable.
- A generation command must include the script version or Git commit, input paths
  relative to the repository/artifact store, and all filters/seeds needed to recreate
  the output.
- Keep generated outputs separate from templates. Do not substitute illustrative
  screenshots, invented metrics, or handwritten conclusions for source evidence.
