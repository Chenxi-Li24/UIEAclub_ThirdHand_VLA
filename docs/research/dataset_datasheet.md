# Dataset Datasheet

Complete one versioned datasheet per recording corpus. The L1 replay dataset is
read-only Lumos RGB, D435 depth/RGB, camera metadata, and robot pose; small,
de-identified CI fixtures are distinct from the complete local corpus.

## Dataset identity and capture

| Field | Required record |
| --- | --- |
| Dataset name and version | Immutable name, semantic version, owner, creation date, and manifest path. |
| Purpose and research tracks | Intended Track A/B/C questions, exclusions, and whether material is training, validation, test, replay, or live. |
| Capture hardware | Lumos Ego RGB/fisheye unit and serial/firmware where available; Intel RealSense D435 RGB-D unit and serial/firmware; host, GPU, and mounting configuration. |
| Logical camera roles | Lumos is canonical appearance/segmentation input; D435 supplies metric depth/RGB registration; document any deviation. |
| Timestamps | Clock source, units, frame timestamp fields, synchronization procedure, observed skew distribution, stale-frame cutoff, and timezone. |
| Calibration | Intrinsics/distortion, extrinsics/frame convention, calibration ID, calibration artifact hash, date, operator, validation residuals, and invalidation criteria. |
| Scenes | Site, lighting, backgrounds, camera/arm placement, scene identifiers, and controlled changes. |
| Object categories | Class taxonomy, instance identifiers, material/color/reflectivity attributes, transparent/black/reflective cases, and class counts. |

## Annotation and partitioning

| Field | Required record |
| --- | --- |
| Annotation policy | Label definitions, boxes/masks/keypoints/identity/occlusion/3D labels, annotation tool/version, annotator guidance, review procedure, and disagreement resolution. |
| Quality assurance | Inter-annotator sample, audit rate, invalid-label rules, correction log, and label version. |
| Splits | Exact train/validation/test/replay/live allocation, split manifest path and SHA-256, counts by scene/category/instance, and frozen test policy. |
| Leakage prevention | Split by recording session, scene, physical object identity, and temporal clip as appropriate; prevent near-duplicate frames and calibration captures from crossing evaluation boundaries. |
| Scenario coverage | Center/edge placement, partial occlusion, class confusion, reflective/transparent/black objects, target exit/re-entry, stale/missing frames, and calibration faults. |

## Governance, integrity, and limitations

| Field | Required record |
| --- | --- |
| Privacy | Whether people, voices, screens, names, or location identifiers occur; minimization/de-identification process; access controls; residual-risk assessment. |
| Consent | Participant notice/consent basis, collection authority, withdrawal contact/process, and records location; state `not applicable` with rationale if no human data exist. |
| Licensing | Dataset license, third-party asset/model terms, redistribution limits, attribution/NOTICE requirements, and license-review date. |
| Checksums | SHA-256 for the dataset manifest, each released archive, calibration artifacts, and annotation export; verification command and expected digest file. |
| Known biases | Class/scene/lighting imbalance, hardware-specific effects, annotation subjectivity, geographic/site restriction, simulation-to-real gap, and excluded failures. |
| Retention | Storage location class, access owner, retention period, deletion/review trigger, backup policy, and handling of superseded versions. |

## Release record

| Field | Value |
| --- | --- |
| Current status | Planned Evidence — no dataset release or quantitative corpus claim is made by this template. |
| Manifest schema | [Experiment manifest](schemas/experiment-manifest.schema.json) links each run to this datasheet version and split checksum. |
| Result linkage | [Result records](schemas/result-record.schema.json) identify the source artifact for every published aggregate. |
