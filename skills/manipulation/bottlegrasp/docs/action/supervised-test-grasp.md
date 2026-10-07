# 人工确认测试抓取（物理验证前保持阻断）

控制页的“测试抓取 · 每步确认”与原有视觉夹取按钮完全分离。输入稳定目标 ID（1–5）并点击“读取目标”，可查看相机、目标表面和 GRIP 点坐标（米转毫米），以及阻断原因。只读 CLI：

```sh
node scripts/action/supervised_test_grasp.js preview --target-id 1
node scripts/action/supervised_test_grasp.js status
```

个人开发分支现在可以构造“预抓 → 接近 → 夹持 → 垂直抬升”的低速计划，并按
`T_base_flange = T_base_grip × inverse(T_flange_grip)` 计算法兰命令；旧的固定
`flange_offset_base_m` 不再用于该计划。计划不会在缺少下列任一证据时执行：已确认且深度有效的目标、真实姿态宽度、静止且健康的新鲜机器人状态、手眼物理验证，以及经测量并带内容 ID 的 `T_flange_grip`。

当前 `configs/action.yaml` 故意把 `grasp.grip_transform.measured` 保持为 `false`，矩阵和验证 ID 均为空。因此离线预览应显示 `grip_transform_unverified`；手眼尚未完成物理验证时还应显示 `calibration_not_approved`。数值调试开关可以生成基坐标，但不会再把“数值可用”冒充“物理验证通过”。**不要仅修改布尔开关来解锁。**

现场剩余工作按顺序进行：

1. 连接机器人但先保持只读，确认法兰位姿、关节角、时间戳和 `stationary=true` 连续稳定。
2. 独立测量夹爪中心相对法兰的刚体变换（20 mm 只是测试值），生成内容寻址的验证记录后再填写 `matrix_4x4` 和 `validation_id`。
3. 用多个空间点完成手眼 3D 误差实测，只有通过后才更新手眼物理验证状态。
4. 先做不夹瓶的高位 dry-run，再做空夹爪接近，最后才对固定瓶型进行单步夹持和小高度抬升。

每一步都要核对桌面净空、机械臂状态、目标 ID、计划坐标和实体急停。相机完全遮挡的 10 mm 说明不是安全距离。软件停止不是安全额定急停；如果机械臂有危险，请使用实体急停。每条运动指令必须由操作员单独确认，失联或超时不可自动续行。

此功能的离线测试不得连接 CAN、移动机械臂或夹爪。上线前须在受控现场重新审查配置、路径、日志和状态关联；本文不构成物理抓取授权。
