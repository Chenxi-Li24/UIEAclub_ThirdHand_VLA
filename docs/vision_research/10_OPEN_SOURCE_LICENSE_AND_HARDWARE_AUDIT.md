# 开源许可与硬件审计

本文件是工程筛选，不是法律意见。部署或商业发布前应由项目负责人复核具体版本的 LICENSE、模型权重条款和数据集条款。

## 当前项目与依赖

| 项目 | 观察到的许可 | 风险/动作 |
|---|---|---|
| ThirdHand 主项目 | MIT | 可继续；保留版权和许可文本 |
| Ultralytics 当前包/YOLOv8n | AGPL-3.0 或商业许可 | 网络服务场景有强 copyleft 义务；研究原型需记录，闭源/商业需购买许可或替换 |
| pyrealsense2/librealsense | Apache-2.0 | 宽松；保留 NOTICE/许可 |
| OpenCV | Apache-2.0 | 宽松 |
| PyTorch | BSD-style | 宽松，逐项审计随附 CUDA/模型 |
| FastUMI_Camera | 仓库无根 LICENSE | 默认视为权利未授予，不复制发布厂商二进制/代码 |
| FastUMI_Hardware_SDK | 仓库无根 LICENSE | 同上；仅作为用户本机依赖 |
| startouch_sdk | 本机仓库未发现 LICENSE | 同上；不打包再分发 |

## 候选视觉/跟踪

| 候选 | 许可 | 决策 |
|---|---|---|
| RT-DETR 官方仓库 | Apache-2.0 | 可作 box 检测候选 |
| MMDetection/RTMDet | Apache-2.0 | 首选可分发实例分割候选；同时审计具体权重来源 |
| Detectron2 | Apache-2.0 | Mask R-CNN 基线 |
| SAM 2 code/checkpoints | Apache-2.0（官方说明） | 可研究，保留第三方字体/组件许可 |
| GroundingDINO | Apache-2.0（代码） | 权重/数据另审 |
| ByteTrack | MIT（官方仓库） | 可用；其完整 demo 依赖也需审计 |
| BoT-SORT | MIT | 可用；ReID 权重另审 |
| Norfair | BSD-3-Clause | 适合轻量定制 |
| Kalibr | BSD | 标定工具可用，注意其特定 attribution 条款 |
| ViSP | GPL-2.0 | 与 MIT 主项目组合/分发需谨慎；优先借鉴而非直接链接 |

## 抓取模型

| 候选 | 许可/限制 | 决策 |
|---|---|---|
| GPD | BSD-2-Clause | 宽松研究/部署候选 |
| GraspNet baseline/model | 免费非商业 | 只允许非商业研究，发布前确认 |
| Contact-GraspNet | NVIDIA 自定义 License.pdf | 不假设允许商业/再分发；隔离评估 |
| AnyGrasp | 社区普遍反馈授权受限 | 不作默认依赖 |
| FoundationPose | 代码与 NGC 模型条款分别适用 | 下载/部署前接受并归档具体条款 |

## 硬件风险

- D435 标称最小约 0.3 m；末端接近物体时会失去有效深度，最终阶段应依赖 Lumos RGB/保守停止，而不是假设深度持续有效。
- D435 深度误差会随距离、材质、边缘和曝光变化；官方 ≤2% 指标有集成/标定/ROI 条件，不等同于本机抓取精度。
- 两相机无硬同步，运动中融合有时间偏差。
- Lumos USB runtime suspended，启动稳定性需要在不修改系统设置的前提下记录；系统级 USB 调优必须是独立、用户授权操作。
- 现有 CAN 单实例锁有效；不得启动第二个 SDK/CAN 实例。

## 分发清单要求

构建包必须包含：项目 LICENSE、第三方 notices、依赖锁定、模型名称/版本/hash/来源/许可、数据集来源和限制。不得打包 `.env`、SSH key、CAN 锁、日志、用户标定原图或无授权厂商二进制。
