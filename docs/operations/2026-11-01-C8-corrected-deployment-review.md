# C8 修正部署审阅：实际设备快照与连接状态收尾

状态：候选已固定，两端默认只读审阅通过；**未应用修正版**。前次云端26文件与Nginx路由已上线；设备原包回退，原因和实测结果见 [C8现场记录](2026-11-01-C8-deployment-change.md)。本次修正仅完成状态上报准备，不连接SDK、不发送运动或夹爪指令。

## 具体变化

### 云端

- 当前release `4688a5dfdcf76810` → 新release `7e39dce24d6ed316`。
- 从Git `6e327b8397a2f255c0e1d8460aeeb0f9a438ceb2` 读取3文件：`admin-control.js`、`device-state.js`、`i18n-cloud-catalog.js`。
- 连接请求成功或失败后结束等待，重新请求实测反馈；15秒后不再显示永久连接中。旧请求不会清除新请求状态，已有实测反馈优先。未知状态补中文。
- 4656件清单保持，4653件字节不变；重启既有 `thirdhand-stage.service`，不修改数据库、角色、认证配置、Nginx或媒体端口。
- 独立目录 `/var/backups/thirdhand/access-C8d-state-followup-20261101`；原release保留。

### Ubuntu

以当前**真正加载的**C3c/C3e源码为基线，创建两个独立新快照：

| 当前目录（保持不变） | 新目录 |
|---|---|
| agent-source-aef304c8c1efc5de | agent-source-c8-a392c80be781b3f1 |
| robot-6a801e6404e6265e | robot-c8-600dde48c691d418 |

均位于 `~/.local/share/thirdhand-stage-device/20261031/`。当前58件文件逐个核验；55件字节不变，runtime.py/telemetry.py/remote-gateway.js共3件改变，新增latest_state.py/state_upload.py共2件。保留真实现场的历史上传连接复用、软件失联保护、控制器/桥接器、seed预览及所有既有控制策略。

仅新增两个drop-in（不覆盖原unit或其7份既有配置文件）：

1. `~/.config/systemd/user/thirdhand-stage-edge-read-only.service.d/zzz-c8-latest-state.conf`：覆盖PYTHONPATH至新Agent目录。
2. `~/.config/systemd/user/thirdhand-tcp-calibration-robot.service.d/zzz-c8-latest-state.conf`：覆盖ExecStart中的server.js路径至新Robot目录，沿用既有Node路径。

独立准备目录 `~/.local/share/thirdhand-stage-device/C8-active-state-20261101/`。不操作现场原仓库、SDK库、CAN设置、相机服务、证书、密钥或outbox数据库。不更改已有443路由。重启两个既有用户服务，不新增服务/端口。

## 固定摘要

| 文件/清单 | SHA256 |
|---|---|
| cloud.delta.json.gz（295496字节） | c75363564dae4e32b5e156a25b922a222a5bc81cd0e86e3b36469d81c300e502 |
| apply_ui_sdk_followup_cloud.py | 1e45e54c10eb1a52ee68d1d6612c55517bdc7b66b415fe55b46d0a7813b79885 |
| 云端新manifest | 7e39dce24d6ed3169e6a85a21013f24ce12e6b7243a5a182afe206eaa163797e |
| device.delta.json.gz（22736字节） | 7ad32168a0cd066b31e2cdcb22a7700ff57d76c5a83d5ef32b66f84aaa3ed00c |
| active-pins.json | 103171b62779c34408845549dc68fe8be7aee0b7b8b83e8be5bf18ae729a34fa |
| apply_ui_sdk_active_device.py | 0b3213bc1fd25f6836f4484ca4977374d198d3265829f40a9b399a25fadff638 |

完整旧/新文件摘要和两份drop-in精确内容在 [固定清单](../../deploy-placeholder)；仓库实际路径为 `deploy/public-access/staging/device/c8-active-pins.json`。模板仅以当前Linux用户home替换`@HOME@`，不接受任意自定义路径。

