# External dependencies and reuse decisions

This register is the source-of-truth for third-party code and design ideas used
by the generic bottle V+A skill. Runtime code must access hardware and learned
models through local adapters; importing a library module must never start a
camera, network connection, model download, or robot command.

| Source | Version / reference | License | Decision and verification |
| --- | --- | --- | --- |
| [Lumos FastUMI / XVisio camera](https://github.com/lumos-open/FastUMI_Camera) | repository reviewed 2026-08-23; local XVisio SDK | repository files and bundled SDK terms must be checked before redistribution | Reuse the SDK stream and registered RGB-D format behind `XVisioFrameSource`; do not copy SDK binaries into this repository. Verify by building `native/vision/xvisio_rgbd_stream` and running the explicitly authorized camera smoke test. |
| [Grounded-SAM-2](https://github.com/IDEA-Research/Grounded-SAM-2) | Grounding DINO commit `a2bb814dd30d776dcf7e30523b00659f4f141c71`; weights SHA-256 in `vision.yaml` | Apache-2.0 repository; model licenses remain model-specific | Reuse the official Grounding DINO + SAM 2 composition through `GroundedSamBackend`; no model download at import. Exact revision and weight hash are checked before load and recorded in every actionable event. |
| [SAM 2](https://github.com/facebookresearch/sam2) | commit `de431c4043854a71d8101e17995dfe596bf101a5`; weights SHA-256 in `vision.yaml` | Apache-2.0 | Reuse mask prediction with an exact locally cached revision. Runtime and preflight reject a different snapshot or weight hash. |
| [Norfair](https://github.com/tryolabs/norfair) | 2.3.0 | BSD-3-Clause | Reuse multi-object association inside `NorfairTrackerAdapter`; keep user-facing stable IDs and reservation lifecycle in this project. Verify with replay sequences that detector IDs and left/right order may change without identity changes. |
| [OpenCV](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) | 4.11.0.86 | Apache-2.0 | Reuse `calibrateHandEye` and standard numerical primitives. Validate on synthetic known transforms and held-out physical samples. |
| [MoveIt Task Constructor](https://moveit.picknik.ai/main/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html) | design reference | BSD-3-Clause | Reuse the staged pick/place failure model concept, not the ROS dependency, because the existing Startouch stack already owns low-level motion. |
| [UIEAclub ThirdHand / local TH-Fanxy](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA) | local `/home/nieqingcao/TH-Fanxy`, `/home/nieqingcao/th0814/TH_MK_D/UIEAclub_ThirdHand_VLA-control-fixed-a-to-b`, and sibling `Reuse`, reviewed 2026-08-24 | MIT; attribution recorded in `native/startouch/NOTICE.md`; the pinned vendor SDK MIT declaration is hash-bound from `pyproject.toml` | Reuse the proven Startouch SDK call shapes and the conservative contained-runtime safety profile behind a strict JSON-lines subprocess. Reference trees are read-only and are not runtime import paths. The VA adapter adds exact request matching, content-bound handshake, flange semantics, single CAN ownership, passive non-loopback `0x11..0x17` feedback proof, a 3° joint stop margin, and truthful cleanup acknowledgement that never claims independent motor depower. |
| [NVIDIA Isaac ROS Manipulator](https://nvidia-isaac-ros.github.io/reference_workflows/isaac_manipulator/index.html) | design reference | NVIDIA component-specific terms | Reuse on-demand perception and stage-orchestration concepts only; do not add Isaac/ROS to this compact deployment. |
| [VGN](https://github.com/ethz-asl/vgn) | design reference | MIT | Reuse candidate quality/orientation/width concepts. Do not add its TSDF and network runtime in the first upright-bottle version. |
| [GPD](https://github.com/atenpas/gpd) | evaluated reference | BSD-2-Clause | Not adopted: its older PCL/C++ stack is disproportionate for separated upright bottles. |
| [Contact-GraspNet](https://github.com/NVlabs/contact_graspnet) | evaluated reference | repository-specific research license | Not adopted: TensorFlow/custom model terms and runtime complexity do not fit this deployable first version. |
| [GraspNet baseline](https://github.com/graspnet/graspnet-baseline) | evaluated reference | non-commercial/research terms in upstream repository | Not adopted for the production path because usage terms and dependency weight are unsuitable; retained only as an academic comparison. |

## Geometry implementation boundary

Table-plane estimation follows the standard RANSAC plane model followed by an
SVD least-squares refinement, implemented with the already required NumPy. A
fixed random seed makes recorded-bundle tests deterministic. Open3D was
evaluated but is not introduced for this first version: only plane fitting and
small masked-cloud statistics are needed, so its additional binary/runtime
surface would not improve the module contract. The implementation is isolated
in `vision/geometry/pointcloud.py` and can be replaced by another plane fitter
without changing the candidate interface.

## Deployment boundary

迁移时复制整个 `PinZiZhuaQuSkill` 即可保留 VA 源码、配置 schema、fixture、F5 入口和离线测试；
不要复制外部仓库的软链接或硬编码导入。目标机需要单独安装兼容的 Lumos/XVisio SDK 与
Startouch SDK，并在 `configs/vision.yaml`、`configs/action.yaml` 更新路径后重新跑 preflight。
项目不会在 import 时安装驱动、拉模型、启动相机或打开 CAN。

## Reproducibility checks

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pip install -r requirements/vision-cu128.txt
npm ci --ignore-scripts
bash scripts/vision/build_native.sh
/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python scripts/runtime/preflight.py --json
```

The preflight is read-only. Live camera and robot checks are separate commands
with explicit authorization flags.

`configs/vision.yaml` currently reuses the complete Hugging Face cache in the
adjacent `ThirdHand-XVisio` checkout. This avoids duplicate multi-gigabyte model
copies and keeps `local_files_only=True`. On another host, update `hf_home` to
that host's reviewed local cache; `preflight.py` now verifies both model
snapshots contain configuration, processor, and weight files without loading
CUDA or contacting the network.

### NumPy compatibility decision

The runtime pins NumPy 1.26.4 rather than 2.x. Norfair 2.3.0 declares
`numpy>=1.23,<2.0`; OpenCV 4.11, Torch 2.7, Transformers 4.56 and the current
project code are compatible with 1.26.4. The environment uses the single
`opencv-python==4.11.0.86` distribution because its existing MMCV/MMEngine
packages declare that distribution by name; installing both GUI and headless
OpenCV wheels would make them overwrite the same `cv2` files. Runtime code does
not call OpenCV GUI APIs. These versions were selected by running pip's resolver
and `pip check` against the complete environment. Installing Norfair with
`--no-deps` against NumPy 2.x is intentionally prohibited because it would
discard the upstream compatibility boundary.
