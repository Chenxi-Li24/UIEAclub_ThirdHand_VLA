# Speech 与 XVisio 运行链路迁移设计

日期：2026-09-11
状态：设计已确认；实施计划待编写

## 1. 问题与证据

当前统一项目只运行两个进程：

- `127.0.0.1:3000`：Robot Service。
- `192.168.58.68:9983`：Web Gateway。

网页中的 XVisio 路由仍由占位实现固定返回 503，且系统中没有 3100 Vision
Service 或相机采集进程。因此网页显示黑屏和“正在重连”，不是本次证据能够支持的
相机硬件故障。Ubuntu 已通过 USB 识别 `040e:f408 MCCI XVisio vSLAM`，系统
`pkg-config` 也能找到 `xvsdk`。

当前语音页面仍使用旧 Jetson 3001/3002 端点和文案，系统中没有 3004 Speech
Service。正式来源 `/home/nieqingcao/Thirdhand_language` 与项目中
`migration/sources/language` 的语音源码一致；三档模型、FunASR 和 Python/Node
运行时已经位于项目的 ignored `local/` 目录。

## 2. 本轮目标

1. 将 `/home/nieqingcao/Thirdhand_language` 的正式 3004 语音能力迁入
   `services/speech`。
2. 保留现有 Claude 对话、动作候选、ASR 模型切换和 TTS，作为兼容模式。
3. 将 `migration/sources/vision-grasp` 中的 XVisio 采集、检测、稳定编号和
   可视化能力提升到正式 `services/vision` 与 `drivers/xvisio`。
4. 让 9983 通过同源代理提供语音、原始视频、检测框视频和视觉状态。
5. 将 Speech/Vision 纳入统一启动、停止、状态和诊断命令。

本轮不拆分中央 Orchestrator，不启用自动夹取，不改变 Robot Service 的 CAN
所有权，不修改任何旧来源目录。

## 3. 方案选择

### 方案 A：正式服务提升并由 9983 同源代理（采用）

- 3004 Speech 和 3100 Vision 只监听 Ubuntu 回环地址。
- 浏览器只访问 9983；Web Gateway 代理语音 WebSocket、视觉 HTTP/MJPEG 和状态。
- Robot Service 继续独占 CAN，语音和视觉不能直接初始化 Startouch SDK。
- 后续可以在不改变浏览器入口的情况下逐步拆分 Claude 和 Orchestrator。

该方案符合现有统一平台设计，避免向局域网额外暴露内部端口。

### 方案 B：浏览器直接连接 3004/3100

实现较少，但要求两个服务监听局域网，并增加跨端口连接、安全边界和地址配置。
浏览器从 Windows 访问时也不能使用 Ubuntu 的 `127.0.0.1`。不采用。

### 方案 C：重新运行旧单体 9983

可以快速恢复画面和语音，但会重新引入相机、语言、机器人和网页混合所有权，与当前
3000 Robot Service 冲突，并使新项目继续依赖旧目录。不采用。

## 4. 服务边界

### 4.1 Speech Service

`services/speech` 复制并适配正式来源中的：

- `voice_bridge.py`
- `asr_model_manager.py`
- `whisper_backend.py`
- `funasr_backends.py`
- `voice_agent.py`
- `tts_bridge.py`
- 相关协议和单元测试

服务监听 `127.0.0.1:3004/v1/voice`，继续使用
`thirdhand.voice.v1` WebSocket 子协议。模型 ID 保持：

- `whisper-small`：Medium，CUDA，默认模型。
- `paraformer-streaming`：Real-time，CPU。
- `fun-asr-nano`：High，CUDA。

项目配置显式把这些 ID 映射到 `local/models/asr/medium`、
`local/models/asr/realtime` 和 `local/models/asr/high`，不创建指向旧工程的
运行时符号链接。

兼容模式保留 Claude 对话和动作候选，但所有真机动作仍必须通过 9983 转发给
3000，并遵守页面确认和 Robot Service 安全检查。Speech 不打开 CAN。

### 4.2 Vision Service

`drivers/xvisio` 拥有原生 XVisio RGB-D 采集程序和构建脚本。
`services/vision` 拥有唯一相机进程，并提供：

- `GET /health`
- `GET /camera/xvisio/raw`
- `GET /camera/xvisio/vision`
- `GET /camera/xvisio/depth`
- 视觉事件和目标选择控制通道

原始预览和模型推理解耦。只要相机采集成功，原始画面就必须可用；检测模型加载失败
时，检测框画面和目标选择显示明确错误，但不能让原始画面一起黑屏。

视觉进程复用 `migration/sources/vision-grasp` 的单帧邮箱策略，不积压过期帧。
检测结果继续携带帧号、单调时间、稳定目标 ID 和图像 SHA-256。Vision 不打开
CAN，也不直接执行夹取。

### 4.3 Web Gateway

9983 保持唯一浏览器入口：

- `/voice` WebSocket 代理到 `ws://127.0.0.1:3004/v1/voice`，保留子协议。
- `/camera/xvisio/*` 代理到 3100 对应 MJPEG 路由。
- `/api/vision/*` 代理视觉状态与只读选择请求。
- `/ws` 继续代理 3000 Robot Service。

语音面板使用正式 Ubuntu 版本，显示 Medium、Real-time、High 三档模型，不再显示
Jetson 3001/3002。浏览器本地存储中的旧端点在版本迁移后被同源 `/voice` 覆盖。

## 5. 生命周期

`./thirdhand start` 的本轮顺序：

1. 验证项目内运行时、ASR 模型和 XVisio SDK。
2. 保留或启动 Robot Service。
3. 启动 Speech Service。
4. 构建或验证 XVisio 原生采集程序，然后启动 Vision Service。
5. 启动 Web Gateway。

重复启动必须幂等。停止时先关闭 Web，再关闭 Speech/Vision，最后才处理 Robot。
本轮验收不重启 Robot Service；只启动 3004/3100，并在必要时受控重启 9983。

## 6. 错误处理与降级

- Speech 失败：文字和 Robot 手动控制继续可用。
- 某个 ASR 模型失败：显示该模型不可用，不能伪造 READY。
- Vision 模型失败：原始 XVisio 画面继续显示，检测和夹取保持锁定。
- XVisio 采集失败：3100 返回结构化健康原因，9983 显示具体错误而不是无限重连。
- 3100 恢复：旧 TargetRef 和选择状态全部失效。
- 9983 与 3004/3100 断开：自动重连只恢复数据通道，不恢复任何运动授权。

## 7. 验证
