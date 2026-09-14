# ThirdHand 统一 Platform 与 Skills 项目重组设计

日期：2026-09-10
状态：设计已由用户逐节批准，尚未开始源码迁移

## 1. 背景

当前可用能力分散在 Ubuntu 主文件夹的多个目录中：

- `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA`：现有 Startouch 网页控制、部分 VLA 框架、视觉实验和受监督夹取入口。
- `/home/nieqingcao/Thirdhand_language`：当前正式且唯一可运行的 Language Part，包含 9983 网页、3004 Voice/Language 服务、三种 ASR 模型、独立 Python/Node 运行环境和运维脚本。
- `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill`：XVisio RGB-D、检测、稳定目标身份、三维几何、监督、安全和瓶子抓放实现。
- `/home/nieqingcao/thirdhand-policy-integration-20260817-01`：ACT 消息契约、服务、checkpoint 加载器和离线测试原型。
- `/home/nieqingcao/TH-Fanxy`：仍被部分脚本引用的旧 Startouch 适配实现。
- `/home/nieqingcao/arm/startouch_sdk`：授权情况不明确的 Startouch SDK 源码和二进制。
- `/home/nieqingcao/FastUMI_Hardware_SDK`：当前 XVisio 原生采集所需外部依赖。
- `/home/nieqingcao/calibration` 及 `th0814` 内标定目录：相机内参、手眼关系、原始图像和历史结果。

实时夹取流程目前跨多个项目和 Conda 环境运行，并存在绝对路径、重复实现、运行产物混入源码目录、能力成熟度不清楚等问题。本设计将所有正式第一方代码归入 `Oliveirah007/UIEAclub_ThirdHand_VLA`，使其成为唯一正式仓库。

统一项目在 Ubuntu 上固定落到 `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`。该目录是独立 Git checkout，不是旧工程的 worktree 或符号链接；其 `origin` 指向 `Oliveirah007/UIEAclub_ThirdHand_VLA`，并以 `upstream` 保留 `Chenxi-Li24/UIEAclub_ThirdHand_VLA`。旧目录只作为迁移输入读取，迁移过程不得移动、改写、清理或删除旧目录中的任何文件。

## 2. 已确认目标

正式支持以下能力：

1. 9983 统一网页控制。
2. 3000 Startouch 机械臂及夹爪控制和维护页面。
3. 3100 XVisio RGB-D 实时视觉、目标选择和稳定身份。
4. 3004 本地 ASR、TTS 和语音指令。
5. 受监督瓶子抓取与放置。
6. 中央 LLM 任务理解、规划、Skill 选择和调度。
7. 可替换的 VLA、ACT、Diffusion Policy 等策略 Skill。
8. 主动视角和自动夹取。
9. 独立视觉执行监督；发现失败时中断任务并反馈用户。

当前版本不做自主恢复。任务中断后必须返回用户，重新规划和授权后才能继续。

## 3. 非目标和历史范围

以下内容不参与正式安装、导入、启动和默认测试：

- 法奥机械臂实现。
- 旧 D435/Lumos 双相机链路和 ROS 深度桥。
- 旧 9981/3002 Language 工程和旧 voice-bridge 环境。
- 重复的固定点演示、废弃视觉实现和只用于历史实验的入口。
- 旧工程中的 Conda 环境、`node_modules`、构建缓存和运行日志。

这些内容统一进入 `archive/`。每个归档项必须记录来源路径、日期、原 Git 状态、归档原因和正式替代模块。正式代码和测试不得引用 `archive/`。

## 4. 总体架构

系统采用“常驻 Platform 服务、可插拔 Skills、中央 LLM 编排”的模块化单仓库架构。

```text
用户语音/文字
      |
      v
9983 Web Gateway
      |
      v
LLM Orchestrator
      |
      v
Skill Registry ----> 任务计划与风险摘要 ----> 用户一次授权
      |
      v
Skills
      |
      v
Platform Services
  |- robot-service
  |- vision-service
  |- speech-service
  |- model-service
  `- execution-supervisor
      |
      v
