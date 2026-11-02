# SDK 浏览器心跳固定部署审阅

状态：材料就绪，尚未上传或应用。源码40d2dacb7067c294885c706161188bf63181e102的[CI 41402908893](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA/actions/runs/41402908893)两个job均success；本地400项业务回归及9项包构建/漂移拒绝测试通过。

用户本轮已允许放宽超时、不发送运动。本候选具体实现是观察模式3000ms，管理员运动模式500ms不变；设备签名/本地1秒租约和1500ms ACK保持。行为、边界与已知限制见[修复记录](2026-11-02-sdk-browser-heartbeat-fix.md)。本次只验收授权，不点击Connect SDK，不执行电机使能/闭爪初始化或后续运动。

## 固定包与运行范围

本地：`.superpowers/sdd/2026-11-01-sdk-source-audit/browser-heartbeat-candidate/sdk-browser-heartbeat-candidate.json.gz`，729667字节。
SHA256：`bf075e0e721df06b1a0fa7fd519792c7cfeea44c4f27569b18f2393923b0a45d`。
构建器：`tools/deploy/build_sdk_browser_heartbeat_candidate.py`；只读取固定Git提交及实际基线，保留其他任务改动，不直接部署。

| 目标 | 文件 | 新SHA256 |
|---|---|---|
| 云端 | apps/web/public/js/admin-control.js | 3bde9d7123236a71ff7414f8a33a7776ce1db6944dc96eebe6b13ee4425cdfb8 |
| 云端 | services/cloud-api/src/control/control-channel.js | 9b00ad327f41c079cee2a241a3513e1a4af4de9326d5f3b36e9ab23f19ca7dde |
| 云端 | services/cloud-api/src/control/websocket.js | 6817103e090e135965477257102d6342097c7bd20bc059e6807f1023dbf0bfff |
| 云端 | services/cloud-api/src/control/leases.js | f2f3739c731f26c6927251ba4a12602c0f8c1c7f9dab9c19b3a8a62b62e1faf2 |
| 云端 | services/cloud-api/src/server.js | e35e1fb8c7b684d3f681abbfc68af1cbbbdf9c33276718dc4930eb4ad8bc23db |
| Ubuntu | services/robot/src/startouch-bridge.js | 3b33ca623e8e529f6a8a32fc35da65b901b77efb5f6392e6ee87dc77067916e7 |

云端现发布`/opt/thirdhand-stage/releases/d5284b8679ff90e8`，manifestSHA256=`d5284b8679ff90e88f0c2138e8b31c9eb53f6197ddef09eb2982300943fc97b7`；新发布`/opt/thirdhand-stage/releases/a3ca345673912070`，manifestSHA256=`a3ca345673912070924dc28d5141c1b0c7e5f736efcaaee7edc6aaf5085a38ad`。4658件中只变5件，保留4653件；不改展示站、环境秘密、数据库、账户、证书、Nginx或端口。

Ubuntu原37件快照`/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-sdk-clock-26c8339436ca6daa`，派生`robot-sdk-browser-heartbeat-f72bba77f012ba0c`，只变上述1件。24件edge快照`agent-sdk-clock-a963153d56dac68d`不改。所有源文件及旧unit/drop-in摘要在包内固定；不得用仓库整体覆盖现场。

唯一新增配置：`/home/nieqingcao/.config/systemd/user/thirdhand-tcp-calibration-robot.service.d/zzzzzz-sdk-browser-heartbeat.conf`，SHA256=`661936e14846505dab7e3275e6d80c7972240f7f9697e48e5070efae575c8366`：

```ini
[Service]
ExecStart=
ExecStart=/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node /home/nieqingcao/.local/share/thirdhand-stage-device/20261031/robot-sdk-browser-heartbeat-f72bba77f012ba0c/services/robot/src/server.js
```

## 应用、备份与回退

