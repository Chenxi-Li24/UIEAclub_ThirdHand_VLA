# C2i 授权请求超时与相机掉线修复

状态：单文件修复已部署。真实浏览器双路观看、连续 5 分钟后台检查、同步 35 秒撤销失败故障复测，以及清理后重新观看均通过。此前三轮未通过报告原样保留。修复后、双路验收前仍记录过一次偶发超时；长期稳定性与端到端解码隐私时限没有标记通过。

## 定位证据

原发布端采用复用的 mTLS HTTPS 连接，但 `http.client` 将 HTTP 头和短 JSON 正文分别交给 TLS 发送。Wi‑Fi 接口抓到同一次报告的 171 字节头包和约 701–705 字节正文包；两次超时窗口中，完整请求需要重传才到达云端。

在北京时间 11:46:26、11:47:13 的失败窗口，设备等待响应头超过原有 0.6 秒读超时。云端对应请求仍返回 200，业务 upstream 处理约 4 ms；TCP 元数据记录客户端关闭后响应才到达。此证据排除了这两次失败主要由数据库/业务处理阻塞造成的解释，但不能说明所有掉线都只有一个根因。

Nginx 每个保活连接处理 100 次后会关闭连接；这是已观察到的行为。上述两个超时请求分别位于连接的第 66 次和第 6 次，不能简单归因于第 100 次换连。另有一次 `MEDIA_LEASE_EXPIRED` 发生在新 TLS 握手期间，部署后的观察继续覆盖这一类失败；没有修改保活上限或扩大租约。

临时网关日志只记录时间、固定路由、状态、处理耗时、字节数和连接计数，不记录请求体、认证头、证书、Cookie、JWT 或私钥。配置变更先备份，已于 **12:08:18** 校验当前诊断配置与原备份摘要后恢复原配置，Nginx 检查及重载通过；原日志格式文件移入备份目录，诊断数据保留为 root-only 文件。首次元数据采样中，11:38:25 的 RemoteDisconnected 与诊断配置重载对应，单独标为操作导致的断开，不作为自然掉线样本。

## 最小修复

仅修改 `services/edge-agent/src/thirdhand_edge/media_upload.py` 的发送实现。私有 `_CoalescedHTTPSConnection` 继续使用标准库构造 HTTP 报文，把一个有界报告的头和正文缓存后，一次交给原 TLS `send`；最大缓存 32 KiB，异常时不发送半截报文。

保持服务端证书和主机名校验、客户端证书、签名字节、设备/启动/连接上下文、序列号及失败不重试规则。原 **950 ms 签名租约、50 ms 单调检查、0.6 秒读超时、0.2 秒续期间隔** 均不变。相机仍是 view only，未启用 SDK 或真机控制。

