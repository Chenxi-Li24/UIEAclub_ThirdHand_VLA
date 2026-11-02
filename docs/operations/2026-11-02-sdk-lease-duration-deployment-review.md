# SDK 专用3秒租约固定部署审阅

状态：用户已批准本固定范围，2026-11-02 已上传并完成云端、Ubuntu 部署。三个既有服务正常，SDK=false、readOnly=true，部署后活动租约和新增命令均为0。600秒浏览器授权验收尚未开始，等待用户在新验收页以Observer登录；不能将部署成功视为稳定性通过。

原因与代价见[修正记录](2026-11-02-sdk-lease-duration-fix.md)：本次真实授权49.278秒后设备1秒租约到期，未通过600秒验收。只将sdk范围单次签名、数据库租约和设备单调有效期上限改为3000ms；control仍1000ms、管理员浏览器心跳500ms、观察模式心跳3000ms、ACK1500ms、最多4条在途均保持。若浏览器失联与撤销链路失效叠加，SDK连接保留时间可能接近6秒；该范围不可发送运动。软件释放不代表独立硬件停止保证。

## 固定材料

源码候选7d16ccaec6387c0b7b3956b8018afda1a875f4b0；后续提交b32238843ce401419f1676192eb230d469bb3e1a仅增加构建器、测试和仓库内容绑定修复，八件运行源码未再改变。[CI 41410717034](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA/actions/runs/41410717034)全通过。本地业务405项、Python157项、构建器10项通过，源码边界审计ready。

本地忽略目录：`.superpowers/sdd/2026-11-01-sdk-source-audit/`。

- 包：`sdk-duration-candidate/sdk-duration-candidate.json.gz`，755195字节；SHA256 `f4e828ff1592f7086470239cc6dde55e2d2e31daa11d01638f883a6a28c103c9`。
- 云端人工应用脚本：`sdk-duration-cloud-operator.py`；SHA256 `b3f5561e92abef03c8983eb2eab90304fad2dc94273878102ea4f8c2f8f12ff5`。
- Ubuntu人工应用脚本：`sdk-duration-edge-operator.py`；SHA256 `5342abfd98ded8466ac9fe57e31cdb5dcb3530abe4b99afecea5813a151f414e`，默认仅预检，显式DURATION_APPLY=1才应用。
- 构建器：`tools/deploy/build_sdk_duration_candidate.py`，仅离线构建，拒绝基线漂移、范围外改动和现场函数冲突。

包和脚本仅包含源码、公开服务路径与摘要，没有账号数据、密码、令牌、证书私钥或数据库内容。获批后仅上传固定包；脚本可通过已登录宝塔终端和SSH标准输入执行，不安装额外服务。

| 目标 | 源码 | 新SHA256 |
|---|---|---|
| 云端 | platform/storage/src/leases.js | 12bd3ae610e4eea340b19d4c23b6ba9a37619e8cb4224743d22d02e8260062d3 |
| 云端 | services/cloud-api/src/control/leases.js | 1ec8ac7b751d6707a1a7c5021397784f6f4c7ad517a347f23ddf827d5bf444f4 |
| Ubuntu edge | thirdhand_edge/lease.py | f170bd1c2a84aeadb1136ac3ffc33f8fcd338e7ea52fe7144429ea1dd3b662bc |
| Ubuntu Robot | services/robot/src/control-policy.js | 980bc7e74be0afe9a05275ea77873e391a6308ac095fdb32607f10b5a2da716c |
| Ubuntu Robot | services/robot/src/lease-watchdog.js | 973cea6462decd27fd29fd1bd85563f74c1768a2f7857a1a07826227904c83e6 |
| Ubuntu Robot | services/robot/src/startouch-bridge.js | 5b713904a8b06192245d97c1658cf4a92dfdbf1aacbaaf624020f1e34b5c42e7 |
| Ubuntu Robot | services/robot/src/remote_lease_guard.py | 69741c0f53af30dc0a941b0da3eea0caf7e248ff713c795ed3e108afa09c6dc5 |
| Ubuntu Robot | services/robot/src/startouch_bridge.py | b13f6f22e812298391df0f800b7451e6e9ecb3940dd1f3f68c64ea7ac4cb2d5b |

Python桥接以实际运行源码为基线，只替换_require_remote_lease和connect两个完整匹配函数，保留现场IK seed分支；不是仓库整体覆盖。两端其余文件保持原摘要：云端4658件中2件改变、4656件保留；edge24件中1件改变；Robot37件中5件改变。

