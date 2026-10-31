# C2g 相机接入实际记录（2026-10-31）

状态：staging 的受保护视频已部署并显示真实画面；两角色鉴权、双观看、正常退出后清除已验证。C2g 初始三轮故障记录未通过，原样保留；后续 C2i 已通过同步 35 秒故障复测、5 分钟双路监测及恢复后观看。仍有一次修复后偶发超时记录，长时稳定性未通过。公网 SDK 控制仍关闭。

## 已部署范围

用户批准了 [C2g 具体配置](2026-10-31-C2g-camera-deployment-review.md)，包括 TCP 7881、UDP 7882；未批准真机运动、展示站改动或资源购买。

| 项目 | 实际配置 |
|---|---|
| 视频页 | `https://staging.uiea-thirdhand.com/control#vision`；选择相机后点击 Load cameras / Watch camera |
| 业务版本 | `/opt/thirdhand-stage/releases/cf0013639f4a681d`，完整 4,613 文件校验通过 |
| 业务归档 SHA-256 | `cf0013639f4a681d53ebf2ce6dcffb1c9ee33df0b2bfde1f1943343a27ce2ae1` |
| 业务 manifest SHA-256 | `4c9ff6ab5b4d051ef7746a84ad19a6aae3d2cb59f24469d086d362a0b42802f3` |
| 媒体服务 | 固定官方 LiveKit 1.13.11；独立 thirdhand-media 身份，API 仅 127.0.0.1:7880 |
| 用户信令 | staging HTTPS `/media/rtc`、`/media/rtc/v1` 及各自 validate；经过业务会话鉴权 |
| 设备入口 | edge HTTPS 严格 mTLS；相机签名绑定当前设备、启动、连接及证书上下文 |
| Ubuntu 相机源码 | 后续 C2i 当前为 `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-e9c8e33a97903125`，20 文件逐项校验通过；旧 7a / f0 快照保留 |
| Ubuntu manifest SHA-256 | `e9c8e33a97903125809ea107571ab9a4abeb003abc293c36846c09dd3ce4edc4` |
| 独立单元 | thirdhand-stage-camera-source / thirdhand-stage-camera-publisher；只读取已有 Vision HTTP 流，不另开硬件采集 |
| 视频规格 | 实际 VP8，640×480；配置上限 800 kbps、15 fps，最多两个观看会话 |
| 相机能力 | camera=true、remoteControlEnabled=false；未登记控制执行实例，未组合 controlService |
| 数据库 | PostgreSQL 17，现有私有 Unix socket；未新增公网数据库端口或运行账户写登记表权限 |

设备 UUID `006e0cac-cf10-427e-a84c-42c260b3ac4e`，credential UUID `550b647b-1529-4776-8bd1-28f6c2795c26`。独立设备私钥始终留在 Ubuntu；临时 clientAuth 证书到期时间为 **2026-11-14 02:38:59 北京时间**。此 staging 身份不能直接作为生产长期身份使用。

后续 [C2h](2026-10-31-C2h-workspace-startup.md) 只修复一个前端启动文件，当前业务版本已为 `fecd12218feca574`；上述 cf0013639f4a681d 保留为 C2g 初始部署及回退版本。媒体/身份策略未变。

## 排障与验证

1. SFU 最初因沙箱不允许 AF_NETLINK 而启动失败。补充本地路由发现所需地址族，继续保持无 capabilities、NoNewPrivileges 和独立身份；未增加其他公网端口。历史启动失败的 NRestarts=35 保留，不称为“从未重启”。
2. 原生 RTC SDK 使用 Authorization Bearer，原信令门禁只支持浏览器查询令牌，实际连接被拒绝 403。修复只允许具有当前相机上下文的机器发布令牌走该路径；浏览器观看令牌仍需同源 Origin 与用户 Cookie，不能借用 Bearer 绕过会话。HTTP 定向测试先失败后通过。
3. 视频能够显示后观察到发布端自动重启，安全诊断仅记录异常类型和允许列出的错误码，观察到 MEDIA_LEASE_EXPIRED / MEDIA_GRANT_UNAVAILABLE。原客户端每次签名后重新建立 TLS，网络抖动可能耗尽短租约。改为复用经验证的 mTLS 连接，冷连接完成后才给报告签名，取消时关闭在途连接，异常不重试签名报告。**950 ms 租约、50 ms 独立检查与 0.6 秒请求读超时未放宽**。

