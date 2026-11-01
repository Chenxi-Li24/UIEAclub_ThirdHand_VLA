# C8 固定部署审阅：统一界面与只读实时状态

状态：候选已完成；**尚未部署、尚未连接 SDK**。依据已批准 C8 方案第9节第6步，实际服务器变更须审阅固定候选后应用。本文件一次覆盖云端、Ubuntu 和状态路由，避免拆开反复确认。

## 范围与结果

部署到 staging.uiea-thirdhand.com。更新两套界面的导航、账户分层、数据入口、教程适配及只读设备反馈；经典仍为全屏模型与右抽屉。Ubuntu 主动向现有 edge.uiea-thirdhand.com:443 上报独立最新快照。历史上传保持原实现。

不增加公网端口、账号、证书、数据库迁移或 SQL 权限。不改展示站、原模型文件、SDK 库、运动门禁、现场原 SDK 控制器/桥接器。模型编辑不会调用真机；不实现跟随，不发送运动/夹爪指令，不自动连接 SDK。

会重启云端 thirdhand-stage.service，以及 Ubuntu 的两个现有用户服务 thirdhand-tcp-calibration-robot.service、thirdhand-stage-edge-read-only.service；Nginx 语法通过后 reload。云端 API 重启可能使相机授权短暂重连；不重启相机发布器或修改视频端口。

## 固定来源与包

云端运行源码来自 Git `004e7f404c1e0d942483f53302d2ccb808899bce`；设备源码仍固定 `7e65b5d3b59fb7359dec1262d1f7a31c9a63139d`，不是当前工作目录。其他任务的 XVisio/C++/相机 Python 未进入候选。

| 项目 | 固定内容 |
|---|---|
| 云端当前 release | /opt/thirdhand-stage/releases/1fdfb95e8d905105 |
| 云端新 release | /opt/thirdhand-stage/releases/4688a5dfdcf76810 |
| 云端变化 | 26份源码，23更新、3新增；总清单4653→4656，4630份原文件不变 |
| 云端包 | cloud.delta.json.gz，388726字节 |
| Ubuntu 基目录 | /home/nieqingcao/.local/share/thirdhand-stage-device/20261031 |
| Ubuntu 变化 | runtime.py、telemetry.py、remote-gateway.js；新增 latest_state.py、state_upload.py，共5份 |
| Ubuntu 包 | device.delta.json.gz，21034字节 |
| Nginx 变化 | /etc/nginx/sites-available/edge.uiea-thirdhand.com 内新增精确 /edge/v1/state 路由；复用既有严格mTLS及后端映射 |

云端完整文件列表、旧/新摘要由 `tools/deploy/build_ui_sdk_release.py` 和 `tools/operations/apply_ui_sdk_cloud.py` 固定。Ubuntu 清单、六份现场源码摘要及保护规则由 `tools/deploy/build_ui_sdk_device.py` 和 `tools/operations/apply_ui_sdk_device.py` 固定。

本地候选均位于 `.superpowers/sdd/2026-11-01-ui-sdk-audit/`：`cloud-candidate-v3/`、`device-candidate/`、`route-candidate/`。旧 `cloud-candidate/` 与 `cloud-candidate-v2/` 已废弃，不能上传。安装器与模板使用UTF-8/LF；上传后必须逐一核对以下SHA-256。

| 产物 | SHA-256 |
|---|---|
| 云端旧manifest | 1fdfb95e8d905105b94238fb1749bcf21f368045e8301d519c0e509d160b97b8 |
| 云端新manifest | 4688a5dfdcf768109296765b7937fd8bbb47ec22bd27ae4b25a11562590da1f8 |
| cloud.delta.json.gz | a6ecf9b39aef8bedbaa41a696927732699c43d2631c05fe8892fcc5acf747006 |
| apply_ui_sdk_cloud.py | c68d0f75533a86cae460b966c5c3618eb90d4484850f0084a982ca35ba6305a2 |
| device.delta.json.gz | 12ac8cf0773393aa4c36e6792f4944e617420b58afb7730b500cd8f06918815d |
| apply_ui_sdk_device.py | d934f64cec10c1649ccc28303e3fd369fa669e8199b2c71b44a03f5bcd902186 |
| apply_ui_sdk_route.py | 72b77a4521ea2f14bfb100f258fcee92e6aafe61213c47fc32ced4dfddf15217 |
| state-location.conf | af9834e79eed184d6bb551d399a4f009967761850f6f79fb193bf754e511b531 |
| Nginx原配置 | a2e7dff2bc075998e1898de8137b0a3386ae828e0a11bf4bfe28412d7663f44a |
| Nginx新配置 | 0b65801a9933e1ad1e3b7f4dbaa69b94b63d9e72032e7ae094b5214e6ed32c68 |

