# 普通瓶子 Skill 受监督真机验收

这份流程只用于获得现场证据，不是日常一键启动脚本。当前状态仍是
`hardware_validation=pending`：自包含 Startouch 进程的连接、状态、停止和小角度空载关节
动作已分别通过，但 Home、手眼抓取误差、抓取偏移、固定点和整条路径仍未获得物理批准。
`configs/action.yaml` 的执行和固定点门必须继续保持关闭，直到前置阶段全部通过。

## 适用场景与通过标准

- Lumos Ego STD/XVisio 是唯一眼在手上的 RGB-D 相机，序列号
  `250801DR48FP25002738`。
- 1--5 个普通不透明瓶子直立、彼此分开、轮廓清楚，位于已测量工作区。
- L/操作员只传画面 Stable ID `1..5`。
- 服务启动先回到同一 Home 并等待实测证明，之后才允许输入编号；每次成功必须完整抓取、
  固定点直立放置、撤离并再次回到该 Home。
- 至少 5 个贴有唯一实体标签、提前写入冻结清单的普通不透明瓶子。
- 30 个受监督随机允许位置；成功率至少 90%，错抓编号 0，身份切换 0，无效证据执行 0。
- 每个失败必须保存 phase、reason、evidence ID；闭合后失败由人处理，不自动张爪。
- 每个成功必须携带可重算的 `thirdhand-action-evidence-v1`，绑定本次基座点、三帧来源、
  模型/标定/Action/路径工件；无效证据计数必须为 0。

## 0. 离线门

```bash
cd $HOME/th0814/VA/bottlegrasp
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/runtime/preflight.py --json
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest \
  tests/common tests/vision tests/action tests/integration -q
npm test
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest \
  tests/hardware -q
node scripts/action/validate_pick_place.js --trials 1
```

最后两条在默认环境中应分别显示全部 `SKIPPED` 和 `blocked`/退出码 2。任何网络、相机或
机器人调用都说明授权门失效，必须先修门。

## 1. 相机与注册深度（只读）

清空机械臂工作区，保持机器人不动，由现场运行者明确执行：

```bash
bash scripts/vision/build_native.sh
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/camera_smoke.py --frames 30 --allow-camera
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/record_rgbd.py \
  --output artifacts/vision/recordings/generic-bottle --frames 30 --allow-camera
```

确认序列号、RGB/depth/XYZ 网格、帧递增和内容哈希。随后用有几何尺寸的现场目标检查
RGB 与深度，而不是只看画面“像是重合”：

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/validate_camera_alignment.py \
  --duration-s 60 \
  --output artifacts/validation/camera-alignment.json \
  --target-check-passed --allow-camera
```

没有人工量测通过时不得传 `--target-check-passed`，也不得进入手眼或动作阶段。

## 2. 眼在手上标定

先用受监督姿态采样工具采集足够旋转轴多样性的样本，再离线求解：

```bash
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/calibrate_handeye.py artifacts/calibration/samples.json \
  --output artifacts/calibration/lumos-tool.json
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/debug_calibration.py artifacts/calibration/lumos-tool.json
```

OpenCV `calibrateHandEye` 的数值通过只代表求解自洽。还必须使用未参与拟合的实际点或
抓取目标验证误差不超过 10 mm，然后由现场负责人把 physical status、相机安装 ID 和
`approved_for_bottle_grasp` 写入冻结标定文件。不要直接修改 fixture 冒充验收。

## 3. 机器人低层协议与固定点

在机械臂服务的假 WebSocket/模拟模式先验证：

- 只允许 `move_l/move_joint/gripper/preset/software_stop/get_state`；
- 每个运动/夹爪完成事件回传原 `request_id` 和 command；
- `move_l` 有实际 `reached`，`move_joint/preset` 有 `actual_joints_deg`，夹爪有实际归一化
  位置/宽度；
- 状态含 TCP 米/rad、关节 deg、速度、连接、健康、静止和新鲜度；
- 连接后必须完成带随机 nonce 的 `thirdhand-robot-capability-v1` 握手，精确声明低层协议、
  命令集、单位、关联完成回执、严格递增的生产端状态序号/单调时间和软件停止确认；
  对端还必须声明停止回执携带所应用的状态序号/生产端时间边界，重复 capability 回包拒绝；
  该边界不得早于发出停止时 VA 已收到的状态；`moving=false` 但关节速度超阈值不算静止，
  软件停止路径必须单独有效。

正式配置使用已验证过合同的项目内 Startouch 子进程；3000 浏览器入口不属于正式动作链路。
先空载、低速、逐步示教并验证启动回 Home、预抓取、固定放置、撤离回 Home 和整条路径。
固定点与 Home 必须实际示教和测量，禁止猜坐标。把测得的 place、pre-place、retreat、
姿态、`linear_speed_m_s`、`home_joints_deg`、`home_tolerance_deg`、逐关节允许的
`startup_joint_ranges_deg` 和
`startup_home_validated=true` 写入 `thirdhand-pick-place-path-validation-v2`，物理批准后
冻结文件并把其 SHA-256 填入 Action 配置；完成后才允许把 `place.validated` 和
`execution_enabled` 改为 true。

## 4. 启动正式 VA 服务

只有 1--3 全绿后，由现场运行者在受控终端设置：

```bash
CAMERA_PYTHON=$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
THIRDHAND_VA_ENABLE_CAMERA=1 \
THIRDHAND_VA_ALLOW_CAMERA=1 \
THIRDHAND_VA_HANDEYE=/绝对路径/lumos-tool.json \
THIRDHAND_VA_ENABLE_ROBOT=1 \
THIRDHAND_ALLOW_ROBOT=I_ACCEPT_SUPERVISED_ROBOT_MOTION \
node apps/bottle_pick/web_server.js
```

检查：

```bash
curl --fail http://127.0.0.1:8766/health
curl --fail http://127.0.0.1:8766/api/va/status
```

先观察 `home.phase` 从 `waiting_robot/homing` 变为 `ready`；只有这时
`robot_control_enabled` 才允许为 true，才能输入瓶子编号。`camera_ready` 也必须为 true。
服务启动时会直接读取并哈希
`VISION_CONFIG`（默认 `configs/vision.yaml`）和 `THIRDHAND_VA_HANDEYE` 指向的批准文件；
`artifacts` 中的相机序列号、安装 ID、标定、视觉配置、模型 revision/hash、Action 配置和
路径 ID 必须与这些冻结文件一致。
`bridge_ready` 只有第一帧完成模型推理后才会发出，之后超过 2 秒没有处理帧即失去就绪。
服务只绑定回环地址；不要端口转发到不受控网络。

## 5. 单次与 30 次验收

先让操作员摆好编号 1 的瓶子，执行一次 pytest smoke。下列两个环境变量是精确授权，
只在这次已清场、有人看护、有软件/硬件停止手段时设置：

```bash
THIRDHAND_LIVE_TEST=1 \
THIRDHAND_ALLOW_ROBOT=I_ACCEPT_SUPERVISED_ROBOT_MOTION \
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest \
  tests/hardware/test_live_va_skill.py -v