设备代理完整 Python 回归 **33/33 通过**，包含连接复用、签名时序、失败无重放和取消关闭。相机业务 Node 回归 **131/131 通过、0 跳过**；后续连接修复只涉及 Python 发布端，未更改云端 Node 版本。

| 实际验收 | 结果与边界 |
|---|---|
| 本机 SDK 通信 | [C3 预检](2026-10-31-C3-device-camera-preflight.md) 记录 24 条六关节状态、连接/读取/断开通过；运动命令 0 条 |
| 管理员真实浏览器 | 当前实际账号已登录；相机视频真实显示、videoWidth=640、videoHeight=480、readyState=4，播放时间持续递增 |
| 两个真实浏览器观看端 | 同一管理员会话的两个标签均显示画面；03:35:04 云端确认一个发布者与两个订阅者。不是两种角色各自的浏览器验收 |
| 两角色真实 HTTPS 鉴权 | 独立 synthetic Observer / Administrator 账号均取得观看授权并通过信令验证；令牌只可订阅，不可发布、发送数据或管理房间 |
| SDK 权限 | Observer 调用 SDK connect 返回 403；Administrator 返回 503（当前未部署控制服务）；没有真正连接 SDK |
| 会话与上限 | 无 Cookie、错误 Origin、观看者 Bearer 均 403；第三观看授权 429；synthetic 退出后旧令牌重新建连 403 |
| 真实已连接观看者退出 | 03:40:25～03:40:33 只读监测窗口内，实际账号正常退出，两个原 SFU 订阅者均被清除，发布者保留；网页回到登录页。窗口包含点击前等待，不将 7,845 ms 误称为退出延迟 |
| 采集时间 | 未知，sourceFresh=false，界面显示 Video timing unavailable · view only；不能用于远控画面就绪判断 |
| 短时稳定性 | 03:28:05 部署修复后，03:42:55 仍为 PID 33827、NRestarts=0；源适配器 PID 28559、NRestarts=0。约 14 分 50 秒采样窗口，不能替代长时验收 |
| 最终现场状态 | 03:42:55 Robot connected=false、stateReady=false、moving=false；Vision 相机和推理 ready、源序号 31,321；本轮 SDK 指令 0 条 |
| 云资源采样 | 03:35:04 双观看时 API 139,063,296 B、SFU 55,173,120 B，MemAvailable 574,172 KiB；这是采样值，不是峰值或十人容量结论 |
| 出站流量采样 | 03:38:28，10,010 ms 内主机非回环接口总出站 2,218,535 B，约 1.773 Mbps；包含运维流量，非单独视频码率或长时峰值 |
| 主展示站 | index SHA-256 仍为 `639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd`；未修改展示站 |

云端原始审计保存在下述 root-only 备份目录：camera-auth-acceptance.json、two-viewers-resource-audit.json、live-resource-audit.json、two-viewers-bandwidth-sample.json、connected-viewer-logout.json。它们不输出密码、用户会话 Cookie、MFA seed、JWT 或私钥。管理员直播截图保存在本任务忽略目录 evidence/C2g-admin-live-stable.png，不打包进 Git。正常退出验收后用户需要自行重新登录；密码/验证码由用户输入。

## 故障测试授权与执行范围

自动审批最初拒绝主动添加 iptables 规则的网络故障模拟，理由是原相机部署/观看授权没有明确覆盖这项具体中断。03:35:04 只读确认当时测试规则及测试报告均不存在。

