# bottlegrasp 功能模块化重组设计

日期：2026-08-21

## 1. 目标

将当前 `bottlegrasp` 按功能职责重组为一个仓库内的两个业务板块：

- `vision`（V）：相机采集、目标感知、选择、三维几何、跟踪、可视化和视觉结果发布。
- `action`（A）：手眼标定、机器人坐标观测、视觉对准、抓取工作流、安全门和操作端。

重组后的每个模块必须职责单一、输入输出明确、可独立导入、可独立调试、可独立测试，并能在其他项目中按模块迁移复用。目录移动不能改变当前视觉决策、安全阻断和物理执行开关的语义。

## 2. 非目标

- 不把 V、A 拆成独立服务。
- 不要求每个函数单独占用一个文件。
- 不重写 Grounding DINO、SAM2、XVisio 或机械臂控制算法。
- 不在重组过程中放宽安全阈值或启用默认物理执行。
- 不把测试、调试脚本、配置或产物作为第三个业务板块。
- 不保留仅为旧路径存在的永久兼容副本；迁移期兼容入口必须薄且有明确删除范围。

## 3. 设计原则

1. 一个模块只承担一个主要功能，相关且共同变化的实现放在同一模块。
2. 库模块导入时不得打开相机、加载模型、连接 WebSocket 或发送机器人命令。
3. 命令行解析、进程生命周期和输出格式放在 `scripts/` 或 `apps/`，不放在算法模块。
4. V 不依赖 A，也不执行机器人动作。
5. A 不读取 V 的模型、掩码跟踪器或内部状态，只通过公共契约消费 V 结果。
6. Python/Node 跨语言数据通过版本化 JSON Schema 和对应语言的数据校验器连接。
7. 硬件、模型、文件系统、网络和机器人连接通过 adapter 注入核心模块。
8. 所有本机绝对路径改为配置项、环境变量或调用参数。
9. 单元测试镜像源码功能目录；硬件测试与离线测试分开。
10. 失败默认关闭授权，保留现有 `robot_control_enabled=false` 和硬件验证状态语义。

## 4. 目标目录

```text
bottlegrasp/
├── README.md
├── pyproject.toml
├── configs/
│   ├── vision.yaml
│   └── action.yaml
├── src/thirdhand_va/
│   ├── __init__.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── errors.py
│   │   └── contracts/
│   │       ├── __init__.py
│   │       ├── rgbd_frame.py
│   │       ├── vision_result.py
│   │       ├── arm_state.py
│   │       └── vision-result.schema.json
│   ├── vision/
│   │   ├── __init__.py
│   │   ├── camera/
│   │   │   ├── __init__.py
│   │   │   ├── protocol.py
│   │   │   ├── stream.py
│   │   │   └── recording.py
│   │   ├── perception/
│   │   │   ├── __init__.py
│   │   │   ├── interfaces.py
│   │   │   ├── grounded_sam.py
│   │   │   ├── bottle_filter.py
│   │   │   ├── fixed_bottle.py
│   │   │   └── references.py
│   │   ├── selection/
│   │   │   ├── __init__.py
│   │   │   ├── ordinal_selector.py
│   │   │   └── target_lock.py
│   │   ├── geometry/
│   │   │   ├── __init__.py
│   │   │   ├── pointcloud.py
│   │   │   └── grasp_pose.py
│   │   ├── tracking/
│   │   │   ├── __init__.py
│   │   │   └── stability.py
│   │   ├── visualization/
│   │   │   ├── __init__.py
│   │   │   ├── overlay.py
│   │   │   └── depth_heatmap.py
│   │   ├── adapters/
│   │   │   ├── __init__.py
│   │   │   ├── mjpeg_publisher.py
│   │   │   └── event_publisher.py
│   │   └── pipeline.py
│   └── action/
│       ├── __init__.py
│       ├── calibration/
│       │   ├── __init__.py
│       │   └── handeye.py
│       ├── observation/
│       │   ├── depth-filter.js
│       │   ├── target-memory.js
│       │   └── base-target-lock.js
│       ├── alignment/
│       │   └── visual-align-controller.js
│       ├── grasp/
│       │   ├── grasp-controller.js
│       │   └── workflow-client.js
│       ├── safety/
│       │   ├── execution-gate.js
│       │   ├── workspace-check.js
│       │   └── software-stop.js
│       ├── adapters/
│       │   ├── vision-client.js
│       │   └── robot-client.js
│       └── operator/
│           ├── status-store.js
│           └── controller.js
├── native/vision/xvisio_rgbd_stream/
├── apps/bottle_pick/
│   ├── camera_bridge.py
│   ├── web_server.js
│   └── run.js
├── scripts/
│   ├── vision/
│   └── action/
├── tests/
│   ├── common/
│   ├── vision/
│   ├── action/
│   ├── integration/
│   └── hardware/
├── artifacts/
│   ├── vision/
│   ├── action/
│   └── integration/
└── docs/
    ├── architecture.md
    ├── vision/
    ├── action/
    └── integration/
```

