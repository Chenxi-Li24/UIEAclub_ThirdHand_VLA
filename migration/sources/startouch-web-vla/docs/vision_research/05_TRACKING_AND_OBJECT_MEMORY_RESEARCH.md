# 稳定跟踪与对象记忆研究

## 两层身份模型

必须区分：

1. `track_id`：图像序列中的短期身份，可在长时间遮挡后失效。
2. `object_id`：机器人 base 坐标系中的对象记忆，包含类别分布、外观、三维位置、协方差、最后观测时间和状态。

不能承诺“永久不换 ID”。ByteTrack、BoT-SORT、SAM2 等都会在漏检、长遮挡、相似对象交叉或重初始化时换 ID。系统应通过三维门控和对象记忆吸收短期 track 变化，并在歧义时显式标为 `AMBIGUOUS`，而不是强行合并。

## 候选跟踪器

| 方法 | 主要信息 | 优点 | 局限 | 用途 |
|---|---|---|---|---|
| ByteTrack | bbox、置信度、运动 | 简单快，利用低分框 | 移动相机/相似对象下易换 ID | 最小基线 |
| BoT-SORT | 运动、外观、相机运动补偿 | 遮挡和相机运动更强 | ReID/参数更重；原实现偏行人 | 增强候选 |
| Norfair | 自定义点/距离、可扩展 ReID | 轻量、任意维度、MIT/BSD 类宽松生态 | 需自行定义 3D/外观门控 | 适合本项目定制 |
| SAM2 video | mask 记忆与传播 | mask 稳定、可交互修正 | 资源开销和漂移需实测 | 研究扩展 |
| FoundationPose/BundleTrack | RGB-D 6D pose | 已知/新对象的姿态跟踪 | CAD/参考图、依赖和许可证复杂 | 特定已知物体扩展 |

## 推荐最小跟踪器

检测帧使用 Hungarian 全局匹配，代价由以下组成：

```text
cost = w_iou*(1-IoU) + w_3d*mahalanobis_xyz
     + w_app*(1-cosine_embedding) + class_penalty
```

每帧用 Kalman/常速度模型预测 2D 中心和 base-frame 3D 位置。只有类别兼容、图像门控和三维门控同时通过才关联。轨迹包含 `age, hits, consecutive_hits, misses, last_seen_ns, state`，状态为 `TENTATIVE/CONFIRMED/OCCLUDED/LOST`。

对象只有在连续 N 帧、三维方差和速度均低于门限时才为 `STABLE`。任何候选动作都绑定 `object_id + observation_id + calibration_id`，执行前必须重新观测并验证未发生身份切换。

## 移动相机

Lumos 为 eye-in-hand，相机运动会使全图 bbox 快速变化。不能把像素静止当成物体静止。每帧应将有效三维观测变换到 robot base，再进行稳定性判断；若手眼标定或 FK 过期，则只输出 2D track，不更新 3D memory。

对于出画目标：保留最后 base 位置和协方差，但随时间扩大不确定度并设置 TTL。`OCCLUDED` 可用于 UI 提示，不能用于盲抓。抓取前必须回到 `VISIBLE + STABLE + FRESH`。

## 指标

- HOTA、IDF1、ID switches、fragmentations、track recall。
- 机器人专用：对象记忆误合并率、遮挡后正确重关联率、稳定确认时间、3D 抖动 P95、出画后误执行次数（目标必须为 0）。
- 测试场景：短漏检、长遮挡、同类交叉、相机平移/旋转、对象移出/重新进入、检测空帧、时间戳倒退。

## 当前实现差距

现有贪心 IoU 不具备上述任何生命周期或三维约束，并在空检测帧清空所有状态。它只能作为“框连续显示”的 demo，不能承担抓取身份。
