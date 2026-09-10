# PinZiZhuaQuSkill 自包含 Startouch 夹瓶运行时设计

日期：2026-08-23
状态：原始设计已实施；Startouch 安全/停机语义已由用户批准的
`2026-08-24-startouch-safety-hardening-design.md` 取代。本文中“外部 SDK 直接加载”和
“cleanup 证明掉电”的历史描述不再是可执行规范。
范围：Vision + Action（VA）；Language（L）由组员实现

## 1. 背景与已确认任务

本项目需要完成一个可被组员 L 模块调用的“按编号夹取瓶子” Skill：

1. 末端安装的 Lumos Ego STD RGB-D 鱼眼相机观察桌面。
2. 桌面上放置彼此分开、轮廓清楚的不透明普通瓶子，瓶子保持直立。
3. VA 将可夹取瓶子从左到右稳定编号，并向操作者显示编号、轮廓、深度和可执行状态。
4. L 传入一个瓶子编号。
5. Action 每次执行完整动作：定位目标、接近、夹紧、抬起、移动到固定放置区域、直立放下、撤离并回到安全状态。
6. 每个核心模块均可在 VS Code Remote-SSH 中单独运行、设置断点、构造测试输入并观察输出，不要求启动整个系统。

现有 VA 已经具备编号选择、RGB-D 几何定位、目标锁定、动作状态机、HTTP 接口和离线模拟链路。本设计只补齐真实机械臂协议、自包含标定导入、固定放置规划和对应的安全验证，不重写已经通过测试的模块。

## 2. 强制边界

### 2.1 文件边界

- 所有由本次工作创建或维护的项目源码、配置、测试、调试脚本、许可证说明和标定派生件，必须位于：
  `/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill`
- `/home/nieqingcao/TH-Fanxy` 和 `/home/nieqingcao/th0814/TH_MK_D/UIEAclub_ThirdHand_VLA-control-fixed-a-to-b` 仅用于阅读、评估和追溯成熟实现；不得被修改，也不得成为运行时 Python/Node 导入路径。
- 不整份复制 `TH-Fanxy`。只把本 Skill 实际需要、许可证允许复用的最小机械臂桥接思想和代码片段适配到独立模块，保留来源及许可证说明。
- Startouch 厂商 SDK 是硬件驱动依赖，不复制厂商二进制或整套 SDK进仓库。它通过配置项指向主机上已安装的 SDK；模拟、单元测试和接口测试不依赖该 SDK。
- 手眼标定原始结果仍保留在原标定目录；运行所需的、带来源哈希的只读派生件复制到本 Skill 的 `configs/calibration/`，因此运行时不依赖原目录。

### 2.2 运行边界

- 开发和自动测试默认全部为模拟或离线模式，不连接相机、CAN 或真实机械臂。
- 当前主机已有进程占用 `can0`。新桥接器必须复用同一个文件锁 `/tmp/startouch-web-can0.lock`；锁被占用时必须明确失败，绝不启动第二个控制器。
- 真实运动只有在配置开关、精确授权环境变量、标定放行和路径放行全部满足时才允许执行。
- 当前手眼标定尚未完成物理验证和激活，固定放置路径也尚未完成整段实机验证。因此开发完成后 Action 仍应保持真实执行锁定；不得通过修改布尔值伪造放行。

## 3. 复用依据与选择

### 3.1 采用的成熟方案

1. **Startouch 桥接结构**
   - 参考本机 `TH-Fanxy/web-control/server/startouch_bridge.py` 及其 Node 管理层。
   - 参考本机 MIT 项目 `UIEAclub_ThirdHand_VLA-control-fixed-a-to-b` 的桥接和动作控制结构。
   - 采用“Python 负责厂商 SDK，Node 负责 VA 工作流”的进程边界，使用逐行 JSON、请求 ID、状态回读和单写者锁。

2. **官方 Lumos/Startouch 生态**
   - 参考 Lumos Robotics 官方 GitHub 组织、`lumos_sdk`、相机仓库和 MIT 许可的 `BestMan_Touch`。
   - 厂商 SDK 只通过稳定的公开接口调用，不把 VA 业务逻辑写入 SDK。

3. **OpenCV 手眼标定语义**
   - 依据 OpenCV `calibrateHandEye` 官方文档：在 eye-in-hand 场景中，结果为相机坐标到夹具坐标的变换，即本项目的 `T_flange_camera`。
   - 使用显式坐标系字段和矩阵链，避免把法兰误写成配置 TCP。

