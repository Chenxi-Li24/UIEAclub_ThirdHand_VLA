# C6 个人模型点位：部署审阅

状态：**用户已批准，已按本文固定范围部署到staging**；默认review与apply均退出0，当前发布为7c7f4b5f3792288e。[实际发布及线上验收记录](2026-11-01-C6-model-waypoints-change.md)。下文保留获准时的具体审阅范围与回退边界。

## 功能结果

手动控制页加入“我的点位”：命名保存当前六轴模型角度和夹爪开度、刷新读取个人列表、一键播放到目标、停止、确认删除。保存在PostgreSQL；同账号重新登录可读取，其他账号不能读取或删除。英文默认、支持中文；来源固定标明模型模拟。

模型未就绪或播放中不能保存。请求等待最多10秒；保存/删除超时提示结果未确认，需刷新核对，不自动重试；迟到响应不会覆盖新列表或复活已销毁面板。当前不提供真机记录或调用，也不补造用户模型执行的持久化历史；后续课程完整场景另验收。

## 已核对的真实基线

只读查询确认云端仍为`/opt/thirdhand-stage/releases/registration-approval-a570d928578cb5bb`，manifest完整摘要`4ece5d6ce0577bfce2e734dbe43f6df617484b01868242f9b813a250f171f552`。业务角色`thirdhand-stage`目前对simulation schema的USAGE和user_programs的SELECT/INSERT/DELETE均为false；查询时控制租约与在途命令均为0。这些状态须在应用时再核对，不能把本次查询永久复用。

本地将固定C3f manifest与已批准的两阶段账号源码包逐项合成，所得4630件完整清单的SHA与上述实际manifest完全一致。新包只覆盖9件源码，其他4625件逐字保留，含首批管理员/开放注册/审批及最新相机脚本。新增4件、修改5件，总文件数4634；无删除、依赖更新或manifest其他元信息变更。

新增：model-waypoints.js前端、model-waypoints.css、platform/storage/src/model-waypoints.js、services/cloud-api/src/routes/waypoints.js。

修改：cloud-workspace.js、simulation-controller.js、workspace-session.js、云端server.js和workspace-pages.js。

## 固定制品

| 项目 | 固定值 |
|---|---|
| 新独立发布 | `/opt/thirdhand-stage/releases/7c7f4b5f3792288e` |
| 新manifest SHA256 | `7c7f4b5f3792288ec42d98ddbd25151ae192a766f8a7f16fd996afe6ba35f63c` |
| cloud.delta.json.gz | 299963字节 |
| 包SHA256 | `654eb9f00887beca0ef228d051d1cbf8223e8bd0ed81dcf6d629801bfdf453d5` |
| 最小授权SQL SHA256 | `9f73fa546cc27fac83eb88f8f192966e8234642dea400c9d1bd24bc4c615b67c` |

本地包位于本计划`.superpowers/sdd/2026-11-01-personal-model-waypoints/deployment-candidate`，源文件逐件摘要见candidate-summary.json。构建器为`tools/deploy/build_model_waypoints_release.py`；应用器为`tools/operations/apply_model_waypoints_cloud.py`，最终指纹见本计划freeze-pins.json。

## 本次拟执行的权限和服务器变更

```sql
GRANT USAGE ON SCHEMA simulation TO "thirdhand-stage";
GRANT SELECT,INSERT,DELETE ON simulation.user_programs TO "thirdhand-stage";
```

只用已有表，不新增/删除表、不修改现有账户和点位内容。角色不增加UPDATE、DDL、schema CREATE或其他表权限。接口仍要求有效会话/同源/CSRF和simulation.use；SQL中的user_id取自已鉴权principal，严格校验六轴/夹爪/名称、每人最多100项。

1. 在root拥有的0700目录`/var/backups/thirdhand/access-C6-model-waypoints-20261101`放入上述固定包、授权SQL与应用器；不上传测试、预览夹具、账户资料、密码或密钥。
2. 默认只读review校验旧current、旧清单全部文件、精确9件差异/4件新增、包及新manifest、受保护环境/展示站摘要、零控制权和在途命令、现有权限状态。旧版C3f安装器和账号部署租约守卫仅复用已在服务器安装且SHA固定的文件，任一变化即拒绝。
3. 获准后使用同一个C3d云安装锁和现有账号发布使用的control_leases SHARE维护守卫；先排空并阻止新控制权进入。保存发布及权限前状态，原子授予上面两个GRANT。
4. 原样复制旧发布到隐藏staging，只覆盖9件源码及manifest，全量核验后rename成新独立发布，再原子切换current，仅重启`thirdhand-stage.service`。整个过程保留已有账号、相机、环境及展示站配置；相机浏览器连接可能因API重启短暂重连。
5. 验证API健康、匿名接口拒绝、Observer个人模型点位真实保存/重新登录读取和回放；核对全量摘要、权限、零真机动作。用户自己的凭据由本人输入；不以预览夹具替代真实上线验收。

不修改Ubuntu、Robot、SDK、CAN、真机门禁、网络、证书或公网端口，不发送运动指令。

## 默认review、apply与rollback

```text
python3 /var/backups/thirdhand/access-C6-model-waypoints-20261101/apply_model_waypoints_cloud.py
python3 /var/backups/thirdhand/access-C6-model-waypoints-20261101/apply_model_waypoints_cloud.py --apply
python3 /var/backups/thirdhand/access-C6-model-waypoints-20261101/apply_model_waypoints_cloud.py --rollback
```

没有--apply/--rollback时只读审阅。新目录或staging已存在、旧发布/配置漂移或控制权非零时拒绝覆盖。自动/显式回退恢复完整旧账号发布，只切代码并重启API；**保留已保存点位以及本次获准的表权限**，不恢复数据库、不删除用户数据、不撤销或重放首批名单。若需要撤销表权限另行审阅；不得为撤销权限删除点位。

显式回退不依赖上传包、授权SQL或新发布内容完整，只依赖完整旧发布、root保存的before-public.json和两个固定已有维护工具。未知状态报告需要复核，保留现场。

## 验证与限制

- 最终public-access/Robot相关Node回归348/348、0fail/0skip；真实隔离PostgreSQL覆盖跨登录保留、账户隔离、CSRF/会话、恶意字段/严格数值、并发配额。独立审查仅1项P2请求卡死，已一轮RED→GREEN修复。
- 包与默认review/回退边界Python测试5/5；部署适配器另作一次针对性审阅，不复评产品。
- 本地浏览器真实点击保存、改变模型角度、调用、刷新及中文切换通过；1440和768像素实际页面宽度无横向溢出。Edge未实际应用375像素请求、仍报告768，未冒称手机验收通过。完整页截图曾超时，已使用正常视口截图。
- 预览使用合成模型和临时列表，截图不代表线上账号持久化；账户持久化由真实数据库/二次会话测试验证。
- 扩展到旧抓取/标定网页测试共791项，771通过、20失败：包括Windows symlink/fsync权限、旧校准哈希和旧grasp UI fixture缺失robot-viewer。没有改动这些无关模块或将其标为通过。
- 真机停止、真实限位/新基线、相机稳定视频等既有未通过项继续保留。此功能只保存/调用Three.js模型。

审阅准备时没有暂存、提交或推送本批变更，其他聊天已暂存的账户改动保留。后续用户在C6验收完成后另行授权按功能整理提交并推送fork/login，具体状态见[实际记录](2026-11-01-C6-model-waypoints-change.md)。
