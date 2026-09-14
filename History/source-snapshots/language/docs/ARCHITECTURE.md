# 架构与运行链路

## 1. 浏览器与 9983

浏览器从 9983 加载完整网页、Three.js、URDF 和 STL。网页通过自身 WebSocket 获取机械臂状态、发送现有手动控制消息，并通过 Voice WebSocket 连接 3004。

## 2. 3004 Voice/Language

3004 接收浏览器录音或文字输入。ASR 管理器只允许一个模型驻留：Medium 为默认 CUDA Whisper，Real-time 为 CPU Paraformer，High 为 CUDA Fun-ASR-Nano。录音期间全局禁止切换。

最终文本继续进入当前 `voice_agent.py`。Claude 调用、模型、认证变量和 Base URL 均保持原样。3004生成语言回复与动作候选，但不直接控制硬件。

## 3. 用户确认与外部 3000

动作候选回到9983，由网页向用户展示确认。确认后，9983按照现有安全门控和协议向 `ws://127.0.0.1:3000/ws` 发送请求。3000及其 Startouch/CAN链路不属于本目录。

## 4. TTS

3004使用现有Edge TTS逻辑合成回复。Edge TTS需要网络；临时音频仍按原逻辑生成和清理。

## 5. 不包含的链路

Camera、Lumos、XVision、3001和3100保持当前关闭状态。本次只复制其现有网页代码，不提供视觉运行环境，也不改变视觉实现。
