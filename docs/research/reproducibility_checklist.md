# Reproducibility Checklist

Use this checklist for every reported experiment and figure. Check a box only when
the referenced artifact exists and can be independently located; otherwise retain
the item as incomplete and label the claim `Planned Evidence`.

## Run identity and environment

- [ ] Experiment ID, hypothesis ID, research track, schema version, and UTC start time are recorded.
- [ ] A 40-character Git commit and the exact command array are recorded in a valid experiment manifest.
- [ ] Python version, operating system, hardware, driver/runtime details, and dependency-lock SHA-256 are recorded.
- [ ] Model identifiers, weights/checksums, configuration files, and calibration ID are recorded.
- [ ] Seeds, deterministic settings, and any non-deterministic operations are recorded.

## Data and protocol

- [ ] Dataset manifest, SHA-256, split, scene/instance allocation, and leakage-prevention rule are frozen before evaluation.
- [ ] Capture hardware, logical camera roles, timestamp/skew policy, calibration validation, annotation policy, privacy/consent, and licensing are completed in the datasheet.
- [ ] Held-out, replay, live, and synthetic data are distinguished; no result silently combines them.
- [ ] Inclusion/exclusion criteria, failure taxonomy, stop conditions, and missing-data policy are documented.
- [ ] Robot control remains a supervised experimental platform: offline/Dry Run evidence is distinguished from any approved hardware observation.

## Comparison and statistics

- [ ] The applicable exact baseline family and ablation delta are selected from the [baseline matrix](baseline_ablation_matrix.md).
- [ ] All compared runs share the stated split, calibration, hardware class, measurement window, and reporting definition, or differences are explicitly stratified.
- [ ] Every metric record has unit, aggregation, sample count, slice, source artifact, and null-or-defined confidence interval.
- [ ] Confidence level/method, statistical test where used, outlier policy, and multiple-comparison handling are recorded.
- [ ] Negative results, uncertainty, threats to validity, and deviations from the protocol are retained in the [claim matrix](claim_evidence_matrix.md).

## Artifact release and review

- [ ] Manifests validate against [experiment-manifest.schema.json](schemas/experiment-manifest.schema.json); results validate against [result-record.schema.json](schemas/result-record.schema.json).
- [ ] JSON/CSV source data, checksums, model/config/calibration references, and artifact retention location are available to reviewers under the stated access terms.
- [ ] Each figure/table follows [the figure manifest](figure_manifest.md), has its source-data links and generation command, and is regenerated from machine-readable results.
- [ ] A reviewer can start from the command and manifest, reproduce the reported aggregation, and explain any expected numerical drift.
- [ ] Privacy, licensing, consent, safety, and disclosure review are complete before external release.
