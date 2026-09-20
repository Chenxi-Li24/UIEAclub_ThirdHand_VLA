# RGB-D 融合相机预览

## 通用瓶 Skill 的编号语义

正式叠加图上的 `1..5` 是 Stable ID，不是这一帧从左到右重新排序的序号。L 传入某个
编号后，目标框会进入选中态；机械臂运动造成视角变化时，该编号仍绑定原物理瓶，并在
静止后重新积累深度证据。若身份、深度或帧同步证据不足，画面应显示 blocker，A 不会
执行。预览只用于观察和提供编号，不拥有机器人控制权。

## Ubuntu 桌面原生窗口（ToDesk）

这是 ToDesk 场景的推荐入口。它不制作网页、不向 Windows 转发，也不监听任何新端口；
只是从已有端口 3000 只读连接算法流 `/camera_lumos_vision` 和深度流
`/camera_xvisio_depth`，
按照 `X-ThirdHand-Frame-Id` 精确匹配后，在 Ubuntu 的 X11 桌面弹出一个 OpenCV 窗口。

终端启动：

```bash
DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority \
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m apps.vision_monitor.main
```

窗口标题是 `ThirdHand RGB-D Vision Monitor`。按 `Q`、`Esc` 或点击关闭按钮退出。深度图
只在非黑有效像素处额外以 `0.35` 透明度增强，右上角显示 `0.15--1.20 m` Turbo 色标，
底部显示实际匹配帧号和有效深度覆盖率。深度暂时缺失时相机和算法画面继续显示，并标记
`DEPTH WAITING`；不会用旧深度强行合成。

黄色 `DEPTH HARDWARE FOV` 框表示序列号 `250801DR48FP25002738` 的 XVisio ToF 硬件
注册到 `640x480` RGB 后的固定覆盖外包框，标定坐标为 `(203,149)--(428,319)`。框不会
跟随物体或当前有效深度像素移动；只有框内的彩色深度云图随实际测量变化。更换相机或
注册标定后，需要更新 `apps/vision_monitor/main.py` 中的 `RegisteredDepthCoverage`。

VS Code Remote-SSH 中选择 `Vision Monitor: Ubuntu Desktop Window` 并按 `F5`，即可在以下
文件设置断点：

- `src/thirdhand_va/vision/preview/source.py`：multipart 帧头、JPEG 与 SHA-256 校验；
- `src/thirdhand_va/vision/preview/synchronization.py`：深度帧缓存与精确帧号匹配；
- `src/thirdhand_va/vision/visualization/monitor.py`：有效深度区域和透明融合；
- `src/thirdhand_va/vision/preview/local_monitor.py`：窗口循环和断线恢复；
- `apps/vision_monitor/main.py`：参数、X11 环境与模块组装。

离线调试不需要相机、模型或端口 3000：

```bash
DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority \
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m apps.vision_monitor.main \
  --algorithm-image /path/to/algorithm.png \
  --depth-image /path/to/depth.png
```

两张图必须是同尺寸、已经配准的画面。该应用没有 `--host` 或 `--port` 参数，也不会停止
端口 3000、8765、8766 的服务。

## Windows 局域网直接查看（不经过 SSH）

Windows 和 Ubuntu 位于同一个 `192.168.58.0/24` 局域网时，可以只传输最终融合视频，
无需打开 VS Code 端口转发，也不经过 SSH。Ubuntu 仍在本机完成相机、算法轮廓和深度
热力图融合；Windows 只负责显示 MJPEG。

在 Ubuntu 或 VS Code Remote-SSH 终端以前台方式启动：

```bash
cd $HOME/th0814/VA/bottlegrasp
$HOME/miniconda3/envs/thirdhand-groundedsam2/bin/python -u \
  -m apps.vision_lan.main \
  --host 192.168.58.68 \
  --allowed-network 192.168.58.0/24 \
  --port 8770
```

终端会输出一行 JSON，其中 `stream_url` 是带随机访问令牌的完整地址。把整个地址复制到
Windows 的 Edge、Chrome 或 VLC 中即可，例如：

```text
http://192.168.58.68:8770/stream.mjpg?token=启动时打印的令牌
```

不要点击 VS Code“端口”面板里的“在浏览器中打开”；那种方式会使用 SSH 转发。不要把
令牌发给同一局域网内的其他人。关闭时回到启动终端按 `Ctrl+C`，它只关闭新端口 8770，
不会停止 3000、8765、8766 或机器人服务。

在 VS Code 中也可以选择 `Vision LAN: Debug Windows Viewer` 后按 `F5`。可以在以下文件
设置断点，并在终端复制它打印的 `stream_url`：

- `src/thirdhand_va/vision/preview/fused_source.py`：精确帧号匹配和三层融合；
- `src/thirdhand_va/vision/preview/server.py`：局域网、令牌和只读 HTTP 边界；
- `apps/vision_lan/main.py`：参数、来源组装和启动/关闭生命周期。

Ubuntu 本机诊断命令：

```bash
ss -ltnp '( sport = :3000 or sport = :8765 or sport = :8766 or sport = :8770 )'
curl --fail 'http://192.168.58.68:8770/health?token=启动时打印的令牌'
```

如果 Ubuntu 上的 `curl` 成功而 Windows 无法打开，通常是 Ubuntu 防火墙或 Wi-Fi 的
客户端隔离。此时应检查局域网策略，不要改成监听 `0.0.0.0`，也不要把包含其他接口的
端口 3000 暴露到局域网。

## Windows VS Code 标签页