Startouch / XVisio / 音频 / 模型运行时
```

执行 `./thirdhand start` 后，基础服务和所有已启用且资源完整的 Skill worker 保持在线。系统不使用 systemd，不随 Ubuntu 开机启动。

### 4.1 服务责任

- **Web Gateway**：唯一普通用户入口，提供网页、WebSocket、任务状态、视觉画面、目标选择、计划预览和授权操作。
- **LLM Orchestrator**：理解目标、查询 Skill 清单、调用只读感知、生成任务步骤并调度 Skill。它不得直接发送关节角、夹爪值或 CAN 命令。
- **Skill Registry**：扫描 Skill 清单，发布用途、Schema、风险等级、依赖、版本和当前可用状态。
- **Robot Service**：独占 `can0` 和 Startouch SDK，统一处理机械臂状态、关节运动、夹爪、限位、速度、反馈连续性和停止。
- **Vision Service**：持续采集 XVisio RGB-D，维护检测、分类、分割、三维坐标和跨帧稳定目标身份。
- **Speech Service**：提供 ASR 和 TTS，不再内置 Claude 或任务规划。语音和网页文字统一进入中央 LLM。
- **Model Service**：管理云端及本地模型适配、资源检查、健康状态和统一推理接口。
- **Execution Supervisor**：独立消费视觉和机器人状态，发现失败时可中断任务，但不自主恢复。

## 5. 目标目录结构

```text
UIEAclub_ThirdHand_VLA/
|- thirdhand
|  # 唯一运维命令。提供 setup-assets、verify-assets、start、stop、restart、
|  # status 和 doctor；不要求用户分别进入 Python 或 Node 子目录。
|
|- apps/
|  |- web/
|  |  # 正式 9983 页面。来源以 Thirdhand_language 为准，整合语音、任务计划、
|  |  # 风险摘要、授权、视觉画面、目标选择、三维模型和执行状态。
|  |- robot-console/
|  |  # 保留 3000 原手动控制页面，仅供维护、标定和故障诊断。
|  |- orchestrator/
|  |  # 中央 LLM 应用。只通过 Platform 契约和 Skill Registry 工作，不直接访问硬件。
|  `- launcher/
|     # 原生 Ubuntu 进程管理器。负责预检、启动顺序、PID、日志、健康检查和停止顺序。
|
|- platform/
|  |- contracts/
|  |  # TargetRef、Skill 请求、计划、风险、授权、事件、动作候选和结果的版本化 Schema。
|  |- skill_registry/
|  |  # 自动发现 skills/*/manifest.yaml，校验清单并向 LLM 发布能力。
|  |- task_engine/
|  |  # 任务状态机：规划、待授权、执行、完成、中断和失败。
|  |- authorization/
|  |  # 一次任务一次授权；授权绑定 plan_id、revision、target_ref、动作范围和有效期。
|  |- resources/
|  |  # 设备、SDK、模型、checkpoint、运行时和文件资源的版本及健康状态。
|  `- audit/
|     # 保存 trace_id、任务计划、授权、Skill 调用、运动命令、监督事件和失败原因。
|
|- services/
|  |- robot/
|  |  # 3000 Startouch 服务。唯一 SDK/CAN 所有者；连接时不得自动回零或运动。
|  |- vision/
|  |  # 3100 XVisio 服务。包含采集、检测、分类、分割、跟踪、深度和三维定位。
|  |- speech/
|  |  # 3004 ASR/TTS 服务。保留 Medium、Real-time、High 三种 ASR 模型。
|  |- model/
|  |  # 模型提供者、模型选择、健康检查和推理适配；不承担任务授权。
|  `- supervisor/
|     # 常驻独立监督和停止决策；监督不可用时锁定自动运动。
|
|- skills/
|  |- vision/
|  |  |- describe-scene/
|  |  |  # 生成结构化场景描述；只读，不产生运动。
|  |  |- detect-objects/
|  |  |  # 识别物体种类，返回稳定 TargetRef、置信度和可用三维信息。
|  |  `- supervise-execution/
|  |     # 为任务配置监督目标和判定规则；实际停止权限仍在 Supervisor Service。
|  |- manipulation/
|  |  `- pick-and-place/
|  |     # 完整抓放能力：观察、选目标、规划、授权、执行、监督和结果验证。
|  `- policies/
|     |- vla/
|     |  # 大模型视觉动作策略，与中央任务规划 LLM 分离。
|     |- act/
|     |  # ACT checkpoint 加载和动作块输出；缺少权重时明确显示 unavailable。
|     `- diffusion-policy/
|        # DP 推理边界；缺少实现或权重时明确显示 unavailable。
|
|- drivers/
|  |- startouch/
|  |  # 本项目拥有的适配层、CAN 锁、状态过滤、限位和 SDK ABI 检查；不复制未授权源码。
|  |- xvisio/
|  |  # FastUMI/XVisio 原生采集、时间同步和错误映射。
|  `- audio/
|     # 浏览器 PCM、麦克风和扬声器适配。
|
|- configs/
|  # 设备、端口、模型、Skill、安全、任务和已批准标定配置。机密值只放本地配置。
|- assets/robot/
|  # 可公开的 URDF、STL、材质、关节限位、速度上限和坐标系说明。
|- local/
|  |- sdk/startouch/
|  |- vendor/funasr/
|  |- models/asr/{medium,realtime,high}/
|  |- models/policies/{vla,act,dp}/
|  `- runtimes/{python,node}/
|     # Ubuntu 上实际存在的一键运行资产。目录位于项目内，但默认不提交公开 Git。
|- runtime/
|  # PID、socket、日志、录音、图像、深度、点云、缓存和任务结果；全部忽略。
|- tools/
|  # 资产导入、安装、诊断、标定、迁移、哈希和兼容性检查。
|- tests/
|  # unit、contract、integration、simulation 和 hardware 分层测试。
|- archive/
|  # 历史源码和说明。不得被正式代码、启动器或默认测试导入。
`- docs/
   # 架构、Skill 开发、环境、端口、操作、安全、验收和迁移记录。
