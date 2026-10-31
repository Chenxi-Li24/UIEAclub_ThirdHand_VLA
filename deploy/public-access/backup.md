# 业务测试环境备份与恢复

C2实际验收见[部署报告](../../docs/operations/2026-10-30-C2-business-staging-change.md)。
以下是独立staging的操作约束，不是生产恢复或真机连接授权。

## 已有备份

- 部署前配置及逻辑快照：服务器 `/var/backups/thirdhand/access-C2-20261030T125221Z/`，root0700。
- 物理基准备份与离线恢复副本：`/var/lib/thirdhand-stage-backups/C2-20261030/`，postgres0700。
- 持续WAL归档：`/var/lib/thirdhand-stage-backups/wal/`，postgres0700。
- 私有环境备份在前者 `private-stage-config/`，文件0600。MFA解密材料不在数据库物理备份内，必须独立妥善保管。

已执行 `pg_basebackup -X stream -c fast` 和 `pg_verifybackup`，并实测基准备份之后的WAL命名恢复点。
当前只有此次基准备份和逻辑快照；持续WAL不等于已建立定期基准备份、异地容灾或自动保留策略。
不自动删除WAL、账号、采样、原始批次或历史；真实源频率与容量策略审阅后再安排轮换和异地加密副本。

## 恢复步骤

1. 保留原库、备份和全部原始数据。只在新建的离线副本恢复，使用独立Unix socket、无公网路由和无SDK进程。
2. 校验基准备份清单与所需WAL，指定明确恢复点；证明基准备份之后的标记已恢复。
3. 将副本数据库命名为 `thirdhand_stage_restore_*`。撤权工具会拒绝在线 `thirdhand_stage`。
4. 从数据库备份之外取得每台设备保留的最高epoch下界，以十进制**字符串**保存；缺失时停止，不猜测0。
5. 使用已校验的 `/opt/thirdhand-stage/maintenance/restore-current/tools/operations/isolate_staging_restore.js`，
   向CLI提供副本MIGRATION_DATABASE_URL、可由执行身份读取的epoch下界JSON文件和字面确认参数 `ISOLATE_STAGING_RESTORE`。
   最初固定业务运行包中的旧版恢复脚本不再是有效操作入口。
6. 校验会话、一次性令牌、所有旧MFA凭据及设备凭据均撤销；设备禁用；控制租约/接管终止；未决命令/运行unknown；导出expired。
   代次应高于恢复值和外部下界。历史原始字节、条数和摘要保持一致，不重放命令。
7. 停止演练副本并保留证据。不得把它直接绑定网页或真实设备。

真实恢复的重新开放还需审阅账号/角色变化、重置必要凭据、重新验证管理员和MFA、重新登记设备，
由真实设备核对最高代次并完成新的握手。C2只用模拟下界验证算法，没有替代现场证据。

`staging_restore_drill.py`、`staging_restore_mfa_check.py` 是本次固定目标的一次性操作记录，
带已存在目标拒绝条件，不应在在线库或已有演练目录上盲目重跑。