## 发布和服务入口

云端旧发布 `/opt/thirdhand-stage/releases/a3ca345673912070`，manifest SHA256 `a3ca345673912070924dc28d5141c1b0c7e5f736efcaaee7edc6aaf5085a38ad`。
新发布 `/opt/thirdhand-stage/releases/e9885d6408e68955`，manifest SHA256 `e9885d6408e68955b109de320e2abc4f3557e692c6807df3c1109b38a344f636`。

Ubuntu根目录 `/home/nieqingcao/.local/share/thirdhand-stage-device/20261031/`：

- edge：`agent-sdk-clock-a963153d56dac68d` → `agent-sdk-duration-550c774c14102253`。
- Robot：`robot-sdk-browser-heartbeat-f72bba77f012ba0c` → `robot-sdk-duration-e559fd326a08a276`。
- 新增 `~/.config/systemd/user/thirdhand-stage-edge-read-only.service.d/zzzzzzz-sdk-duration.conf`，仅Environment=PYTHONPATH指向新edge快照；SHA256 `8f64bbb7e02e768e7803afbacce9a01cfe15588c90e543bdf4deca0bb414d416`。
- 新增 `~/.config/systemd/user/thirdhand-tcp-calibration-robot.service.d/zzzzzzz-sdk-duration.conf`，清空ExecStart后使用原Node二进制执行新Robot快照的services/robot/src/server.js；SHA256 `6c1f337729424b74be39c5f28f20f99b7c5d737ab814f35c875bdb6c081d6b17`。

只重启已有thirdhand-stage.service及上述两个Ubuntu用户服务；相机可能短暂重连。不新增端口、不改变网络、数据库结构、账户权限、Nginx、证书或展示站。仓库frame policy三件摘要引用修复不在本次staging部署包内。

## 实施与回退

1. 上传固定包至云端 `/var/backups/thirdhand/access-sdk-duration-20261102/` 和Ubuntu `~/.local/share/thirdhand-stage-device/SDK-duration-20261102/`；目录0700、文件0600，逐字节SHA匹配。
2. 默认只读预检：云端current/全4658件、保护配置和业务unit与实际基线一致；活动租约及在途命令0。UbuntuSDK=false、readOnly=true，24/37件全摘要和所有旧unit/drop-in摘要一致，服务active、无待重载。任何漂移停止，不能扩大范围或覆盖。
3. 云端使用既有经摘要核验的installation_lock和quiescent_lease_admission（最多240秒）阻断新的授权，备份current、保护摘要、unit和文件清单；生成新发布并全量核验，然后等待DEVICE_APPLIED。
4. Ubuntu持有独立安装锁，保存before-public，复制旧快照只替换六件；编译/语法检查并全量核验。停止edge，再停止Robot，仅写两件新增drop-in，daemon-reload；启动Robot确认SDK仍断开，再启动edge并确认实际入口、SDK断开与只读。旧快照和旧配置不删除。
5. 云端再次核对零租约/配置，原子切换current，仅重启业务API，确认healthz及完整摘要，写入applied-public。没有自动SDK初始化或运动动作。
6. 失败回退：保持准入阻断、零租约且SDK断开，停止edge/Robot；仅在本次两件drop-in摘要仍一致时移除，daemon-reload并恢复旧Robot及edge。云端current恢复a3ca345673912070并重启业务API；核验旧源摘要、入口、SDK=false/readOnly=true及健康检查。保留新旧快照和备份；其他任务变更过的文件不强制覆盖。

## 有界验收

部署后Observer前台设备页显式申请SDK授权，不点击连接SDK。最多3次，单次目标连续600秒，匿名租约采样每2秒记录同一ID散列、状态、有效期与递增序号；结束后通过页面关闭通道释放，确认活动租约0。并行读取SDK=false、readOnly=true及ops.commands计数，不写设备动作。后台采样设置上限并确认退出。

中途到期/断线计为失败，不自动重申请。该步骤只验收授权稳定性，不验收真实关节读取、SDK初始化或真机运动。若仍中断，保留原始分层错误，停止追加尝试后复核；3秒不是任意延长或忽略过期。

批准范围为上述固定包上传、八件源码及两件入口配置、三个已有服务重启和600秒授权验收。此次单独确认依据已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步：“固定源码/资源清单、数据库变更和回退材料完成后才申请实际部署。”上一份批准包明确设备单次租约仍1秒，本次改变该边界，不能沿用原固定包批准直接部署。
