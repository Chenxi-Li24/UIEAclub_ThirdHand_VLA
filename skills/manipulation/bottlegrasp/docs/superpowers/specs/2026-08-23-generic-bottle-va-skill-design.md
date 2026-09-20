# 通用瓶子 V+A Skill 设计

**日期：** 2026-08-23

**项目：** `bottlegrasp`

**范围：** Lumos Ego STD 单目 RGB-D 末端相机、TypeFZ 平行夹爪、Startouch 六轴机械臂

**状态：** 待用户书面审阅

## 1. 目标

交付一个可以由上游 L 模块仅通过稳定瓶号调用的完整 V+A Skill。操作者在
Windows VS Code Remote-SSH 的实时画面中看到最多五个带稳定编号的瓶子；L 调用
`start <stable_bottle_id>` 后，本 Skill 自动完成目标复核、预抓取、近距离重观察、
夹取、垂直提起、移动到固定点、垂直放下、回撤和返回 Home。

正式入口接受任务后运行完整动作，不在夹爪闭合前增加人工继续步骤。任何视觉、标定、
时效、机械臂或安全条件不成立时，Skill 必须在危险动作前 fail closed，并向 L 返回
结构化失败阶段和原因。

## 2. 已确认任务边界

- 只使用一台安装在机械臂末端的 Lumos Ego STD 鱼眼 RGB-D 相机。
- 相机深度来自其自身 ToF；正式路径不依赖 D435 或双相机坐标链。
- 目标为普通不透明瓶，不区分品牌。
- 瓶子保持直立，初始位置在约定桌面工作区内随机。
- 瓶子彼此分开、轮廓清楚，不接触、不重叠、无严重遮挡。
- 同时最多支持五个瓶子，用户可见编号为 `1..5`。
- 夹爪物理最大开口按 80 mm 设计；第一版可执行瓶身宽度上限为 72 mm，保留 8 mm
  总安全余量。显示但超宽的瓶子不得获得执行授权。
- 抓取后直立放到一个经过验证的固定安全点，然后返回 Home。
- 上游 L 只传稳定瓶号，不负责视觉、抓取位姿、运动或放置。

## 3. 第一版明确不做

- 透明或半透明瓶、玻璃瓶；
- 横放、倒放或严重变形的瓶子；
- 瓶子相互接触、堆叠或长时间完全遮挡；
- 移动物体或人员进入机器人工作区的协作安全；
- 自动搜索随机空放置区域；
- 在深度无效时退化为二维检测框中心抓取；
- 训练端到端视觉动作模型；
- 为了架构相似而强行迁入整套 ROS 2、MoveIt 或 Isaac Manipulator。

这些限制必须在 README、配置和运行状态中可见，不能只存在于测试说明中。

## 4. 现有项目基线

现有目录边界适合作为最终结构，不重新建立第二套工程：

```text
bottlegrasp/
├── configs/                    # V/A 配置和硬件来源
├── src/thirdhand_va/
│   ├── common/                 # 公共契约、配置和错误
│   ├── vision/                 # 相机、感知、跟踪、几何、可视化
│   └── action/                 # 标定、观测、对准、抓取、安全、适配器
├── native/vision/              # XVisio 原生 RGB-D 采集
├── apps/bottle_pick/           # 唯一 V+A 组合入口
├── scripts/vision/             # V 独立调试入口
├── scripts/action/             # A 独立调试入口
├── tests/                      # 与源码职责镜像的测试
├── artifacts/                  # 运行证据、录制和报告
└── docs/                       # 架构、接口和操作说明
```

已经具备的基础包括 XVisio RGB-D/XYZ 数据链、通用瓶 Grounded-SAM 感知、瓶子过滤、
掩膜点云几何、目标锁定、多帧稳定、融合画面、手眼变换、安全门、机器人适配器和抓取
工作流骨架。当前离线基线为 128 个测试通过、2 个跳过。

影响本任务的现有问题包括：

- 当前选择语义仍以左/右序号为主，授权候选变化时可能重新编号；
- 稳定跟踪编号尚未成为公共契约；
- 固定可乐瓶参考路径与通用瓶主路径并存；
- D435、双相机和单 Lumos 配置存在历史混杂；
- 运行中的桥接进程使用已删除的旧脚本路径，规范构建二进制又缺失；
- Action 工作流骨架依赖现有 3000 服务，但真实执行默认禁用，完整闭环尚未验收；
- 旧固定点 B/B_UP 存在，但真实成功循环计数为零，不能直接视为已验证。

实现必须在当前目录内定向修复这些问题，不做无关重构，也不能重启尚未建立可回退基线
的在线服务。

