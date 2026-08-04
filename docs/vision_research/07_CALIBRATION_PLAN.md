# 标定计划

## 原则

标定不是“生成一个 JSON”即完成。每个阶段必须有原始数据、独立验证集、单位/坐标系、算法版本、质量指标、物理合理性检查和可回滚版本。旧文件不覆盖，统一进入 `calibration/quarantine/legacy-*`。

## 阶段 1：Lumos 内参

- 模型：厂商 SEUCM/EUCM 为主；Kalibr EUCM、Double Sphere 为对照。
- 标定板：刚性高质量 AprilGrid，准确测量 tag size/spacing；避免普通打印纸翘曲。
- 采集：覆盖中心、四角、图像边缘、距离和姿态，允许部分可见；固定曝光/焦距/分辨率。
- 划分：按采集姿态留出至少 20% 独立验证，不用拟合帧自评。
- 报告：全局与径向环带 median/P95/max reprojection error、残差图、参数置信区间。

## 阶段 2：D435 内参与深度健康

- 读取 factory intrinsics、extrinsics、depth scale 和固件版本，不进行 on-chip calibration。
- 用平面在多个距离评估 Z bias、spatial RMS、temporal RMS、fill rate；分别记录对象材质。
- 明确原始 depth optical 与 aligned-to-color 两套内参语义。

## 阶段 3：D435 到 Lumos 固定外参

由于两相机同装末端，使用共同观测的 AprilGrid/三维靶标标定 `T_lumos_from_d435`。Lumos 采用其 SEUCM PnP/非线性重投影模型，D435 可用 color/depth 对应数据。优化目标同时包含两相机重投影与 D435 深度平面残差。

验证：保留新姿态，将 D435 点云投到 Lumos，报告角点/板边缘像素误差和三维平面误差。物理平移应与尺量安装基线同量级；差异过大直接拒绝。

## 阶段 4：Lumos 到 flange 手眼标定

1. 修正 Startouch RPY：`R = Rz(yaw) Ry(pitch) Rx(roll)`，写数值单元测试。
2. 采集多轴、大角度且非共面的末端姿态；每个样本等机械臂静止后采相机帧和机器人 pose。
3. 使用官方 OpenCV `calibrateHandEye` 的多种方法（Tsai、Park、Horaud、Daniilidis）作对照，不使用当前自定义实现。
4. 明确输入：`R_gripper2base/t_gripper2base` 和 `R_target2cam/t_target2cam`；输出 `T_gripper_from_camera`。
5. 采用 leave-one-out/独立姿态验证，报告 AX=XB rotation/translation residual、靶标 base 坐标一致性、重投影误差。

## 阶段 5：全链验证

- 将 D435 深度靶标点经 D435->Lumos->flange->base 变换，比较已知桌面/靶标位置。
- 多个机械臂静止姿态下，同一静态点在 base 中的 P95 漂移应满足抓取需求。
- 用尺量工作区点进行绝对误差验证，不能只看同一错误链条的自洽性。

## 暂定接受门限

| 项目 | Gate |
|---|---|
| Lumos 验证重投影 | median ≤1 px，P95 ≤2.5 px，边缘 P95 ≤4 px |
| 双相机注册 | 板角点 P95 ≤4 px；桌面平面 P95 ≤8 mm |
| 手眼旋转一致性 | P95 ≤1.0° |
| 手眼/全链静态点 | P95 ≤10 mm（进入抓取前再按夹爪余量收紧） |
| 标定物理尺度 | 与尺量基线/安装方向一致，无 0.3–0.4 m 异常平移 |

任何门限失败只允许继续研究和 UI 可视化，不允许真实动作。
