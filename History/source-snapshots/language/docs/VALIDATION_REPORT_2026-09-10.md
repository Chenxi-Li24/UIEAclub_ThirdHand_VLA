# Thirdhand_language 最终验收报告（2026-09-10）

## 最终结论

`/home/nieqingcao/Thirdhand_language` 已完成本机资源整合、隔离联调、正式端口切换和人工验收。当前由该目录正式提供 9983 网页与 3004 Voice/Language 服务；外部 3000 继续提供 Startouch SDK、CAN 和机械臂控制。

旧目录 `/home/nieqingcao/TH_new_asr_0820`、旧 Python 环境和旧模型均未删除，仅作为回滚备份保留。

## 自动验证结果

- `scripts/verify-runtime`：独立 Python、Node、CUDA 和必要模块通过；
- `scripts/verify-models`：Whisper Small、Paraformer Streaming、Fun-ASR-Nano 文件完整；
- Python 单元测试：Voice/ASR 70 项、交付脚本与工具 21 项，共 91 项通过；
- Node 相关测试：三模型前端、运行策略、协议、手动控制、方向控制和 Language 上游测试通过；
- 9983 页面与 URDF 资源返回 HTTP 200；
- Medium / Whisper Small：CUDA，产生非空转写；
- Real-time / Paraformer：CPU，产生中文流式转写和 partial；
- High / Fun-ASR-Nano：CUDA，产生非空转写；
- 模型切换前卸载旧模型；切回 Medium 后没有遗留 Fun-ASR-Nano 的 vLLM GPU 子进程；
- 录音会话期间切换模型返回 `MODEL_BUSY`，取消录音后可以正常切换；
- Claude 保持原有代码与环境继承方式，普通文本请求返回真实 `assistant.response`；
- 安全测试未生成候选动作、确认或机械臂运动请求；
- 66,216 个稳定文件已写入 `MANIFEST.sha256` 并全量回验通过。

## 正式切换结果

- 旧 9983/3004 已停止；
- 新 9983 进程工作目录为 `Thirdhand_language/app/server`；
- 新 3004 进程工作目录为 `Thirdhand_language/voice`；
- 新 3004 使用 `Thirdhand_language/runtime/python` 和本目录三个模型；
- 新 9983 使用 `Thirdhand_language/runtime/node`；
- 默认模型为 Medium / Whisper Small / CUDA；
- 3000 保持独立运行，新 9983 通过 `ws://127.0.0.1:3000/ws` 使用正式机械臂服务；
- 正式切换过程中没有发送机械臂运动命令。

## 人工验收结果

负责人已在新 9983 页面完成并确认以下项目全部正常：

- 完整网页与机械臂三维模型；
- `SDK: OK / IDLE` 与实时关节反馈；
- 机械臂实际运动；
- Medium、Real-time、High 三个 ASR 模型；
- 录音期间禁止模型切换；
- Claude 文字与语音交互；
- TTS 播放；
- 候选动作、人工确认、`COMMAND_COMPLETE` 与新鲜 `ROBOT_STATE` 双重验证；
- Home 动作，六轴最大误差约 0.49°。

## 已知暂缓项

D435 未检测到设备，独立 3100 XVisio 后端当前未运行。3000 保持原视觉代理配置，但视觉功能不属于本次 Language 交付验收条件。

## 日常启动

```bash
cd /home/nieqingcao/Thirdhand_language
scripts/preflight
scripts/start
scripts/status
```

停止：

```bash
cd /home/nieqingcao/Thirdhand_language
scripts/stop
```

Claude 继续继承当前 Ubuntu 交互式登录环境。不要改动 Claude 调用、共享认证、CC-Switch 或外部 3000。

## 回滚边界

旧工程仅作为备份。若未来需要回滚，必须先停止新目录的 9983/3004，确认端口释放，再按旧目录原启动方式恢复。未获得单独清理授权前，不删除旧工程、旧环境或旧模型。