## 部署前复核

1. 最新提交CI通过；重新核对三组现场摘要。若其他任务已改源码/current/配置，停止，不覆盖或自动扩展范围。
2. 云端部署锁、保护配置、无活动租约/命令；Ubuntu readOnly=true、sdkConnected=false、recordingHealthy=true。状态未知或SDK已连接时不停止服务、不继续安装。
3. 两端时钟同步、现有证书有效。先核对原生SDK构造函数是否有使能/回零副作用；本轮部署不调用它，无法证明时保留SDK未连接。
4. 在上述三个独立运维目录上传包/安装器/模板并验SHA。默认执行安装器只审阅，不写运行文件。

云端源码运维目录 `/var/backups/thirdhand/access-C8a-ui-sdk-20261101`；路由目录 `/var/backups/thirdhand/access-C8b-state-route-20261101`；Ubuntu目录 `/home/nieqingcao/.local/share/thirdhand-stage-device/C8-ui-sdk-20261101`。不上传数据库、密钥或用户信息。

## 获批后顺序

1. 云端运行 `python3 apply_ui_sdk_cloud.py` 审阅，再加 `--apply`。使用已固定摘要的既有部署保护器，备份、构建新release、原子切换，重启业务API并检查healthz仍为explicit-read-only。仅这一实例保存最新缓存。
2. 路由安装器默认审阅，再 `--apply`：独占备份原配置，单锚点插入已固定模板，`nginx -t`，reload；失败立即恢复。无客户端证书访问state应仍拒绝。
3. Ubuntu 再查SDK未连接，停止edge用户服务，再停止robot用户服务。设备安装器检查两者inactive后 `--apply`，备份并原子替换5文件；原历史上传器/控制器/桥接器必须摘要不变。
4. 用既有运行环境做import/语法检查（不初始化SDK），先启动robot，再启动edge；核对两服务、只读context、独立上报工作进程与云端实际接收。此时未连接是正确结果，不应显示“新鲜的零角度”。
5. 浏览器检查两布局/两角色/语言、账户和成员、历史与CSV、点位/偏好/教程保留、相机观看；观察员控制请求仍403。窗口显示状态必须带来源和时间，未知不可用值为“—”。
6. 初始化行为确认后，再由管理员显式连接做至少10分钟只读对照；核对六轴、实际夹爪、所有SDK可供字段、单位、序号及来源时间，记录公网P50/P95。仅中断独立状态发布进程验证过期/恢复，不切断设备网络、不停整个robot、不发送动作。若初始化仍有未决风险，则报告待验收并保持未连接。

## 回退

- 云端加 `--rollback`，使用原保护器校验后恢复旧release并重启；无新数据库schema，数据不删除。
- 设备先确认SDK未连接且停止上述两服务，再 `--rollback`。使用固定备份恢复3文件、移除2份本次新增模块，不依赖候选压缩包仍可读。若出现其他任务修改则拒绝覆盖。按原顺序重启并检查只读状态。
- 路由 `--rollback` 仅在配置仍等于本候选时恢复备份，语法校验后reload；保留并发编辑。恢复过程若失败，停止继续操作并报告具体错误。
- 备份和审阅记录保留，不自动清理。回退不改相机证书/数据库记录/账户或点位。

## 证据及未通过项目

完整记录见 [C8实施记录](2026-11-01-C8-implementation.md)。Node业务327/327、Python edge88/88、部署保护14/14；真实浏览器24组合和教程8组合48步骤通过。合成状态测试与真实SDK验收严格分开。

核心699c424的Linux CI两任务成功；最终补丁CI在推送后核对。Windows扩展回归有25项旧平台限制，未隐藏。性能本机5次样本中模型P50增加56ms，P95降低25ms；慢网模型差异0.2%。尚不能宣布公网性能或真实10分钟状态预算达标。完整读屏/像素基线、正式教程provider、真实跨登录与摄像头稳定性仍需对应验收，不以接口200代替。

本次请求批准的是上述固定部署与只读验收范围；不是运动或正式生产发布审批。
