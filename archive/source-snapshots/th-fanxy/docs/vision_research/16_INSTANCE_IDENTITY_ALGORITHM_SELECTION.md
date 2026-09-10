# Task 1: Instance Identity and 3D Localization Algorithm Selection

Date: 2026-08-04 (Asia/Shanghai)

## 中文执行摘要

任务 1 的最终选型是 **RTMDet-tiny-ins + REMIND 长期实例记忆 + ThirdHand RGB-D/基座坐标
ObjectMemory**，本文简称 **REMIND-3D for ThirdHand**。

- RTMDet 负责类别、检测框和实例掩码；
- REMIND 使用 DINOv3-S/16（并以 DINOv2-S/14 作许可和部署备选）保存同一实物的多视角外观记忆，
  处理遮挡、离开画面、重新进入和相似物体干扰；
- D435 深度经已有的 D435-to-Lumos SEUCM 配准链路，将掩码内点云转换为机器人基座坐标，
  为身份关联和后续抓取提供带协方差的物理位置；
- 外观、三维连续性、时间戳或标定存在冲突时，不强行分配身份，而是输出 `AMBIGUOUS` 并禁止抓取。

这不是把某篇论文原样搬进工程。REMIND 原方法只有 RGB 外观关联，本项目会加入已有的三维追踪、
时间同步和安全 gate。论文和开源结果只用于确定优先路线，真正采用哪个 backbone、原始鱼眼还是
矫正视图，以及是否达到实时要求，都必须在本机 Lumos+D435 回放集上按本文门槛复测。

必须明确物理边界：若两个没有任何可见差异的同款物体在完全遮挡期间被交换，单靠视觉不可能知道
它们是否互换。系统必须拒绝猜测；若业务要求这种情况下仍保证身份，需要增加 AprilTag、UV/IR 标记
或 RFID 等持久物理特征。

## Decision

For ThirdHand, use a layered RGB-D perception stack rather than treating one model as the
complete solution:

1. **RTMDet-tiny-ins**, fine-tuned on Lumos imagery, produces a class, box, and instance mask.
2. **REMIND-style long-term identity memory**, initially using frozen DINOv3 ViT-S/16 features,
   preserves the identity of the same physical instance across occlusion, scene exit, viewpoint
   change, and re-entry.
3. **ThirdHand 3D association**, using registered D435 depth and robot-base coordinates, adds the
   spatial evidence that the RGB-only REMIND method does not have.
4. The existing **timestamp-aware tracker and ObjectMemory** remain the safety-facing state store.
   An identity is actionable only when appearance, 3D position, timing, calibration, and ambiguity
   gates agree.

This design is called **REMIND-3D for ThirdHand** in this document. It is an adaptation of published
methods, not a claim that a new trained model already exists.

The selection is final for the offline prototype and benchmark phase. It does not authorize robot
or gripper motion.

## Required Behavior

The visual system must:

- distinguish one physical object from other objects of the same category;
- retain the target identity through partial and full occlusion;
- re-identify it after it leaves the image and later returns;
- avoid silently switching to a similar object;
- return a measured 3D position in robot-base coordinates, with timestamps, calibration ID,
  covariance, freshness, and validity;
- refuse an identity or grasp candidate when evidence is ambiguous;
- run within the RTX 5060 8 GB GPU and 31 GB system-RAM limits;
- operate first in record/replay and Dry Run, without importing or commanding the arm SDK.

The hardware topology is eye-in-hand Lumos fisheye RGB plus D435 depth. The cameras have no shared
hardware trigger, so the first online version is stop-and-look only.

## Important Physical Limit

No vision algorithm can guarantee the identity of two truly indistinguishable objects if both are
fully hidden and may be exchanged while hidden. If two unmarked, geometrically identical bottles
have the same visible appearance and an unseen person swaps them, the sensor observations contain
no information that reveals the swap.

ThirdHand therefore follows this rule:

- when appearance and 3D continuity identify one instance clearly, preserve its ID;
- when two candidates remain indistinguishable, publish `AMBIGUOUS` and produce no grasp candidate;
- if guaranteed identity is required in that scenario, add a persistent physical cue such as an
  AprilTag/ArUco tag, distinct label, UV/IR mark, or RFID rather than guessing in software.

Failing closed here is part of correctness, not a tracker failure.

## Research Summary

### 1. Short-horizon tracking-by-detection