4. **现有实机经验参数**
   - 固定放置 XY 候选值复用现有、已由操作者确认可到达的桌面中心观测位：
     `[0.26783482212847776, 0.010668622392713049] m`。
   - 垂直安全净空候选值为 `0.10 m`。
   - 水平抓取补偿候选值为 `[0.0475, 0.0100, 0.0] m`。
   - 这些值是“验证输入”，不是自动批准结果；正式执行前必须绑定到新的路径验证记录。

### 3.2 不采用的方案

- 不复制整个 `TH-Fanxy`：包含大量与本 Skill 无关的网页、主动视角和历史兼容逻辑，会增加耦合与维护面。
- 不让 VA 通过现有浏览器 WebSocket 临时翻译命令：其协议没有完整暴露 VA 所需的低层直线运动、严格能力握手、生产者时间戳和可证明的断电确认。
- 不引入 ROS/MoveIt 作为当前固定桌面任务的强依赖：本任务的动作序列和工作空间简单，现有机械臂 SDK 足以完成，新增 ROS 会显著提高部署和调试成本。
- 不自行重新实现手眼标定算法；复用已完成的 OpenCV 标定结果，只修正运行时坐标语义和验证门槛。

## 4. 总体结构

```text
L 模块
  │  POST /execute {target_id}
  ▼
VA HTTP API / Workflow
  ├── VisionSelectionApi ── RGB-D 编号、锁定、3D 目标
  ├── ExecutionPlanner ─── 抓取/抬升/固定 XY 放置轨迹
  ├── SafetyGates ──────── 标定、路径、授权、状态新鲜度
  └── RobotClient（统一接口）
        ├── StartouchProcessClient（生产候选）
        │      └── local startouch_bridge.py ── 厂商 SDK ── CAN
        └── RobotWebSocketClient（保留的可选兼容后端）
```

L 到 VA 的接口保持稳定；真实机械臂适配只发生在 `RobotClient` 边界以内。这样组员不需要知道 Startouch SDK、CAN 或手眼标定文件结构。

## 5. 模块设计

### 5.1 本地 Startouch Python 桥接器

建议位置：

- `native/startouch/startouch_bridge.py`
- `native/startouch/protocol.py`
- `native/startouch/NOTICE.md`

职责：

- 解析 JSON Lines 命令并返回关联请求 ID 的结果。
- 延迟导入厂商 SDK；`--simulate` 模式完全不导入 SDK。
- 执行 CAN 预检和 `/tmp/startouch-web-can0.lock` 排他锁。
- 提供最小命令集：`connect`、`get_state`、`move_l`、必要时 `move_joint`、`gripper_open`、`gripper_close`、`software_stop`、`disconnect`。
- 每次状态包含严格单调递增的 `state_sequence` 与 `producer_monotonic_ns`。
- 运动完成不能仅依据 SDK 函数返回；必须读取实际法兰/TCP 位姿，并在位置和姿态容差内才返回 `reached: true`。
- 夹爪结果包含实际宽度/距离或 SDK 可提供的等价反馈。

非职责：

- 不包含瓶子视觉、编号、轨迹业务逻辑或 HTTP 服务。
- 不负责决定目标是否安全；只严格执行已验证命令并报告真实状态。

### 5.2 Node 进程适配器

建议位置：

- `src/thirdhand_va/action/adapters/startouch_process_client.js`

职责：

- 在所有授权门满足后才启动本地 Python 子进程。
- 完成 `thirdhand-startouch-bridge-v1` 能力握手，校验协议版本、单位、命令集和桥接源码/配置哈希。
- 将 JSON Lines 结果映射为现有 `RobotClient` 的 `send()`、`getRobotState()` 和事件接口。
- 管理请求 ID、超时、重复响应、乱序响应、子进程退出和 stderr 日志。
- 向工作流提供实际位姿、速度、夹爪反馈、状态序列和生产者时间。

保留 `RobotWebSocketClient` 作为可选兼容后端，但生产配置默认只能明确选择一个后端，禁止自动回退到另一个真实控制器。

### 5.3 手眼标定导入与加载

建议位置：

- `src/thirdhand_va/action/calibration/import_handeye.py`
- `src/thirdhand_va/action/calibration/handeye.py`
- `scripts/action/import_handeye.py`
- `scripts/action/debug_calibration.py`
- `configs/calibration/lumos-handeye.pending.json`

输入来源：

`/home/nieqingcao/th0814/相机手眼标定/2026-08-17_250801DR48FP25002738_eye_in_hand/final/solution_85a58f8a28ac/derived/luming_eye_in_hand_calibration.json`

导入器必须：

- 校验原始文件 SHA-256；当前观测到的文件哈希为
  `05e5c8680193dad6bb72370e7ba29c8afafee885f4f139250ca1b9d76303be7c`。