## 5. 巨人复用决策

### 5.1 直接复用

| 能力 | 来源 | 许可证/约束 | 本项目使用方式 |
|---|---|---|---|
| RGB/ToF/XYZ 采集与厂商标定 | Lumos FastUMI/XVisio SDK | 使用本机已安装 SDK；复制上游源码前单独核验许可 | 仅由 `native/vision` 和 camera adapter 调用 |
| 开放词汇检测与实例分割 | Grounding DINO + SAM 2 / Grounded-SAM-2 | 代码与主要组件为 Apache-2.0；模型文件分别记录来源和许可 | 固定版本、模型哈希、本地缓存、感知 adapter |
| 多目标跟踪基础 | Norfair | BSD-3-Clause | 通过 tracking adapter 使用；自定义瓶子匹配距离 |
| 手眼标定求解 | OpenCV `calibrateHandEye` | Apache-2.0 | 独立标定工具和只读运行时加载器 |
| Startouch 通信与软件停止 | 当前已验证的 TH-Fanxy/Startouch 边界 | 项目内部代码 | 只通过 `action/adapters` 注入，不向业务模块泄露协议 |

### 5.2 复用架构思想，不直接引入运行依赖

- MoveIt Task Constructor：复用 open、approach、close、lift、place、release、retreat、
  home 的分阶段任务模型和显式失败传播。
- NVIDIA Isaac Manipulator：复用昂贵感知按需调用、深度证据持续更新、夹取后携带物体
  状态和按阶段协调的思想。
- VGN：复用抓取候选包含质量、方向和夹爪宽度，并在执行前排序与过滤的表示。

### 5.3 第一版不采用

- VGN 完整网络：面向通用六自由度杂乱抓取，当前直立分离瓶任务不需要 TSDF 网络。
- GPD：BSD-2-Clause，但依赖较旧的 PCL/C++ 技术栈，增加部署和调试成本。
- Contact-GraspNet：旧 TensorFlow/CUDA 组合且使用自定义许可证。
- GraspNet baseline：代码、数据和模型限免费非商业使用。
- FoundationPose：需要 CAD 或参考视图，不符合任意普通瓶目标。

每个正式采用的依赖都必须在项目内记录名称、固定版本或提交、来源 URL、许可证、模型
哈希、适配层和本机验证命令。外部对象不得直接穿过项目公共契约。

## 6. 总体架构与依赖方向

```text
L: start(stable_bottle_id)
             |
             v
apps/bottle_pick  <---- status/result ----> L
      |                         |
      v                         v
VisionPipeline -- VisionResult --> Action Orchestrator
      ^                         |
      |                         v
Lumos adapter              safety / robot / gripper adapters
```

依赖规则：

- `common` 不依赖 V、A 或硬件。
- V 只依赖 `common` 和视觉侧 adapter，不导入 A。
- A 只接收版本化 `VisionResult` 和 `ArmState`，不读取模型、掩膜或跟踪器内部对象。
- 外部模型、相机、机器人、夹爪和网络都由 adapter 隔离。
- `apps/bottle_pick` 是唯一组合层，负责进程和硬件生命周期，不存放算法。
- 调试脚本调用单一模块的公共接口，不复制业务算法。

## 7. Vision 设计

### 7.1 单 Lumos 数据链

原生采集进程负责彩色解码、ToF 射线还原、厂商外参与畸变模型、ToF 到彩色坐标注册、
遮挡 z-buffer 和统一网格 RGB/depth/XYZ。Python 只接收带版本、帧号、单调时间戳、相机
序列号、标定 ID 和单位说明的 `RgbdFrame`。

RGB、深度或 XYZ 任一来源不匹配，整帧不得进入可执行路径。实时和录制回放必须使用同一
协议和同一 `VisionPipeline`。

### 7.2 检测和分割

Grounding DINO 使用通用提示词 `bottle` 周期性或按需发现实例；SAM 2 根据检测结果生成
精确掩膜，并在两次完整检测之间传播掩膜。完整检测不得只在第一帧执行，因为后续进入
画面的瓶子需要被发现。

候选过滤仅判断通用瓶语义、掩膜有效性、尺寸、轮廓和基础深度支持。固定可乐瓶参考库不
参与正式授权。被过滤候选仍可按配置显示拒绝轮廓和原因，但不得进入可执行排名。

### 7.3 稳定编号

新增独立的稳定轨迹管理器，编号范围为 `1..5`。Norfair 提供预测、关联和轨迹寿命；本
项目提供自定义匹配距离和状态策略。匹配证据按门控而非简单加权兜底：

