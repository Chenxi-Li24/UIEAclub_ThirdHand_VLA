# 单独运行真实抓瓶（监督分阶段验证）

本入口复用 PinZi RGB-D/分割/深度、已有四步控制器以及 TH-Fanxy 的 Startouch 桥接。末态为保持，不执行放置。物理目标仍是原来从左数第二只的 L2 瓶子，实测直径约 63 mm；现场已移走 L1/L3，只保留这只原 L2，因此当前观察器参数为 `targetOrdinal=1`。

## VS Code Remote-SSH

打开目录 `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA`。`.vscode/launch.json` 已提供离线计划检查、四步控制器回归、模拟 CLI、离线机器人 FK 四个 F5 配置，可在对应源码中直接设置断点。另有一个明确标注 real camera 的只读相机配置。所有配置都不访问机械臂控制接口。

| 要调试的模块 | 打开文件 | 独立验证 |
|---|---|---|
| 坐标候选/工作空间/数据时间 | `web-control/server/supervised-grasp-plan.js` | `node web-control/server/test/supervised-grasp-plan-smoke.js` |
| hover/descend/close/lift 状态机 | `web-control/server/grasp-controller.js` | `node web-control/server/test/grasp-controller-smoke.js` |
| 终端与现有桥接的连接 | `web-control/scripts/grasp_bottle_real.js` | `node web-control/server/test/grasp-bottle-real-cli-smoke.js` |
| 关节查询与两套末端坐标 | `web-control/scripts/read_grasp_robot_pose.py` | `PYTHONPATH=src python3 -m pytest -q tests/test_read_grasp_robot_pose.py` |
| 视觉观察 | `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill/scripts/vision/observe_grasp_bottle.py` | 下面的只读相机命令 |
| 深度/局部宽度/形状规则 | 同 PinZi 项目 `src/thirdhand_va/vision/observer.py` | 同项目 `tests/vision/test_observer.py` |

相机只读观察（会占用 USB 相机，不使能机械臂）：

```bash
cd /home/nieqingcao/th0814/VA/PinZiZhuaQuSkill
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/observe_grasp_bottle.py --ordinal 1 --allow-camera \
  --watch-jsonl --max-observations 8
```

没有同步的机械臂 pose 文件时，观察器仅报告相机数据，Base 候选保持禁止执行。启动后第一次模型预热会较慢，原始采集时间不会被输出时间替换。`--robot-pose-file` 的协议见观察器源码：`pose_frame=sdk_tool`、XYZ/RPY、真实采样 `ts`、`stationary`、`stationary_since_ms`。投影原 pending 手眼时必须显式传 `--handeye-parent-frame sdk_tool`。

机器人离线 FK（不访问 CAN）：

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA
python3 web-control/scripts/read_grasp_robot_pose.py \
  --offline-joints-deg -0.163927 -2.611904 -4 33.058620 0.338783 0.185784
```

去掉 `--offline-joints-deg` 后只查询 CAN 关节反馈，仍不构造 `SingleArm` 或使能电机。CAN 接口需要按原机器配置设为 1 Mbps。

## 独立终端入口

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA
node web-control/scripts/grasp_bottle_real.js --live \
  --settings configs/tasks/grasp_bottle_supervised.json
```

当前磁盘配置选中现场唯一的原 L2（`targetOrdinal=1`），使用固定抓取 TCP 高度 `fixedGraspBaseZM=0.13 m` 和固定 Euler `[0.052626251,0.8,0.49249365] rad`；观察高度为 `observationHeightBaseM=0.12 m`，带宽 ±5 mm；使用现场实测 `bottleDiameterM=0.063 m` 计算表面到轴心的偏移，原始深度和观测宽度仍单独保留。观测宽度不是夹爪开度，也不作为近场投影的单独执行门禁。安全过渡高度仍为 `0.306371896 m`，pregrasp 仍为抓取点上方 `0.15 m`。这些是下一次受监督 Test 2 的候选设置，不代表完整抓取已经通过真机验收。

