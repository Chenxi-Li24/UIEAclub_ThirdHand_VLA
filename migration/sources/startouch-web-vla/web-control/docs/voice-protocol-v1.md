# ThirdHand Voice Protocol v1

## 1. 目的

本协议是控制网页与未来 Jetson 本地 AI 服务之间的通信合同。Jetson 负责语音转文字和候选动作识别；网页负责展示、白名单校验和用户确认。

Jetson 不得直接连接机器人控制端口，也不得返回可原样透传的机械臂命令。

## 2. 连接

| 项目 | v1 规定 |
| --- | --- |
| 传输 | TCP WebSocket |
| 开发地址 | `ws://127.0.0.1:3001/v1/voice` |
| 当前 Jetson 地址 | `ws://192.168.58.43:3001/v1/voice` |
| WebSocket 子协议 | `thirdhand.voice.v1` |
| 并发 | 每条连接最多一个正在处理的语音或文字会话 |

现有机器人代理使用 UDP 3001。TCP 3001 与 UDP 3001 可以同时存在，但配置和文档必须明确写出传输类型。

页面升级为 HTTPS 后，语音服务必须升级为 `wss://`。

## 3. JSON envelope

所有非音频消息均为 UTF-8 JSON：

```json
{
  "v": 1,
  "type": "session.start",
  "messageId": "uuid",
  "replyTo": null,
  "sessionId": "uuid",
  "ts": 1785168000000,
  "payload": {}
}
```

`v`、`type`、`messageId`、`sessionId`、`ts` 和 `payload` 必填。由同一请求产生的状态、
回复、候选动作、错误和完成事件都使用该请求的 `messageId` 作为 `replyTo`。

## 4. 音频

- 编码：PCM signed 16-bit little-endian
- 采样率：16000 Hz
- 声道：单声道
- 帧长：100 ms
- PCM 载荷：每帧3200字节

二进制 WebSocket 帧结构：

| 字节 | 内容 |
| --- | --- |
| 0–3 | ASCII `THV1` |
| 4–7 | `sequence`，uint32 little-endian |
| 8–11 | 会话内 `elapsedMs`，uint32 little-endian |
| 12–3211 | 3200字节 PCM S16LE |

WebSocket 保证顺序；`sequence` 用于诊断客户端采集或发送逻辑中的丢帧。

## 5. 正常事件顺序

语音输入：

```text
session.start
→ session.ready
→ binary audio frames
→ transcript.partial (0..n)
→ session.stop
→ session.processing
→ transcript.final
→ assistant.response
→ intent.candidate
→ session.completed
```

文字输入：

```text
text.submit
→ session.processing
→ assistant.response
→ intent.candidate (0..n)
→ session.completed
```

`text.submit`：

```json
{
  "v": 1,
  "type": "text.submit",
  "messageId": "uuid",
  "replyTo": null,
  "sessionId": "uuid",
  "ts": 1785168000000,
  "payload": {
    "text": "回到初始位置"
  }
}
```

`payload.text` 去除首尾空白后必须为 1–2000 个字符。文字输入直接进入同一连接的
`ClaudeAgent.chat()`，不调用 Whisper ASR。服务端在处理期间必须拒绝该连接的
第二个文字请求或新录音会话。

取消路径为 `session.cancel → session.cancelled`。取消或断线后，服务端必须清空
该连接的音频缓冲或文字任务，并且不得再返回该会话的识别或理解结果。

`transcript.partial`：

```json
{
  "segmentId": "segment-1",
  "revision": 2,
  "text": "打开夹"
}
```

同一 `segmentId` 只保留最高 `revision`，不得把每次 partial 直接追加。
当前 final-only 基线不会发送 partial；该消息保留给后续 VAD 和分段增量 ASR。

`assistant.response`：

```json
{
  "text": "好的，我已理解你的指令。"
}
```

该消息只用于在网页显示 AI 的文字回复。V1 不通过此消息播放 TTS，也不触发机器人动作。

`intent.candidate`：

```json
{
  "candidateId": "uuid",
  "intent": "gripper.open",
  "tool": "release",
  "sourceText": "打开夹爪",
  "requiresConfirmation": true,
  "args": {}
}
```

`tool` 是 `ClaudeAgent` 返回的原始工具名，用于诊断；`intent` 是给网页展示和
白名单校验的候选名称。Bridge 不执行该工具。

v1 网页可确认的候选动作白名单：

- `robot.estop`
- `robot.status`
- `robot.preset`
- `gripper.open`
- `gripper.close`
- `gripper.grip`
- `gripper.set_position`

Bridge 可以把 `move_to` 映射为仅供理解结果展示的 `robot.move_to`，但它不在
网页白名单内，因此确认按钮必须保持禁用。禁止 `servo_raw`、任意关节角度、
复位、网络配置和外骨骼控制。

## 6. 状态、心跳与限制

客户端状态：

```text
offline → connecting → idle → starting → recording
                                      ↓
completed ← awaiting_confirmation ← processing

idle → processing_text → awaiting_confirmation / completed
```

- 单次录音最长 30 秒；
- 单条文字输入最长 2000 个字符；
- 单条 WebSocket 消息上限为 16 KiB；二进制音频帧仍必须严格等于 3212 字节；
- 同一连接的语音与文字请求互斥，但正常完成后共同复用该连接的短期对话历史；
- 客户端每 15 秒发送一次 `ping`；
- 连续两次未收到 `pong`，关闭连接并进入 `offline`；
- WebSocket `bufferedAmount` 超过 1 MiB 时停止录音，不得静默丢音频；
- 断线后创建新会话，不补发旧音频。

## 7. 错误

错误消息的 `payload`：

```json
{
  "code": "UNSUPPORTED_AUDIO",
  "message": "Use PCM S16LE, 16 kHz, mono, 100 ms frames.",
  "recoverable": false
}
```

标准错误码：

- `UNSUPPORTED_VERSION`
- `UNSUPPORTED_AUDIO`
- `INVALID_STATE`
- `BAD_MESSAGE`
- `BAD_AUDIO_FRAME`
- `AUDIO_SEQUENCE_GAP`
- `TEXT_TOO_LONG`
- `RECORDING_LIMIT`
- `ASR_FAILED`
- `LLM_UNAVAILABLE`
- `AI_UNAVAILABLE`
- `TIMEOUT`
- `OVERLOAD`
- `ORIGIN_FORBIDDEN`
- `INTERNAL`

## 8. 安全边界

- Voice AI 只能返回文字回复和候选动作；文字输入同样不能触发执行。
- Bridge 只调用 `WhisperASR` 和 `ClaudeAgent`，不得创建 `RobotExecutor`，
  不得连接 Node.js 机器人控制代理。
- 网页必须对白名单和参数范围进行验证。
- 所有候选动作（包括 `robot.estop`）都必须由用户确认。
- v1 原型确认后只更新本地 3D 预览和日志，不得调用现有 `/ws`。
- 语音急停不能代替实体急停或页面急停。
