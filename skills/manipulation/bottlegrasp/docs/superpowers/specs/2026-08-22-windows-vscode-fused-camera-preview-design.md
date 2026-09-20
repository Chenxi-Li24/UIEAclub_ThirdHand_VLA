# Windows VS Code 融合相机预览设计

日期：2026-08-22

## 1. 目标

在不把调试能力塞进最终前端、也不要求 Windows 运行项目代码的前提下，为远程 Ubuntu
上的视觉系统增加一个可长期显示的只读预览窗口：

- 相机采集、算法推理、深度配准、掩膜生成和画面融合全部在 Ubuntu 运行。
- Windows 只通过 VS Code Remote-SSH 的集成浏览器显示画面。
- 单一画面同时包含 RGB、有效深度的透明热力图、全部目标掩膜、候选/选中标识、距离、
  FPS、推理延迟和阻断状态。
- 正常查看只需在 VS Code 选择一个启动项并按 `F5`。
- 每个新增核心模块都能在 Ubuntu 的 VS Code 中单独运行、传入人工测试源、设置断点并
  通过日志、健康状态或预览图独立判断结果。

## 2. 已确认的运行边界

1. 代码和进程全部位于远程 Ubuntu；Windows 不安装项目 Python、模型或相机 SDK。
2. Windows 上显示为 VS Code 独立预览标签页，不是 Windows 原生 GUI 弹窗。
3. 预览是只读的，不包含选择、机器人控制、相机控制或任何动作接口。
4. 最终业务前端不在本次范围内；本次 HTTP 只承载 MJPEG 和只读健康信息，不提供 HTML
   页面、按钮或业务 UI。
5. 实时目标为 5--10 FPS、观察延迟不高于约 500 ms；处理不及时就丢弃旧帧，绝不累积
   历史帧。
6. 深度只在配准且有效的区域以透明方式叠加；沿用当前默认 `depth_alpha=0.30`，掩膜
   着色沿用 `0.32`。

## 3. 当前项目理解

### 3.1 目录职责

当前仓库已经按 V/A 边界组织：

```text
src/thirdhand_va/common/             公共配置、错误和不可变契约
src/thirdhand_va/vision/             相机、感知、选择、几何、跟踪、可视化、发布适配器
src/thirdhand_va/action/             标定、观测、对准、抓取、安全和外部适配器
native/vision/xvisio_rgbd_stream/    XVisio 原生 RGB-D 采集
apps/bottle_pick/                    V/A 组合与进程生命周期
scripts/vision/                      Vision 独立人工调试入口
tests/vision/                        与 Vision 功能目录镜像的模块测试
artifacts/vision/                    离线输入、截图和验证证据
```

新增预览属于 Vision 的只读输出边界，不进入 Action，不改变机器人安全门。

### 3.2 已有接口链路

现有视觉主链路为：

```text
XVisio / replay bundle
        |
        v
RgbdFrame -> VisionPipeline.process() -> VisionDecision
                                             |
                                             v
render_overlay() -> encode_jpeg() -> LatestFramePublisher -> MJPEG
```

关键复用点：

- `src/thirdhand_va/vision/pipeline.py` 负责感知、选择、几何和稳定性的统一编排，公开接口
  是 `VisionPipeline.process(frame) -> VisionDecision`。
- `src/thirdhand_va/vision/visualization/overlay.py` 已负责 RGB、配准深度、全部掩膜、目标
  轮廓、选择序号、距离、FPS、DINO/SAM2 延迟和阻断状态的融合。
- `src/thirdhand_va/vision/adapters/mjpeg_publisher.py` 已定义带帧来源信息的 MJPEG part。
- `src/thirdhand_va/vision/adapters/event_publisher.py` 的 `LatestFramePublisher` 已采用单槽
  latest-value 策略，旧帧会被新帧替换。
- `apps/bottle_pick/camera_bridge.py` 已支持 `live` 和 `replay`，并分别发布融合、原始 RGB
  和深度热力图。