目录树表达职责边界，不要求创建没有实际内容的占位模块。例如 `execution-gate.js`、`workspace-check.js` 和 `robot-client.js` 只有在从现有 `proxy.js` 提取出对应职责时才创建。

## 5. 公共契约和依赖方向

核心数据流为：

```text
RgbdFrame -> VisionPipeline -> VisionResult -> ActionController -> ActionDecision -> RobotClient
```

依赖方向必须保持：

```text
common <- vision
common <- action
vision -X-> action
action -X-> vision internals
apps -> common + vision + action
```

公共契约包含：

- `RgbdFrame`：RGB、配准深度、相机坐标 XYZ、帧序号、单调时间和相机序列号。
- `VisionResult`：版本号、帧来源、目标身份、选择请求、状态、阻断原因、抓取预览、稳定性证据和安全授权标志。
- `ArmState`：TCP/关节状态、静止状态、采样时间和来源。
- `ActionDecision`：动作阶段、允许状态、阻断原因、目标预览 ID 和将要调用的 adapter 操作。

V 的公开入口保持等价于：

```python
VisionPipeline.process(frame: RgbdFrame) -> VisionDecision
```

A 的公开入口保持等价于：

```javascript
ActionController.update(visionResult, armState) -> ActionDecision
```

跨语言 JSON 不携带 Python/NumPy 私有对象。掩码、模型会话和 SAM2 内存留在 V 内部；A 只接收动作所需的目标身份、坐标、方向、证据和阻断状态。

## 6. 现有文件迁移映射

### 6.1 公共支撑

- `src/thirdhand_va/config.py` -> `src/thirdhand_va/common/config.py`
- `src/thirdhand_va/contracts.py` -> 按职责拆为 `common/contracts/rgbd_frame.py`、`vision_result.py` 和相应公开导出。

### 6.2 Vision

- `src/thirdhand_va/camera/*` -> `src/thirdhand_va/vision/camera/*`
- `src/thirdhand_va/perception/interfaces.py` -> `vision/perception/interfaces.py`
- `src/thirdhand_va/perception/grounded_sam.py` -> `vision/perception/grounded_sam.py`
- `src/thirdhand_va/perception/bottle_candidates.py` -> `vision/perception/bottle_filter.py`
- `src/thirdhand_va/perception/fixed_bottle.py` -> `vision/perception/fixed_bottle.py`
- `src/thirdhand_va/perception/references.py` -> `vision/perception/references.py`
- `src/thirdhand_va/selection.py` -> `vision/selection/ordinal_selector.py` 与 `target_lock.py`
- `src/thirdhand_va/geometry/*` -> `vision/geometry/*`
- `src/thirdhand_va/tracking/stability.py` -> `vision/tracking/stability.py`
- `src/thirdhand_va/visualization.py` -> `vision/visualization/overlay.py` 与 `depth_heatmap.py`
- `src/thirdhand_va/pipeline.py` -> `vision/pipeline.py`
- `src/thirdhand_va/grounded_sam.py` 不迁移；以当前实际引用的 `perception/grounded_sam.py` 为唯一来源。
- `native/xvisio_rgbd_stream/*` -> `native/vision/xvisio_rgbd_stream/*`

### 6.3 Action

- `src/thirdhand_va/handeye.py` -> `src/thirdhand_va/action/calibration/handeye.py`
- `integration/web-control/depth-observation-filter.js` -> `action/observation/depth-filter.js`
- `integration/web-control/locked-target-memory.js` -> `action/observation/target-memory.js`
- `integration/web-control/base-target-lock.js` -> `action/observation/base-target-lock.js`
- `integration/web-control/visual-align-controller.js` -> `action/alignment/visual-align-controller.js`
- `operator/status-store.js` -> `action/operator/status-store.js`
- `operator/workflow-client.js` -> `action/grasp/workflow-client.js`
- `operator/stop.js` -> `action/safety/software-stop.js`

### 6.4 应用和 adapter

- `scripts/camera_bridge_va.py` 不整体移动；拆为 V 的 MJPEG/事件发布 adapter、A 所需的契约输出，以及 `apps/bottle_pick/camera_bridge.py` 进程入口。
- `integration/web-control/camera-bridge.js` 拆为视觉输入 adapter 和应用层进程管理。
- `integration/web-control/vision-selection-api.js` -> A 的视觉输入 adapter 或应用层 HTTP handler，核心选择语义仍由 V 负责。
- `integration/web-control/proxy.js` 不整体移动；按机器人 adapter、动作安全门、Web 服务和应用组装职责拆分。
- `operator/run.js`、`operator/config.js`、`operator/operator-control.sh` -> 应用入口或 `scripts/action/`，不得继续包含动作算法。
- `src/thirdhand_va/bridge.py` 拆为 `vision/adapters/` 中的纯编码发布逻辑和 `apps/bottle_pick/` 中的流编排。
- `src/thirdhand_va/cli.py` 拆为薄命令入口，实际功能调用新的公开模块。

