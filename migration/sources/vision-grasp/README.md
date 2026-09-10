# PinZiZhuaQuSkill

面向“桌面上彼此分开、轮廓清楚、直立摆放的普通不透明瓶子”的 V+A Skill。
组员的 L 模块只需要传入画面上显示的稳定编号 `1..5`；本项目负责重新确认同一瓶子、
计算 RGB-D 抓取位姿，并编排完整的预抓取、夹取、固定点直立放置和 Home 动作。

当前状态：通用瓶检测、稳定编号、RGB-D 几何、法兰语义的眼在手上变换、Startouch
子进程协议、固定 XY/动态 Z 放置计划、安全门、九阶段动作和 L API 已有离线测试。
真实 Lumos 相机预览和 Startouch 低层连接/小角度空载动作已经分别验证；手眼安装关系、
安全 Home、抓取偏移和整条放置路径仍保持显式闭锁。Startouch 二进制虽已按精确
字节纳入项目内受控运行时，但当前清单如实标记其缺少可复现构建证据，
因此真机入口会在导入 SDK 和打开 CAN 前闭锁，不能宣称真机自主抓取已经完成。

## 目录与边界

```text
PinZiZhuaQuSkill/
├── configs/                    # V/A 严格配置；真机执行默认 false
├── src/thirdhand_va/
│   ├── common/                 # 不可变契约、配置、公共错误
│   ├── vision/                 # 检测、稳定 ID、RGB-D 几何、可视化
│   └── action/                 # 标定、锁定、对准、抓放、安全、adapter
├── native/vision/              # Lumos/XVisio RGB-D 原生采集边界
├── native/startouch/           # 独占 CAN 的 Startouch JSON-lines bridge
├── apps/bottle_pick/           # V+A 进程组装和回环 L API
├── scripts/vision/             # V 的独立调试入口
├── scripts/action/             # A/VA 的独立调试入口
├── tests/                      # common/vision/action/integration/hardware
├── artifacts/                  # 本机运行证据，不作为代码依赖
└── docs/                       # 架构、接口、模块和验收说明
```

正式链路只有一套：

```text
L: target_id 1..5
        |  （仅在启动回到已验证 Home 后接受）
POST /api/va/start
        |
Lumos RGB-D -> Grounding DINO + SAM2 -> Norfair -> stable_id
        |                                           |
        +-> RGB-D grasp pose -> eye-in-hand -> same-ID reobserve
                                                    |
                           safety gate -> nine-stage pick/place -> Home
```

V 不导入 A、不发送动作；A 不读取模型、掩膜或 tracker 内部对象，只消费
`thirdhand-va-detection-v3`。所有硬件生命周期只允许出现在 adapter 或 app 中。

## 安装与只读预检

```bash
cd /home/nieqingcao/th0814/VA/PinZiZhuaQuSkill
/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/runtime/preflight.py --json
npm ci --ignore-scripts

# 只准备并校验项目内 Startouch 运行时；不访问硬件
/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/prepare_startouch_runtime.py \
  --source-sdk build/startouch-repro-cpython310-a-20260824/source
```

上面的 source 是 2026-08-24 两次独立干净构建中第一份、已审查的 CPython 3.10
输出；不可改回共享 SDK 工作树中的本地绑定。若需重建或目录已清理，先严格按
[`native/startouch/REPRODUCIBLE_BUILD.md`](native/startouch/REPRODUCIBLE_BUILD.md)
重新导出并完成双构建哈希对比，再运行准备命令。

依赖来源、版本、许可证和取舍见 [docs/dependencies.md](docs/dependencies.md)。主要复用
Grounded-SAM-2、SAM 2、Norfair、OpenCV `calibrateHandEye`，动作阶段设计参考 MoveIt Task
Constructor，低层命令字段参考本机 TH-Fanxy/Startouch 实现；没有引入 ROS/MoveIt 运行时。

## 在 VS Code 中逐模块 Debug

用 Remote-SSH 打开本目录，进入“运行和调试”，选择下列配置后按 F5：

| F5 配置 | 文件 | 观察结果 |
|---|---|---|
| `Vision: Debug Perception` | `scripts/vision/debug_perception.py` | 候选、掩膜、模型来源和耗时 |
| `Vision: Debug Stable IDs` | `scripts/vision/debug_tracking.py` | 每帧物理目标与稳定编号 |
| `Vision: Debug Geometry` | `scripts/vision/debug_geometry.py` | 抓取候选 JSON 和轮廓 JPEG |
| `Vision: Debug Pipeline` | `scripts/vision/debug_pipeline.py` | 指定编号的完整 V 决策 |
| `Action: Debug Calibration` | `scripts/action/debug_calibration.py` | 变换、校验门和内容哈希 |
| `Action: Debug Hand-Eye Clearance Plan (Offline)` | `scripts/action/debug_pregrasp_validation.js` | 事故帧目标的两段高位轨迹；不连接相机或机械臂 |
| `Action: Validate Hand-Eye High Clearance (Real, Select ID)` | `scripts/action/validate_handeye_pregrasp.js` | 输入编号后只升高和平移；不偏移、不转腕、不下降、不夹取 |
| `Action: Debug Home Gate` | `scripts/action/debug_home.js` | Home 目标/实测关节误差、容差和 blocker |
| `Action: Debug Alignment` | `scripts/action/debug_alignment.js` | 预抓取、静止、重观察、交接 |
| `Action: Debug Grasp` | `scripts/action/debug_grasp.js` | 九个低层动作和最终状态 |
| `Action: Debug Fixed Placement Plan` | `scripts/action/debug_execution_plan.js` | 检测点、法兰抓取点与六个路径点 |
| `Action: Debug Startouch Protocol (Simulated)` | `scripts/action/debug_startouch_protocol.js` | 握手、运动、夹爪、cleanup 回执与“未独立确认掉电”语义 |
| `VA: Debug Simulated Workflow` | `scripts/action/debug_workflow.js` | 从编号到放置/Home 的完整轨迹 |

