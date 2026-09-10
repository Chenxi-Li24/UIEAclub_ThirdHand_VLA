# ThirdHand Policy 模块交接文档（HANDOFF）

> 读者：**Orchestrator 负责人** 及其 **AI 助手**
> 模块：Policy（`pick_and_place_bottle@1`）
> 版本：1.0 | 日期：2026-08-17

---

## 0. 一句话结论

Policy 模块是「**动作规划器**」：收 `policy.action.request`（已授权的可乐目标 + 机器人状态引用），回 `policy.action.result`（运动计划）。它**只出主意怎么动，不碰机械臂、不识别物体、不决定要不要执行**。

---

## 1. 在完整链路中的位置

Policy 是整条链路的**第 3 环**（Vision 之后、Robot 之前）：

```text
Language ──skill.candidate──▶ UI ──confirmation.decision──▶ Orchestrator
                                                              │
                                          vision.target.request │
                                                              ▼
                                                    Vision ──vision.target.result──▶ Orchestrator
                                                              │
                                          policy.action.request │          ← Policy 收这个
                                                              ▼
                                       【 Policy ──policy.action.result 】   ← 本模块
                                                              │
                                          execution.request   │
                                                              ▼
                                                    Robot ──execution.result──▶ Orchestrator
                                                              │
                                                    Verifier ──verification.result──▶ skill.result
```

- **上游**：Orchestrator 把「Vision 的授权目标 + 机械臂状态引用」打包成 `policy.action.request` 发来。
- **下游**：Policy 回 `policy.action.result`，Orchestrator 再把其中的 `executionPlan` 转成 `execution.request` 给 Robot。
- **Policy 不绕过 Orchestrator** 直接消费相机或控制机械臂。

---

## 2. 端口约定

| 端口 | 归属 | 说明 |
|---|---|---|
| **8080** | **Policy（本模块）** | 服务默认监听端口，可用 `THIRDHAND_POLICY_PORT` 覆盖 |
| 3211 | Vision | XVisio 服务（`GET /healthz`、`POST /v1/vision/target`） |
| 3000 | Robot / web-control | Startouch 网页控制（proxy.js，唯一 CAN/SDK owner） |
| 8000 | 仓库自带控制台 | FastAPI VLA 控制台 |
| 22 | — | SSH（部署/运维用，非业务端口） |

> Policy 服务默认监听 `0.0.0.0:8080`（局域网可访问）。若只想本机访问，设 `THIRDHAND_POLICY_HOST=127.0.0.1`。

---

## 3. 文件位置

**正式产出**在 Ubuntu PC（`192.168.58.68`）：

```text
/home/nieqingcao/thirdhand-policy/
```

目录结构：

```text
thirdhand-policy/
├── HANDOFF.md               ← 本文档
├── README_CN.md             ← 模块说明（消息类型、字段映射、运行方式）
├── main.py                  ← 服务启动入口（uvicorn）
├── requirements.txt         ← fastapi / uvicorn / jsonschema（lerobot 0.6.0 为可选）
├── thirdhand_policy/        ← 核心包
│   ├── __init__.py
│   ├── messages.py          ← policy.action.result / executionPlan / service.error 构造器
│   ├── schema.py            ← schema.json 加载与校验
│   ├── schema.json          ← 契约副本（唯一准则）
│   ├── policies.py          ← fixed_baseline / fake_act / lerobot_act 三种 kind
│   ├── act_runner.py        ← ACT checkpoint 加载 + 双图像观测解析 + 特征绑定校验
│   ├── handler.py           ← 核心：policy.action.request → policy.action.result
│   └── service.py           ← FastAPI：POST /v1/policy/action + GET /healthz
└── tests/                   ← 21 个用例（证明正确性）
    ├── test_handler.py
    ├── test_messages.py
    └── test_act_runner.py
```

---

## 4. 如何运行

### 4.1 依赖

```bash
pip install -r requirements.txt
# 仅当启用 lerobot_act 真机推理时才需要（另建 Python 3.12 + LeRobot 0.6.0 环境）：
# torch / torchvision / lerobot==0.6.0 / omegaconf
```

### 4.2 环境变量

| 变量 | 含义 | 默认 |
|---|---|---|
| `THIRDHAND_POLICY_HOST` / `THIRDHAND_POLICY_PORT` | 监听地址 | `0.0.0.0` / `8080` |
| `THIRDHAND_POLICY_CHECKPOINT` | ACT checkpoint 目录（启用 lerobot_act） | 空 |
| `THIRDHAND_POLICY_ARTIFACT_DIR` | frames/masks/states 存储（按 frameId/maskRef/robotStateRef 引用） | 空 |
| `THIRDHAND_POLICY_DEVICE` | torch 设备 | `cpu` |
| `THIRDHAND_POLICY_DT_MS` | 单步时长 | `100` |
| `THIRDHAND_POLICY_ACT_CHUNK_ADAPTER_AVAILABLE` | `startouch_action_chunk_adapter_v1` 是否已注册 | `0` |