不依赖网页。终端指令逐条输入，观察每步结果后才输入下一条：

1. `connect`：连接现有 SDK，在当前测量关节位置保持；这一操作会使能电机。收到第一条机器人状态后会自动启动一次只读相机观察器。
2. `home`：低速回到已有实测 Home。`open`：空夹爪打开。
3. `hover`：先竖直到安全高度，再高处平移，最后到瓶子上方；到位后人工核对，不能直接输入后续步骤。
4. `descend`：仅下降；人工核对夹持位置。
5. `close`：仅闭爪，检查接触；不自动抬升。
6. `lift`：抬升约 8 cm，保持。现场确认瓶底离桌至少 5 cm 且保持至少 3 秒，才输入 `confirm success`。

正常流程不需要输入 `observe`。如果首次相机 seed 超时或观察器退出，可在确认机械臂已连接且静止后人工输入 `observe`。该命令只在没有机器人待决命令、控制器处于 `idle`/`aborted`、夹爪没有“可能持物”锁存、旧观察器已经退出且本次会话尚未锁定目标 ID 时启动一次新的只读观察器。它不会自动重试。若本次会话已经锁定目标，CLI 会拒绝重新 seed，避免检测 ID 被静默换绑；此时应结束当前会话并按新的完整监督会话重新选择目标。

空夹爪的常规打开使用 `open`。进入保持阶段，或闭爪过程中发生视觉/机器人故障而无法确认夹爪状态时，CLI 会锁存“可能持物”并拒绝普通 `open`、`home` 和再次抓取。现场人员先托住或取走瓶子并确认开爪不会造成掉落，再输入 `open supported`；只有收到开爪到位反馈后，CLI 才清除该锁存。`open supported` 会真实下发开爪命令，不能把它当作状态复位命令。

每次试验成功或失败已经写入结果后，可用 `new trial` 开始下一次试验。它要求 SDK 仍连接、机器人静止、没有待决命令或潜在持物，并且已有开爪到位证据；若现场已明确确认夹爪中没有物体但尚无开爪到位证据，可输入 `new trial empty`。该命令不重启 SDK/相机、不发送动作，保留同一物理瓶的锁定 ID，清除旧计划并要求新采集帧；同时清除 Home 验证，因此下一次运动前仍须重新执行并验证 `home` 和 `open`。该入口目前只通过 mock/离线回归，尚未完成真机验收。

保持阶段观察到失败时必须输入明确分类，例如 `confirm failure slip`。允许的分类为 `detection`、`depth`、`calibration`、`hover`、`descend`、`grasp`、`slip`、`robot_command`。该命令只记录操作员报告，不生成或替代视觉观测。

`status` 查看当前阶段及坐标。失败需记录具体原因（detection/depth/calibration/hover/descend/grasp/slip/robot command）；以 CLI 当前 `--help` 为准。`stop` 保留原软件停止方式；硬件急停由现场人员操作。

保持期间不要结束进程、关闭控制终端或直接断开 SDK。旧 SDK 的 cleanup 会失能，机械臂可能在重力下移动。只有现场人员已取走/支撑瓶子及机械臂，才输入 `quit supported`。这是一条已在旧实机记录中出现的行为。

## 本轮边界与证据