```

## 6. Skill 模型

Skill 是 LLM 可发现和调用的语义能力，基础相机、语音、跟踪和机器人状态由常驻服务提供。每个 Skill 是可独立增删的目录，至少包含：

```text
skills/<group>/<skill-id>/
|- SKILL.md          # 给 LLM 的用途、限制、使用条件和失败语义
|- manifest.yaml     # ID、版本、风险、生命周期、依赖、入口和健康检查
|- schemas/          # 输入、计划和结果 Schema
|- src/              # Python 或 Node 实现
`- tests/            # 独立测试
```

示例清单：

```yaml
id: manipulation.pick-and-place
version: 1.0.0
summary: 受监督的目标抓取与固定位置放置
risk: physical-motion
lifecycle: worker
runtime: node
operations: [plan, execute, status, cancel]
requires:
  services: [robot, vision, supervisor]
  devices: [startouch, xvisio]
  models: []
schemas:
  input: schemas/input.json
  plan: schemas/plan.json
  result: schemas/result.json
entrypoint: src/worker.js
healthcheck: status
```

LLM 选择语义 Skill，Platform 在 Skill 内根据硬件、GPU、模型可用性和配置选择具体实现。高带宽图片、深度和张量不通过 Skill 消息传输，只传 `frame_ref`、`mask_ref`、`target_ref` 和 `robot_state_ref`。

## 7. 稳定目标身份

稳定目标身份属于 `services/vision` 的基础设施，不作为 LLM 通常直接调用的 Skill。检测 Skill 返回由目标注册表维护的引用：

```json
{
  "target_ref": "target-7",
  "class": "bottle",
  "label": "L1",
  "confidence": 0.94,
  "last_seen_at": "2026-09-10T12:00:00+08:00",
  "pose_revision": 12
}
```

场景描述、监督和夹取引用同一个 `target_ref`。目标丢失、过期、重新识别或位姿版本变化时，Platform 使旧引用失效。运动计划不得使用过期坐标。

## 8. 任务、计划与授权流程

```text
用户输入
  -> ASR 或网页文字
  -> 中央 LLM 提取目标并查询 Skill Registry
  -> 按需调用 describe-scene / detect-objects
  -> 选择操作 Skill 并只调用 plan
  -> Skill 返回不可变计划和风险摘要
  -> 9983 页面请求用户授权
  -> 授权绑定计划版本、目标身份和有效期
  -> Task Engine 调用 execute
  -> Supervisor 同时监督
  -> 完成，或中断后反馈用户
```