### 4.3 启动

```bash
cd ~/thirdhand-policy
THIRDHAND_POLICY_PORT=8080 python3 main.py
```

### 4.4 Endpoints

```text
GET  /healthz               → {"status":"ok","service":"policy"}
POST /v1/policy/action      → 收 policy.action.request，回 policy.action.result 或 service.error
```

### 4.5 运行环境清单

| 项 | 实际值 |
|---|---|
| 部署机 Python | 3.8.10（Ubuntu 192.168.58.68） |
| 开发/测试机 Python | 3.14.6（本地） |
| CUDA / PyTorch / LeRobot | 未安装（`lerobot_act` 需另建 Python 3.12 + LeRobot 0.6.0 环境，含 torch/CUDA） |
| GPU 需求 | `fixed_baseline`/`fake_act` 不需要 GPU；`lerobot_act` 需要 RTX 5060 8GB |
| timeout | 契约 `timeoutsMs.policy = 15000ms`，调用方按此设置 HTTP 超时 |
| 并发限制 | 服务本身无状态可并发；act_chunk 的执行互斥由 Robot 模块的租约保证 |
| 认证 | 无（局域网内部服务） |
| 停止服务 | Ctrl+C（SIGINT/SIGTERM 优雅退出） |
| 环境变量模板 | 见包内 `.env.example` |

> 服务**不包含任何真实 token、密码、私钥或机器专用凭据**。

---

## 5. 消息契约（入站 → 出站）

### 5.1 入站 `policy.action.request`（source=orchestrator, target=policy）

```json
{
  "schemaVersion": "1.0",
  "type": "policy.action.request",
  "messageId": "msg:1",
  "replyTo": "msg:vision-result",
  "sessionId": "session:demo-001",
  "traceId": "trace:demo-001",
  "ts": 1786886198799,
  "source": "orchestrator",
  "target": "policy",
  "mode": "dry-run",
  "payload": {
    "candidateId": "candidate:pick-coke-001",
    "target": {
      "targetId": "coke:xvisio-frame-254cbb0af2fba3d5:0",
      "label": "coke_bottle",
      "confidence": 0.453051,
      "bbox": { "format": "xyxy", "coordinateSpace": "pixel", "values": [213, 368, 307, 478] },
      "maskRef": "file:mask_000.png",
      "frameId": "xvisio-frame-254cbb0af2fba3d5",
      "uniqueTarget": true,
      "authorized": true
    },
    "robotStateRef": "robot-state-42",
    "actionSpaceId": "startouch-j1-j6-rad-gripper-v1",
    "allowedPolicyKinds": ["fixed_baseline", "fake_act"]
  }
}
```

**必填字段校验**（Policy 会强制检查，不满足直接拒绝）：
- `target.label` 必须等于 `coke_bottle`
- `target.uniqueTarget` 必须为 `true`
- `target.authorized` 必须为 `true`
- `target.targetId` / `target.frameId` / `target.maskRef` 必须非空
- `payload.robotStateRef` 必须非空
- `payload.actionSpaceId` 必须等于 `startouch-j1-j6-rad-gripper-v1`
- 整条消息过 `schema.json` 校验（`schemaVersion="1.0"`、base 字段齐全）

### 5.2 出站 `policy.action.result`（source=policy, target=orchestrator）

```json
{
  "schemaVersion": "1.0",
  "type": "policy.action.result",
  "messageId": "msg:new",
  "replyTo": "msg:1",
  "sessionId": "session:demo-001",
  "traceId": "trace:demo-001",
  "ts": 1786886198799,
  "source": "policy",
  "target": "orchestrator",
  "mode": "dry-run",
  "status": "ready",
  "payload": {
    "candidateId": "candidate:pick-coke-001",
    "targetId": "coke:xvisio-frame-254cbb0af2fba3d5:0",
    "frameId": "xvisio-frame-254cbb0af2fba3d5",
    "policy": { "id": "fixed_baseline", "version": "1.0", "kind": "fixed_baseline", "checkpoint": null },
    "executionPlan": {
      "kind": "fixed_waypoint_a_to_b",
      "planId": "plan-xxx",
      "adapterId": "startouch_fixed_waypoint_adapter_v1",
      "bridgeRef": "web-control/server/startouch_bridge.py",
      "configRef": "configs/tasks/fixed_pick_place.yaml",
      "sourceWorkflow": "home_transit_ab",
      "sourceZoneId": "pick_zone_a",
      "destinationZoneId": "drop_zone_b",
      "routeStates": [
        "OPEN_GRIPPER_READY", "MOVE_HOME_START", "APPROACH_A_UP", "DESCEND_TO_A_PICK",
        "ADAPTIVE_GRASP_A", "LIFT_A", "TRANSFER_A_UP_TO_B_UP", "DESCEND_TO_B",
        "RELEASE_AT_B", "LIFT_AFTER_RELEASE_B", "RETURN_B_UP_TO_HOME"
      ],
      "cycles": 1,
      "confirmEachStep": true,
      "speedScale": 0.15
    }
  }
}
```