本地固定文件在 `.superpowers/sdd/2026-11-01-ui-sdk-audit/active-device-candidate-v3/` 与 `cloud-followup-candidate/`。旧active-device-candidate和v2只是压缩器差异失败产物，不得上传。构建使用Python3.14.5；不同zlib版本可能产生不同gzip压缩字节，即使源码相同，仍拒绝摘要不匹配包，不放宽安装校验。Python3.11运行安装器及测试不依赖重压缩。

## 实际预检与测试

- Ubuntu远端默认review返回 `applied=false`、5件源码变化、两新快照和两drop-in；实际Environment/ExecStart与旧源码、7份unit/drop-in摘要均匹配。没有重启或激活。
- 云端默认review返回 `applied=false`、精确3文件变化、sdkActions=0、motionCommands=0；现有manifest及保护配置、无活动租约由既有部署保护器核验。
- Node13项通过；Python24项通过（新快照保护13、三文件云包5、旧候选退役/回退6）。覆盖路径不符、未加载unit修改、服务未停、证明超时/SDK已连/租约活动、并发改动、部分激活失败及不依赖损坏包的回退。
- 这不是实时SDK或相机成功证据。本轮相机请求失败；旧历史记录能读取，不等于真机当前在线。

## 执行顺序与门禁

1. 两端重新核对全部固定摘要、current、活动路径和unit配置。任何变化均停止，不覆盖其他任务发布。记录云端requested/active/revoking租约及在途命令为0。
2. 云端按固定安装器默认review后 `--apply`，由原部署保护器备份并原子切换，重启API；检查私有healthz仍为explicit-read-only。
3. Ubuntu读取当前SDK=false、moving=false、readOnly=true、recordingHealthy=true。先停止edge；再次读取本地SDK和运动状态，任一未知/已连/运动即不继续；然后停止robot。
4. 形成owner-only `clearance.json`：schema=1、phase=C8-active-state、deviceId为既有设备、checkedAt为原核查时间毫秒、activeLeases=0、activeCommands=0以及上述四项状态。保留真实原时间，最长60秒有效，不通过重写时间延长。操作前再核对停止状态；不得把缓存值当新核查。
5. 在独立目录执行 `python3 apply_ui_sdk_active_device.py --apply --clearance /绝对路径/clearance.json`。程序持既有CAN协作锁，但不打开CAN、不导入SDK；停止状态与新鲜证明都必须满足。只复制固定文件，核验全部摘要后写入两份新drop-in。程序不执行daemon-reload/start，也不发送SDK命令。
6. 已创建的新快照做静态语法/import核验（不构造SDK）。`systemctl --user daemon-reload`；先启动robot，复查SDK=false/只读，再启动edge。检查实际PID路径、5件新文件及55件保留文件、状态发布工作进程、服务重启计数和云端缓存。不把没有样本解释为零角度或成功连接。
7. 观察页面连接状态、账户/历史入口，核对无SDK样本时的未知/未提供显示。SDK初始化证据未通过时，到此停止，10分钟真实采集仍待验收。相机故障另行定位，不变更媒体服务配置。

## 回退与失败处理

- 云端固定安装器 `--rollback`，恢复4688旧release；保护器检查并发修改，不覆盖新发布。
- 设备保持原快照完整。先核对SDK未连且无运动、取得新鲜零租约证明，再停edge和robot。`--rollback --clearance ...`只移除字节仍与本次候选一致的两份drop-in，daemon-reload后恢复旧路径，按同样顺序启动与复查。它不要求新源码/上传包完好，不递归删除目录，不清理原数据。
- 过期/未知SDK状态、并发unit改动、部分写入等发生时停止并报告，不伪造停止证据。失败若只留下未激活新目录，保留诊断，不自动删除重试。回退也不绕过新鲜证明；无法安全恢复时保持服务停止，明确告知用户。

## 为什么需要这次确认

原批准的是固定旧目录5文件；实际需新增快照及2份服务路径drop-in，并上线另外3份网页修复。因此触及原[C8审阅](2026-11-01-C8-deployment-review.md)明确要求的“若其他任务已改源码/current/配置，停止，不覆盖或自动扩展范围”。本次先完成具体包、远端只读审阅和测试，再申请上述修正版部署；不重复申请原云端26文件或路由的授权。