任何可能使机械臂或夹爪运动的 Skill 都必须先生成计划和风险摘要。用户一次授权只覆盖该计划；计划、目标、动作范围或状态发生变化时授权失效。只读视觉 Skill 可以直接调用。

Supervisor 始终有权请求停止。停止后不自主恢复，也不得复用原授权。软件停止依赖浏览器、进程、网络、操作系统和 CAN，不替代独立硬件急停。

## 9. 策略 Skill 安全边界

VLA、ACT 和 DP 只输出版本化动作候选或动作块，不能直接打开 CAN。Robot Service 在实际发送前必须再次检查：

- 任务授权和计划版本。
- J1-J6 关节范围和速度上限。
- 起始状态与计划状态连续性。
- CAN 反馈新鲜度和 SDK 状态。
- 突发全零目标保护。
- 夹爪范围及状态。
- Supervisor 在线和本任务监督状态。

当前没有完整 VLA/ACT/DP 模型交付。ACT 已有契约、加载器和测试原型，迁移后仍应标记为缺少 checkpoint；VLA 和 DP 先建立接口和不可用状态。不得把 SDK 示例或 fake policy 标记为正式策略能力。

## 10. 语音设计更新

`/home/nieqingcao/Thirdhand_language` 是唯一正式语音来源，取代 `TH_new_asr_0820`、旧 9981/3002 工程和旧 voice-bridge。

保留三种 ASR：

| 页面名称 | 技术实现 | 设备 | 用途 |
|---|---|---|---|
| Medium | Whisper Small | CUDA | 默认，中英文整句识别 |
| Real-time | Paraformer | CPU | 中文流式识别、降低显存占用 |
| High | Fun-ASR-Nano | CUDA | 高精度实验模式、显存占用较高 |

3004 启动时默认加载 Medium。任一客户端录音期间禁止切换模型，切换时先卸载旧模型再加载新模型。旧实现中 3004 直接调用 Claude 的逻辑要拆除，最终文本统一交给中央 LLM Orchestrator。TTS 作为 Speech Service 的输出能力保留。

## 11. SDK、模型和运行时资产

用户要求 SDK 和模型文件位于项目目录中，以便 Ubuntu 一键运行。由于 Startouch SDK 授权情况不明确且模型体积很大，采用两层交付：

1. Ubuntu 工作目录中的 `local/` 包含实际 SDK、模型、FunASR 源码和独立 Python/Node 运行时。
2. 公开 GitHub 跟踪目录说明、来源、版本、许可证记录、哈希清单和导入/验证工具，不跟踪未确认授权的 SDK、模型权重和平台相关运行环境。

`./thirdhand setup-assets` 从用户指定位置导入或验证资产，不在普通启动过程中隐式下载。`./thirdhand verify-assets` 检查：

- 来源和许可证记录。
- 文件尺寸及 SHA-256。
- Python ABI 和本机架构。
- Ubuntu 版本、glibc、CUDA、NVIDIA 驱动和 PyTorch 组合。
- SDK 动态库依赖和 Startouch Python 扩展可导入性。
- ASR/策略模型所需文件是否完整。

## 12. 启动、端口和生命周期

统一命令：

```bash
./thirdhand setup-assets
./thirdhand verify-assets
./thirdhand start
./thirdhand status
./thirdhand stop
```

端口：

| 端口 | 所有者 | 用途 | 默认范围 |
|---:|---|---|---|
| 9983 | Web Gateway | 正式网页和统一 WebSocket | 局域网或 SSH 隧道 |
| 3000 | Robot Service | Startouch API 和维护页面 | `127.0.0.1` |
| 3100 | Vision Service | XVisio 视频、深度、检测和诊断 | `127.0.0.1` |
| 3004 | Speech Service | ASR/TTS WebSocket | `127.0.0.1` |

启动顺序为：资产预检、Robot、Vision/Speech/Model/Supervisor、Skill workers、Skill Registry、LLM Orchestrator、Web Gateway。Robot Service 启动后只建立状态和控制权，不自动回零或运动。

重复执行 `start` 不得启动第二套服务。停止时先撤销授权和取消任务，再停止 Skill、模型、语音和视觉，最后释放 Robot Service 和 CAN 控制权。

## 13. 故障与降级

