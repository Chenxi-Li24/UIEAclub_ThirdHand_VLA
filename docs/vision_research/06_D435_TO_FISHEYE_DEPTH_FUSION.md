# D435 点云到 Lumos 鱼眼图像的深度融合

## 推荐数据流

```text
D435 depth frame
  -> validity/threshold filtering
  -> deproject with D435 depth intrinsics (XYZ in depth optical)
  -> T_lumos_from_d435
  -> SEUCM project into Lumos pixels
  -> z-buffer / splat
  -> registered depth + coverage + provenance
  -> intersect with Lumos instance mask
  -> robust object point cloud
```

D435 RGB 不参与主语义检测。若 pyrealsense2 的点云基于原始 depth optical，则使用该内参直接反投影；如果先对齐到 D435 color，必须改用“对齐后图像对应的 color intrinsics”，不能混用 depth intrinsics。

## 几何步骤

对每个有效 D435 深度像素 `(u,v,z)`：

```text
p_d = deproject_d435(u, v, z)       # meters, z is optical-axis depth
p_l = T_lumos_from_d435 @ [p_d, 1]
(u_l, v_l) = project_seucm(p_l)
```

以 `p_l` 的可见深度（建议欧氏范围和光轴/模型分母均保留）写入 Lumos 像素。多个点落到同一像素时用最近表面的 z-buffer；不要平均前后两个表面。亚像素投影可使用 2×2 bilinear splat，但每个目标像素仍选择最近深度并保存权重。

输出至少包含：`depth_m, valid, source_count, nearest_range_m, timestamp_delta_ms, calibration_id`。未被 D435 FOV 覆盖的 Lumos 大视场区域是 `NO_COVERAGE`，不是 0 米。

## 遮挡与边界

两相机有基线，D435 可见而 Lumos 被遮挡（或反之）的区域会产生飞边。处理方法：

- z-buffer 保留从 Lumos 视角最近点。
- 对深度不连续区域做前景侵蚀/置信度衰减，不用强 hole filling 跨越对象边缘。
- Lumos mask 内先腐蚀 1–3 px（按分辨率自适应），再计算点云；保留原 mask 用于可视化。
- 用中位数/MAD、百分位和连通 3D cluster 去除桌面与离群点。
- 对透明/反光对象，返回 `LOW_DEPTH_CONFIDENCE`，允许平面交点仅作 UI 粗估，不作自动抓取。

## 时间同步

无硬件同步时必须采用主机单调时间和 bounded queues：每个 Lumos RGB 选择时间最近的 D435 depth，记录 `abs(dt)`。机械臂静止时建议 `|dt| ≤ 33 ms`；运动时不能仅靠近邻帧，应根据两时刻 FK 补偿或直接禁止生成候选。第一阶段选择禁止运动中候选。

## 滤波

- 无效值/范围阈值 -> 可选 disparity-domain spatial -> temporal filter -> 回到 depth。
- 只在回放 benchmark 证明有益时启用；temporal filter 会在运动/遮挡处拖影。
- 不把 hole filling 后的像素与原始测量等价；provenance 中要标记 inferred。

## 对象三维估计

1. 用 Lumos instance mask 选注册点。
2. 去除桌面 RANSAC 平面内点和 mask 边缘低置信度点。
3. 选择与上帧对象位置最近且连通的 cluster。
4. 计算 robust centroid、medoid、PCA 主轴、尺寸、表面法线和协方差。
5. 输出对象表面/几何中心与抓取接触面候选，不再用 bbox 中心单点。

## 离线测试

- 合成平面、两个前后重叠平面、图像边界、无覆盖、NaN/0、同像素冲突。
- 已知变换的 round-trip；与 pyrealsense2 反投影对照。
- 实拍标定板/桌面：注册边缘 P50/P95 像素误差、平面残差、覆盖率。
- 记录 1000 帧性能：CPU/GPU 延迟、内存、掉帧、时间差分布。