1. 类别和尺寸基础一致；
2. 相机静止时检查掩膜 IoU 和二维中心运动；
3. 检查颜色/外观描述子距离；
4. 有可靠深度和同步机械臂姿态时检查 robot_base 三维距离；
5. 任一强冲突都禁止合并轨迹。

轨迹状态为：

```text
Tentative -> Confirmed -> Occluded -> Lost -> Retired
```

- 新实例连续命中后才成为 `Confirmed` 并显示正式编号。
- 新确认轨迹取得当前最小可用编号；Norfair 内部 ID 不得直接成为用户编号。
- 低置信度检测可维持已有轨迹，但不能创建可执行轨迹。
- `Occluded` 保留编号但撤销执行授权。
- 未被选择的轨迹连续丢失 2 秒后进入 `Retired`，编号才可回收；被选择的编号在当前
  request 终止前始终保留，即使目标丢失也不能分配给新瓶子。
- 五个编号均被非 Retired 轨迹占用时，额外候选只显示 `unnumbered_capacity_exceeded`，
  不能进入 L 可调用集合。
- 用户选定目标后以稳定轨迹 ID 锁定；任何冲突都阻断，不自动换邻近瓶。
- 相机移动时不依赖纯图像位移维持身份，优先使用冻结的 robot_base 锚点和重新观察证据。

### 7.4 三维抓取几何

第一版利用“直立、分开、不透明”约束，不使用通用六自由度神经抓取网络：

1. 腐蚀实例掩膜，移除轮廓混合像素；
2. 读取注册 XYZ，剔除非有限值、距离越界和统计离群点；
3. 拟合并移除桌面平面支持；
4. 估计瓶身主轴，并验证其与桌面法向近似平行；
5. 排除瓶盖、瓶肩和瓶底，提取瓶身中部安全带；
6. 在安全带多个高度生成侧向平行夹爪候选；
7. 为每个候选计算中心、接近方向、夹爪方向、宽度、有效深度比例、点数、协方差和
   桌面/邻近物间隙；
8. 过滤宽度大于 72 mm、深度不足、方向不可解释或安全间隙不足的候选；
9. 对 3 至 5 个静止帧做稳健中值与离散度检查，选择最高质量候选。

不得回退到检测框中心。输出至少包括相机坐标夹取位姿、瓶身轴线、估计宽高、接近向量、
质量分量、来源帧和阻断原因。

### 7.5 可视化

融合预览必须显示：

- 所有已确认瓶子的稳定编号、掩膜、轮廓和状态；
- 不可夹瓶子的红色状态及短原因；
- 当前选中瓶子的高亮和身份锁定状态；
- 三维抓取点、瓶身轴线、接近方向和夹爪宽度；
- 深度覆盖、稳定命中、标定 ID、帧年龄和 V/A 当前阶段；
- `READY`、`BLOCKED`、`RUNNING`、`COMPLETE` 或 `FAILED`。

预览是只读观测面，不拥有机器人控制接口。编码异常必须转换为可恢复的预览状态，不能让
工作线程静默死亡。

## 8. V/A 公共契约

V 向 A 只输出不可变、可验证、可序列化的结果。公共契约需要包含：

```text
schema_version
request_id
frame_id / captured_monotonic_ns
camera_serial / calibration_id / motion_epoch
stable_bottle_id / track_state
vision_status / blockers
grasp_pose_camera
bottle_axis_camera
approach_vector_camera
estimated_width_m / estimated_height_m
depth_valid_ratio / valid_point_count
pose_spread_m / stable_hits
evidence_id
```

A 将通过手眼标定生成独立的 `ActionTarget`，其中包含 `robot_base` 目标、来源
`VisionResult` 哈希、可达性和安全检查结果。A 不改写 V 的原始结果。

L 到 VA 的第一版命令语义为：

```json
{"schema":"thirdhand.va.command.v1","cmd":"start","target_id":2,"request_id":"..."}
```

也保留明确的 `stop`。旧 CLI `node apps/bottle_pick/run.js start 2` 由组合层转换成相同
命令。VA 对 L 输出阶段事件和一个最终结果；同一 `request_id` 重复提交不得启动第二个
并发动作。

## 9. 手眼标定和 eye-in-hand 闭环

正式坐标链固定为：

```text
xvisio_color -> tool/TCP -> robot_base
```

不通过 D435 中转。标定流程使用固定标定板、至少 12 个有效姿态、至少两个旋转轴，并保留
独立验证姿态。标定产物包含相机序列号、TCP 语义、输入样本哈希、求解方法、旋转和平移、
拟合误差、验证误差和生成时间。