- `src/thirdhand_va/action/adapters/camera_bridge.js` 已有浏览器慢消费者隔离、MJPEG 扇出
  和子进程 2 秒自动重启机制，但它属于完整应用的相机子进程管理，不适合作为独立的
  Windows 预览入口。

### 3.3 当前运行事实

设计前已经在目标 Ubuntu 上做了只读验证：

- XVisio 相机已被现有进程占用，端口 `3000` 提供
  `/camera_lumos_vision`、`/camera_xvisio_raw` 和 `/camera_depth`。
- `/camera_lumos_vision` 当前输出 `640x480` 的融合画面，实测包含四个瓶子的掩膜、
  选中轮廓、透明深度、距离、FPS、延迟和安全状态。
- 专用环境中的 OpenCV 5.0.0 启用了 FFmpeg，实测可以打开该 URL，并在约 350 ms 内读取
  三帧；因此无需自行实现 multipart/JPEG 网络解析器。
- 远程会话没有 `DISPLAY`/`WAYLAND_DISPLAY`，项目依赖是
  `opencv-python-headless`，所以 `cv2.imshow()` 不能直接在 Windows 弹窗。

## 4. 方案比较与复用结论

### 4.1 采用：OpenCV + Python 标准库 + VS Code 集成浏览器

- 使用项目已有 OpenCV `VideoCapture` 读取 MJPEG。OpenCV 官方为 FFmpeg/GStreamer
  后端提供打开和读取超时参数，可以让断线恢复具备有界等待。
- 使用现有 `encode_jpeg()` 和 `build_mjpeg_part()` 输出，不重复实现 JPEG 和 MJPEG
  编码。
- 使用 Python 标准库 `ThreadingHTTPServer` 处理 VS Code 的预览连接；它仅绑定
  `127.0.0.1`，仅用于开发调试，不作为生产 Web 服务。
- 使用 VS Code 官方 `editor-browser` 启动类型和 Remote-SSH 远程代理。源码和进程仍在
  Ubuntu，按 `F5` 后标签页显示在 Windows。
- 不增加第三方运行依赖。当前 OpenCV 5 使用 Apache-2.0，Python 标准库随解释器提供。

### 4.2 不采用的候选

- **X11 + `cv2.imshow()`**：需要 Windows X Server 和 Ubuntu GUI 版 OpenCV；当前远程
  环境无显示服务，视频链路更脆弱，也违背 Windows 只负责显示、尽量零安装的边界。
- **ROS `image_view` / Foxglove**：都是成熟的机器人可视化方案，但本项目没有 ROS
  消息总线。为了一个只读 MJPEG 窗口引入 ROS/桥接协议和桌面工具属于过度依赖。
- **`mjpg-streamer`**：项目成熟并支持 HTTP 输入/输出，但需要额外 C/CMake/libjpeg
  构建链，许可证为 GPLv2，且官方警告默认服务不应暴露到不可信网络。当前工程已经有
  MJPEG 发布能力，因此不引入。
- **WebRTC**：论文和远程机器人实践表明它适合更低延迟、双向和公网场景，但会引入
  信令、ICE/STUN/TURN 和浏览器媒体协商。本次是 SSH 内单用户、5--10 FPS 的只读调试
  窗口，MJPEG 更简单且满足目标。若以后出现高帧率或公网多用户需求，再单独评估。

## 5. 推荐架构

```text
Ubuntu existing vision service
  /camera_lumos_vision (primary fused MJPEG)
  /camera_xvisio_raw   (fallback raw MJPEG)
                  |
                  v
OpenCvMjpegSource -----> PreviewService -----> LatestPreviewFrame
       ^                       |                       |
       |                       |                       v
ImageReplaySource       retry/fallback/status   PreviewHttpServer
   (offline debug)            |                 127.0.0.1:8765
                              |                       |
                              +-----------------------+
                                                      |
                                      VS Code Remote proxy / SSH
                                                      |
                                                      v
                                      Windows VS Code preview tab
```

