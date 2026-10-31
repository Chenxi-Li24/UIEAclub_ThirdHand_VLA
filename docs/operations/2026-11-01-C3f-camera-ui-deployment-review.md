# C3f 相机观看恢复：云端单文件部署审阅

实际状态补充：本批已上线，随后并行账号发布保留此脚本；实际观看仍未通过。以[实际变更记录](2026-11-01-C3f-camera-ui-change.md)的版本、结果和回退限制为准，下文保留原审阅内容。

状态：**本地候选和应用工具已准备，尚未上传、预检或部署。** 相机前端经过独立复核，无实质发现；实际校园网络仍有600 ms授权失败，持续观看和外网运动验收仍未通过。本批只修复用户已点击 Watch 后的观看恢复，不连接SDK或操作机械臂。

## 范围与真实基线

当前云端发布为 `/opt/thirdhand-stage/releases/986ca7c282e532a8`，完整 manifest SHA-256 为 `986ca7c282e532a83b91195759c7328c8ec906d57bd4113c9ccb3ac6ac9cafdb`。清单实际包含4625件文件；本批只替换其中一件，其余4624件逐字节保留，文件数仍为4625。manifest中除这一文件摘要外的所有字段保持原值。

| 唯一发布差异 | 旧 SHA-256 | 新 SHA-256 |
|---|---|---|
| `apps/web/public/js/camera-view.js` | `4e14379d011652577a04b854e669cdaf3d53fc69126e8e44269266d571dac12f` | `1928d6017925dc09ca35acca021f24d48ca40ae0b3ac7354c79091c8e89bd64f` |

不改业务后端、数据库、权限、环境配置、证书、端口、Ubuntu服务、Robot、SDK、CAN、展示站或授权有效期。服务操作仅允许重启一次 `thirdhand-stage.service`；失败回退时同样只重启此服务。切换会短暂影响网页连接，应在控制租约持续为零的维护窗口进行；零租约检查不代替现场急停或运动验收。

## 页面行为

用户明确点击 Watch 后，发布者断线、取消视频订阅，或12秒没有订阅/解码帧进展，会回收旧观看连接并尝试取得新发布者的授权。自动恢复最多6次，退避依次为1、2、4、8、8、8秒；偶尔收到一帧也不会重置这个上限。耗尽后显示不可用，需要用户再次点击 Watch。

每次恢复先重新查询当前登录会话，核对用户、会话和模式；旧 Room断开以及旧viewer的`closed:true`确认均完成后，才申请新viewer。5秒内不能确认清理、12秒授权/连接超时、权限拒绝或身份变化均终止当前意图。若授权HTTP请求仍未返回，不把超时当作服务器已撤销：它会阻止新的Watch，直到晚到结果被回收。

Close、Sign out、浏览器标签页隐藏、pagehide和页面销毁均立即本地停播并清除恢复意图，重新显示标签页不会自动恢复。工作台内部换页保留原明确观看意图。不会恢复SDK连接、语音或运动。500 ms已验证画面新鲜度规则、600 ms设备请求和950 ms发布授权均未改动，状态提示沿用已有中英文文案。

## 固定制品

候选目录为本计划忽略目录下 `camera-view-recovery/candidate-6edc4258818b6b65`。构建只读取固定C3d包中的准确986 manifest，加上已经冻结的单个前端文件；没有打包当前工作树中的其他未提交内容。

| 内容 | 值 |
|---|---|
| 新独立发布 | `/opt/thirdhand-stage/releases/6edc4258818b6b65` |
| 新 manifest SHA-256 | `6edc4258818b6b65cc305a15af6b075a217f7b836e7d51e90ec836c5a1add0bd` |
| `cloud.delta.json.gz` | 282010 B |
| delta SHA-256 | `7090e30630c214b89d4cc2473ad2db0faff717edc23133b8226c153db319a455` |
| `expected-manifest.json` SHA-256 | 与新 manifest SHA-256相同 |
| 应用工具 | `tools/operations/apply_camera_ui_cloud.py` |
| 应用工具 SHA-256 | `d10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f` |

