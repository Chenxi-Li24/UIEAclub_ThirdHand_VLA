# 三维目标与抓取候选研究

## 分层策略

本项目的首要目标是桌面瓶、杯、罐和盒，不需要第一版就解决任意杂乱场景的完整 6-DoF 抓取。推荐从可解释的几何 top-down/side-pinch 候选开始，保留学习式 6-DoF 作为研究扩展。

## Phase 1：几何候选

输入为对象实例 mask 对应的 base-frame 点云、桌面平面、夹爪几何与工作区。流程：

1. 剔除桌面平面和离群点，选择与目标记忆一致的 3D cluster。
2. 计算 medoid、PCA 主轴、OBB、点云高度/宽度、顶部表面法线和不确定度。
3. 生成多组 top-down 候选：中心附近不同 yaw、必要时箱体边缘/圆柱侧向候选。
4. 用夹爪开口、接触区点密度、法线对向性、桌面间隙、approach corridor、IK/关节限位和自碰撞/桌面碰撞筛选。
5. 评分保留 top-K，UI 显示候选、置信度、拒绝原因和安全余量。

目标点不是 bbox 中心，也不是 mask 点的简单均值；优先使用 medoid/稳健中心并显式给出 covariance。透明杯、反光罐和深度覆盖不足时，返回“不足以抓取”。

## 学习式候选

| 方法 | 能力 | 许可/资源 | 本项目判断 |
|---|---|---|---|
| GPD | 无 CAD 的点云 6-DoF，BSD-2-Clause | C++/ROS 生态较旧 | 可作为宽松许可对照 |
| Contact-GraspNet | 杂乱点云 6-DoF，建议配合实例分割 | 官方说明推理 GPU ≥8GB；NVIDIA 自定义许可 | 8GB 边界，隔离环境 benchmark |
| GraspNet baseline/GSNet | RealSense 训练、标准 benchmark | 仅免费非商业使用 | 研究候选，不能默认商业部署 |
| AnyGrasp | 工程效果常被社区采用 | 授权/下载限制明显 | 不纳入默认架构 |
| FoundationPose + CAD grasps | 已知对象 6D pose 与稳定跟踪 | NVIDIA 代码/模型许可需逐项审计 | 对固定 SKU 很有价值 |

学习式候选也必须经过同一安全过滤器，网络分数不能绕过几何/IK/碰撞检查。

## 可达性与路径

现有末端算法有直线与关节角两类路径，但还没有完整碰撞环境。第一阶段 Dry Run 只计算：

- 目标是否在允许工作区
- 预抓取、抓取、抬升三个 pose 的 IK 是否存在
- 关节限位、奇异性近似指标、直线路径采样是否有效
- 桌面/相机/夹爪的简化体碰撞余量

MoveIt Servo/PlanningScene 提供关节限位、奇异性和碰撞检查参考，但当前 Startouch 栈未集成 MoveIt，不能假设已有这些保障。

## 候选数据合同

```text
GraspCandidate {
  candidate_id, object_id, observation_id, calibration_id,
  pose_base, pregrasp_pose_base, retreat_pose_base,
  jaw_width_m, score, covariance,
  depth_coverage, collision_margin_m,
  ik_status, rejection_reasons[], created_monotonic_ns
}
```

候选不可变；目标更新后生成新 candidate id。执行请求必须引用 exact candidate，不允许只传裸 `(x,y,z)`。

## 验收

- 合成/回放：候选确定性、点云离群鲁棒性、旋转/平移协变、桌面碰撞拒绝。
- Dry Run：100% 拒绝 stale、低覆盖、越界、无 IK 或校准无效目标。
- 实机手动阶段：先空夹爪仅到预抓取上方安全高度，再逐步缩小误差；每次由人在急停旁确认。
