# Ubuntu 本地 RGB-D 视觉监控窗口设计

日期：2026-08-23

## 目标

在 Ubuntu 桌面直接弹出一个只读 OpenCV 窗口，供 ToDesk 查看。一个窗口同时显示现有
相机 RGB、算法轮廓/掩膜/序号/状态，以及更明显的彩色深度云图。不向 Windows 传输，
不制作网页，不新建端口，不重启或停止现有端口 3000、8765、8766 的服务。

## 当前接口与边界

- 端口 3000 的既有服务是实时视觉真源：
  - `/camera_lumos_vision`：相机画面和算法可视化；
  - `/camera_xvisio_depth`：已配准的 Turbo 彩色深度图；
  - 两路 MJPEG 都携带 `X-ThirdHand-Frame-Id`、时间和 SHA-256 帧头。
- `thirdhand_va.vision.preview` 负责只读画面来源；新增带帧头的 MJPEG 读取器，不拥有相机。
- `thirdhand_va.vision.visualization` 负责纯图像融合；不包含网络或窗口生命周期。
- `apps.vision_monitor` 只组装来源、融合与窗口，支持 VS Code 断点和离线图片输入。
- Action、机器人控制、选择接口、相机采集以及已有 preview relay 都不在修改范围内。

## 方案

使用 Python 标准库读取带 `Content-Length` 的 multipart MJPEG part，并用已有 OpenCV 解码。
算法流由主线程读取；深度流由一个后台读取器维护小型按帧号缓存。只有相同
`X-ThirdHand-Frame-Id` 才融合，避免物体移动时出现深度重影。深度短暂缺失时继续显示
算法画面并标记 `DEPTH WAITING`，读取器自动重连。

融合仅作用于深度图中非黑的有效像素，默认附加透明度为 0.35；这样可把既有较弱的深度
层增强到肉眼明显，同时保留算法轮廓和文字。画面右上显示 0.15--1.20 m 的 Turbo 色标，
左下显示匹配帧号和深度有效覆盖率。

窗口使用部署环境已经提供的 OpenCV Qt5 `namedWindow`/`imshow`，通过 Ubuntu X11
`DISPLAY=:1` 打开。`Q` 或 `Esc` 只关闭监控程序自身。应用不监听任何端口，也不发送
任何控制请求。

## 独立调试

- 在线模式读取两个既有 URL。
- 离线模式接受一张算法 JPEG/PNG 和一张深度 JPEG/PNG，不要求相机、模型或端口 3000。
- VS Code 启动项固定使用带 Qt 的部署 Python，并设置 Ubuntu 桌面显示变量。
- 网络解析、帧缓存和融合均有不依赖桌面/硬件的单元测试；GUI 入口有注入式假窗口测试。

## 故障行为

- 算法流断开：保持窗口并显示离线占位画面，按间隔重连。
- 深度流断开或帧号不匹配：显示算法原图与 `DEPTH WAITING`，不拿错帧强行融合。
- 图像尺寸不同：本帧不融合并显示原因，不缩放深度图破坏配准关系。
- 关闭窗口、按键或终止进程：释放两个只读 HTTP 连接和窗口，不影响上游服务。