- 手眼矩阵的历史字段名错误已追溯：它实际以 SDK tool TCP 为父坐标系，详见 `artifacts/test1-coordinate-frame-evidence-20260908.md`。原标定文件和物理 approval 未被改为通过。
- 废弃的固定 Base XY 偏移 `[0.0475,0.01,0]` 不参与动作。观察器的 `base_xyz_m` 保留为每个新鲜静止帧测得的瓶身中心证据；固定高度计划只取它的 Base X/Y，并明确生成 `grasp=[rawBaseX,rawBaseY,0.13]`。预览分别打印 raw Base XYZ、`grasp_height_policy=fixed_base_z`、固定 Z 和最终六维动作 pose，不能把规则 Z 伪装成深度测量。
- 悬停阶段仍要求完整 RGB-D 坐标和新鲜静止 pose。在 Home 获得新鲜 RGB-D 并输入 `hover` 时，冻结同一目标、标定和试验的原始 3D 参考；悬停到位后仍需人工确认，再输入 `descend`；近处改用独立的 `bottle_projection_guard`，不会把 FK 投影填成真实深度。运动中检查新鲜 RGB 跟踪，下一短段和闭爪前要求停稳后的新帧、新鲜 pose 和投影一致；近处没有有效深度时也不能跳过这些检查。近场硬门禁包括同一目标 ID、外观和分割有效、投影位置误差不超过 12 px、投影点可见比例和掩膜支持比例均不低于 0.65、覆盖该帧的新鲜 pose，以及帧龄不超过 300 ms；目标丢失、身份/标定不一致或数据过期仍会锁止并禁止闭爪。`diagnostics.width_ratio` 比较的是稀疏 3D 参考点的全局投影分位宽度与当前瓶身跨肩/收腰行带掩膜的逐行中位宽度，统计定义不同，因此只保留为诊断证据，不生成 `projected_width_mismatch` 硬拒绝。CLI 近场分支不直接读取该宽度比或 `width_m`。RGB 投影只能约束当前图像中可观察的投影位置，不能证明沿相机光轴的全部位移；首次 hover 和 descend 仍分别需要现场人工核对。接触确认后，抬升检查的参考随实际 TCP 位移更新，姿态变化超限则拒绝。
- 工作空间限制针对 SDK tool TCP 和路线端点，不等同于全机械臂碰撞模型。每个动作打印目标位置和姿态；SDK 时长设置加裕度，但不是实测 TCP 峰速证明。
- 目标丢失、无效坐标、过期数据会阻止继续闭爪。SDK 无受支持的“中途取消轨迹并保持”接口，短段动作已经发出时可能完成当前段；之后的段和抓取阶段被锁止，硬件急停仍是立即停止手段。
- 新段/阶段只能使用帧龄不超过 300 ms 的完整坐标。在途相机看门狗使用独立的 500 ms 上限：本次实测输出间隔 120–187 ms，下一帧抵达前上一帧的采集年龄为 330–426 ms。两个检查都使用真实采集时间，不刷新历史帧时间。
- 人工 `hover` 批准后冻结的静态 3D anchor 最多有效 300 秒，从原始 `approved_at_ms` 固定计时且不会被后续帧刷新；超时必须开始新试验并重新取得 RGB-D 参考。该时限只给分阶段动作和人工确认留出余量，不改变上述 300/500 ms 逐帧新鲜度、目标丢失、身份、标定和投影门禁。
- 成功不能由 `command_complete` 或夹爪接触单独推出。必须有机器人抬升/保持证据和现场瓶底离桌确认。5 次至少 4 次的验收尚待真实试验。
- 本轮真实 Home/open 阶段记录为 `artifacts/supervised-bottle-grasp/test2-home-open-20260908.json`：Home 已验证，TCP 误差 6.03 mm、最大关节误差 0.007823 rad；随后 `open` 使用 `kp=2` 时反馈位置 0.956132 且 `reached=false`，该次试验按失败锁止。hover、descend、close、lift 均未执行，不能据此宣称 Test 2 全部通过。后续入口恢复历史已验证的开爪 `kp=8`，闭爪仍保持低刚度 `kp=2`，到位判据不放宽。
- 修正后的真实 Home/open 证据为 `artifacts/supervised-bottle-grasp/test2-home-open-corrected-20260908.json`：Home 再次通过，TCP 误差 5.546 mm、最大关节误差 0.007248 rad；`open` 使用 `kp=8`，约 0.31 s 到达 0.9932179（约 79.46 mm），`reached=true`。这只验证了 Home 和开爪。单瓶观察器 seed 随后连续报告 `depth_points_insufficient`，尚未锁定目标 ID；只读观察器已停止用于图像诊断，机器人 SDK 仍使能并保持 Home。hover、descend、close、lift 仍全部未执行。
- 第一次 Test 2 hover 尝试记录为 `artifacts/supervised-bottle-grasp/test2-first-hover-interface-abort-20260908.json`：只下发了第一条向上短段，目标增量约 18.53 mm，实测 TCP Z 增量约 12.37 mm；随后因当时 producer 在运动中清空 camera tracking 坐标而以 `grasp_height_transform_unavailable` 锁止。当前短段结束后没有发送后续段，descend、close、lift 均未执行。修复后的 producer→consumer 契约只通过离线 fixture，真机 hover 仍需重测。
- 后续真机试验 `a5c8deec-0b72-4b91-ba12-1de0e4668409` 和 `171b043f-6ea3-4893-8a2a-463f0857c99e` 均在 hover 阶段以 `projected_width_mismatch` 记录失败；当时目标 ID、外观、投影中心误差和支持比例仍有效。实图复核确认参考宽度和当前掩膜宽度使用了不同统计定义，因此该失败不能作为瓶子移动的证据。两次均未执行 descend、close 或 lift，也没有真实抓瓶成功。
- `artifacts/supervised-bottle-grasp/fov-audit-20260908/README.md` 是成对 L2 fixture 的离线重投影/IK 证据：pitch `0.8 rad` 在 safe/hover 位置保留足够可观测点，`safeTransitZ=0.306371896 m` 的完整纯数学 IK 路线通过，最小关节限位余量为 `8.237°`。到 `grasp Z=0.13 m` 时，瓶身 0.12/0.13 m 高度带样本全部因 camera depth 小于 `0.15 m` 被过滤；因此该证据只支持下一次 Test 2 hover，Test 3 descend 的近距视觉仍须单独真机验证，不能据此宣称完整抓取可用。
- 文件复用与历史实机进展：`artifacts/supervised-bottle-grasp/ubuntu-reuse-audit.md`。
- 本次 Test 1 原始记录：`artifacts/supervised-bottle-grasp/test1-v2-observations.jsonl`、`test1-plan-preview.json`。历史帧只供复查，不能重新标成新鲜数据执行。

