# ThirdHand VLA：从机器人几何到可验证视觉与 VLA 的完整教程

ThirdHand VLA 是围绕 Lumos Touch R1 六自由度桌面机械臂、Lumos Ego 超广角相机和
Intel RealSense D435 构建的研究与实验仓库。主研究轴是**机器人视觉与三维感知**，
次研究轴是**可验证的 VLA 决策**，视觉–VLA 端到端系统是可选综合路线。机械臂控制只
承担受监督实验平台与安全边界，不是当前 SCI 新颖性主张。

> **安全警告**
>
> 本教程的 L0–L3 不授予真实运动权限。任何真实运动都必须在现场监督、独占 CAN、低速、
> 清空工作区且独立硬件急停可立即触达的条件下进行。网页“软件停止”、键盘中断、语音
> 急停和 SDK `cleanup()` 都依赖计算机与通信链路，不能代替 hardware emergency stop
> （硬件急停）或动力切断。视觉配置保持 `robot_execution_enabled: false`；不得为了
> 通过演示而移除标定、时效、身份、资源所有权或人工确认门禁。

[项目首页](README.md) · [架构](docs/architecture.md) ·
[安装指南](docs/setup_guide.md) · [研究证据中心](docs/research/README.md) ·
[视觉研究索引](docs/vision_research/14_FINAL_TECHNICAL_DECISION.md)

## 学习成果

完成本教程后，你应能：

1. 区分可安装 Python VLA 应用和 Startouch Web 控制栈两条独立运行边界；
2. 用关节空间、笛卡尔位姿、RPY、SE(3)、内外参和手眼标定解释像素到机器人基座的链路；
3. 解释 Lumos 主 RGB、D435 米制深度、跨相机注册、实例身份记忆与 fail-closed 门禁；
4. 说明 VLA/语音为何只产生建议或结构化候选，而不能直接取得执行权；
5. 沿 L0–L4 风险阶梯安装、离线复现、运行模拟/只读服务并保留可审计证据；
6. 把假设、数据集、实验清单、结果记录、图表和限制串成可追溯的 SCI 证据链。

## 建议阅读路线

| 读者 | 最短路线 | 完成标志 |
| --- | --- | --- |
| 新开发者 | 1 → 2 → 5 → 6 → L0–L2 | 能指出每个运行入口的依赖和控制权限，不把接口骨架当成真机能力 |
| 视觉研究者 | 1 → 2 → 3 → 8 | 能从相机时间戳追到掩码三维位姿、协方差、身份与论文证据 |
| VLA 研究者 | 1 → 4 → 5 → 8 | 能设计候选–预览–确认–本地验证的离线比较实验 |
| 复现者 | 1 → 6 → L0–L3 → 8 | 能从 commit、命令、配置、数据校验和重建结果记录 |
| 受监督硬件操作员 | 1 的安全边界 → 2.7 → 5 → L0–L4 | 能在任何门禁失败时停止，不把软件停止当作硬件急停 |

## 导航