**回传规则**：
- `replyTo` = 触发请求的 `messageId`；`traceId` / `sessionId` / `candidateId` / `targetId` / `frameId` **原样保留**。
- `status` 只能 `ready` / `failure` / `uncertain`；`ready` 时必带 `executionPlan`。

### 5.3 完整字段映射表（PART C §4 要求，17 个字段全覆盖）

| 契约字段 | 入站（policy.action.request） | 出站（policy.action.result） |
|---|---|---|
| `schemaVersion` | 校验必须为 `"1.0"` | 原样写 `"1.0"` |
| `messageId` | 校验存在 | **生成新的唯一 ID** |
| `replyTo` | 校验存在 | **= 请求的 messageId** |
| `sessionId` | 校验存在 | 原样保留 |
| `traceId` | 校验存在 | 原样保留（全程不换） |
| `mode` | 校验为 simulate/dry-run/real 之一 | 原样保留 |
| `candidateId` | `payload.candidateId` | 原样回传 |
| `targetId` | `payload.target.targetId` | 原样回传 |
| `frameId` | `payload.target.frameId` | 原样回传 |
| `robotStateRef` | 校验非空 | 不回传；`lerobot_act` 用它从 artifact store 解析 `observation.state` |
| `actionSpaceId` | **必须等于** `startouch-j1-j6-rad-gripper-v1` | 写入 `actionChunk.actionSpaceId` |
| `allowedPolicyKinds` | 用于选择 kind | 不直接回传 |
| `policy.id/version/kind/checkpoint` | 按所选 kind 生成 | 写入 `payload.policy` |
| `executionPlan.kind` | 按 kind 决定 | `fixed_waypoint_a_to_b` 或 `act_chunk` |
| `planId` | 无 | **生成新的唯一 ID** |
| `adapterId` | 无 | `startouch_fixed_waypoint_adapter_v1` / `startouch_action_chunk_adapter_v1` |
| `speedScale` | 无 | 固定路线写 `0.15` |

**action space 固定约定**：`startouch-j1-j6-rad-gripper-v1`，J1–J6 按固定顺序、单位 **rad**；`gripperNormalized` 中 **0=闭合、1=张开**。违反即拒绝。

---

## 6. 三种 policy kind

| kind | 产出 | 前提 |
|---|---|---|
| `fixed_baseline` | `fixedWaypointPlan`（11 状态固定 A→B 路线，speedScale 0.15） | 无模型，随时可用 |
| `fake_act` | `actChunkPlan`（确定性假动作块，测试用） | `startouch_action_chunk_adapter_v1` 已注册 |
| `lerobot_act` | `actChunkPlan`（真实 ACT checkpoint 推理） | checkpoint 就绪 + act-chunk adapter 已注册 + artifact store 有帧/掩码/状态 |

**act_chunk 门控（重要）**：`lerobot_act` / `fake_act` 只有在 `startouch_action_chunk_adapter_v1` 已注册/可用时才产出 `act_chunk`；否则回退 `fixed_baseline`，回退不了就 `policy_unavailable`。**绝不输出 Robot 无法执行的 act_chunk。**

---

## 7. fail-closed 规则（错误处理）

| 场景 | 返回 |
|---|---|
| 目标 `label` ≠ `coke_bottle`（百事/通用 bottle 等） | `service.error`，code=`target_not_authorized` |
| `authorized` ≠ true 或 `uniqueTarget` ≠ true | `service.error`，code=`target_not_authorized` |
| `targetId`/`frameId`/`maskRef`/`robotStateRef` 缺失 | `service.error`，code=`target_not_authorized` |
| `actionSpaceId` ≠ `startouch-j1-j6-rad-gripper-v1` | `service.error`，code=`incompatible_action_space` |
| 允许的 kind 都不在本机可用 | `service.error`，code=`policy_unavailable` |
| checkpoint 缺失 / 动作空间不兼容 / 图像特征不匹配 | `service.error`，code=`checkpoint_missing` / `incompatible_*` |
| 消息过不了 schema 校验 | `service.error`，code=`bad_request` |

**原则：宁可不给计划，也不伪造 success。** 不确定就返回 `uncertain` / `service.error`。

---

## 8. Orchestrator 联调步骤