```

先建立实体瓶清单，例如 `artifacts/validation/specimens.json`：

```json
{
  "schema": "thirdhand-va-bottle-specimens-v1",
  "specimens": [
    {"specimen_id": "opaque-a", "description": "贴有 A 标签的不透明塑料瓶"},
    {"specimen_id": "opaque-b", "description": "贴有 B 标签的不透明塑料瓶"},
    {"specimen_id": "opaque-c", "description": "贴有 C 标签的不透明塑料瓶"},
    {"specimen_id": "opaque-d", "description": "贴有 D 标签的不透明塑料瓶"},
    {"specimen_id": "opaque-e", "description": "贴有 E 标签的不透明塑料瓶"}
  ]
}
```

清单至少包含 5 个不同实体，标签必须贴在瓶上并与 ID 对应，试验期间不得改写。然后运行
受监督 30 次验证器。每次它会要求操作员从清单中输入实体瓶 ID 和唯一位置标签、重新随机
摆放允许范围内的直立瓶子，并在动作后确认直立、错抓和身份切换：

```bash
THIRDHAND_LIVE_TEST=1 \
THIRDHAND_ALLOW_ROBOT=I_ACCEPT_SUPERVISED_ROBOT_MOTION \
node scripts/action/validate_pick_place.js \
  --allow-robot \
  --target-id 1 \
  --trials 30 \
  --calibration artifacts/calibration/lumos-tool.json \
  --specimens artifacts/validation/specimens.json
```

验证器只调用回环 `/api/va/*`，不直接发机械臂 WebSocket 命令。任务启动后的任何网络、
非 JSON、状态关联或超时异常都会触发关联 `/api/va/stop`；只有确认 workflow inactive 且
health 重新报告机器人就绪静止后才退出，并中止后续 trial。报告原子写入
`artifacts/validation/generic-bottle/<run-id>/report.json`，包含环境、配置/标定哈希、
实体瓶清单哈希、每次 result/operator confirmation 和汇总；原始 RGB-D 与报告默认不提交
Git。正式 30 次通过还要求至少 5 个预登记实体瓶、30 个不重复位置标签，并由绑定动作证据
中的实际 XY 抓取点证明至少 27 个位置彼此相隔 30 mm；同一瓶、同一点重复运行不能冒充
验收覆盖度。

## 停止与恢复

任务仍活跃时优先执行：

```bash
node apps/bottle_pick/run.js stop
```

确认机械臂停止后再处理瓶子。闭合后失败必须按 `manual_recovery` 由现场人员托住瓶子并
按机器人操作规程恢复，不要通过重启脚本强制张爪/Home。验收结束后停止 VA 服务，并把
Action 配置恢复为 `execution_enabled=false`，除非现场负责人明确批准部署状态。