复用的外部实现包括现有 Startouch SDK、XVisio SDK、GroundingDINO/SAM2 模型、OpenCV 的旋转矩形与 NumPy 点云统计。本次未引入新的机器人框架、模型或安装依赖；继续使用项目已安装的版本和原有许可证约束。

近场模块可独立断点调试：在 VS Code 选择 `Bottle: body geometry and nearfield guard (offline)`；或在 `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill` 运行 `/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest -q tests/vision/test_nearfield_guard.py tests/vision/test_supervised_nearfield.py`。`nearfield_guard.py` 负责 RGB/投影匹配，`supervised_nearfield.py` 负责参考身份、时间和接触后位移协议。这些离线检查不代表真实抓取成功。

2026-09-08 本次加载前检查：视觉、近场协议及相机流相关48项测试通过；plan、controller、CLI smoke通过。真实L2样本重放已通过producer→CLI合同测试，尚未算作真机成功。CLI的 `--simulate` 将pose/audit/result输出到独立的 `.simulate` 文件，避免覆盖实时机械臂pose或混入真实验收结果。配置和源文件哈希记录在 `artifacts/supervised-bottle-grasp/prepared-nearfield-20260908.json`。

后续真机调试已将 Home 关节容差从0.5°调整至0.6°：两次静止反馈最大误差均0.52457°，TCP误差2.47mm，原8mm位置限制保留。参见 `artifacts/supervised-bottle-grasp/home-steady-error-20260908.json`。控制入口已修复“段已结束而pending残留”的问题，可在失败后回Home并开始新一轮，避免因此重启SDK。当前SDK仍没有取消轨迹并保持的接口。
