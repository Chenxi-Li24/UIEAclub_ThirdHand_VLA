# SDK默认同步六文件固定部署审阅

状态：待用户批准；尚未上传/应用。源码候选 `2b183b9f6983d4ca34cd8d17e72168d1cf74f1b6` 已推送fork login。[CI 41474297962](https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA/actions/runs/41474297962)全部通过。

## 功能与限制

修复实时角度折叠/同步入口，收到新鲜SDK实测后默认跟随3D与关节/夹爪/法兰输入；手动编辑或模型点位播放暂停跟随，实测读数独立持续更新。恢复勾选才覆盖手动草稿。补充后台关闭授权/心跳过期/通道中断提示。详见[修正记录](2026-11-02-sdk-model-follow.md)。

不修改SDK租约时长、心跳门禁、后台释放策略、数据库、权限、Ubuntu、网络、Nginx或展示站，不初始化SDK、不发送运动。该包不宣称解决长期掉线；23:11:06的browser_disconnected尚缺浏览器精确触发事件。

## 固定材料

本地忽略目录 `.superpowers/sdd/2026-11-01-sdk-source-audit/`：

- `model-sync-candidate/model-sync-candidate.json.gz`，729303字节，SHA256 `fb898528bafac18f2aa1da3b62302a87b7bf01db70e1e116a98bf9e5a3bdacf7`。
- `model-sync-cloud-operator.py`，SHA256 `b23d8018b976e3831a927205fe5b05868fae55369e1807fdcb0ab55a7808cb71`；默认只预检，显式`MODEL_SYNC_APPLY=1`才应用。
- 构建器`tools/deploy/build_model_sync_candidate.py`只读取固定manifest与指定Git提交，检查父提交和实际基线相符，拒绝范围漂移。

| 文件 | 新SHA256 |
|---|---|
| apps/web/public/js/admin-control.js | 41c503c1239bbace8d6591ccca12c6f661fbd0f28893bca23b0b35041b72e368 |
| apps/web/public/js/device-state.js | 03b68415b5ce23d18a2d4db8a837e9f5d63d7d0c7c0854e49c98005fe463058c |
| apps/web/public/js/i18n-cloud-catalog.js | 7fc6a9cb9cb747231cca15e1141af000796d733c99fcf9f441cc9387d55b697c |
| apps/web/public/js/simulation-controller.js | c5969b0d26f04fee527095eb20fbfe3ce1fed8a1d979ab22a90fa68d61f1bdeb |
| apps/web/public/js/workspace-session.js | 0955abf0a27da2acede67f3e0e2def0a829f63bee705a38f23a51ec175384e86 |
| apps/web/public/js/workspace-startup.js | 8d98b89ba947c86673b88bf8dc14f9c4aca89cb4e65456cb6f3b36e4e9d7d884 |

云端旧发布 `/opt/thirdhand-stage/releases/e9885d6408e68955`，manifest SHA256 `e9885d6408e68955b109de320e2abc4f3557e692c6807df3c1109b38a344f636`。
新发布 `/opt/thirdhand-stage/releases/a287e6b5558f02b5`，manifest SHA256 `a287e6b5558f02b5604263d0abba464831ff8df9faff4999fb43e840e3132edd`。4658件中仅六件变化，4652件保留。

包/应用器仅含源码、公开路径、摘要；没有用户信息、数据库内容或认证材料。

## 实施顺序及回退

1. 先只读确认云端发布未漂移、用户SDK已断开、requested/active/revoking租约及在途命令均0。如仍在连接则等待，不主动断开或抢占。获批后才上传两件固定材料至`/var/backups/thirdhand/access-model-sync-20261102/`，目录0700/文件0600，逐字节验摘要。
2. 默认预检全4658件、旧manifest、保护文件、业务unit/drop-in与诊断开关；任何漂移停止，不扩大范围覆盖其他人的版本。
3. 应用器复用既有经SHA验证的安装锁/准入暂停（最多240秒），再次确认零租约/在途命令，备份current、保护摘要和unit。复制旧发布仅替换六件，核验全量manifest。
4. 原子切current，只重启thirdhand-stage.service，检查healthz、unit、保护摘要及发布全量摘要。业务API短暂停顿可能导致相机鉴权重新建立；不重启相机/Ubuntu服务。
5. 失败自动切回旧发布并仅重启同一业务API。事后回退先确认仍为本次新发布、无新部署/活跃租约、SDK断开，再用同一安装锁和准入暂停切旧发布。保留两个发布与备份，不删除数据/文件。没有数据库回退步骤。
6. 部署后核验公网六件资源摘要、两套布局双语、实时角度展开、默认跟随与手改暂停。真实反馈只能来自用户显式连接SDK后收到的hardware状态，不替用户点击申请/初始化；若没有现成SDK连接则先完成界面测试并如实标记真实验收待做。没有运动指令。

## 已完成验证

- 定向Node/DOM 69/69；两套布局、两种角色、断线/恢复/过期/读失败/无效反馈/手动草稿及权限边界。
- 固定包构建器4/4；第一次pytest因系统临时目录权限失败，改用仓库忽略目录后通过。完整源码CI两项job通过。
- Edge本地浏览器合成反馈验收：默认勾选、手改J1=25时反馈仍5.73、显式恢复后输入5.73。截图`model-sync-manual.png`和`model-sync-follow.png`；假的渲染适配器，无真实SDK/Three.js验收。
- 本地包manifest与全部六件提交源码摘要匹配，应用器Python语法检查通过。尚未在服务器执行这份应用器预检/部署。

审批请求范围：上传上述两件固定材料、替换六件云端前端文件、只重启staging业务API，并做页面/被动反馈验收。按用户已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步“固定源码/资源清单、数据库变更和回退材料完成后才申请实际部署”，本包须获批后应用。

## 实际结果（2026-11-03补记）

用户批准后两件材料已上传、摘要一致，默认预检通过；SDK断开且租约/命令空闲时应用成功。当前发布a287e6b5558f02b5，4658件全部校验，changed=6、preserved=4652，业务服务active且healthz通过，timingEnabled=false。仅业务API重启，没有SDK初始化/运动。备份与旧发布保留。内置浏览器模型加载、默认同步、展开和手改暂停通过；用户连接后的范围内六轴真实同步通过，但发现J2=-12.21°被编辑限位拒绝，已另行本地修复，尚未上线。详见[实际记录](2026-11-02-sdk-model-follow.md)。
