# C7 具体部署审阅：原版布局复用、启动与模型资源

## 本次申请范围

仅`staging.uiea-thirdhand.com`业务API及其鉴权静态资源：13件现有文件变更、19件新文件，共32件。
应用一次兼容加列迁移011，只重启`thirdhand-stage.service`。
Ubuntu、SDK、真机、相机发布/媒体/中继服务、展示站、env/凭据/证书、账号角色、服务权限及公网端口均不变。
本候选当前只在本地准备，尚未上传或部署；独立于已有fork main合并。

执行计划`docs/superpowers/plans/2026-10-30-public-access-rollout.md`要求：
“C1/C2 对照拟应用配置、数据库迁移、服务列表和回退方案进行部署审阅；批准具体变更后再修改服务器。”
因此本文件给出固定对象供用户批准，代码完成不等于已授权应用本组服务器变更。

## 固定基线与候选

| 项目 | 固定值 |
|---|---|
| current基线 | `/opt/thirdhand-stage/releases/7c7f4b5f3792288e` |
| 基线manifest SHA-256 | `7c7f4b5f3792288ec42d98ddbd25151ae192a766f8a7f16fd996afe6ba35f63c` |
| 候选release | `/opt/thirdhand-stage/releases/2a1bf049a022c65e` |
| 候选manifest SHA-256 | `2a1bf049a022c65e59c1da65c3a6aab72b988b2fd1a889b76eb39b2a5e4b4544` |
| cloud.delta.json.gz SHA-256 | `0b59a622e88ef2fa5e04451b96ef91e142972f6b701610062bd6a1e0ea959c0a` |
| 包大小 | 4,492,505字节 |
| 文件总数 | 4634 → 4653；4621件原文件字节不变 |
| 迁移011 SHA-256 | `31d504df11ff4be7ddb9f321e427e04ba80f0eda1b8d728736ae101ffd4192fd` |
| apply_workspace_layout_cloud.py SHA-256（Git字节） | `f14991ae886e63c9a3e5d90a4fc676a921e6eb0a579809706f30f20ba727c20b` |
| 服务器私有操作目录 | `/var/backups/thirdhand/access-C7-layout-startup-20261101` |

准备期间只读现场检查确认current/基线摘要一致、API active/running、重启计数0、活跃租约0、accepted/started命令0、新偏好列0。
应用前必须重新检查，任何漂移均停止，不覆盖其他聊天的新发布。

候选从Git索引规范化字节生成；LFS载荷验证索引oid与size，不取整棵脏工作目录。
源码范围固化于`tools/deploy/build_workspace_layout_release.py`及`tools/operations/apply_workspace_layout_cloud.py`，
后者验证包摘要、源摘要、完整清单、原元数据、精确新增/改动集合以及迁移摘要。
模型原STL/URDF、业务node_modules及整个其他发布内容从已验证基线复制，不覆盖。
本地候选目录在`.superpowers/sdd/2026-11-01-workspace-performance/deployment-candidate`，不进入Git。

## 数据库变化

以现有root运维通道调用postgres，仅应用`platform/storage/migrations/011-workspace-layout.sql`：

- `auth.user_preferences.layout_id text NOT NULL DEFAULT 'workspace'`，只允许workspace/classic。
- `auth.user_preferences.classic_theme_id text NOT NULL DEFAULT 'deepspace'`，只允许原九配色。
- 在`public.thirdhand_schema_migrations`登记011与固定SQL摘要。

迁移使用与标准迁移器相同的advisory lock `(240103,1)`、原子事务、3秒DDL锁等待和15秒statement上限。
只接受“未应用且两列都不存在”或“相同摘要已应用且两列都存在”，不接受部分/异源迁移。
业务服务原有表级SELECT/UPDATE足够，不增加DDL、表或schema权限。
默认值保持新版布局；用户之后可在账户设置切到原版。

## 执行顺序与备份

1. 用户批准本具体范围后，核对本次提交的32件索引/提交字节与包；远端Linux CI必须通过。
2. 在服务器建root私有0700操作目录，只上传固定候选包和本次应用器；核对上传摘要。未获批准不上传。
3. 应用器默认review（无`--apply`）验证原发布全部4634件、current、固定候选32件、保护env/展示页摘要、数据库迁移状态、无活跃租约及命令。
4. 用共享安装锁和现有lease admission数据库锁阻止并发发布/新控制租约。发现并发任务或基线不符即停止。
5. 保存`before-public.json`（旧release/manifest、env和展示页摘要）及偏好schema状态收据；不导出账户密码/MFA或个人数据库内容。旧发布目录原样保留，作为源码备份。
6. 复制基线至受检临时目录，创建固定新文件父目录、写入32件候选和manifest；验证4653件完整清单后定名候选release。
7. 应用/核对迁移011；再次检查空闲状态和保护文件，原子切换current，仅重启`thirdhand-stage.service`。
8. 本机healthz必须仍为`deviceControl=explicit-read-only`；健康检查或后置校验失败自动切回原发布并重启API。
9. 使用本人真实HTTPS会话验收现代/原版、切换/刷新/重新登录、显示名/退出/相机入口、个人点位、浏览器冷/热加载和资源鉴权；不以localhost替代上线结果。

运维命令（仅批准后执行）：

```sh
cd /var/backups/thirdhand/access-C7-layout-startup-20261101
python3 apply_workspace_layout_cloud.py            # review，不修改业务
python3 apply_workspace_layout_cloud.py --apply    # 固定32件+011+一次API重启
python3 apply_workspace_layout_cloud.py --rollback # 源码回退，保留新增列/偏好
```

## 回退与风险

回退仅依赖已验证旧发布和备份收据，不依赖上传包或损坏候选。
原代码忽略新列，保留011及用户偏好，不DROP列、不恢复旧账户/点位数据，也不删除现存发布目录。
失败时保留候选/临时目录供复核，不自动覆盖或递归清理未知路径。
如果数据库迁移已成功但切换失败，旧代码继续运行，新列及迁移记录保留；恢复前复核现场，不能盲目重跑。
API重启会短暂影响业务请求和观看授权续期；现有媒体/Ubuntu单元不重启，用户必要时重新请求观看。
CSP增加WebAssembly解码许可；静态源码/模型私有长缓存可能留在浏览器，动态身份/权限始终不缓存。
手机断点实际验收尚未完成，生产网络和真实视频性能须另测，不据本机指标扩大真机运动权限。