随后用户明确回复“批准这项 35 秒相机故障测试”。[C2h 登录加载修复](2026-10-31-C2h-workspace-startup.md) 后，用户已自行以 Observer 登录，建立同一观察员会话的两个真实观看端。原脚本 SHA-256 `e24b68ef7a6390489ef2ad07eb1a2d66c2b526161e789f8e40b4c4dd4c6a63fc`；后续 v2 增加实际规则就绪输出和 10 秒操作同步断言，SHA-256 `732ad152b97a1eb628394a7b0acd0037aa14d38768f3b479b8d23e90d4c8c048`。不因断言失败放宽条件或覆盖原始报告。

脚本显式设置定时器 AccuracySec=100ms、RandomizedDelaySec=0，避免默认定时精度使约 35 秒恢复延迟；依据 [systemd 定时器文档](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)。注入仍为 35 秒，恢复后的只读观察最多 55 秒。

另行记录未注入故障期间的网络基线：03:51:11 发布端 active、NRestarts=2；安全诊断日志在 03:48:47、03:50:33、03:53:11、03:54:56 分别记录 MEDIA_GRANT_UNAVAILABLE / TimeoutError。它们发生在本次故障注入之前，不能归因于测试，也说明前述 14 分 50 秒无重启窗口不能外推为长期稳定。原有读超时和授权期限未扩大。

候选实现：[staging_camera_removal_fault.cjs](../../tools/diagnostics/staging_camera_removal_fault.cjs)。申请的具体范围如下：

- 目标是云服务器 47.94.95.244，不是机械臂 SDK。仅在 OUTPUT 中临时拒绝 thirdhand-stage 用户到 127.0.0.1:7880 的 TCP 管理连接；不改公网端口、其他用户或入站规则。
- 两个真实观看端连接后，正常关闭其中一路，故意使其 SFU 移除请求失败，检查发布租约停止续期及发布轨道消失。
- **独立 systemd 定时器 35 秒后移除该条唯一标记规则**；脚本另有 finally 清理。不得清空、恢复整张防火墙表或更改其他规则。
- 期间所有观察者可能短暂失去视频；测试不连接 SDK、不发运动指令、不录制。自动恢复后检查旧观看者已移除、相机恢复、测试规则不存在。
- 记录真实 SFU 轨道移除时间；不把轨道消失误称为浏览器解码缓存的严格 950 ms 隐私截止时间。

### 实际结果（均为北京时间 2026-10-31）

| 轮次 | 事实 | 判定 |
|---|---|---|
| 1 | 05:09:20.405 就绪，05:09:55.222 才出现首个拒绝，未在窗口内同步关闭观看；35 秒后规则清除，发布恢复 | 原脚本虽输出 success=true，人工明确判为 inconclusive，不能算通过；原报告保留为 attempt1，另有 assessment |
| 2 | 05:21:35.513 就绪，浏览器 05:21:58.158 请求关闭；05:21:58.420 出现拒绝、05:21:58.546 发布轨道消失；05:22:10.647 检测规则移除，05:22:11.338 原订阅者全部移除，随后发布恢复 | 已有因果对应的故障停播证据，但触发晚于脚本要求的 10 秒，断言失败；不得称完整脚本通过 |
| 3 | 05:25:19.503 就绪，05:25:32.630 已出现拒绝和停播，早于浏览器 05:25:45.991 的关闭请求；05:25:54.665 检测规则移除、05:25:55.448 旧订阅者清除、发布恢复 | 停播原因混入原有掉线，且不满足 10 秒同步条件；不判通过 |

第二轮 Ubuntu 的独立日志在 **05:21:58.571882** 记录 `MEDIA_GRANT_UNAVAILABLE`、`response_headers`、80 ms、HTTP 503；05:22:05 和 05:22:11 再次记录 503，符合撤销待确认时停止续发租约的行为。轨道消失比首次拒绝采样晚 126 ms，**这不是浏览器解码隐私截止时间，也不是从用户操作开始计算的严格停播上界**。05:22:29 又出现 600 ms TimeoutError，属于恢复后仍存在的链路不稳定。

