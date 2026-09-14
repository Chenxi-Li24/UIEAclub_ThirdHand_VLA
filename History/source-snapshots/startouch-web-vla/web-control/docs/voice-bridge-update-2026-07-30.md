# Voice Bridge Update / 语音桥接更新

更新日期 / Date: 2026-07-30

## 本次范围 / Scope

本次更新把已经隔离验证的语音与文字入口、Voice Protocol v1 和 Jetson Voice
Bridge 基线整理进 VLA 仓库。候选动作只能用于网页展示和本地 3D 预览，Bridge
不会执行真实机械臂动作。

This update brings the isolated voice/text UI, Voice Protocol v1, and Jetson
Voice Bridge baseline into the VLA repository. Candidate actions are limited
to display and local 3D preview; the Bridge never executes robot motion.

## Task 1：Jetson ASR GPU 加速 / Jetson ASR GPU Acceleration

状态 / Status: **基线已完成 / Baseline completed**

- 为 Jetson Orin NX 隔离构建了支持 CUDA 13.2、`sm_87` 的
  CTranslate2 4.8.1。
- Whisper small 已使用 `device=cuda` 和 `compute_type=float16`。
- 同一段约 8 秒真实中文音频的 ASR 对照中，GPU 推理约 2.30 秒，CPU
  推理约 8.01 秒，加速约 3.48 倍。该数据是 ASR 对照，不等同于包含
  ClaudeAgent 的端到端总耗时。
- 原始 `voice_agent.py`、系统 Python、CPU 虚拟环境和正式 `3001`
  服务均未修改，可继续回退。

An isolated CUDA-enabled CTranslate2 4.8.1 build was validated on Jetson Orin
NX. Whisper small runs with CUDA/float16. On the same approximately
eight-second Chinese sample, ASR inference took about 2.30 seconds on GPU and
8.01 seconds on CPU, a roughly 3.48x speedup. This is an ASR comparison rather
than end-to-end latency including ClaudeAgent. The original service and CPU
environment remain available for rollback.

尚未包含 / Not included:

- 将 GPU Bridge 替换为正式 `3001` 服务；
- 测试 Whisper `turbo`、`medium` 或 `large-v3`；
- 修改 Jetson 系统 Python 或原始 `voice_agent.py`。

## Task 2：Voice Bridge final-only 基线 / Final-only Baseline

状态 / Status: **当前范围已完成 / Current baseline completed**

- 网页支持麦克风授权、设备选择、输入音量、开始、停止和取消录音。
- 网页支持无需启用麦克风的文字 AI 对话。
- 音频继续以 100 ms PCM S16LE 帧通过 Voice Protocol v1 传输。
- Bridge 在停止录音后只执行一次最终 ASR，并使用能量门控过滤静音。
- 最终文字交给现有 `ClaudeAgent`，网页接收 AI 回复和候选动作。
- GPU Bridge 已在隔离端口 `3002` 验证，正式 `3001` 服务未受影响。
- 连续录音、取消、断线重连、ASR 异常和 Claude 不可用场景已经覆盖。
- Claude 不可用时仍会保留最终 ASR 文字。
- Bridge 不导入或创建 `RobotExecutor`，不连接机器人 `/ws` 控制代理。
- 用户确认候选动作时只更新本地 3D 模型和日志，不执行真实机械臂动作。

The final-only Voice Bridge baseline has been validated on isolated port
`3002`. Voice and text input, final transcription, Claude replies, candidate
intents, cancellation, reconnection, and error handling are covered. The
production `3001` service remains unchanged, and no robot action is executed
by the Bridge.

验证证据 / Validation evidence:

```text
Bridge protocol and safety tests: 28 / 28 PASS
Baseline-only protocol scenarios: 3 / 3 PASS
VLA browser simulation checks: 34 / 34 PASS
Candidate-to-real-control commands: 0
```

当前限制 / Current limitations:

- 当前是 final-only，说话期间不会显示实时 `transcript.partial`。
- Whisper 不是原生流式模型。
- ClaudeAgent 的响应时间会影响 AI 回复和会话完成时间，但不阻止最终转写先返回。
- 当前只保留同一连接内的进程级短期对话历史。

## Future / 后续计划

- 加入 VAD 说话与静音检测。
- 只识别新增音频和少量重叠上下文，避免重复处理全部累计音频。
- 返回带 revision 的 `transcript.partial`，保证内容不倒退、不乱序。
- 用户停止或一句话结束时优先执行最终校正，过期 partial 不得覆盖 final。
- 流式链路稳定后，再比较 Whisper small 与 `turbo`。
- 增加可选的“对话历史记录”功能，将语音和文字会话持久化到本地，并提供
  查看、清空、保留期限和隐私控制。

Future work includes VAD, chunked incremental ASR, stable partial revisions,
final-result priority, model comparison, and optional persistent dialogue
history with retention, deletion, and privacy controls.

## 安全与回退 / Safety and Rollback

- Voice Bridge 只返回文字、AI 回复和候选动作。
- `intent.candidate` 表示 AI 的理解结果，不表示动作已经执行。
- 页面上的本地预览不能证明真实机械臂已经运动。
- 语音“停止”不能替代独立、可触达的实体急停。
- 正式切换前应继续在 `3002` 验收，并保留 CPU 环境和 `3001` 回退路径。
