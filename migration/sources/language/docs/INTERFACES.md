# 端口与接口边界

| 端口 | 所有者 | 用途 | 交付包是否包含 |
|---|---|---|---|
| 9983 | `app/server` | 正式网页和浏览器WebSocket | 是 |
| 3004 | `voice/voice_bridge.py` | 正式Voice/Language WebSocket | 是 |
| 9984 | `app/server` | 临时无运动验收网页 | 是，仅测试时启动 |
| 3005 | `voice/voice_bridge.py` | 临时无运动Voice服务 | 是，仅测试时启动 |
| 3000 | 外部正式控制服务 | 机械臂状态与控制 | 否 |
| 3001/3100 | 外部视觉链路 | 当前暂缓 | 否 |

正式配置位于 `config/runtime.env`；临时无运动配置位于 `config/runtime.staging.env`。

3004使用 `thirdhand.voice.v1` WebSocket子协议。3004只产生候选；真实控制仍由9983确认层转发到3000。不要让3004直接拥有SDK、CAN或机械臂执行权。