网页应尽量启动并显示每个模块的健康状态和修复建议。所有运动能力采用失效关闭：

- Vision 故障：锁定视觉夹取和所有策略运动，保留维护页面。
- Speech 故障：保留文字输入、视觉和维护控制。
- LLM 故障：保留只读状态和维护页面，不允许复用旧候选绕过规划授权。
- Robot/CAN/SDK 故障：锁定所有运动，视觉和语音仍可运行。
- Supervisor 故障：锁定自动、VLA、ACT、DP 和主动视角运动。
- Skill worker 故障：只将该 Skill 标记 unavailable，不伪造成功结果。
- 任一安全关键服务恢复后，旧计划、授权和 TargetRef 全部失效。

Launcher 可以重启空闲服务，但不得自动恢复被中断的任务。

## 14. Ubuntu 支持范围

- Ubuntu 20.04 是当前真机正式环境。
- Ubuntu 22.04 是源码和安装脚本的兼容目标。
- 22.04 在取得匹配的 Startouch SDK 二进制并完成硬件验收前，不标记为真机已验证。
- 不把 20.04 的 Conda、Python 扩展或 Node 运行目录直接认定为 22.04 可用；必须通过资产验证并按需重建。

## 15. 迁移顺序

迁移先在全新的 `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA` 中进行。所有来源内容均复制到新目录，不在新项目中建立指向旧项目的符号链接。SDK、模型和运行时也复制进新项目的 `local/`，保留来源、哈希和许可证状态记录。初始验证不得停止或替换现有服务，须使用备用端口；正式端口切换和旧服务停止由用户在验收后另行批准。

1. 建立目标目录、公共契约和资产清单。
2. 以 `Thirdhand_language` 接入最新版 9983 页面和 3004 Speech Service。
3. 接入当前 3000 Startouch 服务和维护页面，消除对 `TH-Fanxy` 的运行时引用。
4. 以 `PinZiZhuaQuSkill` 接入 3100 XVisio、稳定身份、RGB-D 和 Supervisor。
5. 封装 `describe-scene`、`detect-objects`、`supervise-execution` 和 `pick-and-place`。
6. 接入中央 LLM、Skill Registry、Task Engine 和一次性授权。
7. 迁入 ACT 原型，建立 VLA/DP 接口和 unavailable 状态。
8. 完成功能回归后归档法奥、旧双相机、旧语音、旧固定演示和重复实现。

每一步先复制和适配、运行测试、切换正式入口，再归档旧位置。现有可运行目录在新系统验收前不得删除。

## 16. 验证体系

| 等级 | 验证内容 | 运动 |
|---|---|---|
| L0 | 目录、Schema、配置、静态检查和单元测试 | 否 |
| L1 | 一键启动、端口、进程、模拟服务和故障降级 | 否 |
| L2 | XVisio 实时画面、分类、稳定 ID、ASR 和 TTS | 否 |
| L3 | CAN/SDK 连接、实时关节/夹爪反馈和零位跳变保护 | 否 |
| L4 | 维护页面逐轴低速运动和夹爪测试 | 是，人工操作 |
| L5 | 受监督单瓶抓放、视觉中断和重新授权 | 是，逐阶段验收 |
| L6 | 自动夹取完整验收和重复实验 | 是，专项批准 |
| L7 | VLA/ACT/DP 策略 Skill | 模型到位后单独验收 |

测试目录与实现目录保持对应。`tests/hardware/` 默认跳过，真机测试必须由现场人员明确批准，并保持独立硬件急停可用。

## 17. 完成标准

- `./thirdhand start` 可启动所有已安装能力，9983 展示完整健康状态。
- 正式源码不存在 `/home/nieqingcao/...` 绝对路径。
- 正式代码不引用旧工程、`archive/` 或运行产物。
- 3000、3100、3004 单独故障时符合降级规则。
- 未授权、Supervisor 离线、目标过期、反馈异常或计划变化时不能运动。
- 每个 Skill 清楚说明用途、输入、输出、依赖、风险、可用状态和测试方法。
- Ubuntu 20.04 通过真机验收；Ubuntu 22.04 通过软件验收，并在匹配 SDK 到位后完成硬件验收。
- 所有迁移来源、版本、许可证状态和替代关系均可追溯。