预览模块消费“已经融合好的图像”，不调用模型、不读取掩膜内部对象、不抢占相机，也不
依赖 Action。现有视觉链路仍是融合真源；预览层只负责读取、状态标记、latest-frame
缓存和只读传输。

## 6. 模块和文件职责

### 6.1 可复用库模块

`src/thirdhand_va/vision/preview/source.py`

- 定义 `FrameSource` 协议和不可变 `SourceFrame`。
- `OpenCvMjpegSource`：打开一个 MJPEG URL、设置打开/读取超时、输出 RGB 帧、关闭资源。
- `ImageReplaySource`：循环读取人工指定的 JPEG/PNG，作为无相机测试输入。
- `SourceFrame` 记录 relay 收到该帧的单调时间；OpenCV 不暴露上游 multipart 自定义
  header，因此该时间只代表 relay 内部帧龄，不能伪称相机到屏幕的完整端到端时间。
- 不负责重连、不启动 HTTP 服务、不写日志、不接触相机设备。

建议接口：

```python
class FrameSource(Protocol):
    def open(self) -> None: ...
    def read(self) -> SourceFrame | None: ...
    def close(self) -> None: ...
```

`src/thirdhand_va/vision/preview/service.py`

- 组合 primary/fallback source，维护 `fused -> raw_fallback -> offline` 状态机。
- primary 断开后立即尝试 raw；每 2 秒重试 primary，恢复后自动切回。
- 只保存最新一帧和递增序号；慢客户端只拿最新帧，不阻塞上游。
- raw fallback 帧增加 `VISION OFFLINE - RAW CAMERA` 明显标记；两路都不可用时持续发布
  离线占位帧，让 Windows 窗口保持打开。
- 接收 source、时钟和停止事件注入，单元测试不访问网络或硬件。

建议只读接口：

```python
service.start()
service.wait_for_frame(after_sequence, timeout_s) -> PreviewFrame | None
service.status() -> PreviewStatus
service.stop()
```

`src/thirdhand_va/vision/preview/server.py`

- `ThreadingHTTPServer` 的薄封装，只暴露：
  - `GET /stream.mjpg`：`multipart/x-mixed-replace; boundary=frame`
  - `GET /health`：只读 JSON，包含状态、来源、最后帧时间、重连次数和客户端数
- 拒绝其他路径和所有修改型 HTTP 方法。
- 默认且正常模式只允许绑定 `127.0.0.1`；不提供 HTML、静态资源和控制 API。
- 每个客户端独立等待新序号，网络慢时自然跳过中间帧。

`src/thirdhand_va/vision/visualization/preview_status.py`

- 只负责在 RGB 图上绘制 fallback/offline 标记和生成离线占位图。
- 输入图像和结构化状态，输出新图像；无网络、线程和全局状态。

这些文件按“来源、运行状态、HTTP 边界、画面状态渲染”拆分，数量有限且各自变化原因
不同，不把所有逻辑塞进一个脚本，也不把每个小函数单独成文件。

### 6.2 应用入口

`apps/vision_preview/main.py`

- 只负责参数解析、依赖组装、日志和进程退出。
- 默认连接：
  - primary：`http://127.0.0.1:3000/camera_lumos_vision`
  - fallback：`http://127.0.0.1:3000/camera_xvisio_raw`
  - listen：`127.0.0.1:8765`
  - reconnect：`2.0 s`
- 支持 `--replay-image PATH`，不启动完整系统也能验证窗口、HTTP 和断点。
- 只停止自己创建的 source/service/server，不停止端口 3000 的既有服务或相机进程。

### 6.3 VS Code 配置

`.vscode/settings.json`

- 启用 `workbench.browser.enableRemoteProxy`，让集成浏览器的 localhost 请求通过当前
  Remote-SSH 工作区到达 Ubuntu。

`.vscode/tasks.json`

