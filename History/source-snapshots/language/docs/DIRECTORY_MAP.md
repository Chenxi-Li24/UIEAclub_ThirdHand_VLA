# 目录与责任说明

| 路径 | 内容 | 主要责任 |
|---|---|---|
| `app/web/` | 完整9983网页、三维模型和前端交互 | Web/Language协作 |
| `app/server/` | 9983 Node服务、状态及3000转发 | Web/Integration |
| `voice/` | 3004、ASR后端、Claude与TTS | Language |
| `models/whisper-small/` | Medium模型 | Language |
| `models/paraformer-streaming/` | Real-time模型 | Language |
| `models/fun-asr-nano/` | High模型 | Language |
| `FunASR/` | 当前3004直接使用的FunASR源码 | Language |
| `runtime/python/` | 唯一活动Python运行环境 | Delivery维护 |
| `runtime/node/` | 9983专用Node运行时 | Delivery维护 |
| `config/` | 正式、示例和临时无运动配置 | Integration |
| `scripts/` | 预检、启停、状态和验证入口 | Operations |
| `tests/`、`app/server/test/`、`voice/test_*` | 自动化测试 | 各模块负责人 |
| `logs/` | 当前交付版运行日志和PID | Operations |
| `docs/` | 协作文档 | 全体协作者 |

不要让新代码跨目录引用旧工程。若增加新依赖，先更新 `config/versions.lock`、测试和本文档。
