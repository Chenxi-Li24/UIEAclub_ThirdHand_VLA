# V/A 与 L 接口契约

## L -> VA

服务默认地址为 `http://127.0.0.1:8766`。正式启动请求：

```http
POST /api/va/start
Content-Type: application/json

{"schema":"thirdhand.va.command.v1","cmd":"start","target_id":2,"request_id":"L-0002"}
```

字段必须精确匹配，`target_id` 是当前画面显示的 Stable ID，范围 `1..5`。同一个
`request_id + target_id` 重试返回成功并标记 duplicate；存在不同活动请求时返回 409。

```http
POST /api/va/stop
Content-Type: application/json

{"schema":"thirdhand.va.command.v1","cmd":"stop","request_id":"L-stop-0001"}
```

```http
GET /api/va/status
```

状态 schema 为 `thirdhand.va.status.v1`，含 `active`、`target_id`、`request_id`、workflow
阶段和最后结果。只有 `RETURN_HOME` 完成才得到 `phase=complete, ok=true`。

## V -> A

唯一正式视觉 schema 是 `thirdhand-va-detection-v3`。关键字段：

```json
{
  "type": "detection_result",
  "schema": "thirdhand-va-detection-v3",
  "frame_id": 7,
  "monotonic_ns": 700,
  "request_id": "L-0002",
  "selected_stable_id": 2,
  "camera_serial": "250801DR48FP25002738",
  "registration_id": "xvisio-sdk:250801DR48FP25002738",
  "model_provenance": {
    "vision_config_id": "sha256:<64 hex>",
    "camera_registration_id": "xvisio-sdk:250801DR48FP25002738",
    "camera_mount_id": "lumos-ego-std:end-effector:installation-1",
    "grounding_model": "IDEA-Research/grounding-dino-tiny",
    "grounding_revision": "<40 hex>",
    "grounding_weights_sha256": "sha256:<64 hex>",
    "sam_model": "facebook/sam2.1-hiera-tiny",
    "sam_revision": "<40 hex>",
    "sam_weights_sha256": "sha256:<64 hex>"
  },
  "motion_epoch": 1,
  "evidence_id": "sha256:<64 hex>",
  "status": "ready",
  "robot_control_enabled": false,
  "targets": [{
    "stable_id": 2,
    "track_state": "confirmed",
    "selected": true,
    "depth_valid": true,
    "actionable": true,
    "blockers": [],
    "grasp_preview": {}
  }],
  "pose": {}
}
```

A 拒绝未知 schema、重复 Stable ID、选中关系不一致、旧 motion epoch、过期证据、深度
无效、未确认 track 或任何 blocker。传输 `robot_control_enabled=false` 是 V 无执行权的
声明，不是错误。

Camera bridge 只转发与启动时相机序列号、注册/安装 ID、标定 ID、视觉配置和全部模型
ID/revision/hash 精确一致的 detection。正式服务启动时从 `VISION_CONFIG` 和
`THIRDHAND_VA_HANDEYE` 指向的批准文件读取原始字节并计算内容 ID；workflow 在 `/start`
要求当前运行快照与这两个批准文件逐项一致，再逐帧复核。中途换标定、模型或配置会请求
软件停止，不能等动作结束后再由验收器判错。

A 在 Grasp 前把至少三帧 `vision evidence + preview + arm state`、同一基座检测点、加过一次
`flange_offset_base_m` 的法兰命令点、模型权重、
视觉/标定/Action/放置路径工件 ID 生成 `thirdhand-action-evidence-v1` 内容哈希。执行计划
只接受可重算且与实际点/姿态/宽度逐项一致的证据；最终成功结果必须原样携带该证据。

## A -> robot adapter

正式配置默认使用 `StartouchProcessClient`。Node 只负责高层状态机；它拉起项目内
`native/startouch/startouch_bridge.py`，由该子进程独占 CAN 和 Startouch SDK。bridge 首行
必须精确声明 `thirdhand-startouch-bridge-v1`、`thirdhand-robot-lowlevel-v1`、法兰位姿、单位、
backend 配置内容 ID 和 runtime 内容 ID，任何不一致都在首条动作前失败。每条 JSON line
只有一个对象，命令/完成回执用同一 `request_id` 关联。
命名 `preset` 在 adapter 内翻译为 `move_joint`，但完成事件必须恢复为 `command=preset`
并携带厂商 SDK 实测的 `actualJointsDeg`；启动和任务末尾都按配置 Home 六关节逐项比较，
任一关节超过批准容差都不能进入等待编号或报告成功。

