# 依赖与外部条件

## 已包含

- Python 3.11.15及当前3004所需Python包；
- Node 24.18.0；
- 当前完整 `app/server/node_modules`；
- Whisper Small、Paraformer Streaming和Fun-ASR-Nano；
- FunASR当前源码；
- Three.js、URDF、STL及前端加载器。

精确关键版本见 `config/versions.lock`。这些内容来自本机当前正式安装，不通过网络重建，也不在本次工作中升级或降级。

## 外部系统条件

- Ubuntu x86_64；
- NVIDIA显卡及兼容驱动；
- `setsid`、`ss`、`curl`等Ubuntu基础工具；
- 外部3000机械臂服务；
- Claude所需认证变量由当前登录环境提供；
- Claude和Edge TTS运行时需要网络。

## 明确不依赖

- 旧项目 `.venv`；
- `/home/nieqingcao/miniconda3/envs/voice-bridge`；
- 系统Node；
- Hugging Face或ModelScope模型缓存；
- 9981、3002、3001或3100服务。

## 变更规则

第一交付版以功能稳定为优先，不做激进裁剪。未经单独评审，不运行 `pip install`、`conda install`、模型下载或版本升级命令。
