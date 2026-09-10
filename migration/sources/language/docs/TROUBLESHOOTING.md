# 故障处理

## 端口被占用

先运行 `scripts/status`。不要按端口盲目结束进程。确认PID、工作目录和启动来源后再决定停止哪个版本。

## Medium无法READY

运行 `scripts/verify-models` 和 `scripts/verify-runtime`，检查 `logs/voice-3004.log`。不要自动下载模型或升级CTranslate2。

## High显存占用未释放

检查3004所属完整进程组，包括其vLLM子进程。只停止本目录PID文件和工作目录能够验证的进程组，不影响其他GPU任务。

## Claude不可用

保持 `voice_agent.py`、模型、Base URL及认证方式不变。先确认启动3004的登录环境仍继承认证变量；不要显示密钥值，不修改CC-Switch或共享配置。

## 3D模型缺失

检查 `app/web/models/startouch-v3/` 中URDF和STL、`app/web/js/lib/` 中Three.js及加载器。浏览器控制台不应出现404。

## 网页有状态但机械臂不能动

确认外部3000正在运行且来源正确，再检查状态是否新鲜、是否IDLE以及正式配置中的真实控制开关。临时9984配置本来就禁止真实运动。

## 视觉不可用

这是当前预期状态。视觉、Lumos和XVision不在本交付范围，不要为解决该问题改动Language目录。