1. [认识系统](#tutorial-01-system)
2. [机器人学与几何基础](#tutorial-02-robotics-geometry)
3. [感知与视觉主研究轴](#tutorial-03-perception)
4. [VLA、语音与人机交互](#tutorial-04-vla-interaction)
5. [控制、编排与安全](#tutorial-05-control-safety)
6. [代码地图与运行接口](#tutorial-06-code-map)
7. [L0–L4 动手教程](#tutorial-07-hands-on)
8. [SCI 验证、排障与论文路径](#tutorial-08-research-verification)

---

<a id="tutorial-01-system"></a>

## 1. 认识 ThirdHand 系统

### 1.1 目标、非目标与典型任务

本项目研究“怎样把有时间戳、有标定来源和不确定度的视觉证据，安全地送入可审计的
机器人决策边界”。典型对象包括桌面实例分割、跨相机深度注册、遮挡后重识别、离线
VLA 候选评估，以及在人工监督下验证固定点运动平台。

当前非目标是：无人监督自主抓取、通用碰撞规划、安全认证控制器、以低层运动控制作为
论文核心贡献，或用单次定性截图宣称算法优越。任何没有数据清单、实验清单、样本量、
区间和生成命令的效果都不能成为论文结论。

### 1.2 硬件与数据/控制拓扑

```text
观测平面
  Lumos Ego RGB（canonical_rgb，SEUCM） ─┐
                                          ├─ 时间配对 → 注册 → 实例/身份/三维 → 只读状态
  Intel D435 depth（metric_depth，pinhole）┤
  Intel D435 RGB（debug_rgb）──────────────┘

控制平面
  浏览器 → Node :3000 → Startouch Python bridge → vendor SDK → SocketCAN can0
                                                    → Lumos Touch R1 + gripper

独立边界
  可安装 Python 应用 :8000（实验性框架）
  Lumos HTTP/MJPEG :3001；只读双相机页面 :3100
  固定 A/B 本机控制页 127.0.0.1:8766
```

逻辑角色在 [REMIND-3D 配置](configs/vision/remind3d.yaml) 中固定为 Lumos 主外观、D435
米制深度、D435 RGB 调试。物理设备枚举会变化，算法不应把 `/dev/videoN` 当作持久身份；
设备拓扑与稳定标识策略见[硬件与相机拓扑](docs/vision_research/02_HARDWARE_AND_CAMERA_TOPOLOGY.md)。

### 1.3 两条运行边界

**边界 A：可安装 Python VLA 应用。** [入口](src/uiea_thirdhand_vla/__main__.py) 通过
`python -m uiea_thirdhand_vla` 或 `thirdhand-vla` 启动，组织相机、ArUco/YOLO、可选
云端 VLA、确定性状态机、控制适配器和 FastAPI 对象，默认端口 `8000`。但当前
[Robot](src/uiea_thirdhand_vla/control/robot.py)、ASR/NLU/TTS 和部分 Web API 仍是
框架实现；[FastAPI 工厂](src/uiea_thirdhand_vla/web/server.py) 尚未装配各 API router
与 `/ws`。因此它是便于开发和离线验证的 **Experimental** 框架，不是已验证真机入口。

```text
Lumos frame → ArUco / YOLO → deterministic state machine → local checks → adapters
optional VLA recommendation ────────────────────────────────┘
optional intent candidate ──────────────────────────────────┘
FastAPI object :8000 → `/static` mount / future route integration
```

**边界 B：Startouch Web 控制栈。** [Node 代理](web-control/server/proxy.js) 默认监听
`0.0.0.0:3000`，通过 JSON Lines 子进程连接
[Startouch bridge](web-control/server/startouch_bridge.py)，后者独占指定 CAN 接口并调用
外部 vendor SDK。这是仓库中经过真机联调的直接控制边界；相机与视觉状态是旁路输入，
不能绕过资源锁、命令校验和执行开关。部署前必须读 [Web 控制说明](web-control/README.md)。

### 1.4 能力成熟度与证据成熟度

功能状态和科研证据状态是两套不同维度：

- **Implemented**：代码和公开接口存在；不等于部署或算法有效性已经验证。
- **Verified**：有自动化测试或明确、带日期的工程验收证据；不自动构成 SCI 比较结论。
- **Experimental**：可以运行，但仍有硬件、标定、任务模型或系统集成门禁。
- **Planned**：只有研究/设计路径，尚不是受支持运行能力。
- **Planned Evidence / 待补实验证据**：完全没有结果，只能描述未来协议和所需产物。
- **Evidence Incomplete / 待补充证据**：已有部分结果，但样本量、置信区间、统计方法或
  来源证据缺失/不足/不可追溯。两种证据标签都不得支撑摘要结论。

预注册准备度是第三个独立字段。缺阈值或统计计划意味着预注册未就绪；若尚无测量，证据
仍是 Planned Evidence，而不是 Evidence Incomplete。完整规则见
[研究证据中心](docs/research/README.md)。

| 能力 | 功能状态 | 可引用事实 | 仍缺什么 |
| --- | --- | --- | --- |
| Python 配置、ArUco/YOLO、SEUCM、FSM | Implemented / Experimental | 模块和单元接口存在 | 端到端 router、真实控制适配与任务验收 |
| Startouch Web 直接控制 | Verified（工程） | Ubuntu 20.04 真机路径、CAN 预检、限位、锁和停止路径有文档/测试 | 它不是安全认证控制器 |
| 固定 A/B 逐步演示 | Experimental | 模拟、dry-run、资源预检和人工逐步入口存在 | 配置仍记录 `validated_real_cycles: 0`，不能升级为无人监督流程 |
| 离线视觉安全核心与确定性回放 | Verified（离线工程） | 几何、注册、追踪、记忆、门禁和回放测试存在 | 真实数据集与比较统计尚未完成 |
| RTMDet + DINOv2 双相机在线只读状态 | Experimental | 有带日期的部署记录和状态 verifier | 任务权重、跨相机/手眼标定与论文统计不完整 |
| 视觉触发真实执行 | Planned | 授权器代码 fail-closed，配置执行锁为 false | 所有标定、身份、深度、时延、模型、现场安全门禁 |
| 语音/文字结构化候选 | Experimental / 部分 Verified | 隔离 Voice Bridge、协议和 mock 有测试 | 候选不会获得真实机器人权限；VLA 对比研究未完成 |
| 视觉/VLA/综合论文主张 | Planned Evidence | 假设、schema 与基线模板存在 | 冻结数据、重复实验、区间、统计检验和生成图表 |

### 1.5 端口是“主机 + 传输 + 端口”

| 服务 | 默认绑定 | 端口/传输 | 权限与来源 |
| --- | --- | --- | --- |
| Python VLA FastAPI 对象 | `0.0.0.0` | `8000/TCP` | 实验性；[配置](configs/web.yaml) |
| Startouch Web/机器人 WebSocket | `0.0.0.0` | `3000/TCP` | 可产生控制权；[Node 配置](web-control/server/config.js) |
| Lumos HTTP 快照/MJPEG | `0.0.0.0` | `3001/TCP` | 相机只读；[服务](web-control/server/lumos_http_server.py) |
| Voice Protocol v1 | `0.0.0.0` | `3001/TCP`（通常在 Jetson） | 候选只读；与同主机 Lumos TCP 3001 冲突，可先用 `3002` |
| 双相机在线页面 | `0.0.0.0` | `3100/TCP`（安全启动脚本固定） | 模拟机器人、只读视觉；[启动器](scripts/vision/start_dual_camera_online.sh) |
| 固定 A/B 控制页 | `127.0.0.1` | `8766/TCP` | 页面空闲不占 CAN；开始后可启动受监督运动 |

暴露到 `0.0.0.0` 不等于已具备身份认证或公网安全性。仅在受控局域网使用，先检查端口
占用；Voice 与 Lumos 可复用端口号的前提是位于不同主机，或改用不同 TCP 端口。

---

<a id="tutorial-02-robotics-geometry"></a>

## 2. 机器人学与几何基础

### 2.1 六自由度、关节空间与笛卡尔空间

机械臂状态可写为六维关节向量

\[
\mathbf q=[q_1,q_2,q_3,q_4,q_5,q_6]^T,
\]

仓库控制接口以度显示/校验关节，以 SDK 所需的弧度下发。关节运动 `move_j` 指定目标
`q`，优点是可直接检查每轴限位；笛卡尔运动 `move_l` 指定末端位姿
`(x,y,z,roll,pitch,yaw)`，必须经逆运动学、工作区、路径和碰撞检查。当前可安装应用的
[Robot 适配器](src/uiea_thirdhand_vla/control/robot.py) 只是框架；真实 Startouch 桥接的
关节路径、反馈与校验在 [startouch_bridge.py](web-control/server/startouch_bridge.py)。

**知识链：**关节角 → 正/逆运动学 → 末端位姿 → 限位/速度/时效 → CAN 运动。任何一步
无效都应拒绝，而不是裁剪到“最近可用”值。

### 2.2 坐标系与命名

本文用 `T_target_from_source` 表示把 source 坐标转换到 target 坐标的齐次变换。主要坐标系：

| 坐标系 | 含义 | 代码/证据 |
| --- | --- | --- |
| `robot_base` | 固定机器人基座，三维目标与工作区的共同坐标 | [类型合同](web-control/server/vision/types.py) |
| `robot_flange` | 末端法兰，随关节运动 | [双相机组合](web-control/server/vision/dual_camera.py) |
| `lumos` | 主视觉相机原生 SEUCM 坐标 | [相机模型](web-control/server/vision/camera_models.py) |
| `d435` | D435 深度光学坐标，输入是轴向 Z 深度 | [深度注册](web-control/server/vision/depth_registration.py) |
| pixel | 图像 `(u,v)`，不是米制空间 | Lumos mask 和注册深度必须有相同原生图像形状 |

当前融合链为：

\[
T_{base\leftarrow lumos}=T_{base\leftarrow flange}T_{flange\leftarrow lumos},\quad
p_{base}=T_{base\leftarrow lumos}T_{lumos\leftarrow d435}p_{d435}.
\]

链中每个标定对象都应有方向、单位、内容寻址 ID、验证状态和残差；不能仅写“camera pose”。

### 2.3 RPY 约定

本仓库视觉几何将 SDK 的 `(roll,pitch,yaw)` 解释为固定顺序

\[
R=R_z(yaw)R_y(pitch)R_x(roll).
\]

实现见 [rpy_xyz_to_matrix](web-control/server/vision/geometry.py)。RPY 不是 Rodrigues 旋转
向量，乘法顺序也不可互换。复现时应把角度单位、主动/被动旋转、行/列向量约定写进
实验清单，并用复合旋转测试防止“单轴都对、组合错误”。

### 2.4 齐次变换与 SE(3)

刚体位姿属于 \(SE(3)\)：

\[
T=\begin{bmatrix}R&t\\0&1\end{bmatrix},\quad R^TR=I,\quad \det R=1,
\]

点 `p_source` 先补齐为 `(x,y,z,1)`，再左乘变换。逆变换是

\[
T^{-1}=\begin{bmatrix}R^T&-R^Tt\\0&1\end{bmatrix}.
\]

[几何模块](web-control/server/vision/geometry.py) 会检查有限值、旋转正交性、行列式和齐次
末行；[类型模块](web-control/server/vision/types.py) 还冻结时间戳、协方差、frame 和
`calibration_id`，防止无来源的三维点进入后续门禁。

### 2.5 内参、畸变与两类相机模型

针孔相机内参

\[
K=\begin{bmatrix}f_x&0&c_x\\0&f_y&c_y\\0&0&1\end{bmatrix}
\]

把三维点映射到像素。D435 的 depth 是光轴方向 `Z`，不是从光心到点的欧氏距离；
[PinholeCamera.deproject_z](web-control/server/vision/camera_models.py) 明确按轴向深度反投影。

Lumos 超广角采用 SEUCM。对相机点 `(X,Y,Z)`，实现先计算
`d=sqrt(beta*(X²+Y²)+Z²)`、`s=alpha*d+(1-alpha)*Z`，再用
`u=fx*X/s+cx`、`v=fy*Y/s+cy` 投影，并显式返回有效域。全图先拉直成针孔会损失边缘
分辨率和视野；主算法保留原生 Lumos 像素，虚拟针孔视图只可作为受控消融。详见
[鱼眼模型研究](docs/vision_research/03_FISHEYE_VISION_RESEARCH.md)。

### 2.6 外参和手眼标定

内参描述单个相机，外参描述坐标系之间的刚体关系。当前完整链需要 D435→Lumos、
Lumos→flange（或固定相机的 base→camera）和时间对齐的机器人姿态。以下仍使用
`T_{target←source}`，即矩阵把 source 坐标中的点变换到 target 坐标。

OpenCV `cv2.calibrateHandEye` 的输入合同是每个姿态的 `T_{base←gripper}`
（参数名 `gripper2base`）与 `T_{camera←target}`（`target2cam`）；返回值是
`T_{gripper←camera}`（`cam2gripper`），而不是 `T_{base←camera}`。eye-in-hand 中相机刚性
安装在 gripper 上，后者是固定外参，某一机器人姿态下应显式组合
`T_{base←camera}=T_{base←gripper} T_{gripper←camera}`。eye-to-hand 中相机固定在 base，目标
量才是固定的 `T_{base←camera}`；它使用不同的运动链/输入倒置或交换，不能把 eye-in-hand
返回值直接改名为 base→camera。

当前 [CoordinateTransforms.calibrate_hand_eye](src/uiea_thirdhand_vla/perception/transforms.py)
把 `T_base_ee` 和 `T_camera_marker` 传入上述接口，却把返回的 camera→gripper 直接存成
`T_base_cam` 并声称返回 base→camera；这是 frame 标注与组合错误。在实现按安装方式拆分、
修正方向/组合并通过独立留出姿态验证以前，该 helper **不得用于真实执行，也不得作为 SCI
标定证据**。研究管线用[标定审计与双相机 bundle](web-control/server/vision/dual_camera.py)
把来源校验和组合成新的内容 ID，但内容 ID 本身不修复坐标链。

手眼结果必须在独立留出姿态上报告平移/旋转或重投影残差。现有研究审计明确指出旧
Lumos 标定残差不可用于执行；不要把“文件存在”当作 `validated=true`。重采集协议见
[标定计划](docs/vision_research/07_CALIBRATION_PLAN.md)。

### 2.7 限位、速度、watchdog 和停止层级

真实 Startouch Web 边界使用下列硬件联调限位；它们也写入
[fixed_pick_place.yaml](configs/tasks/fixed_pick_place.yaml)：

| 轴 | 角度范围 | 标称最大速度 | Web 默认命令比例 |
| --- | ---: | ---: | ---: |
| J1 | `[-162°, 162°]` | `300°/s` | `5%` |
| J2 | `[-12°, 201°]` | `300°/s` | `5%` |
| J3 | `[-183°, 0°]` | `300°/s` | `5%` |
| J4 | `[-98°, 98°]` | `1000°/s` | `5%` |
| J5 | `[-98°, 98°]` | `1000°/s` | `5%` |
| J6 | `[-164°, 164°]` | `1000°/s` | `5%` |

[configs/robot.yaml](configs/robot.yaml) 和 [configs/workspace.yaml](configs/workspace.yaml)
定义可安装应用的通用配置，但其中关节范围与 Startouch 硬件联调范围并不相同；真实 Web
入口以 `server/config.js`/bridge 校验为准。当前 `setup_system()` 也没有把独立 workspace
块完整接入 `Safety`，所以不能声称 YAML 中的工作区已在所有入口统一强制执行。

Startouch bridge 还执行：控制锁、六轴有限值/限位、意外全零拒绝、稳定初态、CAN 主动
反馈、运动串行化和反馈停更 watchdog。默认 `STARTOUCH_CAN_RX_STALE_SEC=1`，检测到反馈
停更会断开/清理。`configs/workspace.yaml` 的参考边界为 x `[-0.3,0.5]`、y
`[-0.4,0.4]`、z `[-0.05,0.4]` m，参考线速度 `0.5 m/s`、关节速度 `90°/s`、超时
`10 s`；这些值必须在具体控制边界中验证已接线后才能称为执行约束。

停止层级从弱到强是：任务取消/停止发新命令 → SDK 软件停止和 `cleanup()` → 独立硬件急停
或动力切断。软件链路失败、机械臂行为异常或人员进入工作区时，直接使用硬件急停；不要
等待浏览器响应。

---

<a id="tutorial-03-perception"></a>

## 3. 感知与视觉主研究轴

本章按六个可独立检验的方法单元组织。每个单元都给出 Problem、Method、Protocol、
Metrics、Evidence、Limits，便于直接映射到[主张矩阵](docs/research/claim_evidence_matrix.md)、
[数据集说明](docs/research/dataset_datasheet.md)、[基线/消融矩阵](docs/research/baseline_ablation_matrix.md)、
[图表清单](docs/research/figure_manifest.md)与[复现清单](docs/research/reproducibility_checklist.md)。

### 3.1 方法一：逻辑相机角色与原生成像模型

#### Problem

广角主图像和米制深度来自不同相机；若身份、分割和深度各自随意选择 RGB，会出现语义
漂移、边缘畸变误差和不可复现的设备角色切换。

#### Method

`canonical_rgb=lumos_rgb`：RTMDet mask、DINOv2 外观和身份都以 Lumos 原生 SEUCM 像素
为准；`metric_depth=d435_depth`：D435 pinhole Z-depth 提供米制几何；
`debug_rgb=d435_rgb`：只显示调试画面，不决定实例身份。角色合同见
[online_frames.py](web-control/server/vision/online_frames.py)和
[remind3d.yaml](configs/vision/remind3d.yaml)。

#### Protocol

记录设备序列/固件、逻辑角色、分辨率、帧率、像素格式、内参 ID 与每帧 monotonic
timestamp；数据 split 按录制会话/场景/物理实例隔离。SEUCM 必须用中心/边缘留出点验证，
D435 深度单位必须在录制清单中固定。

#### Metrics

中心/径向分桶重投影 median、P95、max；无效域比例；采集丢帧率；角色错误率；主/调试
源切换次数；按径向分桶的 mask AP/recall。

#### Evidence

相机模型单元测试和带日期的只读部署记录已存在，属于工程验证；真实比较研究仍是
Planned Evidence。清单入口见[数据集模板](docs/research/dataset_datasheet.md)，预览位置 V3。

#### Limits

官方 COCO 权重的单帧输出不证明任务类别性能；设备枚举、曝光、照明和鱼眼域偏移仍是
混杂因素。当前标定链未完成执行验收。

### 3.2 方法二：时间配对、标定来源与坐标链

#### Problem

运动场景中即使几何外参正确，过期或错配的 RGB/depth/robot pose 也会生成错误三维点；
无版本的标定文件无法判断结果属于哪条坐标链。

#### Method

[LatestFramePairer](web-control/server/vision/online_frames.py) 使用 monotonic 时间戳，采用
latest-only 配对，不等待、不插值、不发明时间。当前配置要求 RGB–depth skew ≤`50 ms`、
帧龄 ≤`200 ms`、机器人姿态 skew ≤`50 ms`；超限只产生原因码。每个有效标定以
`sha256:` 内容 ID 和 `validated` 状态进入 [DualCameraCalibrationBundle](web-control/server/vision/dual_camera.py)。

#### Protocol

冻结时钟源与单位；记录每帧序号、三个时间戳、pair 决策、排除原因、标定文件校验和、
外参方向及独立验证残差。按静态/运动、中心/边缘、不同 skew 桶分别评估，禁止同一 clip
跨训练和测试。

#### Metrics

skew/age P50、P95、max；配对接受率；错配率；不同 skew 桶的注册像素误差、平面 mm
误差和三维位置误差；标定失效检出率。

#### Evidence

时间与标定 fail-closed 测试已实现；A-REG-01 仍为 Planned Evidence，且预注册阈值未
就绪。使用[主张矩阵](docs/research/claim_evidence_matrix.md)记录这一状态，而不是从工程
预算倒推出论文阈值。

#### Limits

单机 monotonic 时间不能自动解决不同设备硬件时钟偏置；重新安装相机、移动支架或更新
内参会使旧外参失效。缺机器人姿态时允许做身份观察，但不得生成可执行 base-frame 目标。

### 3.3 方法三：D435→Lumos 深度注册与 z-buffer

#### Problem

D435 的深度像素不与 Lumos mask 共格；直接按相同 `(u,v)` 取深度会把背景或遮挡面赋给
目标，尤其在双相机基线、边缘和深度不连续处。

#### Method

[register_depth_to_lumos](web-control/server/vision/depth_registration.py) 依次：过滤无效/范围外
Z-depth → 用 D435 pinhole 反投影 → 左乘 `T_lumos_from_d435` → 用 Lumos SEUCM 投影 →
最近整数像素栅格化。多个源点落入同一 Lumos 像素时，z-buffer 保留正 Z 最近表面，同时
记录 `source_count`、轴向 `z_m`、欧氏 `range_m` 和 Lumos 三维点。最后由布尔实例 mask
选择点云；缺深度时绝不以桌面平面伪造。

#### Protocol

用已知平面/标靶和遮挡边界录制同步深度；固定 min/max depth、分辨率、取整策略、外参 ID
与无效值政策。比较无注册、无时间门禁、无 z-buffer 和完整方法；按径向与遮挡边界切片。

#### Metrics

注册 coverage、像素误差 P50/P95、平面 mm 误差、flying-edge 率、mask 内点云纯度、
空洞率、单帧/端到端 P50/P95 时延。

#### Evidence

合成注册测试和微基准见[离线实现记录](docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md)，
只能证明实现与确定性；其真实精度证据为 Planned Evidence。未来 V1/V3/E1/E2 必须由
机器可读结果生成。

#### Limits

最近像素是基线而非亚像素最优方法；透明、反射、黑色物体和视差遮挡会造成深度缺失。
纯 NumPy 微基准不含采集、模型和 UI，不能证明端到端实时性。

### 3.4 方法四：RTMDet 实例 mask 与 DINOv2 描述符

#### Problem

检测框混入背景，难以获得纯目标点云；仅靠类别/框位置也无法在同类物体遮挡后维持身份。

#### Method

[RTMDet adapter](web-control/server/vision_models/rtmdet.py) 要求原生图像尺寸的非空布尔实例
mask，并校验配置 labels 与 checkpoint 元数据完全一致。
[DINO adapter](web-control/server/vision_models/dino.py) 将 mask 映射到 patch coverage，
池化、归一化为每实例描述符；模型只在适配器实例化时懒加载。当前默认是官方 COCO
RTMDet-Ins tiny 和 `facebook/dinov2-small`，且 `task_checkpoint_validated: false`。

#### Protocol

建立任务专用类别与实例标注，冻结 train/validation/test；所有模型在相同主图、输入尺度、
阈值、硬件和测量窗口下比较。基线包括 YOLOv8n detect、YOLO nano segmentation、
RTMDet-tiny-ins、Mask R-CNN R50-FPN；记录权重 SHA-256 和许可。

#### Metrics

per-class box/mask AP 与 recall、empty-scene FP、径向分桶、mask coverage、点云纯度、
描述符类内/类间距离、P50/P95 时延、吞吐、CPU/GPU/VRAM。

#### Evidence

真实帧 GPU smoke 和在线可用性是带日期的工程证据，详见
[部署记录](docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md)；因任务权重与完整统计缺失，
论文层面属于 Evidence Incomplete，不能宣称检测优越。比较计划见[基线矩阵](docs/research/baseline_ablation_matrix.md)。

#### Limits

COCO 类别与桌面任务域不等价；单帧非空 mask 不等于 recall/精度验收。鱼眼边缘、截断、
相似外观、mask 漂移和模型许可都需单独报告。

### 3.5 方法五：短期追踪、work/stable 记忆与重捕获

#### Problem

逐帧 detection ID 不是物理实例身份。漏检、遮挡、离开后重入和多个相似物体会引发 ID
switch、轨迹碎裂或危险误合并。

#### Method

基础 [MultiObjectTracker](web-control/server/vision/tracking.py) 用常速度预测、同类门控、
组合协方差 Mahalanobis 代价与 Hungarian 全局分配。研究在线路径进一步使用
[PersistentIdentityMemory](web-control/server/vision/identity.py)：外观相似度占 `0.8`、短期
三维占 `0.2`，维护最多 8 个 work 和 12 个 stable 原型；低置信度/低可见度观测不能创建
或污染记忆。当前 `300 ms` 后标记 occluded、`1.5 s` 后 inactive，重捕获需连续 2 次
带深度确认；近优全局分配差小于 ambiguity margin 时显式返回 `AMBIGUOUS`。

#### Protocol

按物理实例和 clip 冻结遮挡/重入测试集，固定 detections 与 descriptors，分别比较
IoU-only、appearance-only、appearance+3D、work-only、work+stable 和歧义拒绝 on/off。
每个种子保留逐帧 assignment、cost、status、memory bank 状态和拒绝原因。

#### Metrics

HOTA、IDF1、ID switches、fragmentation、reacquisition rate/time、false identity merges、
ambiguous accept/reject、身份容量和内存/时延。

#### Evidence

合成身份回放证明状态机输出可确定且歧义不会被强制分配，但不证明真实 ReID 准确率。
A-ID-01、V2、E1、E2 仍需 held-out 真实序列、重复测量和区间，见
[主张矩阵](docs/research/claim_evidence_matrix.md)。

#### Limits

descriptor 域偏移、同款同色物体、长期光照变化和 detector 变化会混淆身份贡献。长期重入
保留 ID 后仍先处于 tentative；不能因“看起来相似”跳过连续确认。

### 3.6 方法六：mask 三维位姿、协方差与 actionability

#### Problem

bbox 中心或点云均值会被背景、边缘噪声和离群深度偏移；即使有三维中心，未量化时效与
不确定度也不能决定目标是否可供后续动作考虑。

#### Method

[estimate_instance_pose](web-control/server/vision/instance_pose.py) 默认腐蚀 mask `3 px`，要求
至少 `80` 个有效点，以逐轴 median 和 `3.5×MAD` 去除离群，变换到 `robot_base` 后用
median 得到中心，并将样本 covariance 加 `0.002 m` noise floor。身份层要求标定有效、
位姿年龄 ≤`200 ms`、最大位置标准差 ≤`0.025 m`、至少 2 次 pose hit；通用
[Safety](web-control/server/vision/safety.py) 还检查标定匹配、点云数量、工作区与显式可达性。
在线页面再强制目标 `actionable:false`/execution false。

#### Protocol

在有真值的静态/重复放置序列中，按材质、距离、径向和遮挡切片；比较 bbox 中心、mask
均值、mask median、侵蚀/MAD/noise-floor 消融。冻结标定、工作区、时效与可达性判据，
同时记录被拒绝样本而不是删除失败。

#### Metrics

三维位置误差和轴向偏差、静态 jitter、covariance calibration/coverage、有效点数、
actionability 接受/拒绝率、错误放行率、拒绝原因分布、P50/P95 时延。

#### Evidence

单元/合成测试覆盖稀疏深度、离群、协方差和 fail-closed 原因；真实 base-frame 精度仍是
Planned Evidence。预览 V1/V3/F1 只有链接 manifest 和生成命令后才能升级为结果。

#### Limits

covariance 表达观测点分散度，不自动包含全部外参系统误差；当前没有通过验收的完整标定链
和碰撞规划器。`actionable` 是感知条件，不等于机器人执行授权。

---

<a id="tutorial-04-vla-interaction"></a>

## 4. VLA、语音与人机交互

### 4.1 建议，不是执行权

[VLAClient](src/uiea_thirdhand_vla/reasoning/vla_client.py) 把图像和结构化上下文发送给
Anthropic、DeepSeek 或 OpenAI-compatible provider，返回 `VLARecommendation`：action、
target、confidence、reasoning、recovery 或 clarification。暴露给模型的
[tools](src/uiea_thirdhand_vla/reasoning/vla_tools.py) 只有选对象、请求澄清和建议恢复；没有
关节、CAN 或 SDK tool。密钥仅从环境变量读取，见 [.env.example](.env.example)，不得进入
日志、数据集或 Git。

当前 packaged FSM 在多目标时消费建议；API 失败会退回第一个 detection，这一行为只适合
无真实控制权的实验框架，不能作为安全 VLA 执行策略。科研路径应将超时、未知 target、
低置信度和不支持 action 记录为拒绝/澄清，而不是隐式选第一个对象。

### 4.2 ASR、NLU、TTS 与 Voice Bridge 是两条路径

| 路径 | 当前状态 | 数据流 | 控制权限 |
| --- | --- | --- | --- |
| `src/.../interaction` | Planned/框架 | ASR → NLU `Intent` → FSM；文本 → TTS | ASR/NLU/TTS 方法尚无完整实现 |
| Jetson Voice Bridge | Experimental，隔离测试部分 Verified | WhisperASR（语音）→ ClaudeAgent → 回复 + candidate | 不导入 RobotExecutor，不连接机器人 `/ws` |
| 浏览器文字输入 | Implemented 于 Voice Protocol v1 | `text.submit` 直接进 ClaudeAgent，不调用 ASR | 与语音共用候选、预览和确认边界 |

[ASR/TTS 配置](configs/asr_tts.yaml) 描述 faster-whisper、中文、16 kHz、local NLU 和
edge-tts，但配置存在不代表模块已完成。生产型 Bridge 的 final-only 基线不发送 partial，
也不播放 TTS；`assistant.response` 只显示文字。协议与部署细节见
[Voice Protocol v1](web-control/docs/voice-protocol-v1.md) 和
[Voice Bridge README](web-control/voice-bridge/README.md)。

### 4.3 结构化候选、预览和确认

```text
audio/text/image
  → transcript / grounded context
  → structured intent.candidate
  → schema + whitelist + range validation
  → local 3D preview and audit log
  → explicit human confirmation
  → deterministic local safety validation
  → supervised platform consideration（当前仍不执行）
```

Voice v1 候选包含 `candidateId`、`intent`、`tool`、`sourceText`、
`requiresConfirmation` 和 `args`。网页白名单只涵盖受限 status/preset/gripper 类候选；
任意关节角、raw servo、网络配置等意图应保持禁用。即使用户点击确认，当前原型也只更新
本地 3D 预览和日志，不发送到机器人 `/ws`。不支持的意图、未知参数、过期候选、断线、
模型超时或多个并发会话必须显式拒绝。

### 4.4 VLA 次研究轴的可证伪问题

Track B 比较自由文本直接输出（仅离线不安全基线）、structured candidate、
candidate+preview、candidate+preview+human confirmation+local validation。指标包括 task/
intent accuracy、schema validity、unsupported-action rate、unsafe-action interception、human
correction、refusal quality、recovery success 和端到端 latency。自由输出基线不得连接 actuator、
CAN 或真实机器人；协议见[基线矩阵](docs/research/baseline_ablation_matrix.md)。

隐私上，录音、转写、图像和云端 prompt 都可能含个人/场地信息。数据集必须记录同意、
去标识、访问控制、保留期、第三方 API 传输和删除流程。网络不可用时保持离线 mock/拒绝，
不能绕过候选校验。

---

<a id="tutorial-05-control-safety"></a>

## 5. 控制、编排与安全

### 5.1 确定性编排

[StateMachine](src/uiea_thirdhand_vla/orchestration/state_machine.py) 的主路径是：

```text
IDLE → DETECT → APPROACH → GRASP → LIFT → TRANSFER → PLACE → RETURN → SUCCESS
          ↘ ERROR ←──────────────────────────────────────────────┘
EMERGENCY_STOP → IDLE（只表示软件状态转换，不表示硬件急停已复位）
```

[CentralControlUnit](src/uiea_thirdhand_vla/orchestration/central_control.py) 是 FSM 与相机、
detector、robot、gripper、safety 的 facade，关节/位姿命令在适配器前做本地检查。当前 FSM
`IDLE` 会自动进入 `DETECT`，且 control adapter 不是真机实现，所以不得将 packaged `full`
模式用于无人值守硬件。真实 fixed A/B 使用独立 runner、固定配置和逐步人工确认，详见
[FIXED_PICK_PLACE.md](web-control/FIXED_PICK_PLACE.md)。

### 5.2 控制适配器和 CAN 所有权

真实链路只有一个 CAN owner：

```text
Browser /ws → proxy.js → startouch-bridge.js → startouch_bridge.py
             validation     child lifecycle      SDK + can0 + feedback
```

bridge 在非 simulate/dry-run 时尝试取得 `/tmp/startouch-web-<interface>.lock` 的非阻塞
`flock`；失败即拒绝连接。固定点启动器还扫描实际控制进程、锁、worktree 文件占用、分支、
CAN UP/1 Mbps、点位、段间跳变和日志目录。资源锁不能阻止仓库外所有错误程序，因此现场
仍需进程审计和硬件急停。

### 5.3 分层门禁与 fail closed

| 层 | 必须成立 | 失败行为 | 实现 |
| --- | --- | --- | --- |
| 输入 | 六轴/位姿/时间戳有限、shape/单位正确 | 拒绝消息 | [bridge](web-control/server/startouch_bridge.py)、[vision types](web-control/server/vision/types.py) |
| 资源 | CAN 独占锁、桥接状态稳定、无运动并发 | 不连接或不排队 | [Startouch bridge](web-control/server/startouch_bridge.py) |
| 运动 | 关节限位、速度/时间、非意外全零 | 拒绝目标 | [Node config](web-control/server/config.js) |
| 相机 | 逻辑角色、帧新鲜、skew 在限 | 只报 blocker | [online frames](web-control/server/vision/online_frames.py) |
| 几何 | 标定有效、深度足够、机器人姿态同步 | 不产生可信 base pose | [dual camera](web-control/server/vision/dual_camera.py) |
| 身份 | 非歧义、确认、fresh、covariance 在限 | `actionable:false` | [identity](web-control/server/vision/identity.py) |
| 授权 | task checkpoint、安全字段、人工与执行开关 | `robot_execution_disabled` 等原因 | [grasp authorization](web-control/server/grasp-authorization.js) |

在线状态页把来源对象重新清洗并强制不可操作；[配置](configs/vision/remind3d.yaml)必须保持
`stop_and_look_only: true`、`task_checkpoint_validated: false` 和
`robot_execution_enabled: false`。这些 blocker 是正确安全结果，不是需要“修掉”的异常。

### 5.4 软件停止与硬件急停

- **任务停止**：阻止后续阶段，不保证正在执行的物理运动立即失能。
- **软件停止**：bridge 请求 SDK `cleanup()` 和电机失能，释放锁；依赖进程、操作系统、
  CAN 与 SDK 正常，页面只可停止它拥有的进程组。
- **硬件急停/动力切断**：独立于浏览器、网络和代码，是人员/设备风险时的首选措施。

若 Stop 按钮、Ctrl+C 或软件急停没有获得明确完成确认，按“停止未证实”处理：使用硬件急停，
隔离动力，检查日志/CAN/物理状态，原因未明前不得重启。

### 5.5 为什么控制不是当前 SCI 新颖性

Startouch bridge、固定点 runner 和资源门禁是让视觉/VLA 实验可监督、可复现的基础设施。
论文不能把 vendor SDK 包装、固定 A/B 点或已有安全检查包装成视觉算法贡献。可选 Track C
研究的是“感知不确定度如何改变候选、拒绝和恢复”，机械臂只提供受监督验证平台。

---

<a id="tutorial-06-code-map"></a>

## 6. 代码地图与运行接口

### 6.1 精选目录树

```text
TH-Fanxy/
├── src/uiea_thirdhand_vla/       # 可安装 Python 实验框架
│   ├── config/ perception/ reasoning/ interaction/
│   ├── orchestration/ control/ logging/ web/
├── web-control/                  # Startouch 真机边界、相机、视觉、语音和网页
│   ├── server/{vision,vision_models}/
│   ├── web/  voice-bridge/  scripts/  demo/
├── configs/                      # robot/camera/workspace/VLA/Web/task/vision YAML
├── scripts/                      # 部署、回放模型、固定演示与诊断入口
├── tests/                        # docs/core/web/vision-deployment 离线合同
└── docs/                         # 架构、API、安全、视觉研究与 SCI 证据层
```

### 6.2 `src/uiea_thirdhand_vla`：可安装应用

| 模块 | 职责/接口 | 依赖 | 安全边界与深链 |
| --- | --- | --- | --- |
| `config` | 合并 YAML；Pydantic 配置模型 | PyYAML/Pydantic | loader 当前静默忽略解析异常；[代码](src/uiea_thirdhand_vla/config/loader.py) |
| `perception` | Camera、SEUCM、ArUco/YOLO、pixel↔base | OpenCV/NumPy/可选 Ultralytics | 默认手眼为单位阵不能用于真机；[模块](src/uiea_thirdhand_vla/perception/) |
| `reasoning` | `reason()`/`reason_sync()` → `VLARecommendation` | 云 API/HTTP/Pillow | advisory only；[client](src/uiea_thirdhand_vla/reasoning/vla_client.py) |
| `interaction` | `ASREngine`、`NLUEngine`、`TTSEngine` 合同 | voice extras | 当前方法未完成；[模块](src/uiea_thirdhand_vla/interaction/) |
| `orchestration` | FSM、CCU、task base | perception/control | 确定性转换；packaged full 会自动开始；[模块](src/uiea_thirdhand_vla/orchestration/) |
| `control` | Robot/Gripper/Safety adapter | 当前无 vendor SDK 接线 | 不是真实控制证据；[模块](src/uiea_thirdhand_vla/control/) |
| `logging` | run metadata、transition、可选帧 | 标准库/OpenCV | 日志不得含 secret；[模块](src/uiea_thirdhand_vla/logging/) |
| `web` | FastAPI app/static/API router 文件 | web extras | routers/WS 当前未装入 app；[server](src/uiea_thirdhand_vla/web/server.py) |

### 6.3 `web-control`：硬件、视觉和交互边界

| 模块 | 责任/接口 | 依赖 | 安全边界与深链 |
| --- | --- | --- | --- |
| `server/proxy.js` | 静态 UI、`/ws`、相机与 vision HTTP | Node/Express/ws | 运动前校验；vision execution 强制 false；[代码](web-control/server/proxy.js) |
| Startouch bridge | JSON Lines、CAN preflight、SDK 状态/轨迹/夹爪 | vendor SDK/SocketCAN | 单接口锁、反馈 watchdog、cleanup；[Python](web-control/server/startouch_bridge.py) |
| camera bridge | D435 owner、MJPEG、可选在线模型事件 | pyrealsense2/OpenCV | 不打开 CAN/robot；[代码](web-control/server/camera_bridge.py) |
| `vision` | 几何、注册、追踪、身份、位姿、安全、回放 | NumPy/SciPy | 纯计算，invalid/stale/ambiguous 拒绝；[目录](web-control/server/vision/) |
| `vision_models` | RTMDet、DINO、online/replay adapter | Torch/MMDetection/Transformers | lazy heavy imports，execution false；[目录](web-control/server/vision_models/) |
| Lumos HTTP | `/health`、`/frame.jpg`、`/camera_lumos` | OpenCV/V4L2 | 相机只读、帧序号和 monotonic header；[服务](web-control/server/lumos_http_server.py) |
| Voice Bridge | `/v1/voice`、audio/text candidate | websockets/现有 voice_agent | 无 RobotExecutor/机器人 WS；[README](web-control/voice-bridge/README.md) |
| fixed runner/demo | simulate/dry-run/real、loopback page | bridge/YAML | 逐步确认、资源预检、30% 硬上限；[说明](web-control/FIXED_PICK_PLACE.md) |

### 6.4 `configs`：配置不是验收证据

| 文件/深链 | 职责/接口 | 依赖/读取者 | 安全边界 |
| --- | --- | --- | --- |
| [robot.yaml](configs/robot.yaml) | 通用型号、CAN、TCP、home、gripper | packaged config loader/models | 范围不同于硬件 Web 联调范围 |
| [camera.yaml](configs/camera.yaml) | Lumos 设备、像素、SEUCM/深度字段 | packaged Camera/models | 实际默认值仍需核对接线 |
| [workspace.yaml](configs/workspace.yaml) | base-frame bounds、桌面、速度、超时 | packaged config contract | 不能假设所有入口已统一应用 |
| [asr_tts.yaml](configs/asr_tts.yaml) | ASR/NLU/TTS/mic | packaged interaction | interaction 尚未完整实现 |
| [vla.yaml](configs/vla.yaml) | provider/model/image/session/trigger | VLA client/FSM | 建议层，不含执行权限 |
| [web.yaml](configs/web.yaml) | `0.0.0.0:8000`、WS/video | packaged FastAPI | routers/WS 尚未装配 |
| [fixed_pick_place.yaml](configs/tasks/fixed_pick_place.yaml) | 点位、限位、速度、lift、确认、验收计数 | fixed runner/demo | 真实模式仍受 bridge/人工门禁约束 |
| [remind3d.yaml](configs/vision/remind3d.yaml) | 角色、模型、时间、身份、位姿、预算、安全 | vision/vision_models/launcher | v1 宽松配置；执行固定 false |
| [active_view.yaml](configs/vision/active_view.yaml) | dry-run 观测提案参数 | active-view dry-run modules | `active_view_execution_enabled:false`，不代表运动能力 |

### 6.5 `scripts` 与受支持入口

| 入口/深链 | 职责/接口 | 依赖 | 安全状态 |
| --- | --- | --- | --- |
| [packaged CLI](src/uiea_thirdhand_vla/__main__.py) | `thirdhand-vla` / `python -m`；`camera/detect/pick_place/web/full` | Python extras/configs | Experimental；不作为真机指南 |
| [setup_ubuntu.sh](web-control/scripts/setup_ubuntu.sh) | 检查环境并 `npm ci` | Ubuntu/Node/npm/可选 SDK | L0；不修改系统包 |
| [start_ubuntu.sh](web-control/scripts/start_ubuntu.sh) | 启动 Node Web 栈 | Node、可选 SDK/CAN/camera | L2 simulate 或 L4 受监督真实 |
| [bootstrap_remind3d_env.sh](scripts/vision/bootstrap_remind3d_env.sh) | 打印/安装独立 CUDA 模型环境 | Conda/pip/CUDA | L0；模型主机专用 |
| [vision replay](web-control/server/vision/replay.py) / [identity replay](web-control/server/vision_models/offline_replay.py) | 合成几何/身份确定性回放 | NumPy/SciPy/fixture | L1，无硬件 |
| [smoke_remind3d_models.py](scripts/vision/smoke_remind3d_models.py) | RTMDet+DINO 资源/合同 smoke | model env/本地图像权重 | L1/L3，只读图像与 GPU |
| [start_dual_camera_online.sh](scripts/vision/start_dual_camera_online.sh) | 端口 3100 安全生命周期 | Lumos HTTP/D435/model env/Node | L3，固定 simulate/假 CAN/无 gripper |
| [verify_dual_camera_online.py](scripts/vision/verify_dual_camera_online.py) | 一秒采样、原子 readiness JSON | HTTP status/Python | L3，只读 |
| [demo_fixed_pick_place.sh](scripts/demo_fixed_pick_place.sh) | 固定点手动演示包装入口 | branch/CAN/owner/点位/路径/lift/YAML/bridge | 唯一教程 L4 入口；默认 `manual` 并按配置逐步确认 |
| [open_fixed_pick_place_control.sh](scripts/open_fixed_pick_place_control.sh) | loopback 8766 操作页 | Python/demo runner | Experimental、非教程入口；自动路由尚未硬门禁 |
| [fixed_pick_place.py](web-control/scripts/fixed_pick_place.py) | simulate/dry-run/real 底层 runner | YAML/Startouch bridge | L2 可直接 simulate/dry-run；真实模式仅供包装脚本内部调用 |
| [teach_fixed_point.py](web-control/scripts/teach_fixed_point.py) | 读取/验证/原子保存 J1–J6 点位 | real bridge/YAML | L4；会备份旧 YAML |
| [check_hardware.py](scripts/check_hardware.py)、[calibrate_camera.py](scripts/calibrate_camera.py)、[teach_points.py](scripts/teach_points.py) | 早期脚本骨架 | 当前仅标准库打印 | Planned；不完成自动检查/标定/教学 |

### 6.6 `tests`：验证什么、不验证什么

| 区域 | 责任/接口 | 依赖 | 安全含义 |
| --- | --- | --- | --- |
| [tests/docs](tests/docs/) | README、链接、身份、schema 合同 | pytest | 防止文档把规划写成结果 |
| [tests/web](tests/web/) | fixed demo 与 UI 安全源合同 | pytest | 不启动真实 CAN |
| [tests/vision_deployment](tests/vision_deployment/) | 环境/launch/bridge 静态与单元合同 | pytest | 强制 fake CAN、execution false |
| [server/tests/vision](web-control/server/tests/vision/) | SE(3)、SEUCM、注册、tracking、memory、安全 | NumPy/SciPy/pytest | 纯离线核心 |
| [server/tests/vision_models](web-control/server/tests/vision_models/) | model adapter/回放/online fake | pytest；重模型懒加载 | 单元测试不证明任务模型效果 |
| [server/test](web-control/server/test/) | Node protocol/browser/vision smoke | Node/npm | mock/simulate，无真实运动 |

### 6.7 `docs`：事实和证据来源

| 区域 | 责任/接口 | 依赖 | 深链 |
| --- | --- | --- | --- |
| 架构/安装/API/模块 | 两边界、系统依赖、接口合同 | 当前源码必须复核 | [architecture](docs/architecture.md)、[setup](docs/setup_guide.md)、[web API](docs/web_api.md) |
| `vision_research` | 设计、审计、实现/部署记录、验收计划 | 带日期、可能随部署失效 | [当前决策](docs/vision_research/14_FINAL_TECHNICAL_DECISION.md) |
| `research` | claim/dataset/experiment/result/figure/repro 合同 | machine-readable artifact | [证据中心](docs/research/README.md) |
| 安全文档 | Startouch 与 fixed demo 操作边界 | 现场监督 | [Web README](web-control/README.md)、[fixed demo](web-control/FIXED_PICK_PLACE.md) |

### 6.8 环境变量索引

| 变量 | 默认/示例 | 作用与安全说明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 仅本机 `.env` | 云 VLA；不得提交/录入数据集 |
| `THIRDHAND_WEB_HOST` / `THIRDHAND_WEB_PORT` | `0.0.0.0` / `8000` | `.env.example` 声明的覆盖名；当前 loader/server 未读取，不能依赖 |
| `STARTOUCH_PYTHON` / `STARTOUCH_SDK_PATH` | LumosTouch env / `~/arm/startouch_sdk` | 外部 SDK 不进入仓库 |
| `STARTOUCH_CAN_INTERFACE` | `can0` | 离线测试必须改为 `thirdhand-test` 类假名 |
| `STARTOUCH_SIMULATE` / `STARTOUCH_DRY_RUN` | `0` / `0` | simulate 不导入 SDK；dry-run 导入检查但不控硬件 |
| `STARTOUCH_SPEED_SCALE` | `0.05` | Web 比例被 clamp 到 `[0.01,1]`，真实 fixed runner另有 `0.30` 硬上限 |
| `STARTOUCH_REQUIRE_CAN_RX` / `STARTOUCH_CAN_RX_STALE_SEC` | `1` / `1` | 真实运行不得随意关闭反馈 watchdog |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `3000` | Startouch Node 监听 |
| `CAMERA_ENABLED` / `CAMERA_PYTHON` | enabled / REMIND env | D435 bridge 与模型 Python |
| `CAMERA_YOLO_MODEL` / `CAMERA_CALIB_FILE` | 本地权重/本地标定 | 文件存在不代表任务/标定已验收 |
| `VISION_ONLINE_ENABLED` / `VISION_CONFIG` | `0` / REMIND YAML | 在线模型只读开关与配置 |
| `LUMOS_HTTP_HOST` / `LUMOS_HTTP_PORT` | `0.0.0.0` / `3001` | Lumos camera-only HTTP |
| `LUMOS_SNAPSHOT_URL` / `LUMOS_STREAM_URL` | loopback `:3001` | 在线模型快照/浏览器 MJPEG 来源 |
| `VOICE_HOST` / `VOICE_PORT` | `127.0.0.1` / `3001`（mock） | 与同主机 Lumos TCP 端口互斥 |

更多 bridge 调优变量见 [Web README](web-control/README.md)；没有验收记录时不要用调参绕过
stale、初态匹配或速度门禁。

### 6.9 HTTP、REST 与 WebSocket

| 边界/传输 | 路径与默认 bind | 认证 | 控制权限与安全门禁 | 停止语义 | 成熟度 |
| --- | --- | --- | --- | --- | --- |
| packaged FastAPI HTTP/WS | 配置为 `0.0.0.0:8000`；文档列出 `/api/robot/*`、`/api/camera/*`、`/api/task/*`、`/ws` | 当前 app 未见有效认证接线，CORS 为 `*` | router 文件存在但 `create_app()` 未装配，不能取得实际控制权限 | 仅接口文件中的任务/机器人停止合同，运行 app 不可依赖 | Experimental 接口合同，非可用生产 API |
| Startouch Node HTTP | `0.0.0.0:3000`；`/`、`/diag`、`/camera`、`/camera_lumos`、`/camera_lumos_vision`、`/api/vision/status` | 无认证 | 静态页面与只读 vision status；实际控制经同服务 `/ws` | HTTP routes 不提供硬件急停 | Experimental；只能放在受控网络 |
| Startouch Node WebSocket | `ws://<host>:3000/ws` | 无认证；只按连接级 control lock 排他 | 精确 command 集：`connect`、`disconnect`、`servo`、`preset`、`gripper`、`software_stop`、`status`、`ping`、`estop`、`grasp_object`、`estop_camera`、`camera_refresh`；运动仍经限位、稳定初态、CAN feedback/watchdog 与串行化校验 | `software_stop` 调 SDK 软件停止；`estop` 只是它的别名，**不是硬件急停**；`disconnect` 清理 bridge；`estop_camera` 只停 camera bridge | 真实控制边界，L4 现场监督；无认证，禁止暴露到不受控网络 |
| Lumos HTTP | `0.0.0.0:3001`；`/health`、`/frame.jpg`、`/camera_lumos` | 无认证 | camera-only、只读；frame 含 sequence/monotonic headers，不获机器人权限 | Ctrl+C/进程停止仅结束相机服务 | L3 只读；按教程改绑 loopback |
| Voice Bridge WebSocket | 默认 `0.0.0.0:3001/v1/voice`，subprotocol `thirdhand.voice.v1` | 无认证 | audio/text → response/candidate；设计上无 RobotExecutor 且不连接 robot `/ws` | `session.stop`/断开只结束语音会话，不停止机器人 | Experimental 候选层；只能放在受控网络，且同机不能与 Lumos TCP 3001 并占 |
| fixed demo HTTP | `127.0.0.1:8766`；GET `/api/status`；POST `/api/start`、`/api/start-auto`、`/api/stop`、`/api/continue` | 无认证，但默认仅 loopback | 只拥有自己启动的 runner；`/api/start` 为 manual，`/api/continue` 放行下一步；`/api/start-auto` 可启动自动三循环 | `/api/stop` 只停止页面拥有的 runner，不终止无关控制器，也不替代硬件急停 | Experimental、非教程入口；`/api/start-auto` 在 `validated_real_cycles: 0`、`require_step_confirmation: true` 下仍缺实现级硬门禁，L4 禁用 |

`grasp_object` 当前由 `execution=false` 的授权器 fail closed，不能触发抓取；`estop_camera`
只关闭相机 bridge；`camera_refresh` 只请求相机状态。命令名出现于协议不代表拥有执行权限，
更不能把任何软件停止消息等同于独立硬件急停或动力切断。

### 6.10 模型和运行产物政策

模型权重（`*.pt`、`*.pth`、`*.onnx`）、Hugging Face/cache、vendor SDK、API key 都是本机
部署资产，来源、许可证和 SHA-256 写入 manifest，不提交 Git。项目专用 RTMDet checkpoint
没有仓库内权威下载地址；不得用无关权重冒充。详见[模型资产政策](docs/model_assets.md)。

日志、PID、点位备份、标定输出、采集帧、完整数据集、readiness 报告和生成图表也是运行
产物，应进入受控 artifact store 或 gitignored 目录；小型、去标识、确定性 test fixture
可以版本化。任何论文图必须从 machine-readable JSON/CSV 生成，而不是手工改图。

---

<a id="tutorial-07-hands-on"></a>

## 7. L0–L4 动手教程

每一级都独立授权；完成 L2 不意味着可以进入 L3，更不意味着可以运动。命令默认从仓库根
目录运行。开始前记录 `git rev-parse HEAD` 与 `git status --short`，不要在 dirty 工作树上
覆盖标定、配置或他人的运行产物。每打开一个新终端，都应先进入该 checkout 内的任意目录，
再运行 `cd "$(git rev-parse --show-toplevel)"`；下文多终端步骤会显式重复该命令。

### L0：阅读、安装和准备（无硬件权限）

**前置条件：**Ubuntu 20.04/22.04，Python ≥3.10；运行 Web 还需 Node ≥18/npm。完整
依赖见 [pyproject.toml](pyproject.toml) 和[安装指南](docs/setup_guide.md)。

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[core,dev,web]"
python -c "import uiea_thirdhand_vla; print(uiea_thirdhand_vla.__version__)"
node --version
npm --version
```

需要理解模型环境而不安装时：

```bash
bash scripts/vision/bootstrap_remind3d_env.sh --print-plan
```

**预期观察：**包导入成功、版本命令可用、环境计划显示独立 `thirdhand-remind3d`，不会
修改 LumosTouch/system Python。

**禁止：**填写并提交 API key；下载权重后加入 Git；把配置默认值称为标定/验收结果；
在 L0 启动 CAN、真实 SDK 或相机服务。

**停止条件：**Python/Node 版本不满足、依赖来自不可审计源、安装试图覆盖系统/现有机器人
环境。先修复隔离环境，不使用 `--break-system-packages`。

**保留证据：**commit、OS/Python/Node/npm 版本、pip lock/checksum、安装命令与 stderr、
模型来源/许可证/哈希（若已取得）。

### L1：离线验证与确定性回放（无硬件权限）

**前置条件：**完成 L0；没有进程持有真实 `can0` 不作为要求，因为下列命令显式使用假接口
或纯计算，但仍不得删除该假接口覆盖。

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
STARTOUCH_CAN_INTERFACE=thirdhand-test \
  .venv/bin/python -m pytest tests/ -q --ignore=tests/e2e/
PYTHONPATH=web-control/server \
  .venv/bin/python -m pytest \
  web-control/server/tests/vision \
  web-control/server/tests/vision_models -q
```

几何/门禁回放与身份回放：

```bash
PYTHONPATH=web-control/server .venv/bin/python -m vision.replay \
  --manifest web-control/server/tests/vision/fixtures/synthetic_replay.json \
  --output /tmp/thirdhand-vision-replay.json
PYTHONPATH=web-control/server .venv/bin/python -m vision_models.offline_replay \
  --manifest web-control/server/tests/vision_models/fixtures/remind3d_observations.json \
  --output /tmp/thirdhand-identity-replay.json
```

**预期观察：**测试通过；同一输入重复生成字节稳定/语义一致的 metrics；输出含 calibration
ID、frames、identity/registration/Dry Run 指标与拒绝原因。fixture 数字只验证计算管线。

**禁止：**把 `/tmp` fixture 数字报告为真实相机精度；把假 `calibration_id` 写入部署；
移除时间单调、相对路径或 execution-field 拒绝检查。

**停止条件：**任何测试失败、输出含 NaN/绝对逃逸路径、两次回放不一致、出现 CAN/Startouch/
WebSocket 动作依赖。先定位离线原因，不连接硬件“试试看”。

**保留证据：**完整命令、exit code、pytest/JUnit 输出、两个 JSON 及 SHA-256、dependency
lock、seed 与 commit。

### L2：模拟、dry-run Web UI 与语音 mock（无真实 CAN 运动）

**前置条件：**完成 L1；端口 3000/3001 未被无关进程占用；模拟 Web 不需要 vendor SDK。

```bash
STARTOUCH_SIMULATE=1 web-control/scripts/setup_ubuntu.sh
CAMERA_ENABLED=0 STARTOUCH_SIMULATE=1 \
  web-control/scripts/start_ubuntu.sh
```

打开 `http://127.0.0.1:3000`，检查六关节模型、connect/servo/preset、gripper 和软件停止仅
改变模拟状态。若要验证“可导入 SDK 但不控制硬件”的 dry-run，必须先有匹配 ABI 的 SDK：

```bash
CAMERA_ENABLED=0 STARTOUCH_DRY_RUN=1 \
STARTOUCH_SDK_PATH="$HOME/arm/startouch_sdk" \
  web-control/scripts/start_ubuntu.sh
```

固定点软件验证使用仓库 fixture，严禁带 `--real`：

```bash
.venv/bin/python web-control/scripts/fixed_pick_place.py \
  --simulate --config tests/fixtures/fixed_pick_place_test.yaml
STARTOUCH_SDK_PATH="$HOME/arm/startouch_sdk" \
  "$HOME/miniconda3/envs/LumosTouch/bin/python" \
  web-control/scripts/fixed_pick_place.py \
  --dry-run --config tests/fixtures/fixed_pick_place_test.yaml
```

Voice Protocol 自动 smoke（会退出）与交互 mock（保持运行）：

```bash
cd "$(git rev-parse --show-toplevel)"
npm --prefix web-control/server run test:voice-protocol
VOICE_HOST=127.0.0.1 VOICE_PORT=3001 node web-control/server/test/voice-mock.js
```

**预期观察：**模拟 Web 只报告模拟/干运行状态；协议 smoke 按顺序收到 audio/text 事件；
mock 显示 candidate，在浏览器确认后也只更新预览/日志。

**禁止：**同时设置正常硬件模式；把 voice candidate 转发到 `/ws`；用真实点位替换 test
fixture；对外网暴露无认证 mock。

**停止条件：**任何进程尝试打开 `can0`、候选直接触发 robot command、端口落到错误主机、
软件停止不能结束模拟进程。用 Ctrl+C 结束自己启动的进程并保留日志。

**保留证据：**Node/Python 版本、protocol 输出、browser/mock 截图（标为模拟）、candidate/
confirmation/refusal 日志、端口与 PID。

### L3：双相机在线只读服务（相机权限，无运动权限）

**前置条件：**现场允许读取 Lumos 和 D435；精确模型环境已按
[模型资产政策](docs/model_assets.md) 准备；USB 设备可见；端口 3001/3100 空闲；明确接受
启动器会把 3100 绑定到 `0.0.0.0`。机器人执行配置必须仍为 false。

先在独立终端启动 camera-only Lumos 服务（无 CAN/Startouch 依赖）：

```bash
cd "$(git rev-parse --show-toplevel)"
LUMOS_HTTP_HOST=127.0.0.1 LUMOS_HTTP_PORT=3001 \
  "$HOME/miniconda3/envs/thirdhand-remind3d/bin/python" \
  web-control/server/lumos_http_server.py
```

在第二个终端进行只读预检、启动和短时 verifier：

```bash
cd "$(git rev-parse --show-toplevel)"
curl --fail http://127.0.0.1:3001/health
bash scripts/vision/start_dual_camera_online.sh --background
bash scripts/vision/start_dual_camera_online.sh --status
"$HOME/miniconda3/envs/thirdhand-remind3d/bin/python" \
  scripts/vision/verify_dual_camera_online.py \
  --base-url http://127.0.0.1:3100 \
  --duration-seconds 60 \
  --output /tmp/thirdhand-dual-camera-readiness.json
```

打开 `http://127.0.0.1:3100/camera-test.html`；结束时只停止启动器验证拥有的 3100 进程，
再在 Lumos 终端 Ctrl+C：

```bash
bash scripts/vision/start_dual_camera_online.sh --stop
```

**预期观察：**角色严格为 Lumos canonical RGB、D435 metric depth/debug RGB；两路 sequence
前进，model ready、status non-stale，`robotExecutionEnabled` 始终 false。缺有效标定/机器人
姿态/任务 checkpoint 时目标保持 non-actionable，这是正确结果。

**禁止：**同时启动第二个 D435 owner；连接真实 Startouch；编辑 execution flag；把 blocker
从输出过滤；将 3100 暴露到不受控网络；将只读页面称为抓取验证。

**停止条件：**角色错误、序号停滞/倒退、stale、模型失败、GPU reserved >`7.2 GiB`、P95
latency >`300 ms`、任何 execution true/CAN/robot/gripper I/O。立即停止本任务拥有的服务，
不杀无关 PID。

**保留证据：**readiness JSON 与 SHA-256、状态采样、配置/模型/标定 hash、USB/driver/GPU
版本、开始/结束时间、blocker histogram、日志和明确“零机器人执行”声明。历史部署数字若缺
区间/统计方法，应标 Evidence Incomplete，而不是论文结果。

### L4：受监督真实硬件（显式人工门禁）

**前置条件（全部满足才可继续）：**L0–L3 证据已审阅；Ubuntu/SDK ABI 匹配；`can0` 为
UP/1 Mbps；只有一个控制 owner；点位由本机实教并逐点复核；15% demo speed 和 30% 硬上限
未被提高；25 cm 抬升路径实测清空；硬件急停/动力切断在手边；第二人或等效现场监督；
`configs/tasks/fixed_pick_place.yaml` 的未验收计数不会被手工伪造。

先只读检查接口和竞争进程：

```bash
cd "$(git rev-parse --show-toplevel)"
ip -details -statistics link show can0
ps -ef | rg 'startouch_bridge.py|proxy.js|fixed_pick_place.py|teach_fixed_point.py|ros2|move_group'
```

本教程唯一允许的 L4 启动入口是默认 manual 的包装脚本；它先检查预期 branch、CAN
UP/1 Mbps、唯一控制 owner、资源锁、点位/分段/25 cm lift/限位与配置，再启动底层 runner：

```bash
bash scripts/demo_fixed_pick_place.sh
```

保持默认 `DEMO_RUN_MODE=manual`。当前配置为 `validated_real_cycles: 0` 且
`require_step_confirmation: true`，包装脚本会要求每一步在终端显式确认；不要通过环境变量
切换模式或移除确认。

`web-control/scripts/fixed_pick_place.py` 的真实模式是包装脚本内部接口，禁止操作员直接调用：
直接调用会绕过仅由包装层实施的 branch、CAN、控制资源、点位、路径分段和 lift preflight。
`scripts/open_fixed_pick_place_control.sh` 与 `127.0.0.1:8766` 页面也仅为 Experimental，**不是
本教程 L4 入口**。页面可见的“一键自动循环 3 次”只确认一次便调用 `/api/start-auto`，随后
不再逐步确认；当前实现没有在上述未验收计数和逐步确认配置下硬拒绝该路由。在代码完成
实现级 fail-closed 门禁并重新审计以前，禁止打开或使用该 UI 和 `/api/start-auto`。

这不是无人监督运动配方：不要使用任何自动三循环入口，不要后台运行，不要移除确认，也
不要在无人现场时复用包装命令。

**预期观察：**终端依次报告包装层 preflight 通过、状态稳定，并在每一步等待 stdin 确认；
关节/CAN feedback 持续、每个逻辑 route 完成后才进入下一步，日志写入
`logs/fixed_pick_place/`。

**禁止：**打开 fixed demo UI、调用 `/api/start-auto` 或任何自动 route；直接调用真实 Python
runner；Web controller 与 fixed runner 并行；使用 test fixture 的点位执行真实运动；跳过
点位/限位/分支/锁检查；提高速度；无人监督或远程盲操；把软件 Stop 当硬件急停。

**停止条件：**任何 `RESOURCE_CONFLICT`、CAN stale、初态/反馈不匹配、意外方向/声音/振动、
物体滑落、线缆靠近、人员进入工作区、确认通道断开或日志异常。按下现场硬件急停/动力
切断；软件仍响应时再 Stop/Ctrl+C，原因未查清前不复位。

**保留证据：**operator/observer、commit/config hash、point backup、CAN/SDK/机器人版本、
逐阶段时间线、速度、软件/硬件停止事件、完整日志、失败照片/描述和 `validated_real_cycles`
更新依据。失败记录不得删除。

---

<a id="tutorial-08-research-verification"></a>

## 8. SCI 验证、排障与论文路径

### 8.1 三条研究路线

| Track | 地位 | 可证伪问题 | 机器人角色 | 当前证据状态 |
| --- | --- | --- | --- | --- |
| A：视觉与三维感知 | 主轴 | 时间/标定/注册/实例记忆/不确定度是否改善 held-out 感知与安全拒绝 | 只读姿态或受监督验证平台 | 部分工程结果；SCI 比较多为 Planned Evidence/Evidence Incomplete |
| B：可验证 VLA | 次轴 | candidate+preview+confirmation+validator 是否比弱约束基线拦截更多不安全请求 | 离线基线无 actuator；硬件只作受监督平台 | Planned Evidence |
| C：视觉–VLA 综合 | optional | 感知不确定度传播是否改善长时任务拒绝、纠正与恢复 | 受监督系统展示，不是低层控制创新 | Planned Evidence |

### 8.2 从 claim 到可审计结果

```text
falsifiable hypothesis
  → preregistered protocol/threshold/statistical plan
  → versioned dataset datasheet + split SHA-256
  → experiment manifest (commit/command/env/models/calibration/seeds)
  → raw machine-readable result records
  → baseline/ablation aggregation + uncertainty/statistics
  → generated figure/table + exact command
  → claim matrix + failure/threat review
  → methods/results/limitations in paper
```

[实验 manifest v1](docs/research/schemas/experiment-manifest.schema.json) 要求 schema version、
experiment/hypothesis/track、40 位 commit、命令数组、环境、dataset、models、calibration、
seeds、UTC 时间和 artifacts。[结果 record v1](docs/research/schemas/result-record.schema.json)
要求 metric/value/unit/aggregation/sample_count/confidence_interval/slice/source_artifact。
v1 有意保持宽松：`hardware`、`models`、`artifacts` 等内部对象未强制领域字段；不要在本教程
擅自收紧 schema，缺失的领域细节由实验协议与复现清单补齐。

### 8.3 数据集与协议冻结

每个 corpus 单独填写[数据集说明](docs/research/dataset_datasheet.md)：硬件/固件、逻辑角色、
时钟与 skew、标定 ID/残差、场景/物体/材质、标注政策与复核、split/count/hash、泄漏防止、
隐私/同意、许可、保留与已知偏差。synthetic、replay、live 和硬件 motion 必须分开，不能
悄悄合并。

训练/验证/测试应按 session、scene、物理 object identity 和 temporal clip 隔离，防止邻近帧
或同一实例泄漏。透明/黑色/反光、中心/边缘、遮挡/重入、stale/missing、标定故障必须保留
为测试 slice 和 failure taxonomy。

### 8.4 基线、消融和指标

| 研究单元 | 基线/消融 | 主指标 |
| --- | --- | --- |
| mask | YOLOv8n detect、YOLO-seg、RTMDet-ins、Mask R-CNN | box/mask AP/recall、radial、point purity、latency/resource |
| registration | none、无 timestamp gate、完整 z-buffer | pixel/mm error、coverage、flying edge、3D error/jitter |
| identity | IoU、appearance、appearance+3D、work/stable、ambiguity on/off | HOTA、IDF1、switch、fragment、reacquisition、false merge |
| pose/gate | bbox/mean/median、erosion/MAD/covariance/gate 消融 | 3D error、jitter、coverage、错误放行/拒绝 |
| VLA | free-form offline、candidate、+preview、+confirm+validator | accuracy、unsupported、interception、correction、refusal、recovery、latency |
| integrated | 无 uncertainty propagation vs 完整链 | completion、grounding、interception、recovery、end-to-end cost |

比较时固定 split/calibration/model hash/hardware/input/seed/window；消融一次只改一个因素。
分类/事件比例报告样本量与适当区间（例如预注册的 bootstrap 或二项区间）；连续/长尾时延
报告 P50/P95 与区间；按对象/scene 独立性选择统计单元，必要时配对/分层并记录多重比较、
缺失值和 outlier 政策。不要只报均值或最佳 seed。

### 8.5 证据状态和预注册准备度

| 情形 | 正确标签 | 能否进摘要结论 |
| --- | --- | --- |
| 尚无任何 measurement，只有计划/门限位置 | Planned Evidence / 待补实验证据 | 否 |
| 已有 smoke/样例/部分结果，但样本量、CI、统计方法或来源不充分 | Evidence Incomplete / 待补充证据 | 否 |
| 没有结果且 protocol/threshold/stat plan 未冻结 | Planned Evidence；另记 preregistration incomplete | 否 |
| manifest/source/sample count/CI或合理 null/stat method/figure command 都完整 | 按研究审核记录为可报告证据 | 通过复核后才可 |

工程 Verified 与“可报告科研证据”也不可互换。失败假设、negative result 和 protocol deviation
留在[主张矩阵](docs/research/claim_evidence_matrix.md)，不得删除。

### 8.6 图表预览注册表

下表全部是 **Planned Evidence / 待补实验证据**，只描述未来生成物，不是空白结果图，也
不能填入虚构数字。来源与生成命令要求以[图表清单](docs/research/figure_manifest.md)为准。

| ID | 计划内容 | 最低来源 | 释放门禁 |
| --- | --- | --- | --- |
| V1 | Lumos mask + D435 depth + base-frame 3D | 同步帧、calibration、mask、registered points、manifest | 命令无手工改图复现 panel |
| V2 | 遮挡前/中/重捕获身份 | held-out clip、IDs/cost/memory/annotations | 选择规则和 identity truth 固定 |
| V3 | 注册误差、径向残差、不确定度 | correspondence、radial bins、covariance | 单位/聚合/排除/标定 ID 完整 |
| L1 | instruction→context→candidate→preview→confirmation/refusal | 去标识 scenario 与 validator log | 不出现 secret 或执行成功暗示 |
| E1 | baseline + confidence intervals | 全部 result records、n、CI、slice | 与预注册基线/区间方法一致 |
| E2 | ablation table/curve | one-delta variants、seeds、source JSON/CSV | 控制条件完整 |
| E3 | accuracy–latency–resource trade-off | accuracy/P50/P95/FPS/CPU/GPU/VRAM | 硬件和测量窗口可比 |
| F1 | success/failure paired cases | 预先声明选择规则与 failure taxonomy | 不 cherry-pick，限制同时可见 |

### 8.7 失败案例与 validity threats

至少报告：鱼眼边缘域偏移、深度空洞/flying edge、标定漂移、时间错配、相似实例误合并、
长期光照变化、detector 变化、任务 checkpoint 域外、prompt/model 漂移、人类 evaluator bias、
网络/API failure、GPU 热/资源变化和 simulation-to-real gap。内部 validity 关注 split leakage、
非独立帧、调参看 test、缺失值和选择性报告；外部 validity 关注单硬件/单场地/单物类；
construct validity 关注 proxy metric 是否真的表示安全/完成；统计 validity 关注小样本、区间、
多重比较与分母定义。

### 8.8 故障排查：症状 → 诊断 → 安全决策 → 恢复 → 证据

| 症状 | 安全诊断 | 决策 | 恢复 | 必须保留的证据 |
| --- | --- | --- | --- | --- |
| `can0 already controlled`/lock owner | 只读检查 PID、cmdline、cwd、lock；不要 kill by pattern | 停止本次连接/运动 | 让真实 owner 正常 cleanup；确认锁释放后再审计 | PID/cmdline/lock、时间、owner 日志 |
| CAN feedback stale/初态不匹配 | `ip -details -statistics`、bridge event、物理电源/线缆 | 软件停止；风险时硬件急停 | 修复 CAN/SDK 后从低风险状态重做 preflight | RX counters、错误、cleanup/急停记录 |
| Lumos 或 D435 role lost | `/health`、USB ID、status roles/sequences；不依赖 `/dev/videoN` 猜测 | L3 停止/降级为不可操作 | 恢复唯一 camera owner，重新验证角色和序号 | USB/firmware、role map、前后 samples |
| frame stale/skew exceeded | 查 monotonic age、队列、pair reasons、系统负载 | 保持 non-actionable，不重复旧帧 | 清理阻塞消费者、重启自己拥有的只读服务、重跑 verifier | skew/age 分布、sequence、restart 原因 |
| calibration invalid/mismatch | 核对方向、hash、validated residual、安装变化 | 停止三维/运动；可保留 RGB 身份观察 | 按标定计划重采集并在留出集验证，生成新 ID | 原/新 artifact hash、residual、operator |
| invalid/insufficient depth | 查范围、零/NaN、mask erosion、有效点数、材质 | 拒绝目标；不得用桌面平面补深度 | 调整观测条件/标定后重新采集，不降低门限掩盖故障 | depth/mask slice、point count、reason |
| identity ambiguous/false merge 风险 | 查全局/替代 assignment cost、appearance/3D gate、memory quality | 拒绝/请求澄清，不猜 ID | 获取新视角仅限明确授权的只读/active-view dry-run，连续确认 | assignment、bank state、clip、annotation |
| 端口占用或连错主机 | `ss -ltnp`，区分 host/TCP；3001 Voice/Lumos 不能同机并占 | 不杀未知服务、不换成公网随机端口 | 停止自己拥有的进程或在明确配置中换端口并同步 UI | listener PID、host/transport、配置 diff |
| Robot `/ws` 失败 | 先区分 Startouch `/ws` 与 Voice `/v1/voice`；看 subprotocol/事件 | 不重发运动、不降级绕过确认 | 恢复连接后先 `status`，人工重新评估已过期候选 | close code、last command ID、robot state |
| Voice WebSocket/LLM 失败 | 检查 `thirdhand.voice.v1`、路径、ping/pong、错误码 | 候选无效；不转文字为直接控制 | 离线 mock 复现，恢复后创建新 session，不补发旧音频 | session/message IDs、event order、error code |
| missing/incompatible weights | 核对本地 path、label metadata、SHA-256、license/cache | model unavailable，execution locked | 从审阅来源取得正确权重或重训；重跑 smoke | source/license/hash/config/model smoke |
| GPU OOM/容量不足 | 看 reserved/allocated、device、并发模型与输入尺度 | 停止在线模型；不转 CPU 后宣称同协议性能 | 减少经过预注册的负载/调度或换硬件，重新比较 | GPU/driver、memory trace、配置、latency |
| P95 latency 超限 | 分解 capture/pair/model/register/UI，检查 latest-only/热状态 | 保持 non-actionable，终止 readiness | 定位瓶颈，冻结修改后重跑足够窗口 | 原始 per-frame times、P50/P95/n/CI |

### 8.9 复现与论文写作路径

1. 在[主张矩阵](docs/research/claim_evidence_matrix.md)选择一条可证伪 claim，先补齐预注册
   protocol、精确 threshold 和 statistical plan。
2. 完成[数据集说明](docs/research/dataset_datasheet.md)，冻结 manifest/split/checksum，完成
   隐私、同意、许可和 leakage review。
3. 从[基线/消融矩阵](docs/research/baseline_ablation_matrix.md)选择 exact variants；为每次 run
   生成 v1 experiment manifest 和 result records，失败 run 同样保留。
4. 从机器可读 source 生成 V1–F1 中需要的图/表，登记 command/commit/input/output hash。
5. 逐项通过[复现清单](docs/research/reproducibility_checklist.md)，让独立 reviewer 从命令复建
   聚合并解释数值漂移。
6. 写作顺序建议：Methods（模型/算法/假设）→ Protocol/Dataset → Results（含区间与失败）→
   Ablations → Threats/Limitations → Safety/Ethics → Abstract。摘要只使用已完成证据链的结论。

### 8.10 术语与文档索引

| 术语 | 本教程含义 |
| --- | --- |
| canonical RGB | 唯一决定分割、外观和身份的 Lumos RGB |
| metric depth | D435 以米为单位的 pinhole Z-depth |
| registration | 把 D435 点云变换/投影/z-buffer 到 Lumos 原生像素 |
| persistent identity | 结合外观、短期三维、work/stable 原型和显式歧义拒绝的实例 ID |
| actionability | 感知目标满足当前 freshness/calibration/identity/pose 条件；不等于执行授权 |
| fail closed | 输入不完整/过期/歧义时输出拒绝原因，不猜测、不默认放行 |
| Dry Run | 只产生候选/报告，不包含或调用执行传输 |
| hardware emergency stop | 独立于软件链路的硬件急停/动力切断 |

进一步阅读：[模块合同](docs/module_guide.md)、[Web API 合同](docs/web_api.md)、
[固定点安全审计](docs/fixed_pick_place_audit.md)、
[视觉验收计划](docs/vision_research/13_BENCHMARK_AND_ACCEPTANCE_PLAN.md)、
[视觉实施门禁](docs/vision_research/IMPLEMENTATION_GATE.md)、
[离线实现记录](docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md)和
[部署记录](docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md)。

## 许可

仓库代码采用 MIT License，详见 [LICENSE](LICENSE)。模型、vendor SDK、数据集和第三方资产
可能使用不同许可证；发布前逐项完成 license/NOTICE 与数据治理审查。