- `Vision Preview: Start Relay`：在 Ubuntu 启动独立预览入口，背景任务检测 ready 日志。

`.vscode/launch.json`

- `Vision Preview: Open Window`：使用 `editor-browser` 打开
  `http://127.0.0.1:8765/stream.mjpg`，以后台 task 为前置任务；日常只按一次 `F5`。
- `Vision Preview: Debug Live Attach`：用 Python debugger 启动服务并连接现有实时流。
- `Vision Preview: Debug Replay`：传入仓库内验证图片，适合单步调试且不访问相机。

日常 `Open Window` 配置追求一步打开，不承载 Python 断点；需要调试实现时使用两个
`Debug` 配置之一，在 `source.py`、`service.py` 或 `server.py` 设置断点。这一区分避免把
后台常驻任务和调试器生命周期强行耦合。

由于 VS Code 的远程终端运行在 Ubuntu，不能可靠地用普通 Ubuntu shell 命令直接控制
Windows 桌面 UI；`editor-browser` 的 `F5` 启动配置是官方且稳定的一步入口。终端方式
仍保留给人工测试，输出可点击的预览 URL。

## 7. 状态与错误处理

状态转换：

```text
STARTING
   |
   +-- primary frame --------> FUSED
   |
   +-- primary failed
           |
           +-- fallback frame -> RAW_FALLBACK
           |
           +-- fallback failed -> OFFLINE

RAW_FALLBACK/OFFLINE -- primary retry succeeds --> FUSED
```

规则：

- Open/read 超时必须有上限；失败记录结构化日志，但线程继续运行。
- 每 2 秒重试，不使用无上限紧循环。
- JPEG 编码失败只丢当前帧，不杀死服务。
- 客户端断开只移除该客户端，不停止 source。
- 服务收到 `SIGINT`/`SIGTERM` 后按 server -> service -> source 顺序关闭并等待线程退出。
- 日志至少包含 `source_state`、脱敏 URL、frame sequence、relay frame age、
  reconnect count 和异常类型。
- `/health` 不返回堆栈、本机秘密或环境变量。

## 8. 独立运行和 Debug

### 8.1 Source 单元

在 VS Code 打开 `src/thirdhand_va/vision/preview/source.py`，在 `open()`/`read()` 设置断点，
通过测试创建本机假 MJPEG 服务或传入验证图片：

```bash
python -m pytest tests/vision/preview/test_source.py -q -s
```

### 8.2 Service 单元

在 `service.py` 的状态转换处设置断点，测试注入成功、断线、恢复和慢帧 source：

```bash
python -m pytest tests/vision/preview/test_service.py -q -s
```

### 8.3 HTTP 单元

在 `server.py` 的请求处理和客户端发送处设置断点，使用内存帧服务：

```bash
python -m pytest tests/vision/preview/test_server.py -q -s
```

### 8.4 离线可视化调试

无需相机、模型或端口 3000：

```bash
python -m apps.vision_preview.main \
  --replay-image artifacts/vision/validation/spatial/three-left-2-overlay.jpg \
  --port 8765
```

打开 `http://127.0.0.1:8765/stream.mjpg` 即可独立判断显示、状态标记和 MJPEG 是否正常。

### 8.5 实时 attach 调试

不会抢占当前 XVisio：

```bash
python -m apps.vision_preview.main \
  --primary-url http://127.0.0.1:3000/camera_lumos_vision \
  --fallback-url http://127.0.0.1:3000/camera_xvisio_raw
```

## 9. 测试顺序与验收标准

### 9.1 模块测试

- source：正常帧、打开失败、读取超时、颜色通道、close 幂等。
- status renderer：raw/offline 标签可见、输入不被原地修改、JPEG 可编码。
- service：primary 优先、fallback、2 秒重试、恢复切回、只保留最新帧、停止无残留线程。
- server：流 MIME/boundary 正确、health 字段正确、404/405、慢客户端不阻塞快客户端。

### 9.2 接口与集成测试

