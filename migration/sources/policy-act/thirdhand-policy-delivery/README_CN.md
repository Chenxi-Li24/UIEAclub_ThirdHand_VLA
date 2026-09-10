# ThirdHand Policy 模块（pick_and_place_bottle@1）

独立常驻服务，负责 `policy.action.request -> policy.action.result`。符合
`contracts/schema.json`，不直接控制机械臂——只产出 execution plan 交给
orchestrator，由 Robot 模块的 adapter 转成现有 `startouch_bridge.py` 命令。

## 我负责的消息类型

| 方向 | 类型 | source/target |
|---|---|---|
| 入站 | `policy.action.request` | orchestrator -> policy |
| 出站 | `policy.action.result` | policy -> orchestrator |
| 出错 | `service.error`（stage=policy） | policy -> orchestrator |

## 字段映射（Policy 内部 -> Schema）

| 内部 | Schema 契约 |
|---|---|
| 关节角（rad） | `actionChunk.steps[].jointsRad`，严格 J1..J6 六个数 |
| 夹爪 0-1 | `actionChunk.steps[].gripperNormalized`，**0=闭合 1=张开** |
| 单步时长 | `actionChunk.steps[].dtMs` |
| action space | 固定 `startouch-j1-j6-rad-gripper-v1` |

## 三种 policy kind

- `fixed_baseline`：输出 `fixedWaypointPlan`（`pick_zone_a -> drop_zone_b` 前半段，复用现有 YAML + bridge，无需模型）。
- `fake_act`：输出确定性 `actChunkPlan`（集成测试用，无模型）。
- `lerobot_act`：加载 LeRobot ACT checkpoint 输出 `actChunkPlan`（需 torch/lerobot + artifact store）。

**act_chunk 门控**（policy/policy.md）：`lerobot_act`/`fake_act` 只有在独立的
`startouch_action_chunk_adapter_v1` 已注册/可用（`THIRDHAND_POLICY_ACT_CHUNK_ADAPTER_AVAILABLE=1`）时才产出
`act_chunk`；否则回退到 `fixed_baseline`，回退不了就 fail-closed，绝不输出 Robot 无法执行的 `act_chunk`。

## 观测空间（lerobot_act）

技术方案 §6.3 固定了 ACT 的观测/动作空间，Policy 内部按此解析，**不使用单图**：

| feature | 来源 |
|---|---|
| `observation.images.ego_rgb` | 请求 `target.frameId` → `frames/<frameId>.npz` |
| `observation.images.target_mask` | 请求 `target.maskRef` → `masks/<maskRef>.npz`（二值 mask 转 3 通道 uint8） |
| `observation.state` `[7]` | 请求 `robotStateRef` → `states/<robotStateRef>.npz`（6 关节 rad + 夹爪） |
| `action` `[7]` | 策略输出（同 state 布局） |

checkpoint 的 feature 顺序 / 图像名 / action space 与上面不一致时**拒绝加载**（`incompatible_observation_space` / `incompatible_action_space`），不按文件名猜测。

## 环境与版本

- 学习环境：**Python 3.12 + LeRobot 0.6.0**（LeRobotDataset v3），与控制环境 Python 3.10 隔离。
- 服务本体（fixed_baseline / fake_act）不依赖 torch/lerobot，仅 `lerobot_act` 惰性导入。

## 运行

```bash
pip install -r requirements.txt
# 可选：启用 lerobot_act 时另装 torch/lerobot
THIRDHAND_POLICY_PORT=8080 python main.py
# 健康检查
curl http://localhost:8080/healthz
```

环境变量（不把 IP/端口写死在代码里）：

| 变量 | 含义 | 默认 |
|---|---|---|
| `THIRDHAND_POLICY_HOST` / `_PORT` | 监听地址 | `0.0.0.0` / `8080` |
| `THIRDHAND_POLICY_CHECKPOINT` | ACT checkpoint 目录（启用 lerobot_act） | 空 |
| `THIRDHAND_POLICY_ARTIFACT_DIR` | frames/states 存储（按 frameId/robotStateRef 引用） | 空 |
| `THIRDHAND_POLICY_DEVICE` | torch 设备 | `cpu` |
| `THIRDHAND_POLICY_DT_MS` | 单步时长 | `100` |
| `THIRDHAND_POLICY_ACT_CHUNK_ADAPTER_AVAILABLE` | `startouch_action_chunk_adapter_v1` 是否已注册 | `0` |

## 测试

```bash
python -m pytest tests/ -v
```

## 安全与失败处理

- 入站/出站都通过 `schema.json` 校验；生成非法结果直接返回 `service.error`。
- 目标授权校验（对齐 `VISION_TO_POLICY_HANDOFF` 清单）：**`label` 必须等于 `coke_bottle`**、
  `authorized=true`、`uniqueTarget=true`、`targetId/frameId/maskRef/robotStateRef` 齐全；
  非可乐、百事、通用 `bottle` 等一律 `target_not_authorized`。
- 不兼容 action space、checkpoint 缺失 → `service.error`，**不伪造 success**。
- 不确定（无法解析 frame/state 引用）→ 返回 failure/uncertain。
- 全程保留 `traceId`，`replyTo` 指回请求 `messageId`。
- Policy 不执行机械臂运动，`mode`（simulate/dry-run/real）如实回传。

## 真机规划前的已知缺口（Vision 侧待交付）

当前 Vision 只输出 2D bbox + mask，**尚未提供 robot_base 坐标系下的三维抓取位姿与标定 ID**。
因此 `lerobot_act` 现阶段只能走 dry-run/格式验证，真机抓取需等 Vision 把 mask 内 XVisio 深度
反投影成标定后的 3D 位姿并写入契约字段后才能启用。Policy 不从 2D bbox 猜 3D 坐标。
