# ASR 模型说明

| 模型ID | 页面名称 | 后端 | 设备 | 模式 |
|---|---|---|---|---|
| `whisper-small` | Medium | faster-whisper/CTranslate2 | CUDA | 非流式，默认 |
| `paraformer-streaming` | Real-time | FunASR Paraformer | CPU | 中文流式 |
| `fun-asr-nano` | High | FunASR-Nano/vLLM | CUDA | 非流式，实验 |

## 选择规则

- 每次3004启动都加载Medium。
- 任意客户端录音期间，模型按钮不可切换。
- 切换顺序为卸载当前模型，再加载目标模型。
- 失败时按照现有逻辑恢复先前模型或默认Medium。
- 不自动把Paraformer改到GPU。
- 不使用模型缓存下载缺失权重；缺失时预检直接报错。

## 验收范围

每个模型只使用同一段短音频确认可以输出文字；这不是准确率评测，不计算CER/WER，也不据此排名。
