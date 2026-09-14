# ChArUco 双相机外参重新拟合设计

## 背景与目标

现场 DFOPTIX `CC200-15-11.25` ChArUco 板在同一对真实帧中恢复了 87 个共同角点，D435 PnP 重投影 RMSE 为 `0.357 px`，但旧 Lumos↔D435 候选外参的 Lumos P95 为 `118.749 px`。因此停止验证旧候选，只重新拟合两台固定相机之间的 6 自由度外参；两台相机内参保持不变。

## 方案选择

采用 OpenCV ChArUco/PNP、仓库已有 EUCM/SEUCM 投影和 SciPy `least_squares` 的薄适配方案。

- 不把 220° Lumos 图像当作针孔图像。
- 不从零实现非线性优化器；使用 SciPy 的信赖域最小二乘和 `soft_l1` 鲁棒损失。
- 不临时安装 Kalibr/Basalt：它们是成熟多相机标定工具，但正式目标提取流程以 AprilGrid、棋盘格或圆点阵列为主，不能直接复用现场 ChArUco ID 对应关系。
- 不采用单姿态结果；单姿态只证明模型和初始化可收敛，正式拟合必须使用多姿态，验收必须使用完全独立的数据集。

一手资料：

- Kalibr 多相机工具与支持目标：<https://github.com/ethz-asl/kalibr>、<https://github.com/ethz-asl/kalibr/wiki/calibration-targets>
- Basalt EUCM 标定实现与 AprilGrid 流程：<https://gitlab.com/VladyslavUsenko/basalt/-/blob/master/doc/Calibration.md>
- SciPy 鲁棒非线性最小二乘：<https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html>
- EUCM/大视场模型综述：<https://arxiv.org/abs/1807.08957>

## 模块边界

### 拟合样本采集

新增独立 `dual_camera_refit_capture.py` 模块，职责仅为：

- 并发抓取 Lumos 1280×1280 与 D435 640×480 原始 JPEG；
- 检测同一 ChArUco 板并按角点 ID 建立对应；
- 用 D435 针孔内参求 `T_d435_from_board`；
- 保存原始图像、角点、D435 板姿态、双帧时差和哈希；
- 在任何图像写入前拒绝重复姿态和不合格样本。

拟合集固定要求：

- 12 个不同姿态；
- 共同角点不少于 24；
- D435 重投影 RMSE 不高于 1.5 px；
- 双帧采集时差不高于 100 ms；
- 新姿态相对每个已选姿态至少平移 15 mm 或旋转 3°。

拟合采集不使用旧外参的 Lumos 重投影误差作为门禁，因为旧外参正是待替换对象。它可显示旧候选残差作为诊断，但不影响样本入集。

### 外参求解

新增纯离线 `dual_camera_refit_solver.py`：

1. 每个样本以旧候选外参为初值，固定 `T_d435_from_board`，对该样本的 Lumos 角点运行 6 自由度 EUCM 重投影优化。
2. 用各样本平移中位数和 SciPy `Rotation.mean()` 形成全局初值，降低单帧局部异常影响。
3. 将所有拟合样本的 Lumos 像素残差拼接，固定两台相机内参和每帧 D435 板姿态，只联合优化一个 `T_lumos_from_d435`。
4. 使用 `least_squares(method="trf", loss="soft_l1", f_scale=2.0, x_scale="jac")`。
5. 只有优化收敛、全部点处于 EUCM 有效域、平移基线在 `[0.02, 0.30] m`、旋转不超过 45°、拟合集 P95 不高于 3 px 时才写出新候选。

输出为内容寻址的 `candidate_only` JSON，包含源拟合集 ID、求解器版本、固定内参 ID、4×4 变换、样本数、角点数和拟合 residual 指标。始终写 `executable: false`。

### 独立验证

新候选不能读取拟合集作为验收证据。求解完成后，网页切换到全新的验证目录，复用已实现的候选验证器采集 10 个不同姿态：

- 每对公共角点不少于 24；
- D435 RMSE 不高于 1.5 px；
- Lumos P95 不高于 4 px；
- 10 个姿态全部通过才把 `relative_extrinsic_validated` 设为 true；
- 即使通过，手眼和桌面标定仍是 blockers，机械执行仍为 false。

## 网页状态机

现有 `calibration-capture.html` 保持唯一操作入口，增加四个明确阶段：

1. `fit_collect`：显示拟合集 `0/12`，按钮为“采集拟合姿态”。
2. `fit_ready`：12 个姿态齐备，按钮为“求解新外参”。
3. `validation_collect`：显示验证集 `0/10`，按钮为“采集验证姿态”。
4. `relative_validated`：显示双相机外参通过，但手眼/桌面仍未完成。

页面继续只提供一个主按钮，防止操作员混淆当前样本用途。每次成功后给出下一姿态建议，显示共同角点、D435 RMSE、采集时差；求解后额外显示拟合 median/P95、基线和旋转角。拟合集与验证集使用不同颜色和清晰标签。

## API 与安全

Node `calibration-capture-api.js` 继续只做受限适配：

- `GET /api/calibration/status` 返回阶段与白名单字段；
- `POST /api/calibration/capture-fit` 自动生成 `fit-NN`，不接收路径、URL 或样本 ID；
- `POST /api/calibration/solve` 只在 12 个合格拟合姿态后运行固定脚本；
- `POST /api/calibration/capture` 只在新候选存在后采集独立验证姿态；
- 同时最多运行一个采集或求解任务；只允许本机、同源请求；子进程无 shell、15 秒采集超时、60 秒求解超时、输出上限 1 MiB。

所有输出目录和配置由服务端固定。网页不提供删除、重置、覆盖、机械臂、CAN、夹爪或抓取接口。

## 证据与失败恢复

- 拟合和验证使用不同的内容寻址 manifest 与图像目录。
- 每个 manifest 锁定标定板配置、相机内参、源 URL 角色和用途。
- 失败采集不写图像；重复姿态不增加进度。
- 求解失败保留拟合集但不生成候选，页面允许重新求解，不自动改变运行时标定。
- 服务重启后只从完整性验证通过的 manifest 恢复阶段，不依赖浏览器本地状态。
- 旧候选文件保留作为审计输入，新候选写入数据目录，不能覆盖仓库旧候选或在线 active-view evidence。

## 测试与验收

- 合成多姿态测试从已知 EUCM↔针孔变换生成像素，加入受控噪声和少量离群点；恢复误差要求平移不超过 1 mm、旋转不超过 0.2°、验证 P95 不超过 2 px。
- 采集测试证明重复姿态、低公共角点、高 D435 RMSE 和高时差在写盘前拒绝。
- 数据隔离测试证明求解器只读取 `purpose=fit`，验证器只读取新候选与独立验证目录。
- Node 与浏览器测试覆盖四阶段、单按钮、并发闭锁、本机同源限制和零机械控制入口。
- 真实现场验收为 12 个拟合姿态求解后，再采集 10 个未用于拟合的验证姿态；只报告独立验证结果。