1. 起服务：`cd ~/thirdhand-policy && python3 main.py`。
2. 健康检查：`curl http://<host>:8080/healthz` → `{"status":"ok"}`。
3. 发请求：把 Vision 的 `vision.target.result` 里的 `target` + `robotStateRef` + `candidateId` + `actionSpaceId` + `allowedPolicyKinds` 组进 `policy.action.request`，`POST /v1/policy/action`。
4. 收结果：拿到 `policy.action.result`，取 `payload.executionPlan`。
5. 校验：用 `contracts/schema.json` 校验响应；或对照 `contracts/examples/demo_flow.json` 的第 5→6 条（msg-005→msg-006）。
6. 转发：把 `executionPlan` + `confirmed=true` + `safety` 组进 `execution.request` 发给 Robot。

---

## 9. 边界（Policy 做什么 / 不做什么）

**做**：
- 校验输入（目标授权、动作空间、schema）。
- 选 kind、产 `fixedWaypointPlan` 或 `actChunkPlan`。
- 保留 `traceId`/`replyTo` 链，fail-closed 拒绝非法输入。

**不做**：
- ❌ 不创建 CAN/SDK owner、不直连 `startouch_bridge.py`、不执行机械臂（那是 Robot）。
- ❌ 不识别「哪个是可乐」（那是 Vision）。
- ❌ 不决定「要不要执行」（那是 Orchestrator + 用户确认）。
- ❌ 不从 2D bbox 猜 3D 坐标；缺失 3D 位姿/标定时不产出真机抓取计划。

---

## 10. 测试与证据

- **21 个单元测试全部通过**（`pytest tests/`）。
- **官方 `demo_flow.json` 对照**：喂官方 msg-005（policy.action.request），产出与官方 msg-006（policy.action.result）**12 项字段全部一致**（type/status/source/target/kind/executionPlan.kind/adapterId/bridgeRef/routeStates/speedScale/traceId/replyTo），且通过 `schema.json` 校验。
- **真实 Vision 输出实测**：冒号 ID（`coke:xvisio-frame-...:0`）、`maskRef="file:mask_000.png"`、低 confidence 0.45 均正常处理；pepsi/bottle/unauthorized 均正确拒绝。

---

## 11. 已知缺口（需团队后续补齐）

1. **三维抓取位姿未交付**：Vision 目前只给 2D bbox + mask，还没给 `robot_base` 坐标系的三维位姿 + 标定 ID。因此 `lerobot_act` 真机抓取暂不可用，`fixed_baseline`（固定示教点）不受影响。该字段将来需加进 `schema.json` 的 `targetRef`。
2. **`lerobot_act` 真推理未验证**：需真实 ACT checkpoint + torch/lerobot 0.6.0 环境，尚未具备。
3. **Policy 服务未启动**：代码已部署在 Ubuntu PC `~/thirdhand-policy/`，联调时按第 4 节启动。

---

## 12. 给 Orchestrator 的 AI 的标准提示词

> 把下面这段连同本目录交给负责 Orchestrator 的 AI：

```text
你正在为 ThirdHand 的 pick_and_place_bottle@1 接入 Orchestrator 模块。

开始前必须完整阅读：
1. contracts/README_CN.md
2. contracts/schema.json
3. contracts/pick_and_place_bottle.skill.json
4. contracts/examples/demo_flow.json
5. HANDOFF.md（本文件，Policy 模块交接说明）

你的任务：实现 Orchestrator 的状态机与消息转发，不要重写任何模型或机器人算法。

与 Policy 模块对接的关键点：
- 你向 Policy 发 policy.action.request（source=orchestrator, target=policy），
  把 Vision 的 vision.target.result 里的 target 原样放进 payload.target。
- 你收 policy.action.result（status=ready 时取 payload.executionPlan），
  再组 execution.request（confirmed=true + safety）发给 Robot。
- 全程保留 traceId，replyTo 指向触发消息的 messageId。
- 没有 confirmed 决定不得生成 execution.request。
- Policy 返回 service.error 或非 ready 状态时，停止后续动作，不要跳过安全门。

硬性规则：
- 所有消息通过 contracts/schema.json 校验。
- 不得让 Language 直接触发 Robot。
- simulate / dry-run / real 必须如实标记。
- 找不到唯一 coke_bottle 时必须拒绝，不能换成其他物体。
- 接入和测试阶段不得开启真实机械臂运动。

请先输出：
1. 你负责的消息类型（Orchestrator 的 source/target 与全部入站/出站）；
2. 状态机设计（6 状态）与每个状态的输入/输出/失败规则；
3. 与 Policy 的字段映射表；
4. 失败、超时和重试处理；
5. 将要新增或修改的文件清单。

确认映射后再编码。完成后用 demo_flow.json 做一次无真机 dry-run，并给出从
skill.candidate 到 skill.result 的可复现样例。
```