预览模块只负责把 Ubuntu 已经生成的融合 MJPEG 画面稳定地显示到 Windows 的 VS Code
标签页中。它不打开 XVisio、不加载模型、不发送选择命令，也不控制机器人。

## 日常查看：一次 F5

1. 在 Windows 用 VS Code Remote-SSH 打开 `bottlegrasp` 根目录。
2. 点击左侧“运行和调试”（三角形加小虫图标）。
3. 顶部下拉框选择 `Vision Preview: Open Window`。
4. 按 `F5`。

VS Code 会在 Ubuntu 启动只读 relay，并在 Windows 的编辑区打开相机标签页。默认输入是
`http://127.0.0.1:3000/camera_lumos_vision`；融合流断开时自动显示带红色提示的原始
RGB，二者都断开时保留离线占位画面。relay 每两秒重试融合流。

这是直接 MJPEG 预览，不是最终业务网页。Windows 不运行 Python、模型或相机 SDK。

## 单独 Debug

调试前若日常 relay 已运行，先按 `Ctrl+Shift+P`，执行
`Tasks: Terminate Task`，选择 `Vision Preview: Start Relay`，避免 8765 端口冲突。

无相机回放调试：

1. 在下列任一文件设置断点：
   - `src/thirdhand_va/vision/preview/source.py`
   - `src/thirdhand_va/vision/preview/service.py`
   - `src/thirdhand_va/vision/preview/server.py`
2. 选择 `Vision Preview: Debug Replay`，按 `F5`。
3. 再选择 `Vision Preview: Open Running Debug Window`，按 `F5` 查看画面。

连接当前实时流调试时，把第 2 步换成 `Vision Preview: Debug Live Attach`。这两种 Debug
配置都在 Ubuntu 执行，断点、变量、日志和终端输出都留在 Remote-SSH 会话中。

## 终端独立运行

回放模式不需要相机、模型或端口 3000：

```bash
python -u -m apps.vision_preview.main \
  --replay-image artifacts/vision/validation/spatial/three-left-2-overlay.jpg
```

连接当前实时融合流：

```bash
python -u -m apps.vision_preview.main
```

## 单独调试深度融合

深度融合算法不需要启动模型、相机、端口 3000 或预览 relay。它直接读取一个已录制的
`RgbdFrame` bundle；默认仅在 `0.15--1.20 m` 的有效配准像素上，以 `0.50` 透明度叠加
OpenCV Turbo 色图，并在右上角标出 `NEAR`/`FAR` 色标。候选掩膜仍由 `overlay.py`
单独绘制，填充强度为 `0.20`，轮廓、序号和选中标记不变。

在 VS Code Remote-SSH 中，可以打开：

- `src/thirdhand_va/vision/visualization/depth_heatmap.py`：在色图、有效像素或融合逻辑处
  设置断点。
- `src/thirdhand_va/vision/visualization/overlay.py`：在深度层与识别结果合成处设置断点。
- `scripts/vision/debug_visualization.py`：修改输入 bundle 或输出路径。

随后选择 `Vision Visualization: Debug Bundle` 并按 `F5`。默认读取仓库已有的录制帧，
输出 `artifacts/vision/debug/depth-fusion.jpg`，终端同时打印有效深度像素数、覆盖率、
距离范围和透明度。也可以完全从终端运行：

```bash
python scripts/vision/debug_visualization.py \
  artifacts/vision/validation/live-bundles/frame_000000 \
  --output artifacts/vision/debug/depth-fusion.jpg \
  --depth-alpha 0.50
```

替换第一个参数即可提供自己的录制测试输入。该脚本只写指定的 JPEG，不建立网络连接，
并始终输出 `robot_control_enabled=false`。

服务输出 `preview_ready` JSON 后，预览地址为：

```text
http://127.0.0.1:8765/stream.mjpg
```

只读健康状态和消费者验证：

```bash
curl --fail http://127.0.0.1:8765/health
python scripts/vision/preview_smoke.py --frames 10
```

终端启动的进程用 `Ctrl+C` 停止。停止 relay 只关闭它自己的连接和端口 8765，不会停止
端口 3000 的相机/算法服务。

## 故障定位

检查 relay 是否监听：

```bash
ss -ltnp 'sport = :8765'
```

如果提示端口被占用，终止已有 `Vision Preview: Start Relay` task，或在终端为人工实例
传入其他端口，例如 `--port 8766`。不要通过杀死端口 3000 的进程来解决预览端口冲突。

如果窗口显示 `VISION OFFLINE - RAW CAMERA`，说明融合算法流暂时不可用，但原始相机
仍在线；如果显示 `CAMERA PREVIEW OFFLINE`，说明两路输入都不可用。保持窗口打开即可，
relay 会自动重试。可同时查看 `/health` 中的 `mode`、`reconnect_count` 和
`relay_frame_age_ms`。

`/health` 中的 `mode=fused` 只表示 relay 成功读到了端口 3000 的融合 URL，不代表上游
一定由当前 checkout 的代码生成。若修改 `visualization` 后画面没有变化，先检查实际
上游进程：

```bash
ps -eo pid,args | rg 'apps\.bottle_pick\.camera_bridge|camera_bridge_va'
```

若输出仍是旧的 `camera_bridge_va.py`，仅重启端口 8765 的 relay 不会加载新融合逻辑；
需要在确认机器人和相机处于安全状态后，由运行者明确重启或迁移端口 3000 的上游服务。
不要为了刷新预览而直接杀死端口 3000 的进程。

如果 VS Code 标签页访问到 Windows 本机而不是 Ubuntu，确认工作区的
`workbench.browser.enableRemoteProxy` 为 `true`，并确认左下角显示当前 Remote-SSH 主机。