每个可执行视觉结果必须绑定同步 `ArmState`。若机械臂姿态时间差、相机时间、标定 ID 或
TCP 语义不一致，则阻断执行。

末端相机移动后，旧的相机坐标位姿不得直接用于最终夹取。Action 采用粗到细闭环：

```text
远处稳定观察
-> 变换到 robot_base 并冻结目标身份
-> 移动到距候选 100~150 mm 的预抓取位姿
-> 停稳并开启新的 motion_epoch
-> 重新取得 3~5 个稳定 RGB-D 结果
-> 允许不超过 5 mm 的迭代修正
-> 冻结最终证据
-> 最终接近和闭合
```

运动期间可以维持身份预测和显示，但不得积累用于最终授权的深度稳定帧。

## 10. Action 状态机

正式入口每次成功接受命令后执行完整状态机：

```text
IDLE
-> VALIDATING_TARGET
-> MOVING_TO_PREGRASP
-> SETTLING
-> REOBSERVING
-> FINAL_APPROACH
-> CLOSING
-> LIFTING
-> MOVING_TO_PLACE
-> LOWERING
-> RELEASING
-> RETREATING
-> RETURNING_HOME
-> COMPLETE
```

固定放置点由 `robot_base` 坐标中的 `place` 和 `pre_place` 组成。旧 B/B_UP 只能在空载
预演、位置检查和低速完整循环通过后迁入正式配置；否则重新示教。固定点数据不写死在
控制器源码中。

Action 各模块职责：

- `calibration`：坐标转换和标定来源验证；
- `observation`：目标记忆、基坐标锚点和多帧质量；
- `alignment`：预抓取、停稳、重观察和有限微调；
- `grasp`：完整状态机和阶段超时；
- `safety`：工作区、时效、宽度、标定、机械臂和执行许可；
- `adapters`：视觉服务、机器人、夹爪和软件停止。

业务模块不得直接建立网络连接、退出进程或读取其他模块私有状态。

## 11. 安全和失败语义

所有安全门默认拒绝。至少覆盖：

- `target_id_not_found`
- `target_not_confirmed`
- `target_identity_conflict`
- `target_occluded`
- `depth_insufficient`
- `pose_unstable`
- `pose_stale`
- `camera_or_arm_moving`
- `calibration_mismatch`
- `grasp_width_exceeded`
- `target_outside_workspace`
- `pregrasp_unreachable`
- `robot_state_unavailable`
- `gripper_state_unavailable`
- `motion_timeout`
- `software_stop_requested`

失败不得自动换瓶。恢复行为按阶段固定：

| 失败阶段 | 自动行为 |
|---|---|
| `VALIDATING_TARGET` 至 `REOBSERVING` | 取消后续动作；机器人保持，只有 adapter 明确报告未运动且 Home 路径已验证时才允许单独的人工 Home 命令 |
| `FINAL_APPROACH` | 请求受控停止并保持当前位置，不自动闭合夹爪，不自动回 Home |
| `CLOSING` 至 `LOWERING` | 保持夹爪当前命令和机械臂位置，禁止自动松开、放置或回 Home，返回 `manual_recovery_required` |
| `RELEASING` | 若无法证明瓶子已释放，保持当前位置并请求人工处理 |
| `RETREATING` 或 `RETURNING_HOME` | 仅在机器人健康且预验证剩余路径可继续时完成回撤；否则保持并请求人工处理 |

任何无法确认物体是否仍被夹持的情况不得自动打开夹爪。

运行日志按 `request_id`、`stable_bottle_id`、阶段、命令 ID 和 evidence ID 串联；日志不得
替代公共返回值。

## 12. 独立运行和调试要求

每个核心模块必须可在 VS Code Remote-SSH 中直接打开、设置断点并单独运行：

| 模块 | 独立输入 | 可观察输出 | 调试入口 |
|---|---|---|---|
| RGB-D 协议/录制 | bundle 或显式授权相机 | 帧信息、图像、深度统计 | `camera_smoke.py`、`replay_rgbd.py` |
| 检测/分割 | 单个或一组 bundle | 框、掩膜、分数、延迟 | `debug_perception.py` |
| 稳定跟踪 | 检测序列 fixture | 编号、状态、关联原因 | 新增 `debug_tracking.py` |
| 抓取几何 | bundle + mask | 候选、宽度、质量、3D 可视化 | `debug_geometry.py` |
| 完整 V | bundle 序列 + 目标号 | `VisionResult`、叠加帧 | `debug_pipeline.py` |
| 手眼标定 | 标定 YAML + 验证点 | 误差和坐标预览 | `debug_calibration.py` |
| 对准 | 模拟 V/机器人事件 | 状态转移和命令轨迹 | `debug_alignment.js` |
| 抓取状态机 | 模拟 adapters | 全阶段日志和最终结果 | `debug_grasp.js` |
| 完整 Skill | L 编号 + 组合配置 | 预览、阶段事件、最终结果 | `run.js start <id>` |