ByteTrack, DeepSORT, BoT-SORT, StrongSORT, and Deep OC-SORT are effective when detections are close
in time and object motion is continuous. Their normal assumptions do not fit a camera on a moving
arm, generic tabletop objects, or re-entry after hundreds of frames. Person/vehicle ReID networks
also do not provide reliable generic-object identity embeddings.

**Decision:** retain a lightweight motion/3D tracker for frame-to-frame continuity, but do not use
it as the persistent identity authority.

Primary references:

- ByteTrack: https://arxiv.org/abs/2110.06864
- BoT-SORT: https://arxiv.org/abs/2206.14651
- Ultralytics tracking/ReID documentation:
  https://github.com/ultralytics/ultralytics/blob/main/docs/en/modes/track.md

### 2. Video object segmentation

SAM 2.1, Cutie, XMem, SAM2Long, and DAM4SAM can propagate high-quality masks through video and
handle temporary occlusion. SAM2Long improves long-video robustness using a training-free memory
tree. DAM4SAM protects a target memory from distractors.

These are strong mask-continuity methods, but they are not the best primary identity layer here:

- targets generally require an initial prompt or detector;
- each target is handled mainly with its own memory;
- multiple similar instances are not jointly assigned under one global identity constraint;
- long VOS memories can consume substantial VRAM;
- complete re-entry under a different view is harder than short occlusion recovery.

REMIND's published evaluation reports that its SAM2-based comparison failed from GPU OOM on 66.9%
of ScanNet++ scenes under YOLO detections, while REMIND completed the scenes. The exact number is
benchmark-specific, but it is a useful warning for an 8 GB deployment.

**Decision:** keep SAM2.1-tiny or Cutie as an optional mask-refinement benchmark, not as the identity
authority or initial production dependency.

Primary references:

- SAM 2: https://arxiv.org/abs/2408.00714
- SAM 2 official code: https://github.com/facebookresearch/sam2
- SAM2Long: https://github.com/Mark12Ding/SAM2Long
- DAM4SAM: https://github.com/jovanavidenovic/DAM4SAM
- Cutie: https://github.com/hkchengrex/Cutie

### 3. MASA generic instance matching

MASA learns class-agnostic object matching from SAM proposals and can be attached to detectors or
segmenters. It is a much better baseline than person ReID for generic objects and is Apache-2.0.

Its published limitations are material for ThirdHand: it cannot recover objects that the detector
misses, cannot repair inconsistent detections, and can degrade under heavy occlusion. Its standard
association is also short-horizon and does not accumulate a persistent multi-view object memory.

**Decision:** use MASA-R50 as the strongest comparison baseline if time permits, but select REMIND
memory for the main route.

References:

- Paper: https://arxiv.org/abs/2406.04221
- Official code: https://github.com/siyuanliii/masa

### 4. REMIND long-term generic-object ReID

REMIND was released in July 2026 specifically for long-term re-identification of generic indoor
objects. One DINOv3 forward pass provides dense patch features for all detections. Each object owns
work and stable banks containing global, trimmed, part, and local-background prototypes. Context
and ambiguity guards enrich a class-wise Hungarian assignment, and inactive identities keep their
memory for later re-entry.

Reported results relevant to this project:

- 90.35% IDF1 on the authors' controlled indoor revisit sequence;
- almost 20 IDF1 points over DAM4SAM and more than 36 over MASA on that sequence;
- stronger association accuracy than MASA on ScanNet++ with the same YOLO detections, although
  MASA has higher detection accuracy and therefore slightly higher end-to-end IDF1 on all scenes;
- about 348 ms average loop time with YOLO on ScanNet++ in the reported experiment;
- less than 0.3 GiB peak allocated VRAM for the REMIND association stack in the ground-truth-mask
  evaluation, but up to 20.71 GiB CPU RSS in dense ScanNet++ scenes.

The paper is new and currently an arXiv preprint, so the numbers are evidence for prioritization,
not proof that it works on Lumos. The code is MIT-licensed and provides automatic YOLO-seg inputs,
configuration, ambiguity states, metrics, and a custom dataset.

Why it fits ThirdHand:

- the task definition is almost exactly the requested behavior;
- the DINO encoder is shared across every object in the frame;
- multi-prototype memory represents multiple viewpoints of the same object;
- global assignment reduces duplicate or crossed IDs;
- ambiguity is explicit and can feed a fail-closed robot gate;
- tabletop scenes contain relatively few simultaneous objects, avoiding its worst dense-scene
  CPU behavior;