Vision 的 F5 配置会先运行 `scripts/vision/build_debug_fixture.py`，在被 Git 忽略的
`artifacts/vision/debug-fixture/` 生成确定性三瓶 RGB-D 输入；因此干净 checkout 也能直接
Debug。你可以在 `.vscode/launch.json` 的 `args` 中替换为自己的 bundle；所有 Node 入口
使用假机器人。
推荐断点和输入/输出字段见 [V 模块说明](docs/vision/modules.md)与
[A 模块说明](docs/action/modules.md)。

最重要的完整离线命令是：

```bash
node scripts/action/debug_workflow.js \
  --target-id 2 \
  --fixture tests/fixtures/integration/full-cycle.json
```

它会输出稳定编号选择、运动后证据重置、一次对准和九阶段抓放命令；顶层始终为
`robot_control_enabled=false`。

两个新增的 A 模块可以完全单独运行：

```bash
node scripts/action/debug_execution_plan.js \
  --fixture tests/fixtures/integration/full-cycle.json

THIRDHAND_VA_PYTHON=/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python \
  node scripts/action/debug_startouch_protocol.js --simulate
```

前者使用 `fixed_xy_keep_grasp_z`：放置 X/Y 固定，Z 沿用本次瓶子抓取高度，抬升和撤离
再加安全余量；后者只拉起 `--simulate` bridge，不打开 CAN、相机或 3000 端口。

### 碰撞后安全复测顺序

先在“运行和调试”中选择 `Action: Debug Hand-Eye Clearance Plan (Offline)` 并按 F5。
终端必须显示两段且只能是 `safe_height`、`over_target_clearance`，同时
`commandsDescent=false`、`commandsGripper=false`、`robot_control_enabled=false`。

第一次真机复测必须移走其他瓶子，只留一个空的轻质软塑料测试瓶，周围保持足够空旷；确认
急停可用、机械臂已经处于配置中的 Home。然后选择
`Action: Validate Hand-Eye High Clearance (Real, Select ID)`，按 F5 后在输入框填写编号。
真机入口会在相机启动和编号选择前核验 Home，并在真正发运动命令前再次核验六关节；未处于
Home 时直接拒绝。获准后只竖直升到 `safe_transit_z_m`，再保持当前末端姿态水平移动到视觉
目标正上方，停留后回 Home 并调用 SDK cleanup 释放控制。cleanup 返回不是电机掉电或
急停证明，现场仍必须保持硬件急停可用。该流程不会生成可用于批准手眼标定的报告，也不会开放
正式夹取。

## L 调用接口

服务默认只监听 Ubuntu 回环地址 `127.0.0.1:8766`：

```bash
node apps/bottle_pick/web_server.js
```

未显式启用相机和机器人时，服务可以检查 API/状态，但会拒绝执行。L 的正式请求是：

```http
POST /api/va/start
Content-Type: application/json

{"schema":"thirdhand.va.command.v1","cmd":"start","target_id":2,"request_id":"L-0002"}
```

```http
POST /api/va/stop
Content-Type: application/json

{"schema":"thirdhand.va.command.v1","cmd":"stop","request_id":"L-stop-0001"}
```

服务真机启动时先回到已验证 Home，并用六关节反馈确认；之后才等待编号。状态读取为
`GET /api/va/status`，其中 `home.phase=ready` 才表示可以输入编号。同一个
`request_id + target_id` 重试是幂等的；已有任务
运行时，另一个请求返回冲突。完整成功只在瓶子释放、撤离并回 Home 后产生。薄客户端：

```bash
node apps/bottle_pick/run.js start 2
node apps/bottle_pick/run.js stop
```

请求/响应、视觉 v3 和机器人 adapter 契约见
[docs/integration/contracts.md](docs/integration/contracts.md)。

## 离线测试

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python -m pytest \
  tests/common tests/vision tests/action tests/integration -q
npm test
```

VS Code 也可运行任务 `VA: Full Offline Regression`。硬件测试在 `tests/hardware/`，默认
跳过；没有当次明确授权时，不运行 live camera/robot 命令。

受监督真机验收的分阶段门、精确授权条件、30 次记录格式和停止/恢复方法见
[docs/hardware/generic-bottle-validation.md](docs/hardware/generic-bottle-validation.md)。
当前 `configs/action.yaml` 已选择自包含的 `startouch_process` backend，但
`execution_enabled=false`。不要仅修改这一个布尔值：批准的法兰手眼文件、抓取偏移验证和
`thirdhand-pick-place-path-validation-v2` 路径工件必须同时绑定并批准固定路径、Home 六关节、
0.5° 容差、允许启动关节范围和启动回 Home 验证，否则运行时仍会拒绝动作。当前配置已经保存
非零 Home 六关节，可用于证明机械臂“已经在 Home”；但任意姿态自动回 Home 的路径范围仍未批准，
因此超出 Home 容差时必须拒绝，不能靠一个布尔值绕过。

## 可视化

Windows 局域网只读端口 8770、Remote-SSH 标签页、Ubuntu ToDesk 原生窗口、精确帧号
同步和深度融合调试仍保留，见 [docs/vision/preview.md](docs/vision/preview.md)。局域网入口
只传最终融合视频，不经过 SSH，也不暴露端口 3000 的其他接口。旧的固定可乐瓶、左右
序号和外置 D435 路径只作为历史实验资产，不是本 Skill 的正式输入或快速开始。