- 使用仓库图片启动入口，读取三帧并验证 JPEG 可解码。
- 使用本机假 primary/fallback MJPEG 服务验证断开、raw fallback 和自动恢复。
- 连接真实 `/camera_lumos_vision` 进行只读 smoke test；不重启、不停止现有相机服务。
- 验证只监听 `127.0.0.1`，没有控制路由。
- 在 Windows VS Code Remote-SSH 中按 `F5`，确认标签页持续显示。

### 9.3 验收指标

- 融合模式包含 RGB、有效深度透明层、全部掩膜、选中目标、距离、FPS、延迟和阻断状态。
- steady state 目标 5--10 FPS；在当前上游约 3--4 FPS 时不人为制造额外队列。
- relay 内部新增延迟目标小于 100 ms，relay frame age 只按 Ubuntu 收帧时刻计算；完整
  观察延迟由融合图中的上游推理延迟与 relay 指标共同判断。若上游推理本身使总观察
  延迟超过约 500 ms，必须如实显示，不能以缓存旧帧伪装实时。
- primary 断开后窗口不关闭，2 秒周期内进入 fallback/offline；恢复后自动回到 fused。
- Windows 无项目进程、无模型、无 X Server；关闭 VS Code 预览不影响 Ubuntu 相机和算法。

## 10. 修改范围与非目标

预计只新增 `vision/preview`、薄应用入口、镜像测试、VS Code 配置和说明文档；除必要的
公开导出外，不修改 perception、selection、geometry、tracking、action 或机器人安全
逻辑。现有 `overlay.py` 的融合语义和透明度默认值保持不变。

本次明确不做：

- 最终网页前端或业务 UI。
- Windows 原生程序、Windows Python 或 X11 配置。
- WebRTC/RTSP/ROS 迁移。
- 相机参数、算法参数、瓶子选择或机器人动作控制。
- 自动停止、替换或接管当前端口 3000 的外部服务。

## 11. 调研来源与许可证判断

- [VS Code Integrated Browser](https://code.visualstudio.com/docs/debugtest/integrated-browser)：
  `editor-browser`、`F5` 启动和 Remote-SSH proxy 的官方依据。
- [VS Code Remote-SSH](https://code.visualstudio.com/docs/remote/ssh)：远程代码运行和端口
  转发边界的官方依据。
- [OpenCV Video I/O flags](https://docs.opencv.org/4.10.0/d4/d15/group__videoio__flags__base.html)：
  FFmpeg/GStreamer open/read timeout 的官方接口。
- [OpenCV GitHub](https://github.com/opencv/opencv)：现有依赖，Apache-2.0；目标环境已经
  实测 FFmpeg MJPEG 读取成功。
- [Python `http.server`](https://docs.python.org/3/library/http.server.html)：
  `ThreadingHTTPServer` 官方说明；文档同时指出不适合生产，因此设计强制 loopback 且
  仅用于本地开发预览。
- [ROS image_pipeline](https://github.com/ros-perception/image_pipeline)：成熟参考，包含
  `image_view`，但需要 ROS 生态，本次不引入。
- [`mjpg-streamer`](https://github.com/jacksonliam/mjpg-streamer)：成熟 MJPEG 工具，GPLv2，
  需要额外原生构建并有不可信网络警告，本次不引入。
- [低延迟机器人遥操作架构论文](https://arxiv.org/abs/2510.11421)：WebRTC 适用于更复杂
  的远程操控；本次没有双向公网媒体需求，因此暂不采用。

社区和 GitHub issue 中反复出现的实践风险主要是 GUI OpenCV 的远程显示依赖、视频
读取无限阻塞、浏览器慢消费者导致上游背压，以及将未认证 MJPEG 暴露到局域网。本设计
分别用 VS Code 远程代理、有界读取超时、latest-value 单槽和 loopback 绑定规避；社区
材料只用于发现风险，最终技术判断以上述官方文档、仓库实测和上游项目许可证为准。
