# Staging 回退

已实测的回退仅影响 `/etc/thirdhand-stage/business-upstream.inc` 与新C2服务。

1. 先保存该include及活动staging vhost原文，确认主站和edge配置与备份一致。
2. 将staging业务include切为 `return 503;`，`/usr/sbin/nginx -t`通过后才reload；新连接验证503。
3. 仅停 `thirdhand-stage.service` 和 `thirdhand-stage-export.service`。保留PG、数据、WAL、主站、C1b和现场程序。
4. 检查主站200及原首页摘要；C2 API不应转发至旧9983、语音或媒体入口。
5. 修复后启动C2服务，先核实回环healthz，再恢复原include，nginx-t通过才reload，并复核HTTPS与权限。

本次只有一个固定业务运行版本，已验证维护模式→服务重启→原版本恢复；没有伪称测试过不存在的历史业务版本。
数据库迁移不做破坏性回滚、不DROP、不删除历史或恢复旧待执行命令。
更换版本时只指向已校验且迁移兼容的固定release；不覆盖当前运行目录或秘密文件。

具体路径、摘要、状态与实测结果见[C2报告](../../docs/operations/2026-10-30-C2-business-staging-change.md)。