该实现没有依赖 Linux 特有的 TCP_CORK，也没有调整主机全局 TCP 参数。标准库的 [HTTPConnection.send 文档](https://docs.python.org/3.11/library/http.client.html#http.client.HTTPConnection.send) 是使用的发送接口；最终效果以现场抓到的单个约 854 字节发送包为准。

## 部署与回退

| 项目 | 记录 |
|---|---|
| 业务版本 | 云端仍为 fecd12218feca574，未更新业务代码 |
| Ubuntu 新源码 | `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-e9c8e33a97903125` |
| manifest SHA-256 | `e9c8e33a97903125809ea107571ab9a4abeb003abc293c36846c09dd3ce4edc4` |
| 文件范围 | 20 个公开源码文件逐项校验；相较旧快照只改变 media_upload.py |
| 部署器 SHA-256 | `94b1461a5651057f2cc34d9d631ce057e5dd061bbf61f3004809cf7db19c2373` |
| 保留旧源码 | source-7a882e8da122266f |
| 单元备份 | `units/publisher.before-coalesced-https.service` |
| 原有服务 | 仅新 camera publisher 切换源码并重启；camera source 与 Robot/Vision/Web 未改动 |
| 临时日志备份 | 云端 `/var/backups/thirdhand/access-C2i-timing-20261031T033825Z` |

部署器核对旧文件摘要、仅一个文件变化、单元仍 PrivateDevices 且无 AF_CAN，再安装单元；失败恢复备份。人工回退也只安装上述 publisher 单元备份并重启它，不影响已有机械臂服务。

## 验证结果与范围

- 真实回环双向 TLS 回归先 RED：每次短报告产生两次 SSL 写入；修复后 GREEN，接收端仍校验客户端证书和报告签名。
- 本地设备代理完整测试 **35/35 通过，7.58 秒**，包括原有取消、坏响应不重试和安全诊断。
- Ubuntu 实际 Python 3.11 验收环境运行 TLS 专项 **5/5 通过，0.58 秒**。
- 部署前稳定配置下 11:42:56–11:47:57 的 5 分钟采样记录两次响应头超时和一次租约过期；未修改网关配置或加入故障规则。
- 部署后 **11:56:19–12:01:20**，300 个 TCP 状态样本，元数据确认单个约 854 字节报告发送，失败列表为空。该窗口没有浏览器观看负载，不能替代双观看和长时容量验收。
- 云端对应前后两个约 5 分钟窗口分别处理 1,034 / 1,159 次授权请求，均无 HTTP 错误；upstream 最大耗时均为 12 ms，P99 为 8 / 4 ms。修复前的 HTTP 200 不能覆盖设备端实际超时结论。摘要保存在 root 备份目录的 request-timing-summary.json。
- 新源码实际部署于 **11:55:37.521**，之后到 **12:08:18.585** 无自然失败记录；约 12 分 41 秒后，恢复诊断配置的 Nginx 重载导致一次预期 RemoteDisconnected 和自动重启。12:08:23 publisher 恢复 active，NRestarts=1；不能称整个维护过程零重启。源适配器仍 PID 28559、NRestarts=0，Robot connected/stateReady/moving 均 false，Vision camera ready。
- 额外尝试完整仓库 `python -m pytest -q`，收集阶段有 9 项错误：缺少 PyYAML / cv2，以及 edge_agent 与 speech_service 的同名 test_runtime 模块冲突。完整仓库未被标记通过；这些错误与已通过的设备代理及 Ubuntu 专项分开记录，未为本次修复更改其他子系统。

原始网络元数据、状态样本与无秘密失败报告保存在 Ubuntu `diagnostics/tcp-timing-20261031T034256Z`、`tcp-timing-20261031T035619Z`；临时数据不加入 Git。

完整仓库收集阻塞的具体项目如下，均未计为通过：

| 项目 | 收集错误 |
|---|---|
| assets/test_dummy_runtime_assets.py、robot_service/test_dummy_simulated_chain.py | 缺少 yaml |
| vision_service/test_geometry_quality.py、test_motion_tracking_unittest.py、test_projection_runtime.py、test_projection_snapshot.py、test_track_recovery_unittest.py | 缺少 yaml |
| vision_service/test_person_follow_vision_pipeline.py | 缺少 cv2 |
| speech_service/test_runtime.py | 与 edge_agent/test_runtime.py 同名模块冲突 |

## 本轮真实浏览器与故障复核（北京时间）

用户确认已登录后，实际页面起初显示 Administrator；使用已有 Switch to Observer 按钮降为 Observer 后继续，无需重新输入认证信息。未读取用户密码、MFA 或会话秘密。两个观看标签使用同一个真实 Observer 会话，不冒充两个不同账号的实际浏览器测试。

**双路稳定窗口：12:44:57–12:49:58，300.018 秒、61 次采样。** 每个样本均有两个观看者、一个未静音的 640×480 视频发布者，业务 API / SFU 进程和重启计数保持一致。Ubuntu 12:45:45–12:49:45 的 49 次独立采样确认 publisher PID 73363 / NRestarts=2 与 source PID 28559 / NRestarts=0 不变，无 camera.unavailable 事件。两个浏览器均实际解码，readyState=4；故障前最后样本播放时间为 617.072 / 616.404 秒，均超过 10 分钟。

资源仅为该窗口的采样值：API 最高 194,011,136 B、SFU 最高 90,791,936 B，MemAvailable 最低 531,412 KiB；不能当作峰值或十人容量结论。

本轮使用与原批准相同的脚本 v2、35 秒独立定时器和唯一规则，未放宽 10 秒同步断言。启动与正常关闭第二个观看端在同一批操作内完成，消除前轮工具往返造成的触发延迟。

| 事件 | 实际时间 |
|---|---|
| 规则就绪 | 12:53:39.656 |
| 第二个浏览器请求 Close camera | 12:53:40.972 |
| 首次记录被拒绝的管理请求 | 12:53:41.201 |
| 记录到发布轨道移除 | 12:53:41.440 |
| Ubuntu 记录 MEDIA_GRANT_UNAVAILABLE / HTTP 503 | 12:53:41.453446，55 ms；此前最近成功约 47–58 ms |
| 记录到规则自动移除 | 12:54:14.767，距规则就绪约 35.111 秒 |
| 原观看者全部移除 | 12:54:15.002 |
| 发布恢复且脚本完成 | 12:54:21.366 |

完整脚本结果 **success=true、rejectionWithinTriggerWindow=true、recovered=true、previousViewersRemoved=true、exactRuleAbsent=true**。Ubuntu 在故障窗口内共记录六次明确的 503，publisher 重启计数由 2 变为 8；这是本次注入导致的预期停播/重新建立发布，不是六次自然超时。source 的重启计数仍为 0。

首次拒绝采样与轨道移除采样相差约 239 ms，只是服务端轨道观测值。decoderPrivacyDeadlineVerified=false 保持原值；没有据此宣称浏览器编码/网络/解码缓存满足严格 950 ms 截止。

独立检查确认规则不存在、定时器 inactive、原 Nginx 配置摘要匹配。重新点击主页面 Watch camera 后，12:56:19 的实际视频为 640×480、readyState=4、播放 82.265 秒；12:59:23 同一画面仍为 readyState=4、播放 275.194 秒；13:03:08 为 490.924 秒，证明恢复后持续解码超过 8 分钟。额外测试标签已关闭，主页面保留供用户复核。

本轮原始结果和汇总：

- root C2i 备份目录 two-observer-stability-1793421897971.json、camera-C2i-review.json。
- root 原 C2g 备份目录 camera-removal-fault.C2i-20261031T045339Z.json；canonical 报告另保留，attempt1 / attempt2 / attempt3 及旧人工判定没有覆盖。
- Ubuntu diagnostics/two-observer-units-20261031T044545Z.json；安全 journal 与实际服务状态单独核对。
- 忽略目录 evidence/C2i-browser-samples.json、故障前和恢复后截图；没有录制视频或提交这些临时数据。

## 仍需保留的限制

修复后 **12:41:50.527515**、本轮观看开始之前仍有一次 601 ms 响应头超时，publisher 因既定失败关闭规则重启。这条记录没有删除，也没有扩大期限来掩盖它。合并发送修复已通过所述对照窗口验证，当前双路窗口与故障恢复通过；仍不能称所有链路波动已经消失。需要更长观察与进一步网络证据来确认这条剩余超时的原因。

当前网页在发布恢复后通过重新点击 Watch camera 取得新授权恢复观看；没有新增浏览器自动重连功能。采集时间仍未校验、sourceFresh=false，只提供观看，不能据此开放公网 SDK。全仓测试收集阻塞、长时/十人容量、不同网络路径、生产证书轮换及 C3 真机控制仍保留在各自验收清单中。

本轮没有 Git commit、push、PR、额外公网端口或 SDK/运动指令。