1. 获批后上传上述单一固定包到云端`/var/backups/thirdhand/access-sdk-browser-heartbeat-20261102/`及Ubuntu`/home/nieqingcao/.local/share/thirdhand-stage-device/SDK-browser-heartbeat-20261102/`。目录0700，包0600。包只有源码、摘要与公开服务路径，没有密码/令牌/数据库数据。
2. 复核云端current、4658件全量摘要、保护的业务配置/展示站摘要、现有业务unit；活动租约和在途命令均0。Ubuntu须可达，SDK=false、readOnly=true、两服务active、无pending daemon reload，有效入口和全量24/37件摘要与包一致。漂移即停止，不扩大范围。
3. 使用既有经摘要核验的installation_lock和quiescent_lease_admission协调零租约切换；准入阻断最多240秒。先备份原current、所有源清单和unit摘要到两个目录的before-public记录，旧源码和配置保留。
4. 云端复制旧发布生成新目录，只替换5件和manifest，验证完整清单；等待Ubuntu切换。Ubuntu先停止edge代理，再停止Robot，创建上述唯一drop-in，daemon-reload、启动Robot并确认SDK仍断开后恢复edge。只重启这两个已有用户服务；采集/相机可能短暂重连。
5. Ubuntu成功后云端再次核对保护摘要和准入，原子切换current，仅重启thirdhand-stage.service。核对healthz、源摘要、SDK断开及只读状态，保存applied-public记录。总计3个既有服务重启，无新服务/永久网络设置。
6. 已准备只执行本文动作的人工操作脚本，通过宝塔终端/SSH标准输入执行，不上传额外程序。云端本地`browser-heartbeat-cloud-operator.py` SHA256=`1a8c08d216035a5c8cac1aa43e2364ea8ee475abaf1c980e8a625403a8b166d9`；Ubuntu本地`browser-heartbeat-edge-operator.py` SHA256=`31231c7b7a1874ee91c9165137b3d7ac5c9b8d84437a4893523a147037bbad0a`，位于上述`.superpowers/sdd/2026-11-01-sdk-source-audit/`。设备脚本默认仅预检，显式HEARTBEAT_APPLY=1才应用。脚本先校验固定包SHA与固定范围，不执行包提供的任意命令。
7. 失败回退：在零租约且SDK断开条件下，停止edge/Robot，仅在新增drop-in摘要仍匹配时移除该一件，daemon-reload并恢复原Robot及edge服务。云端current恢复d5284b8679ff90e8并重启业务API。验证原全量清单、设备绑定、SDK断开和readOnly。保留快照/备份/数据库；若其他任务改变发布或配置，不强行覆盖。

## 真实验收

Observer前台设备页显式申请授权，最多3次尝试；单次成功持续10分钟，再通过页面关闭通道释放。预先启动有界只读后台观察，记录开始/结束时刻、连续active状态与续约序号、拒绝原因及SDK断开；避免为了看日志切换浏览器标签导致visibilitychange主动释放。采样只输出状态/计数/时间，不记录账号、cookie、nonce或签名。

验收指标：持续不少于600秒、同一授权连续有效且序号递增；期间没有初始化/运动命令，SDK=false；结束后释放/撤销，不自动重新授权。任何中途失效都记为不通过并保留错误码，不用反复自动重试掩盖问题。观察模式的后台3秒容忍不适用于管理员运动控制。真实设备授权与模拟测试、真实SDK连接读取分别标注。

本轮只读预检已确认：云端current完整摘要通过、活动租约/在途命令0；Ubuntu初始SSH两次超时，现场确认开机联网后TSMP探测268ms、SSH恢复，实际路径/服务符合基线，SDK=false、readOnly=true、recordingHealthy=true、videoHealthy=false。没有变更网络。应用前重复这些准入条件。

需确认的是上述新固定包上传/应用、1件新增入口配置、3个服务重启及有界授权验收。依据用户已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步：“固定源码/资源清单、数据库变更和回退材料完成后才申请实际部署。”用户允许放宽超时不表示上一时钟固定包自动包含本次新增源码。
