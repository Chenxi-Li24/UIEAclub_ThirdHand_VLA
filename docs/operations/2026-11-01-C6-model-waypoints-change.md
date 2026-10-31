# C6 个人模型点位：实际部署与验收

状态：**已获准并部署到 staging，个人模型点位验收完成**。2026-11-01 02:07（中国时间）发布后检查通过；02:13:52完成实际点位数据库核对。真实账号保存、刷新读取、管理员/观察员模型调用，以及退出后新登录读取和调用均已通过。重新登录期间用户报告较长转圈，随后自行完成，原因尚未定位，不能标为延迟问题已修复。

## 授权与实际发布

用户回复“批准 C6 模型点位上线”，对应[固定部署审阅](2026-11-01-C6-model-waypoints-deployment-review.md)中的9件源码、固定应用器和两项最小GRANT，仅重启staging业务API。没有追加Ubuntu、SDK、CAN、机械臂、相机或网络变更。

| 项目 | 实际结果 |
|---|---|
| 旧发布 | `/opt/thirdhand-stage/releases/registration-approval-a570d928578cb5bb` |
| 新发布/current | `/opt/thirdhand-stage/releases/7c7f4b5f3792288e` |
| manifest SHA256 | `7c7f4b5f3792288ec42d98ddbd25151ae192a766f8a7f16fd996afe6ba35f63c` |
| 上传包SHA256 | `654eb9f00887beca0ef228d051d1cbf8223e8bd0ed81dcf6d629801bfdf453d5` |
| 应用器SHA256 | `acf303ea608fadaa8702ec66c484c4774759fb7bba8ab450a46291d7f32dfcde` |
| 授权SQL SHA256 | `9f73fa546cc27fac83eb88f8f192966e8234642dea400c9d1bd24bc4c615b67c` |
| 全量文件核验 | 4634/4634，4件新增、5件修改，其他4625件保留 |
| 环境/展示站 | 与发布前受保护摘要相同 |
| API健康 | `thirdhand-cloud-api`，`deviceControl: explicit-read-only` |
| 公网匿名点位GET | HTTP401 |

在root私有0700目录`/var/backups/thirdhand/access-C6-model-waypoints-20261101`上传3个已批准文件，逐件SHA核验后设0600。默认只读review退出0：精确9件差异、现有权限全部false、无控制租约/在途命令。随后`--apply`退出0、`applied:true`、`tableGrantsApplied:true`，原子切换current并仅重启`thirdhand-stage.service`。

业务角色`thirdhand-stage`现在具有simulation.USAGE及simulation.user_programs的SELECT/INSERT/DELETE；只复用已有表，不做数据库迁移或增表。身份/首批管理员/注册审批和相机源码来自旧发布并完整保留。操作前后凭据内容均未输出。

## 线上功能验收

用户自行登录的是现有管理员模式页面。通过可见界面保存`C6 model check 2026-11-01`，收到“模型点位已保存”。把J1模型从0改为15°后调用，观察到插值中间值和最终0°，状态“模型已到达点位”。整页刷新、模型重新加载后仍显示同一项。

在账户页切换为观察员，重新进入手动控制，仍可读取同一账户点位。把J1模型改为12°再调用，模型回到0°，状态完成。观察员页面没有真机控制区；SDK连接按钮禁用。该页浏览器警告/错误日志为空。为便于用户复核，验收点保留，未删除用户数据。

数据库只读核对：匹配记录1条、归属账户1个、模型版本正确、source=model；六轴`[0,90,-90,0,0,0]`，夹爪归一化开度`1`。2026-10-31T18:07:00Z（模型验收前）以来`ops.commands`新增0条；最终活动控制租约0。没有通过此功能连接SDK或发真机命令。

用户退出原验收页后，在原有另一个登录标签页自行输入密码并登录Observer；期间报告一直转圈。最初浏览器观察该标签页出现一次CDP响应超时，随后实际截图和可访问性树均确认已进入`/control#control`。此新登录页面仍显示同一保存点位。将J1模型改为10°后调用，观察插值及最终0°，状态“模型已到达点位”，浏览器警告/错误日志为空。因此真实跨登录读取和调用已通过；没有通过复制会话、提取凭据或冒用账号完成。

对长时间转圈只做只读诊断：02:21中国时间API健康HTTP200/5.2ms、服务器到公网登录页面GET200/79.4ms、业务服务active/running、NRestarts=0、ExecMainStatus=0。这些检查不包含用户那次认证POST耗时，不能定位当时是认证、网络还是浏览器加载延迟；未改认证逻辑、限流或超时，也未声称已修复。保留为独立待复现项，不重复提交登录请求。

本地证据位于`.superpowers/sdd/2026-11-01-personal-model-waypoints/`：

- `c6-apply-terminal.png`：应用成功。
- `c6-live-recall-zh.png`：真实模型、管理员调用完成。
- `c6-live-observer-recall.png`：真实模型、观察员调用完成。
- `c6-live-relogin-recall.png`：用户退出后新Observer登录，点位仍在且调用完成。
- `c6-database-verification.png`：持久化与零命令核对。

服务器同一私有目录保存`review-output.json`、`apply-output.json`、`before-public.json`、`grant-before-public.json`、`post-verify-public.json`、`model-acceptance-public.json`及`login-delay-check-public.json`。两次仅核验命令的终端引号/语法问题已改正，成功结果单独保存；未重跑apply、未改变已发布源码。

## 验证边界与回退

发布前相关Node348/348及部署Python5/5通过；部署后未修改冻结源码。真实删除未在用户账户执行，删除/确认/账户隔离有本地测试证据。此次没有重新运行相机故障测试或机械臂运动验收。

显式回退使用同一应用器`--rollback`：恢复完整旧代码，保留保存的点位与已批准表权限，不恢复数据库或撤销用户数据。回退后再次应用需要重新核对实际权限基线，不能直接重跑首次apply。

真机点位、真实运动、独立物理停止、限位/新基线、夹爪实测标定及相机稳定性/采集时间仍按C3e/C3f记录待验收。本次个人模型点位不改变这些门禁。部署完成后用户新增授权跟踪必要文件、按功能提交并普通推送到fork的login；既有其他聊天身份变更原样纳入基础提交，不重写历史。详见[Git交付记录](2026-11-01-login-git-delivery.md)。