### 6.5 调试、测试和产物

- 现有 `scripts/run_*`、`validate_*`、`capture_*`、`evaluate_*` 按功能移动到 `scripts/vision/` 或 `scripts/action/`；脚本只负责解析参数和调用模块。
- Python 测试镜像 `tests/vision/`、`tests/action/` 和 `tests/common/`。
- Node smoke tests归入 `tests/action/`，跨板块测试归入 `tests/integration/`。
- 连接真实相机、端口或机器人才能运行的测试归入 `tests/hardware/`。
- `artifacts/reference`、相机报告和视觉截图归入 `artifacts/vision/`；操作端状态归入 `artifacts/action/`；端到端日志归入 `artifacts/integration/`。
- `*.py..bak` 不进入新结构；删除前确认正式文件包含其仍需保留的变化。

## 7. 调试和复用方式

库模块通过 import/require 复用：

```python
from thirdhand_va.vision.geometry import estimate_grasp_pose
from thirdhand_va.vision.selection import SpatialBottleSelector
from thirdhand_va.vision.camera import read_frame_bundle
```

人工调试使用薄脚本：

```text
scripts/vision/camera_smoke.py
scripts/vision/debug_perception.py
scripts/vision/debug_selection.py
scripts/vision/debug_geometry.py
scripts/vision/debug_pipeline.py
scripts/action/debug_calibration.py
scripts/action/debug_alignment.js
scripts/action/debug_grasp.js
```

模块异常由调用者处理；库代码不 `sys.exit()`。调试脚本负责日志、退出码和产物路径。可复用模块不得读取仓库外硬编码路径。

## 8. 测试策略

1. 在移动任何实现前，为公开接口建立导入测试。
2. 每次只迁移一个功能模块，并立即更新其测试导入路径。
3. 使用兼容导出保持上层调用可运行，待所有消费者迁移后删除兼容导出。
4. Python 单元测试覆盖 `common`、V 和 Python A 模块。
5. Node 测试覆盖 A 的观察、对准、抓取和安全模块。
6. 离线集成测试使用录制 RGB-D bundle 和模拟 ArmState，不连接硬件。
7. 硬件测试单独标记，默认测试命令不得打开相机或执行机器人动作。
8. 重组完成后运行全部 Python、Node、离线集成和静态导入检查。

## 9. 兼容与安全策略

- 迁移期间允许旧 import 路径通过薄 re-export 转发到新模块，转发层不得复制实现。
- 旧脚本路径若被外部服务使用，保留薄 wrapper，内部调用新入口，并在 README 标记迁移路径。
- 当前 `robot_control_enabled=false`、执行环境开关、工作空间检查和硬件验证阻断保持不变。
- V 输出状态不是 `ready`、证据过期、校准不匹配或 A 安全门关闭时，不允许生成物理执行命令。
- 重组不以“测试通过”为理由启动相机或机器人；硬件行为必须由用户明确授权。

## 10. 实施顺序

1. 建立目标目录、公共契约和导入兼容层。
2. 迁移纯函数模块：配置、契约、点云、抓取几何和评估。
3. 迁移 V 的相机、感知、选择、跟踪、可视化和流水线。
4. 迁移手眼标定和 A 的小型 Node 模块。
5. 拆分 CameraBridge、Web proxy 和 operator 工作流。
6. 重组 scripts、tests、native、artifacts 和 docs。
7. 删除重复源码和已确认无用的备份文件。
8. 更新 README、运行命令、配置路径和外部集成说明。
9. 执行完整验证并输出旧路径到新路径的最终清单。

## 11. 验收标准

- 源码按 `common`、`vision`、`action` 分类，无功能不明的重复实现。
- `camera_bridge`、`proxy` 和 operator 入口只负责编排，不包含可独立复用的算法。
- V、A 的核心模块可被独立导入，导入时无硬件或网络副作用。
- 每个功能模块有对应单元测试或明确的硬件测试归属。
- 离线测试可以单独验证相机协议、录制回放、感知过滤、选择、几何、稳定性、手眼转换和动作控制。
- V 与 A 只通过版本化公共契约交换数据。
- 不存在本机绝对模型、Node 依赖或外部仓库路径作为默认硬编码。
- 默认运行不打开相机、不连接机器人、不启用物理执行。
- 原有离线行为、视觉状态和安全阻断语义保持一致。
- README 能说明每个模块的职责、输入、输出、单独调试命令和复用方式。

