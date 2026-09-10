# A（Action）模块说明

A 只消费版本化 Vision 结果和标准化机器人状态。真实机器人访问必须经过 adapter 注入；
库文件不建立 WebSocket、不调用 `process.exit()`。

| 模块 | 职责 | 输入 -> 输出 | 独立入口与预期结果 |
|---|---|---|---|
| `calibration` | OpenCV 眼在手上求解、法兰语义导入、内容哈希和物理门 | 标定样本/文件 -> `T_flange_camera` | `debug_calibration.py` 输出验证状态，pending 文件不得放行 |
| `observation` | request-bound Stable ID、深度和 epoch 锁 | v3 targets -> 同一瓶的新鲜基座点 | observation 单测；跨 ID/旧 epoch 必须拒绝 |
| `alignment` | 到预抓取位、静止、重观察和微调 | target lock + robot state -> `move_l`/handoff | `debug_alignment.js` 输出四个阶段和假命令 |
| `safety` | Home 启动协调、Home 实测门、工作区和执行证据门 | robot state/execution context -> blockers/allowed | `debug_home.js` 与 safety 单测；不在 Home 不接收编号 |
| `evidence` | 绑定本次执行的视觉帧、基座点和冻结工件 | handoff + config IDs -> 内容寻址证据 | evidence 单测篡改任一字段必须失效 |
| `grasp` | 固定 XY/动态 Z 路径、不可变计划和九阶段抓放状态机 | approved plan + robot events -> complete/recovery | `debug_execution_plan.js`/`debug_grasp.js` 输出路径和九个命令 |
| `adapters` | Vision、camera、Startouch 子进程或显式 WS 边界 | wire message <-> normalized event | adapter 测试校验 schema/白名单/request ID |
| `native/startouch` | 校验项目内 SDK 运行时、独占 CAN、验证真实入站反馈、状态采样与 SDK cleanup | 严格 JSON-lines 命令 -> 关联回执/状态 | 模拟入口通过同一 `thirdhand-startouch-bridge-v1` 协议，不碰硬件；cleanup 不声明电机掉电 |
| `operator` | 单任务、幂等、状态原子写入 | L command -> workflow/status | controller 单测与 `/api/va/status` |
| `workflow` | 组合 alignment、gate、plan、grasp | `target_id + request_id` -> complete/failed | `debug_workflow.js` 输出完整轨迹 |

## 直接运行

```bash
python scripts/action/debug_calibration.py \
  tests/fixtures/calibration/pending-handeye.json

node scripts/action/debug_home.js \
  --home 0,15,-30,5,0,0 \
  --actual 0.2,14.7,-29.6,4.8,0.1,-0.2 \
  --tolerance 0.5

node scripts/action/debug_pregrasp_validation.js \
  --fixture tests/fixtures/action/handeye-clearance.json

node scripts/action/debug_alignment.js \
  --target-id 2 --fixture tests/fixtures/action/alignment.json

node scripts/action/debug_grasp.js \
  --fixture tests/fixtures/action/approved-plan.json

node scripts/action/debug_execution_plan.js \
  --fixture tests/fixtures/integration/full-cycle.json

THIRDHAND_VA_PYTHON=/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  node scripts/action/debug_startouch_protocol.js --simulate

node scripts/action/debug_workflow.js \
  --target-id 2 --fixture tests/fixtures/integration/full-cycle.json
```

## 推荐断点

- 标定：`calibration/solver.py` 的 OpenCV 求解与 held-out 验证。
- 锁定：`observation/base_target_lock.js` 的 `observe`/`resetEvidence`。
- 对准：`alignment/visual_align_controller.js` 的 `_sendPregrasp`、`_refineOrHandoff`。
- Home：`safety/home_coordinator.js` 的 `_attempt`/`onRobotEvent`，以及
  `safety/home_gate.js` 的 `evaluateHomeState`。
- 其他安全门：`safety/execution_gate.js`，逐项查看 blocker。
- 抓取：`grasp/grasp_controller.js` 的 `onRobotEvent` 和 `_sendCurrentPhase`。
- 完整链路：`grasp/workflow.js` 的 `_startGrasp` 与 `_finish`。
- 动作证据：`evidence/action_evidence.js` 的 `buildActionEvidence`/`validateActionEvidence`。
- 固定放置：`grasp/execution_plan.js` 的 `deriveExecutionGeometry`；可对比检测点、偏移后法兰点和放置点。
- Startouch 进程：`adapters/startouch_process_client.js` 的 `_onStdout`/`send`。
- SDK/CAN：`native/startouch/backends.py` 的 `CanOwner`、`SdkBackend`（仅受监督真机调试）。

`debug_alignment.js`、`debug_grasp.js`、`debug_workflow.js` 中的 robot client 都是内存假对象；
输出中的命令用于检查，不会发往 CAN 或 3000 端口。`debug_startouch_protocol.js` 只允许
`--simulate`；真实 bridge 必须同时给出 `--real` 和精确授权短语。夹取接触验证使用实际宽度区间，闭合后失败
进入 `manual_recovery`，不会擅自释放瓶子。

`calibration/pregrasp_validation.js` 是碰撞后的独立高位检查授权器。它忽略候选
`flange_offset_base_m` 和正式抓取姿态，只允许 `safe_height → over_target_clearance` 两段，
两段均保持授权瞬间实测法兰姿态且 Z 不下降；在生成计划前再次校验六关节 Home。对应真机脚本
不发夹爪命令，生成的 `thirdhand-handeye-clearance-observation-v1` 报告明确不能用于激活手眼
标定。事故前的 `thirdhand-handeye-pregrasp-validation-v1` 已被审批模块拒绝。

## 放置点与三道物理门

候选固定点取自已有安全观测路径：`X=0.26783482212847776 m`、
`Y=0.010668622392713049 m`。策略 `fixed_xy_keep_grasp_z` 保留本次抓取 Z，以适配普通瓶子的
桌面高度；pre-place/retreat 在 Z 方向增加 `0.10 m`。这只是确定性的候选方案，不是已验证
的真机路径。执行前必须分别生成并批准：

1. 与当前 Lumos 安装关系一致的法兰手眼工件；
2. `flange_offset_base_m` 的实测结果；
3. 绑定固定 XY、Z 范围、净空、姿态、速度、Home 六关节值、容差、允许启动回 Home 的
   六关节起始范围 `startup_joint_ranges_deg` 和 `startup_home_validated=true` 的
   `thirdhand-pick-place-path-validation-v2` 工件。

三个门缺少任意一个，`execution_enabled=true` 也不能绕过 fail-closed 校验。
服务启动后先由 `HomeCoordinator` 发送一次命名 Home；只有厂商 SDK 返回的
`actual_joints_deg` 六关节全部落入批准容差，`/health` 和 `/api/va/status` 中的
`home.phase` 才变为 `ready`，此时编号输入才会被接受。每次完整动作最后也执行同样的
实测校验，而不是仅凭“回 Home 指令已发送”判成功。
机械臂若不在 Home 且当前关节超出批准的启动范围，协调器直接报
`startup_pose_outside_validated_range`，不会尝试从未知姿态自动回 Home。