三轮原始报告分别保留为 root 备份目录中的 `camera-removal-fault.attempt1.json` / `attempt2.json` / `attempt3.json`；后两轮均没有 success=true。第三轮之后独立审计 `faultRulePresent=false`，视频服务保留一个发布者、无测试观看者；没有第四轮注入。`finally` 在独立定时器已清除规则后再次删除同一规则时提示 Bad rule，随后 absence 检查为真，不是整张防火墙表的修改。

C2g 三轮当时的结论：**故障关闭行为已观察到，但完整故障验收尚未通过**。后续同步复测结果见文末 C2i 链接，不覆盖这些原始判定。正常退出清除已通过；还需测量编码/网络/解码截止时间、长时负载、校园重认证/网络切换、必要时另行审阅 TURN/TLS，以及生产证书轮换。当前限两人；未购买或承诺十人资源。

### 新增诊断与非注入基线

只为发布请求增加安全诊断：阶段、耗时、最近八次成功耗时、允许范围内的 HTTP 状态；不记录异常原文、URL、JWT、密码或私钥。诊断异常在工作线程内部包装，防止 asyncio 转换 TimeoutError 时丢失属性。新增回归先 RED 后 GREEN，完整设备 Python 测试 **34/34 通过**；仅切换独立 publisher 的源码路径并重启它，源适配器及原 Robot/Vision/Web 不动。

保持原 **950 ms 签名租约、50 ms 单调检查、0.6 秒读超时、0.2 秒续期等待**。故障前已有多次 600–601 ms `response_headers` TimeoutError，之前八次成功通常约 100–120 ms。24 次暖连接健康检查均成功，多数 41–55 ms、最大约 290 ms；这只是不同路由的样本，不能排除授权接口、服务器或网络的间歇延迟。等待响应头超时是已定位的故障阶段，根因尚未确定，不能简单归因于学校防火墙或 USB。

05:30 附近非注入期间仍有相同超时；publisher active、当前单元 NRestarts=40，源适配器 PID 28559、NRestarts=0。源码切换重启会重置单元计数，不能把该 40 与之前快照计数直接相减。前述 14 分 50 秒无重启仅是旧的短时窗口，不代表当前稳定。

## 备份与回退

云端 `/var/backups/thirdhand/access-C2g-camera-20261030T182905Z` 保存原版本、环境、Nginx、组成员、监听、防火墙和 PG dump；其中 private / key 文件不可下载到文档或聊天。旧业务版本和 Ubuntu source / source-9b4ad0d21ad2aac8 均保留。

仅回退连接修复时，使用 Ubuntu `units/publisher.before-keepalive.service` 恢复该单元的旧 PYTHONPATH，再 daemon-reload、重启新 publisher；不重启已有 Robot/Vision/Web。若回退整个 C2g，按原审阅文件先停新相机单元，再恢复业务/配置和本次独有规则；不得将无鉴权 SDK 或 9983 开到公网作为替代。

本次没有 Git commit、push 或 PR，也没有真机运动。

## 后续授权请求修复

[C2i 实际记录](2026-10-31-C2i-camera-request-timeout.md) 已定位短报告拆包、网络重传与设备端读超时的对应证据，部署单文件合并发送修复。本地35/35和Ubuntu TLS专项5/5通过；原有期限未扩大，12:08:18已恢复临时网关诊断配置。用户恢复会话后，两个真实Observer观看端持续解码；连续300.018秒、61次采样全部正常。本轮12:53:39开始的35秒故障严格同步断言及完整脚本均通过，规则独立清理、原观看者清除、发布恢复和再次观看已核对。C2g前三轮未通过记录仍保留；一次修复后自然超时和长时未验收的限制也明确列出。