delta只含一个文件的内容、旧文件摘要和完整新manifest，不含运行目录、依赖副本、账户数据或秘密配置。`expected-manifest.json`供独立审阅；应用器以包内同一manifest的固定完整摘要核验。

## 默认审阅与应用步骤

应用器要求Linux root、Python≥3.9。准备固定root拥有的0700目录 `/var/backups/thirdhand/access-C3f-camera-ui-20261101`，上传准确delta和工具，核对以上摘要。原C3d私有目录也必须保持root拥有、0700。

默认执行以下命令仅审阅；不建立锁文件、备份或发布，不重启服务：

```text
python3 /var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py
```

工具检查实际current仍指向986，验证旧manifest、4625件文件完整库存和每件SHA，拒绝链接、源文件变化、额外文件、新发布或staging路径碰撞。核对压缩包固定SHA、精确一个变更、无文件新增/删除、无额外源码变化、无manifest元信息变化，并查询requested/active/revoking租约数量必须为零。环境文件与展示站首页只计算摘要，不打印内容。

取得这组具体检查结果后，主任务在已授权范围内决定是否添加`--apply`。apply和`--rollback`使用同一个非阻塞锁，并复用C3d实际云安装锁：

```text
/var/backups/thirdhand/access-C3d-compact-camera-20261031/installer.lock
```

占用时返回`INSTALLER_BUSY`，拒绝并行切换。应用器先保存只含旧发布标识及受保护配置摘要的0600本机备份，再复制旧发布到新发布同级的隐藏staging目录；覆盖唯一前端文件与manifest，全量验哈希，再检查零租约及受保护配置，最后rename为正式新目录。原子替换current链接前后以及API重启后，均重新核对current、旧/新完整文件、零租约及环境/展示站摘要。任何未知状态停止，不自动覆盖现有目标；失败遗留的staging或候选目录留供检查，不递归删除。

## 回退与复核

```text
python3 /var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py --rollback
```

显式回退只依赖完整旧986发布与C3f本机公开备份；上传包丢失、新发布丢失或损坏均不会阻挡恢复。回退同样核验current属于本次新旧两者、旧发布全部文件、零租约、环境/展示站摘要，再原子恢复旧current并只重启API。若出现新租约或外部配置变化，报告blocked并保留现场，不抢占控制权或覆盖外部修改。应用失败后自动回退沿用已持有锁，采用相同条件。

部署后需要重新加载控制页使浏览器取得新脚本，再由用户明确点击Watch。复核观察员可在发布者恢复时取得新画面、旧观看连接被撤销、Close/退出/隐藏立即停播、反复失败达到上限后停止。网络故障依旧时应如实记录失败，不能以这项UI修改宣称30分钟稳定观看或真机运动可用。

## 本地证据与尚待完成

- `camera-view-recovery/red.log`：原界面6项行为失败；`race-red.log`另证授权超时后未决旧grant竞争。
- `green.log`：相机/会话15项通过；`ui-local-green.log`：相关UI24项通过。独立复核相机13项通过，无实质发现。
- `deploy-red.log`：旧C3d多文件/新增文件逻辑不满足本次单文件替换，10项失败；`deploy-green.log`：新C3f工具24项合成测试通过。
- 工具测试覆盖默认零写、精确替换与元信息保持、隐藏staging后发布、额外变化/新增/删除/错误摘要拒绝、旧源变化/current变化/目标碰撞、同锁冲突、包丢失或候选丢失/损坏后独立回退、重启失败恢复、新租约阻挡重启/回退、外部展示页修改不被覆盖。
- `deploy-package-validation.json`：真实本地delta通过应用器只读解析，确认4625件、只改一件、其余4624件保留。没有执行远端应用器路径，也未读取实际私有凭据。

完整Node/Python回归由主任务在其既有PostgreSQL及回环网络环境完成；本分任务不重复广测。真实服务器默认审阅、实际应用、浏览器可用画面及故障验证尚待主任务完成。Ubuntu工作进程watchdog为独立C3e批次，不包含在本包内。
