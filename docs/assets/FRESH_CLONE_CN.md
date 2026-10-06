# 新克隆的运行准备

仓库包含 URDF/STL、YuNet 和 MediaPipe 人脸模型、YOLOv8n 人物模型、三套 ASR 模型、固定版本的
Grounding DINO/SAM2 模型、Startouch/XVisio SDK 和实际部署使用的 FunASR 源码。
大型二进制通过 Git LFS 跟踪。每个文件的 SHA-256 和大小在
`configs/assets/runtime-assets.json` 中记录，不依赖另一份项目目录。

## Ubuntu x86_64

先安装 Python 3.11、Node.js 24 和 Git LFS，再克隆：

```bash
git lfs install
git clone https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
bash tools/assets/setup_clone.sh
```

准备脚本拉取 LFS、校验资产、还原超大权重分片，创建项目内 Python 环境，
安装固定依赖和仓库内 FunASR，安装所需系统库，构建 Startouch 绑定和 XVisio
采集程序。它不启动服务、不连接机械臂，也不发送运动指令。

`python`/`vision-python` 环境用于语音、机器人和 Norfair 视觉服务；
`dummy-python` 独立安装 OpenCV 5 和 NumPy 2，供默认 YuNet 跟随使用。
网页优先选择该环境；命令行运行 Dummy 时使用
`local/runtimes/dummy-python/bin/python`。

默认配置已启用 FACE/BODY 补偿：人脸暂时不可见时，使用与该人脸绑定的
BoT-SORT 人体轨迹。所需 `local/models/vision/yolov8n.pt` 已纳入 Git LFS
和资源清单，不再要求从项目外复制权重。Dummy 准备配置安装现用版本的
Ultralytics 8.4.160、LAP 0.5.12、Torch 2.10.0 和 Torchvision 0.25.0。
MediaPipe 与 Ultralytics 分别要求 contrib/base OpenCV 包，两者固定为
同一 5.0.0.93 构建；不要向该隔离环境额外安装 OpenCV headless 4。
准备资源不会启动人物跟随或连接机械臂，实机跟随仍需从网页明确启动。

如需高精度 Nano/vLLM 后端，用 `bash tools/assets/setup_clone.sh --with-high-asr`。
默认 Medium 和 CPU Paraformer 不要求安装 vLLM。视觉检测需要兼容的 NVIDIA
GPU/驱动；SDK 载荷为 Linux x86_64 版本，不能当作 Windows 或 ARM SDK 使用。

已有环境只需补全资产时：

```bash
bash tools/assets/setup_clone.sh --assets-only
```

仅本地校验并还原分片，无网络或硬件操作：

```bash
python3.11 tools/assets/restore_runtime_assets.py
```

启动前设置本机的 `configs/runtime/manual-control.json` 中的 `WEB_HOST`/`bind`，
并在自己的登录环境配置 LLM 凭据。API 密钥不包含在仓库中。
连接相机和机械臂、准备 CAN 后执行：

```bash
./thirdhand ensure --profile manual-control
```

`ready` 表示服务就绪；机械臂仍需在网页手动连接。历史的
`configs/assets/ubuntu20.manifest.json` 包含旧环境目录哈希，不用于验证当前
交付载荷；使用新的 `runtime-assets.json` 和还原脚本。

## 资产维护

新增/更新资产后应更新清单的大小和 SHA-256，并执行校验与边界审计。
只允许清单内的 `local/` 载荷进入 Git。环境、运行日志、令牌、凭据和原始
标定采集数据继续被忽略。不要把整个旧 `local/runtimes/` 复制进 Git。
