# Claim-to-Evidence Matrix

One row represents one falsifiable claim. Populate all columns before presenting a
claim as a result; retain a row for a failed hypothesis and record its threats to
validity rather than deleting it. `Planned Evidence / 待补实验证据` means no result
exists. `Evidence Incomplete / 待补充证据` means partial results exist but the sample
count, confidence interval, statistical method, or source evidence is absent, empty,
inadequate, or untraceable. The two labels are not interchangeable, and neither may
support a claim, abstract conclusion, or deterministic figure/table conclusion.

The rows below are illustrative candidate claims, not measured outcomes. Each
`Metric and threshold` entry must name an exact threshold and protocol artifact/path
from a preregistration before a run begins. `Preregistration readiness / 预注册准备状态`
records whether that protocol, threshold, and analysis plan are complete. It is not
an evidence status: a missing protocol/threshold does not make an unmeasured example
`Evidence Incomplete / 待补充证据`. These examples have no results and therefore
remain `Planned Evidence / 待补实验证据`; do not infer a threshold from a benchmark
reference or use a row as a result.

| Claim ID | Track | Falsifiable hypothesis | Method/config | Dataset/split | Baselines | Metric and threshold | Preregistration readiness / 预注册准备状态 | Experiment IDs | Figures/tables | Status | Threats to validity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A-REG-01 | A | Timestamp-aware Lumos-to-D435 registration reduces held-out alignment error relative to an unaligned or stale-pair control. | Versioned calibration, skew gate, z-buffer registration; record calibration ID. | L1 replay, held-out scenes and radial bins. | No registration; registration without timestamp gate. | Exact P95 pixel and planar-mm threshold required from preregistration protocol artifact/path; not yet supplied. | Incomplete / 待补：exact threshold and statistical-analysis plan in preregistration protocol artifact/path. | Planned: manifest IDs required. | E1, E2, V3; generated only. | Planned Evidence / 待补实验证据 | Calibration drift, scene geometry, depth holes, and correlation among replay clips. |
| A-ID-01 | A | Persistent appearance-plus-3D identity memory improves occlusion reacquisition without exceeding the false-merge gate. | Fixed detector, descriptor, association gates, ambiguity rejection policy, and seeds. | L1 replay, object revisits and occlusion subset held out by scene. | IoU-only tracker; appearance-only; work bank only. | Exact HOTA, IDF1, reacquisition, and false-merge thresholds required from preregistration protocol artifact/path; not yet supplied. | Incomplete / 待补：exact thresholds and statistical-analysis plan in preregistration protocol artifact/path. | Planned: manifest IDs required. | E1, E2, V2; generated only. | Planned Evidence / 待补实验证据 | Detector changes, same-object leakage, annotation ambiguity, and unrepresentative occlusions. |
| B-SAFE-01 | B | Candidate+preview+human confirmation+local safety validation intercepts more unsafe requests than less constrained candidates. | Offline VLA output, structured schema, preview, explicit confirmation, deterministic validator. | Offline scenario test split with unsafe, unsupported, and ambiguous requests. | Free-form direct output offline unsafe baseline only; structured candidate; candidate+preview. | Exact unsafe-interception, refusal-quality, accuracy, and latency thresholds required from preregistration protocol artifact/path; not yet supplied. | Incomplete / 待补：exact thresholds and statistical-analysis plan in preregistration protocol artifact/path. | Planned: manifest IDs required. | E1, E2, L1; generated only. | Planned Evidence / 待补实验证据 | Prompt/model drift, evaluator bias, scenario coverage, and simulated-versus-hardware gap. |
| C-LOOP-01 | C | Propagating perception uncertainty into the candidate validator improves safe recovery in long-horizon tasks. | Track A confidence fields supplied to Track B candidate/validator and recovery logic. | Joined held-out replay/scenario split. | Integrated pipeline without uncertainty propagation; Track A/B component controls. | Exact recovery, interception, completion, and P95-latency thresholds required from preregistration protocol artifact/path; not yet supplied. | Incomplete / 待补：exact thresholds and statistical-analysis plan in preregistration protocol artifact/path. | Planned: manifest IDs required. | E1, E2, E3, F1; generated only. | Planned Evidence / 待补实验证据 | Upstream error coupling, scenario selection, human intervention, and small sample sizes. |