库模块导入时不得启动模型、相机、网络或机器人。真实硬件入口必须有显式开关；模拟模式与
真机模式使用同一业务状态机，只替换 adapter。

## 13. 测试与验收

### 13.1 自动化测试顺序

1. `common` 契约和配置测试；
2. V 感知、跟踪、几何、稳定和可视化模块测试；
3. A 标定、观测、对准、安全和状态机模块测试；
4. V/A schema、时效、身份和 evidence 一致性测试；
5. 录制 RGB-D 回放测试；
6. 模拟 adapters 的完整 `start <id>` 流程和故障注入；
7. 依赖、模型和原生构建可复现检查。

### 13.2 硬件验证顺序

1. Lumos 相机只读 smoke 和长时间流稳定性；
2. RGB/深度/XYZ 配准板和真实瓶边界验证；
3. 手眼标定采集、拟合和独立验证；
4. 机器人空载路径、固定点和工作区检查；
5. 使用模拟瓶位执行低速完整循环；
6. 1 至 5 个不同不透明直立瓶、随机允许位置的完整循环；
7. 深度不足、超宽、编号失效、目标遮挡和软件停止故障注入。

所有真实硬件步骤都需要当次明确授权和现场监管。正式端到端测试一旦接受 `start`，每次均
尝试完成抓取、固定点放置和回 Home；模块级硬件检查使用各自的受限入口，不伪装成完整
Skill 成功。

### 13.3 第一版验收标准

- 约定验收集中的错误目标抓取次数为 0；
- 允许场景内稳定编号无身份交换；
- 无效目标和过期证据获得执行授权的次数为 0；
- 至少覆盖五种普通不透明瓶和 30 个随机允许位置完整循环；
- 端到端成功率目标不低于 90%；
- 每个成功任务完成固定点直立放置并返回 Home；
- 每个失败任务产生明确阶段、原因和可追溯证据；
- 模块、契约和模拟集成测试全部通过；
- 文档中的每个独立调试命令从干净终端可以复现。

90% 是真机验收目标，不能用离线通过率代替。若真实数据不能达到该目标，项目状态应保持
“未完成”，报告失败分布后针对对应模块修正。

## 14. 迁移和交付

最终运行入口和源文件只位于 `bottlegrasp`。其他 ThirdHand 目录只作为只读参考或由
adapter 调用的外部服务，不能成为隐藏源码来源。部署前必须消除已删除脚本、陈旧二进制和
隐式全局依赖。

交付说明必须列出：

- 修改模块、职责和接口；
- 采用与拒绝的外部方案、版本、许可证和原因；
- 配置、标定、模型和运行产物来源；
- VS Code 中每个模块的文件、断点位置建议和独立命令；
- 模块、契约、集成和硬件测试证据；
- 未覆盖场景和剩余风险。

本设计优先完成一个可靠、可解释、可独立调试的直立不透明瓶 Skill；透明物体、杂乱堆叠
和通用六自由度抓取只有在第一版数据证明必要时才进入后续独立设计。

## 15. 主要上游参考

- Lumos FastUMI Camera：<https://github.com/lumos-open/FastUMI_Camera>
- Grounded-SAM-2：<https://github.com/IDEA-Research/Grounded-SAM-2>
- SAM 2：<https://github.com/facebookresearch/sam2>
- Norfair：<https://github.com/tryolabs/norfair>
- OpenCV hand-eye calibration：
  <https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html>
- MoveIt eye-in-hand calibration：
  <https://moveit.picknik.ai/main/doc/examples/hand_eye_calibration/hand_eye_calibration_tutorial.html>
- MoveIt Task Constructor pick-and-place：
  <https://moveit.picknik.ai/main/doc/tutorials/pick_and_place_with_moveit_task_constructor/pick_and_place_with_moveit_task_constructor.html>
- NVIDIA Isaac Manipulator pick-and-place：
  <https://nvidia-isaac-ros.github.io/v/release-3.2/reference_workflows/isaac_manipulator/tutorials/tutorial_pick_and_place.html>
- VGN：<https://github.com/ethz-asl/vgn>
- GPD：<https://github.com/atenpas/gpd>
- Contact-GraspNet：<https://github.com/NVlabs/contact_graspnet>
- GraspNet baseline：<https://github.com/graspnet/graspnet-baseline>