- its RGB-only design leaves a clean place to add our reliable 3D base-frame evidence.

References:

- Paper: https://arxiv.org/abs/2607.09267
- Project: https://cvar-vision-dl.github.io/remind-reid-tracker/
- Code: https://github.com/cvar-vision-dl/remind-reid-tracker

### 5. RTSM persistent RGB-D memory

RTSM is a useful integration reference: it consumes RGB-D plus camera pose, segments objects,
associates CLIP embeddings with spatial proximity, and stores stable IDs and world coordinates.
It already supports RealSense input, record/replay, APIs, and multiple segmenters.

It is not selected as the identity core because its published accuracy evaluation is still marked
"coming soon", its public benchmarks use an RTX 5090, and CLIP/SigLIP semantic embeddings are aimed
more at semantic retrieval than fine-grained same-instance discrimination.

**Decision:** reuse architectural lessons, not the whole system. ThirdHand already has its own
camera transforms, timestamp contracts, 3D tracking, replay, and safety gates.

References:

- Code: https://github.com/calabi-inc/rtsm
- Documentation: https://calabi-inc.github.io/rtsm/
- Benchmarks: https://calabi-inc.github.io/rtsm/benchmarks/

### 6. FoundationPose and BundleTrack

FoundationPose is an excellent optional route when a CAD model or a set of reference views exists
and a rigid object's full 6-DoF pose is required. BundleTrack targets novel-object 6-DoF tracking
without an instance CAD model. Both solve a harder pose-estimation problem but add CUDA extensions,
rendering, object initialization, and substantially more integration complexity. They do not by
themselves solve persistent multi-object identity.

**Decision:** do not block Task 1 on 6-DoF pose. Add FoundationPose later for selected known rigid
objects if grasp orientation needs more than the mask point cloud can provide.

References:

- FoundationPose: https://github.com/NVlabs/FoundationPose
- BundleTrack: https://github.com/wenbowen123/BundleTrack

## Candidate Comparison

| Route | Long re-entry | Similar-instance handling | 3D position | 8 GB fit | Main problem |
|---|---:|---:|---:|---:|---|
| YOLO + ByteTrack/BoT-SORT | weak | weak | add-on | strong | short-horizon/person-oriented ReID |
| Grounding DINO + SAM2Long | medium | medium | add-on | uncertain | prompt/memory cost, no joint identity assignment |
| RTSM grounded-SAM2 | medium | medium | built in | needs measurement | no published identity/position accuracy yet |
| FoundationPose | medium | single target | strong 6-DoF | uncertain | CAD/reference setup, not multi-object identity |
| **RTMDet + REMIND-3D** | **strong** | **strong with ambiguity gate** | **built in** | **most plausible** | new method; must benchmark on Lumos |

## Selected Architecture

### A. Canonical image and fisheye handling

Lumos remains the canonical RGB coordinate system. Models trained on conventional perspective
images may lose accuracy at the outer fisheye rings, so the model adapter exposes two replay modes:

1. native 1280x1280 SEUCM image;
2. a calibrated virtual-pinhole workspace view derived from the SEUCM model.

The benchmark selects between them using radial recall and ID metrics. If rectification wins, masks
are mapped back to native Lumos pixels with a precomputed lookup; all provenance still names the
native frame and calibration. No ordinary Brown distortion model is substituted for SEUCM.

### B. Instance segmentation

Use RTMDet-tiny-ins as the default production candidate because it provides a precise instance mask,
has an Apache-2.0 implementation in MMDetection, supports TensorRT deployment, and has a good
real-time parameter/accuracy trade-off. Fine-tune it on the actual target classes and Lumos optics.

The existing YOLOv8n detector is retained only as a baseline. During early data collection, a
YOLO-seg checkpoint may bootstrap masks faster, but it is not the final selection until measured
against RTMDet on the same replay set.

References:

- RTMDet paper: https://arxiv.org/abs/2212.07784
- MMDetection: https://github.com/open-mmlab/mmdetection

### C. Persistent identity memory

Adapt the REMIND data flow:

1. Extract one DINO dense feature map from each accepted Lumos frame.
2. Pool mask-weighted global and trimmed descriptors.
3. Build 3-5 part descriptors per sufficiently large mask.
4. Store recent views in a work bank and consolidated high-confidence views in a stable bank.
5. Compare every current same-class detection with every eligible persistent identity.
6. Solve a global Hungarian assignment rather than assigning detections greedily.
7. Preserve `AMBIGUOUS` and provisional states instead of forcing the nearest match.
8. Update memory only from high-confidence, sufficiently visible, temporally fresh observations.

DINOv3 ViT-S/16 is the accuracy-first candidate: 21.6M parameters and the backbone used by the
REMIND evaluation. Access requires accepting Meta's DINOv3 license and sharing contact information
on Hugging Face. DINOv2 ViT-S/14 is the Apache-2.0, ungated fallback and is explicitly compatible
with REMIND's frozen-patch-encoder interface. Both must be measured on the same data before model
packaging is finalized.

### D. ThirdHand 3D association

For each instance mask:

1. Deproject valid D435 Z-depth pixels in the D435 optical frame.
2. Transform them through the calibrated D435-to-Lumos SE(3).
3. Project them into native Lumos SEUCM pixels and retain the nearest surface with a z-buffer.
4. Erode the instance mask before selecting points to suppress foreground/background boundary
   mixing.
5. Reject invalid range, sparse coverage, high temporal skew, and large uncertainty.
6. Remove the support plane and isolated clusters where enough data exists.
7. Estimate the object center with a robust median/geometric-median estimator, not bbox-center
   depth.
8. Transform the estimate into robot-base coordinates using the time-matched flange pose.

The association score combines REMIND appearance evidence with base-frame 3D consistency, mask
overlap, and short-term motion. Missing evidence is not treated as zero; weights are renormalized
over valid channels. Hard gates are applied before scoring:

- incompatible class: reject;
- invalid/stale calibration or timestamp: reject;
- valid 3D displacement outside the uncertainty-aware gate: reject;
- two candidates within the ambiguity margin: return `AMBIGUOUS`;
- no valid D435 depth: the track may remain visible, but it is not actionable.

For a moved object, 3D position is a short-term continuity cue, not a permanent identity claim.
Appearance must re-confirm the identity before the base position is updated.

### E. Identity state machine

Use explicit states:

```text
NEW -> TENTATIVE -> CONFIRMED -> OCCLUDED -> INACTIVE
                    |              |
                    +-> AMBIGUOUS <-+
```

- `CONFIRMED`: repeated high-confidence appearance and 3D agreement.
- `OCCLUDED`: recently missing, memory retained, predicted position non-actionable.
- `INACTIVE`: long missing, memory retained for re-entry, no current position claim.
- `AMBIGUOUS`: more than one plausible identity; no selection or grasp candidate.
- `STALE` is an orthogonal validity flag for timestamps/calibration.

Only `CONFIRMED`, fresh, stable, low-covariance tracks may reach Dry Run grasp planning.

## Why the Design Is Better Than the Current Code

The current online system uses YOLOv8n COCO boxes, CPU inference, and a greedy IoU tracker. It does
not have instance masks, long-term appearance memory, joint assignment, reliable depth-to-mask
selection, or ambiguity-aware persistent IDs.

The selected route replaces all five weak points:

- box -> instance mask;
- class label -> physical-instance appearance prototypes;
- frame-local IoU -> long-term multi-view memory;
- greedy match -> global assignment plus 3D gate;
- bbox/plane position -> measured mask point cloud with covariance.

## Deployment Feasibility

Current workstation observations:

- GPU: NVIDIA RTX 5060, 8151 MiB;
- system RAM: approximately 31 GiB;
- DINOv3-S and DINOv2-S are about 22M parameters;
- REMIND reports low VRAM for its identity stack but high CPU RSS in very dense scenes;
- ThirdHand tabletop scenes have far fewer simultaneous objects than ScanNet++;
- the current `LumosTouch` Python 3.10 environment does not contain PyTorch;
- the current base Python 3.14 Torch import is broken by a NumPy/`libstdc++` ABI mismatch.

Therefore create an isolated Python 3.10/3.11 vision environment for evaluation. Do not upgrade or
mutate the environment used by the active Startouch bridge. Model processes remain separate from
the CAN/robot process.

## Licensing