- 输出显式 v3 语义：机器人状态为 `T_base_flange`，标定为 `T_flange_camera`。
- 保存相机序列号 `250801DR48FP25002738`、安装 ID、数值误差和来源路径，但运行时只读取项目内派生件。
- 保留 `physical_validation: pending` 和 `activation: locked`，不能把数值标定通过解释为抓取批准。

运行时矩阵链为：

```text
T_base_object = T_base_flange @ T_flange_camera @ T_camera_object
```

现有 v2 配置可作为兼容输入读取，但只要它声称 `T_tool_camera` 而又无法证明 tool 与 flange 等价，就不得用于真实执行。

正式放行要求至少包含：

- 当前相机序列号与标定记录一致；
- 当前安装 ID 与物理安装一致；
- 独立物理点检误差 `<= 0.010 m`；
- 验证记录包含时间、操作者、测量值、配置哈希和批准状态。

### 5.4 抓取与固定放置规划

建议位置：

- 继续使用现有规划模块；只在其内部加入明确的放置策略对象，避免创建一个只有几行转发代码的过细模块。
- 配置位于 `configs/action.yaml`，结构化字段替代模糊的固定 XYZ。

候选配置：

```yaml
place:
  strategy: fixed_xy_keep_grasp_z
  fixed_xy_m: [0.26783482212847776, 0.010668622392713049]
  vertical_clearance_m: 0.10
  validated: false

grasp:
  flange_offset_base_m: [0.0475, 0.0100, 0.0]
  offset_validated: false
```

使用固定 XY、动态 Z 的原因：普通瓶子高度和视觉选取高度可能变化。放置下降高度应以本次经过验证的抓取命令 Z 为基准，而不是使用一个对所有瓶子都相同的固定 Z。

一次完整动作的计划为：

1. 获取稳定目标锁并冻结本次 `target_id`。
2. 将相机 3D 点变换到基坐标，并加入已验证的法兰抓取补偿。
3. 移动到抓取点正上方 `vertical_clearance_m`。
4. 垂直下降到抓取 Z。
5. 关闭夹爪并检查反馈。
6. 垂直抬升到安全 Z。
7. 水平移动到固定放置 XY 上方。
8. 垂直下降到本次命令抓取 Z。
9. 打开夹爪，保持瓶子直立放下。
10. 垂直撤离并执行已验证的回撤/安全结束动作。

规划阶段必须检查所有航点都位于工作空间限制内，且验证记录覆盖完整 Z 范围、净空、补偿、速度与回撤路径。

### 5.5 安全停止语义

现有桥接设计中存在一个需要避免的风险：SDK `cleanup()` 异常被捕获后，仍可能发出看似断开的事件，进而被上层误认为已经断电。

新桥接器必须满足：

- 只有 SDK 清理/断开成功时，才返回关联请求的
  `software_stop_complete`，并包含 `stopped: true`、`depowered: true`、应用时的序列和单调时间。
- 清理失败时返回错误，绝不发出 `depowered: true`。
- 对本地进程后端，经验证的断电确认本身是终端安全边界；断电后不要求一个不可能产生的“连接态后续状态帧”。
- 对保留的 WebSocket 后端，继续使用其既有的状态序列边界，不能混淆两种协议的停止证明。
- 子进程崩溃、超时或管道断开只能标记“控制状态未知/执行失败”，不能推断机械臂已停止或断电。

## 6. 接口契约

### 6.1 L 到 VA

保持现有接口，不向 L 泄漏硬件细节：

```json
{
  "target_id": 2
}
```

VA 响应应包含稳定的执行 ID、阶段、是否接受、拒绝原因和最终结果。常见拒绝原因必须机器可读，例如：

- `target_not_found`
- `target_not_stable`
- `handeye_physical_validation_pending`
- `handeye_activation_locked`
- `place_path_validation_pending`
- `robot_authorization_missing`
- `robot_resource_locked`

### 6.2 Node 到 Python

命令示例：

```json
{"request_id":"...","command":"move_l","pose_m_rad":[...],"speed_scale":0.05}
```

完成响应示例：

```json
{
  "request_id":"...",
  "event":"command_complete",
  "reached":true,
  "actual_pose_m_rad":[...],
  "state_sequence":123,
  "producer_monotonic_ns":1234567890
}
```

所有长度统一为米、角度统一为弧度；协议握手中必须显式声明，禁止根据数值大小猜单位。

## 7. 独立调试入口

每个核心模块都应有无硬件入口和 VS Code 配置：

- 桥接协议：
  `python native/startouch/startouch_bridge.py --simulate`