真实模式不会隐式回退到模拟：只有 `startouch_process` backend、运行时完整批准以及精确的
`I_ACCEPT_SUPERVISED_ROBOT_MOTION` 授权同时满足时，factory 才会传入 `--real`。bridge 先校验项目内
SDK 资产、MIT 来源证据、安全配置精确哈希、可复现构建标志和实际加载的
`libstartouch.so`；然后独占 `/tmp/startouch-web-can0.lock`，并被动接收非本机回环的
`0x11..0x17` 全部反馈 ID。启动关节姿态必须保留至少 3° 限位余量。

`software_stop` 仅能回执 `cleanup_acknowledged=true`、
`cleanup_confirmation_mode=vendor_cleanup_returned` 和
`depower_independently_confirmed=false`。它证明 SDK cleanup 已返回并释放了该进程的控制权，
不证明电机物理掉电，也不能取代硬件急停；清理失败绝不伪造成功。

`websocket` 是显式的备选 backend，不是 Startouch 失败后的 fallback。其合同如下：

`RobotWebSocketClient` 白名单仅包含：

```text
move_l, move_joint, gripper, preset, software_stop, get_state
```

连接后 adapter 先发送带随机 nonce 的 `thirdhand-robot-capability-v1` 握手；对端必须精确
声明 `thirdhand-robot-lowlevel-v1`、上述命令集、米/rad/deg/米单位、关联完成回执和软件
停止确认，声明停止回执含 `applied_state_sequence + applied_producer_monotonic_ns` 边界，
并声明严格递增的 `uint53 state_sequence + producer_monotonic_ns` 状态流，否则不允许发送
任何命令。nonce 握手只接受一次，迟到或重复的 capability 回包视为协议错误。运动/夹爪
命令必须有非空 `request_id`，一次只允许
一个 in-flight 命令；完成或错误事件
必须关联相同 request ID 和 command，所有运动完成还必须有 `reached=true`。机器人状态
只有在 `moving=false` 且全部关节速度不超过 0.5 deg/s 时才算 stationary，并规范化为：

```javascript
{
  connected, moving, stationary, stateFresh, healthy,
  tcpPositionM, tcpEulerRad, jointsDeg, velocitiesDegS,
  gripperWidthM, stateSequence, producerMonotonicNs, observedMonotonicNs
}
```

重复/倒序/超龄生产端状态全部拒绝；软件停止必须先收到关联 ack，再看到生产端序号和时间
均严格越过该 ack 声明边界的新鲜静止状态。adapter 在发送停止命令时还会冻结当时已知
的生产端序号/时间下界；ack 声明的应用边界低于该下界同样拒绝，不能用本地重新接收的
旧消息确认停止。

当前本机 3000 浏览器协议尚未满足上述完整 WS 合同，因此没有把它当默认路径。
`configs/action.yaml` 仍保持关闭，因为物理标定、抓取偏移和放置路径还没有本轮真机证据。
离线协议入口为 `node scripts/action/debug_startouch_protocol.js --simulate`，固定放置计划入口为
`node scripts/action/debug_execution_plan.js --fixture tests/fixtures/integration/full-cycle.json`。

## 固定点放置合同

正式策略字符串为 `fixed_xy_keep_grasp_z`。A 从 Vision 接收瓶子检测点 `p_detected`，严格只加
一次已验证的 `flange_offset_base_m` 得到法兰抓取点 `p_flange`；放置点使用配置的固定 X/Y 和
`p_flange.z`。安全门会重新计算这一关系并检查 pregrasp、grasp、lift、pre-place、place、
retreat 六点的工作区，因而缺失偏移或重复加偏移都会拒绝。

## MJPEG 只读路由

- `GET /camera_lumos_vision`：算法叠加图。
- `GET /camera_xvisio_raw`：Lumos 原始 RGB。
- `GET /camera_xvisio_depth`：配准深度图。

相机未就绪时返回 503；这些路由没有机器人权限。