| Component | License/condition | Decision |
|---|---|---|
| RTMDet/MMDetection | Apache-2.0 | preferred detector |
| REMIND code | MIT | acceptable |
| DINOv3 code/weights | custom DINOv3 license; gated access | evaluate, record acceptance, do not vendor silently |
| DINOv2 code/model | Apache-2.0 | permissive fallback |
| SAM 2 | Apache-2.0 | optional benchmark/refiner |
| MASA | Apache-2.0 | comparison baseline |
| Ultralytics models/package | AGPL-3.0 or commercial terms | baseline/internal evaluation only unless obligations accepted |
| FoundationPose | NVIDIA source license | optional later module, separate review |

## Community Evidence

Community material was used to find integration patterns and failure reports, not as a substitute
for controlled evidence.

Chinese practical examples repeatedly use D435 depth, object masks/boxes, coordinate transforms,
and hand-eye calibration for grasping. They also show the recurrent engineering problem: getting a
detection is easy compared with maintaining calibration and a reliable target position.

- YOLOv8 + D435i + ROS arm grasp demonstration:
  https://www.bilibili.com/video/BV1dh4y1Q7QS/
- D435 3D grasp-position processing:
  https://www.bilibili.com/video/BV18q4y1Z7kw/
- D435 3D ROI, point-cloud filtering, ICP, and accuracy measurement series:
  https://www.bilibili.com/video/BV1VT421Y7AG/
- RealSense reproduction of FoundationPose:
  https://www.bilibili.com/video/BV1Bf421q7R1/

International practitioner discussions likewise report that generic ReID remains the bottleneck,
that person-oriented trackers do not transfer cleanly, and that persistent embedding galleries plus
spatial memory are needed. RTSM is a recent open-source example of RGB-D object memory, but it has
not yet published identity or absolute-position accuracy.

- RTSM community discussion:
  https://www.reddit.com/r/robotics/comments/1smaekh/
- Practical tracker/ReID limitations:
  https://www.reddit.com/r/computervision/comments/1l4dvfm/
- Long-term object memory discussion:
  https://www.reddit.com/r/computervision/comments/1rvjmi2/

Searches of Douyin and Xiaohongshu did not expose reproducible source code, datasets, or quantitative
benchmarks suitable for this decision. Their absence from the evidence table is deliberate.

## Offline Acceptance Gate

Before any online robot integration, record a Lumos+D435+arm-pose replay set containing:

1. one target at center and fisheye edge;
2. two visually different instances of one class;
3. two near-identical same-SKU instances;
4. partial and full occlusion;
5. target exit and re-entry from new viewpoints;
6. crossing detections and deliberate distractors;
7. object moved while hidden;
8. transparent, reflective, dark, and low-depth-coverage objects;
9. camera motion and stop-and-look segments;
10. an intentionally impossible identical-object swap.

Compare at minimum:

- existing YOLOv8n + IoU tracker;
- RTMDet-tiny-ins + existing 3D tracker;
- RTMDet-tiny-ins + REMIND appearance memory;
- RTMDet-tiny-ins + REMIND-3D;
- DINOv3-S vs DINOv2-S in the REMIND adapter;
- native fisheye vs calibrated virtual-pinhole model input.

Initial go/no-go thresholds:

- target-class mask recall at least 0.90;
- long-gap re-identification at least 0.90;
- no forced ID assignment in the impossible-swap sequence;
- ID switch rate at most 1% overall and zero in the controlled pick sequence;
- base-frame static position P95 jitter at most 8 mm;
- measured absolute 3D error P95 at most 15 mm in the validated workspace;
- all stale, ambiguous, invalid-calibration, low-coverage, and out-of-workspace inputs rejected;
- end-to-end Dry Run latency P95 at most 300 ms after optimization;
- GPU peak below 7.2 GB and no increasing memory use over 30 minutes.

These are gates for the local replay dataset, not claims about current performance.

## Task 1 Outcome

The selected algorithm family is **RTMDet-tiny-ins + REMIND-style DINO appearance memory +
ThirdHand RGB-D/base-frame object memory**, with conservative ambiguity rejection. This is the best
fit among the reviewed choices because it directly addresses persistent generic-object identity,
uses instance masks for accurate D435 point selection, fits the available hardware more plausibly
than a SAM2-heavy multi-object stack, and extends rather than discards the already-tested ThirdHand
3D safety core.

Task 2 should begin with an isolated replay benchmark and adapter implementation. Robot movement
remains out of scope until the replay, calibration, Dry Run, and human approval gates pass.
