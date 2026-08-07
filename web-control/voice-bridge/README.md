# Jetson Voice Bridge

`voice_bridge.py` 是网页与 Jetson 现有语音程序之间的薄桥接层。它只导入
`voice_agent.py` 中的 `WhisperASR` 和 `ClaudeAgent`：

```text
网页麦克风
  → PCM S16LE / WebSocket 3001
  → voice_bridge.py
  → WhisperASR.transcribe()
  → ClaudeAgent.chat()
  → 转写文字、AI 文字回复、候选动作
  → 网页

网页文字输入
  → text.submit / WebSocket 3001
  → voice_bridge.py
  → ClaudeAgent.chat()（不调用 ASR）
  → AI 文字回复、候选动作
  → 网页
```

它不会导入或创建 `RobotExecutor`，不会启动 `VoiceAgent.run()`，也不会采集
Jetson 本地麦克风、播放 TTS 或连接 Node.js 机器人控制代理。候选动作只代表
Claude 的理解结果，不代表机械臂已经执行。

## 部署到 Jetson

Bridge 的仓库源文件位于：

```text
web-control/voice-bridge/
```

把 `voice_bridge.py` 和 `requirements-voice-bridge.txt` 复制到 Jetson 的现有
项目目录，并与 `voice_agent.py` 放在同一级。从仓库根目录的 Windows
PowerShell 可以执行：

```powershell
scp ".\web-control\voice-bridge\voice_bridge.py" <JETSON_USER>@<JETSON_IP>:~/d435-yolo-project/
scp ".\web-control\voice-bridge\requirements-voice-bridge.txt" <JETSON_USER>@<JETSON_IP>:~/d435-yolo-project/
```

然后在 Jetson 上创建一个能够复用现有语音依赖的虚拟环境。不要使用
`--break-system-packages`：

```bash
cd ~/d435-yolo-project
python3 -m venv --system-site-packages .venv-voice-bridge
.venv-voice-bridge/bin/python -m pip install -r requirements-voice-bridge.txt
.venv-voice-bridge/bin/python voice_bridge.py --host 0.0.0.0 --port 3001
```

服务地址：

```text
ws://<JETSON_IP>:3001/v1/voice
WebSocket subprotocol: thirdhand.voice.v1
```

如果暂时只想验证 ASR、不调用 Claude/CC-Switch：

```bash
.venv-voice-bridge/bin/python voice_bridge.py --host 0.0.0.0 --port 3001 --no-llm
```

`--no-llm` 模式只能验证语音转写；文字输入会返回 `LLM_UNAVAILABLE`。

当前版本采用 final-only 策略，`--partial-interval` 必须为 `0`。这样每次录音只在
停止后调用一次 Whisper，最终识别不会等待已经过期的 partial 推理。建议先用备用
端口 `3002` 验证，再决定是否替换正在运行的 `3001` 服务：

```bash
.venv-voice-bridge/bin/python voice_bridge.py \
  --host 0.0.0.0 \
  --port 3002 \
  --partial-interval 0
```

静音门控默认要求至少 60 ms 连续有效语音，裁剪首尾静音时各保留 150 ms。真实
麦克风校准时可以调整：

```text
--silence-rms-threshold 0.003
--min-voiced-ms 60
--trim-padding-ms 150
```

提高 `--silence-rms-threshold` 会过滤更多背景噪声，但过高可能漏掉轻声或远场
说话。服务端 INFO 日志会分别输出 `asr_timing`、`llm_timing` 和
`session_timing`，用于比较排队、推理和总响应时间。

## 运行前检查

```bash
.venv-voice-bridge/bin/python -c "import numpy, websockets; from voice_agent import WhisperASR, ClaudeAgent; print('dependencies OK')"
ss -ltnp | grep ':3001'
```

`3001/tcp` 必须没有被其他 TCP 服务占用。已有的 `3001/udp` 可以同时存在，
因为 TCP 和 UDP 是不同的传输协议。

网页当前默认连接 `ws://192.168.58.43:3001/v1/voice`。如果 Jetson IP
或测试端口发生变化，可直接在网页的“本地 AI WebSocket 地址”输入框修改并
点击“重连”。

## 会话行为

- 每条 WebSocket 连接最多一个正在处理的语音或文字会话。
- 文字通过 `text.submit` 直接进入同一连接的 `ClaudeAgent`，最多 2000 个字符，
  与语音共享该连接的进程内短期对话历史。
- 文字请求不会调用 Whisper ASR；不同连接的 Claude 历史相互隔离。
- 音频必须是 `THV1` 二进制帧：16 kHz、单声道、PCM S16LE、100 ms/帧。
- 当前 Bridge 不发送 `transcript.partial`，停止录音后只执行一次 final ASR。
- 纯静音不会进入 Whisper 或 Claude；有语音时只裁首尾静音，内部停顿会保留。
- 停止录音后返回 `transcript.final`；Claude 可用时再返回
  `assistant.response` 和零个或多个 `intent.candidate`。
- Claude/CC-Switch 不可用不会丢失最终 ASR 文字；Bridge 会单独返回
  `LLM_UNAVAILABLE` 错误，然后完成会话。
- 单次录音上限为 30 秒；取消或断线会清空音频并取消该会话的后台任务。

完整协议见上一级目录的 `docs/voice-protocol-v1.md`。

## 测试

测试使用假的 ASR 和 Claude 实现，不加载模型，也不连接机器人控制软件：

```bash
cd web-control/voice-bridge
python3 -m unittest -v test_voice_bridge.py
```

当前 final-only GPU 基线的验收结果、回退边界和 Future Plan 见
[`../docs/voice-bridge-update-2026-07-30.md`](../docs/voice-bridge-update-2026-07-30.md)。
