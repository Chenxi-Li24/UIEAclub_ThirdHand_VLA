# Baseline and Ablation Matrix

Freeze dataset split, calibration version, hardware class, reporting aggregation,
and seeds before comparing a row. Comparison rows start as `Planned Evidence` until
any result exists.

`Planned Evidence / 待补实验证据` means no result exists. If partial comparison
results exist but sample count, confidence interval, statistical method, or source
evidence is absent, empty, inadequate, or untraceable, label them `Evidence
Incomplete / 待补充证据` instead. The two statuses are not interchangeable, and neither
may support a claim, abstract conclusion, or deterministic figure/table conclusion.

## Detection and segmentation baselines

| Family | Exact baseline | Fixed comparison conditions | Primary measures | Status |
| --- | --- | --- | --- | --- |
| detection/segmentation | YOLOv8n detect | Same class taxonomy, input resolution, held-out split, and latency measurement envelope. | Per-class box AP/recall, empty-scene FP, radial bins, P50/P95 latency, memory. | Planned Evidence |
| detection/segmentation | YOLO nano segmentation | Same class taxonomy, input resolution, held-out split, and latency measurement envelope. | Per-class mask AP/recall, mask coverage, point-cloud purity, radial bins, P50/P95 latency. | Planned Evidence |
| detection/segmentation | RTMDet-tiny-ins | Same class taxonomy, input resolution, held-out split, and latency measurement envelope. | Per-class mask AP/recall, mask coverage, point-cloud purity, radial bins, P50/P95 latency. | Planned Evidence |
| detection/segmentation | Mask R-CNN R50-FPN | Same class taxonomy, input resolution, held-out split, and latency measurement envelope. | Per-class mask AP/recall, mask coverage, point-cloud purity, radial bins, P50/P95 latency. | Planned Evidence |

## Identity baselines and ablations

| Family | Exact baseline or ablation | Fixed comparison conditions | Primary measures | Status |
| --- | --- | --- | --- | --- |
| identity | IoU-only tracker | Same detections, clip boundaries, association threshold-selection protocol, and held-out occlusion subset. | HOTA, IDF1, ID switches, fragmentation, reacquisition, false merges. | Planned Evidence |
| identity | appearance-only | Same detections, descriptor model, clip boundaries, and held-out occlusion subset. | HOTA, IDF1, ID switches, fragmentation, reacquisition, false merges. | Planned Evidence |
| identity | appearance+3D gate | Same detections, descriptor model, 3D registration/calibration version, and held-out occlusion subset. | HOTA, IDF1, ID switches, fragmentation, reacquisition, false merges. | Planned Evidence |
| identity | work bank only | Same association policy; disable stable long-term memory. | HOTA, IDF1, revisit reacquisition, false merges, resource use. | Planned Evidence |
| identity | work+stable memory | Same association policy; enable stable long-term memory. | HOTA, IDF1, revisit reacquisition, false merges, resource use. | Planned Evidence |
| identity | ambiguity rejection on/off | Same candidate association scores; compare reject policy enabled versus disabled. | False merges, accepted/rejected association rate, downstream safe-candidate rate. | Planned Evidence |

## VLA baselines and ablations

| Family | Exact baseline or ablation | Safety boundary | Primary measures | Status |
| --- | --- | --- | --- | --- |
| VLA | free-form direct output (offline unsafe baseline only) | Offline evaluation only; no actuator call, CAN command, or robot authority. | Task/intent accuracy, unsupported-action rate, unsafe-action interception opportunity, refusal quality, latency. | Planned Evidence |
| VLA | structured candidate | Candidate is logged and checked offline; no direct actuator authority. | Task/intent accuracy, schema validity, unsupported-action rate, latency. | Planned Evidence |
| VLA | candidate+preview | Candidate and local preview are logged; no direct actuator authority. | Preview-detected issue rate, correction rate, task/intent accuracy, latency. | Planned Evidence |
| VLA | candidate+preview+human confirmation+local safety validation | Explicit human confirmation and deterministic local safety validation precede any supervised platform consideration. | Unsafe-action interception, refusal quality, correction rate, recovery success, latency. | Planned Evidence |

## Required ablation record

| Field | Required value |
| --- | --- |
| Hypothesis and variant delta | State exactly one changed component or policy and the expected direction of change. |
| Controls | Dataset/split SHA-256, calibration ID, model hashes, command, environment, hardware, seed list, and evaluation window. |
| Statistics | Sample count, aggregation, confidence interval method/level, and per-slice reporting. |
| Safety | Dry Run/offline status, rejected-input handling, and statement that robot control is an experimental platform rather than the contribution. |
| Evidence links | Experiment manifests, result records, source CSV/JSON, and generated figure/table command. |