- Node 适配器：
  `node scripts/action/debug_startouch_protocol.js --simulate`
- 手眼标定：
  `python scripts/action/debug_calibration.py --config configs/calibration/lumos-handeye.pending.json`
- 单次轨迹规划：
  `node scripts/action/debug_execution_plan.js --target-pose ... --dry-run`
- 完整 VA 模拟：
  使用现有模拟机器人和录制 RGB-D 输入，传入编号后观察全部阶段、轨迹和最终状态。

调试输出必须包括配置来源、坐标系、单位、状态序列、安全门结果和拒绝原因。默认禁止在仅按 F5 时意外连接真实机械臂。

## 8. 测试策略

开发遵循测试先行，按风险从小到大验证：

1. **Python 模块测试**
   - JSON Lines 解析、请求关联、单位和状态序列；
   - `--simulate` 下不导入厂商 SDK；
   - 文件锁冲突；
   - 实际位姿容差；
   - `cleanup()` 失败绝不报告断电。

2. **Node 模块测试**
   - 能力握手、协议不匹配拒绝；
   - 子进程启动/退出、stderr、超时和乱序响应；
   - `RobotClient` 接口映射；
   - 停止确认的后端差异。

3. **标定与规划测试**
   - 原始哈希和 v3 坐标语义；
   - `T_base_flange @ T_flange_camera @ T_camera_object` 的已知矩阵样例；
   - pending/locked 门不能被绕过；
   - 不同瓶高使用相同固定 XY、各自动态 Z；
   - 所有航点工作空间和净空检查。

4. **模拟集成测试**
   - L 传入编号后，模拟完成定位、接近、夹取、抬升、放置、撤离全套动作；
   - 目标消失、深度过期、夹爪失败、运动未到位、资源锁冲突、停止失败等故障注入；
   - 确认任何失败均不能被报告为成功或已断电。

5. **实机验证（另行明确授权）**
   - 先只读状态和锁冲突验证；
   - 再做手眼物理点检；
   - 再以低速、无瓶、分段方式验证路径；
   - 再用单个轻质不透明瓶完成监督抓放；
   - 最后才批准自动全流程。

自动测试不得启动或停止当前运行中的 3000 服务，不得抢占 CAN。

## 9. 配置与放行记录

真实执行至少需要以下四类相互独立的证据：

1. `execution_enabled: true`：功能开关；
2. 精确授权环境变量：本次运行的操作者授权；
3. 已激活手眼标定：相机和安装匹配、物理误差达标；
4. 已验证放置路径：覆盖固定 XY、动态 Z 范围、净空、抓取补偿、速度和安全回撤。

任何一项缺失都返回明确拒绝原因。配置文件中的候选数值不等于批准记录。

## 10. 交付和迁移结果

完成实现后，`PinZiZhuaQuSkill` 将形成一个自包含 VA 包：

- 组员只需要调用稳定的编号执行接口；
- Vision 和 Action 可分别运行、测试和调试；
- 不需要启动 `TH-Fanxy` 才能运行本 Skill；
- 换到另一台 Ubuntu 主机时，只需复制本 Skill、安装声明的 Python/Node 依赖和厂商 SDK，并重新绑定设备/标定/路径批准；
- 没有硬件时仍可运行全套模拟测试；
- 未完成实机验证时系统会明确显示“软件已具备、真实动作被安全门锁定”，不会冒充实机完成。

## 11. 实施顺序

1. 先为桥接协议、标定语义、动态放置规划和停止失败编写失败测试。
2. 在项目内实现最小 Python 桥接器及模拟模式，添加来源说明。
3. 实现 Node 进程适配器，并接入现有 `RobotClient` 边界。
4. 导入项目内 pending 手眼标定派生件，升级加载器坐标语义。
5. 实现固定 XY + 动态 Z 的规划及路径验证契约。
6. 运行模块测试和模拟集成测试，修正回归。
7. 提供 VS Code 调试配置、独立命令和模块说明。
8. 实机验证保持锁定，等待用户另行逐阶段授权。

## 12. 参考来源

- OpenCV `calibrateHandEye` 官方文档：
  https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html
- Lumos Robotics GitHub：
  https://github.com/Lumos-Robotics
- Lumos Robotics `BestMan_Touch`（MIT）：
  https://github.com/Lumos-Robotics/BestMan_Touch
- 本机成熟实现（只读参考）：
  `/home/nieqingcao/TH-Fanxy/web-control/server`
- 本机 MIT 基线（只读参考）：
  `/home/nieqingcao/th0814/TH_MK_D/UIEAclub_ThirdHand_VLA-control-fixed-a-to-b`
