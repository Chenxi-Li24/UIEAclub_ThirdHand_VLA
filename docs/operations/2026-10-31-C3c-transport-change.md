# C3c 第一批传输修复实际记录

本轮按用户批准的[实施计划](../superpowers/plans/2026-10-31-remote-motion-readiness.md)推进；确切范围见[部署审阅](2026-10-31-C3c-transport-deployment-review.md)。以下区分本地验证、实际部署与真实硬件验收。

## 云端已应用

- 时间：2026-10-31 21:26:28.831，中国时间。
- 旧发布：`/opt/thirdhand-stage/releases/6187bbbe8ec4d5e8`；保留用于回退。
- 新发布：`/opt/thirdhand-stage/releases/04cc19054caa45a6`，由新manifest摘要命名，不是完整tar摘要。
- 唯一运行源码变化：`services/cloud-api/src/control/websocket.js`。修复异步身份校验期间合法挑战响应突发被误判的问题；有界串行处理，不延长500ms有效期，不缓存已撤销身份。
- 部署前默认审阅退出0：4624个清单文件全部核验、精确一文件差异、无requested/active/revoking租约。实际主单元及原camera.conf drop-in核对，使用既有Node24.22.1。
- Ubuntu21:25:58即时确认SDK=false、readOnly=true；本轮没有发出connect、运动或夹爪指令。
- 仅重启`thirdhand-stage.service`；API健康保持`deviceControl=explicit-read-only`，私有cloud.env和展示站index哈希保持一致。未改账号权限、数据库、凭据、Nginx路由或公网端口。
- 备份/审阅/结果：`/var/backups/thirdhand/access-C3c-transport-20261031/`，包括`cloud-before-release.txt`、`cloud-review.json`、`cloud-applied.json`及日志。
- 应用器：`tools/operations/apply_motion_transport_cloud.py`，本次实际文件SHA为`092840402b5328bcadd08888dcfb52828febbe41504d7b6f2112eb12691e6bd3`。独立审阅指出的损坏新版本阻断显式回退问题已有RED→GREEN修复，7项专项通过。

## Ubuntu 当前进度

已于21:53按固定候选应用，21:54:58完成复核。原Agent20模块、camera20模块和两个主单元均实际核对；首次审阅时两个drop-in目录均不存在。

- 安装器SHA：`05ccb3e2e32614259bf7af92ee6afaa73e3205056e54c28761ea409a9a10e375`。显式回退与apply共用锁，回退各步骤及最终确认均重查60秒云回执，拒绝尚未daemon-reload的磁盘未知配置和符号链接。安装器34项及包装/既有部署合计44项通过。
- 云端即时记录：21:53:38.689821，current=04cc，requested/active/revoking租约总数0；公开JSON摘要`cfd47edbdc78823964afe84c01e23312e591e7700f6b70fb194c2142027b9a72`，以owner1000/mode600传入并在60秒内使用。
- Agent新增`50-C3c-transport.conf`，指向`agent-source-aef304c8c1efc5de`；相机发布同名drop-in指向`source-5bf518471ff7aa60`。原source快照、状态/outbox和私有配置保留。
- 更新后edge PID246729、publisher PID246767均active，初次复核重启计数0。相机源PID28559、Robot PID86836保持；SDK=false、readOnly=true、recordingHealthy=true。
- 仅重启edge和camera-publisher。Robot、相机源、SDK、CAN、Vision及现场原仓库没有修改。

更新后的120秒实测（21:55:44–21:57:44）仍有8次600毫秒响应头超时，**未通过稳定性验收**。此前TCP头部证据表明1894字节响应的首1428字节分段缺失/延迟，尾段先到；首段到达时客户端已按原600毫秒期限关闭。不能用调度修复或延长期限宣称网络问题消失。gzip仅测量未应用，因为典型响应仍超过单MSS；下一批紧凑签名续期仅为本地候选，须另行审阅。

## 本地验证与现场验证边界

- Node完整相关回归257/257、0失败、0跳过，涵盖全部公网业务测试及Robot Service模拟测试；使用Node24、既有独立Python解释器及专用本机PostgreSQL。
- Python相关回归68/68、0跳过，涵盖edge-agent、停止语义、候选打包与云应用器；Ubuntu应用器独立测试及后续改动另行记录。
- 真实Ubuntu Node24.18.0独立诊断目录的POSIX文件/策略单元测试15/15，使用合成ID和合成反馈；这不是真实停止验收，没有生成当前设备的运动准入记录。
- 停止回执、范围限制、硬件证据加载器与相机源证明的新模块已在本地验证；没有接入生产运动入口，不能据此宣称已具备外网真机运动。
- 相机安装头文件给出ColorImage.hostTimestamp为steady_clock域物理测量时间；当前运行Native丢弃该字段，保留的monotonic_ns为RGBD回调接收时间。新兼容时间戳链路32项协议测试通过，并于21:58:26在Ubuntu独立诊断目录完成纯C++测试及真实xv/OpenCV完整编译；未执行完整驱动或替换服务。UTC映射误差仍未知，不把接收时间伪装成采集时间，不把未知误差写为synchronized。

## 仍未完成

当前版本30分钟稳定性/两路观看/故障恢复、真实上传延迟复测仍待完成，短期复测已证明超时尚存。实际停止/独立看门狗能力、真实限位/新实测起点、夹爪测试量以及当前操作者可信帧条件尚未通过；真实运动保持关闭。账号正常登录由用户本人操作，旧会话到期后的浏览器验收正在等待恢复。

没有Git提交、推送或PR。本轮截至此记录的SDK connect、运动、夹爪、Home/Zero和序列命令均为0。
