# SDK实测显示修复：固定部署审阅（2026-11-03）

状态：用户批准后已上传并部署；后台校验通过，浏览器被动验收等待重新登录。源码提交 `26937d012cfff89215821d69cfa0059a015c2195`。

## 具体变更

云端只替换下表4件前端文件；将实测姿态显示与编辑限位分离。真实J2=-12.21°不会因编辑下限-12°而阻止整帧同步；原目标限位和管理员运动门禁不变。范围及证据见[修复记录](2026-11-03-sdk-measured-pose-fix.md)。

| 文件 | SHA256 |
|---|---|
| apps/web/public/js/i18n-cloud-catalog.js | c37d1ad0c2e6383d65716507418857c2eb4f8e74ffcb1ff575c8f6f8144acd57 |
| apps/web/public/js/robot-viewer.js | 7eb105580818340747a1373e2cd3650c988d0bdad72941a031af0066aaca4c47 |
| apps/web/public/js/simulation-controller.js | fbc7488875f99f252898c36e320a237e0e7b45f59f83ac519ba83b749b923f97 |
| apps/web/public/js/workspace-session.js | 722002d38ec7bf8f3a226dc072f9a60f9875a7c4df334e40b4b130a92d8e0109 |

## 固定材料

本地忽略目录 `.superpowers/sdd/2026-11-01-sdk-source-audit/`：

- `measured-pose-candidate/measured-pose-candidate.json.gz`：719716字节，SHA256 `ed7d4173499a257470a50360ceec75fa2254b40db48445733011a5e90621be4a`。
- `measured-pose-cloud-operator.py`：SHA256 `dd33f6dc2194dc266e2c23ccf598c393c706019c0a9abb73bf3a1c45e7c231a3`。默认预检；仅显式`MEASURED_POSE_APPLY=1`应用。
- 基线 `/opt/thirdhand-stage/releases/a287e6b5558f02b5`，manifest `a287e6b5558f02b5604263d0abba464831ff8df9faff4999fb43e840e3132edd`。
- 新发布 `/opt/thirdhand-stage/releases/2719d1b4fcdc6f06`，manifest `2719d1b4fcdc6f0677ddc9dcc9fa10c7211bd20500357b3abbf40dd24987c061`。
- 全4658件中仅4件变化，4654件完整保留；固定包只包含公开源码/摘要/路径，不包含用户信息或凭据。

## 执行与回退

1. 用户当前连接SDK时不得重启。先只读确认SDK已断开且requested/active/revoking租约及在途命令均0；等待空闲，不主动断开、抢占或初始化SDK。
2. 获批后上传上述包和应用器至`/var/backups/thirdhand/access-measured-pose-20261103/`，目录0700/文件0600，确认两件SHA一致。默认预检全量基线、metadata、unit/drop-in、保护文件与诊断开关。
3. 采用既有经SHA核验的安装锁及最多240秒准入暂停，再次确认空闲、备份、复制旧发布，仅替换四件并验证全量manifest。任一范围/配置漂移即停止，不自动覆盖其他人的发布。
4. 原子切current，仅重启thirdhand-stage.service。检查healthz、服务状态、全量manifest及保护文件；短暂停顿可能导致视频鉴权重建。无Ubuntu/相机服务重启，无数据库、权限、端口、网络、租约变化。
5. 失败自动切回a287e6b5558f02b5并重启同一业务API。事后回退也先确认current仍为本包、SDK及租约空闲，在同一锁内切回；保留发布/备份，不删除数据。
6. 内置浏览器在用户方便刷新时加载新版本，读取已有或用户显式连接产生的hardware反馈。核对3D/关节数值/夹爪/法兰及手动暂停；不申请/初始化SDK、不发运动。超编辑限位实测只有自然出现时才能做真实验收，不为复现移动真机。无自然越界样本时明确保留该验收限制。

## 验证与审批

78项Node/DOM/ArmModel测试和4项构建器测试通过；包含两套布局和两种角色、越界实测原值、手动目标仍拒绝、URDF编辑限位在异常路径恢复、草稿保留和无运动请求。构建器从提交读取源码，父提交与已部署基线逐文件一致。应用器语法检查通过，远端预检尚未执行。源码26937d0的CI运行41482183785已完成，public-access和test均success。固定包4件内容与Git提交逐字节一致，其余4654件与现行发布一致。

审批范围：上传上述两件固定材料、更新4件云端前端源码、仅重启staging业务API，然后被动反馈验收。依据已批准[C8方案](2026-11-01-C8-ui-sdk-audit-and-design.md)第9节第6步“固定源码/资源清单、数据库变更和回退材料完成后才申请实际部署”。新增robot-viewer.js不在上一六文件包内，因此需批准本次固定候选。

## 实际执行（2026-11-03，Asia/Shanghai）

11:26上传两件固定材料，SHA256与审阅逐字一致，权限收紧为0600，父目录0700。部署前Ubuntu SDK=false、readOnly=true；云端基线a287e6b5558f02b5，活跃租约和在途命令均0。最初只读检查调用旧helper的current_target，因未设置其旧常量而报CURRENT_RELEASE_CHANGED；改用直接只读解析current确认实际基线未漂移，未修改任何部署门禁。

默认固定应用器预检通过；MEASURED_POSE_APPLY=1执行成功。新发布2719d1b4fcdc6f06，全4658件校验通过，changed=4 / preserved=4654。仅thirdhand-stage.service重启，active；healthz返回thirdhand-cloud-api及explicit-read-only。保护摘要、服务unit、诊断开关均通过检查。未修改Ubuntu或租约参数，未初始化SDK/发送运动。备份和旧发布保留，无回退触发。

后台复核时活跃租约和在途命令仍0。内置浏览器会话已过期，已打开Observer登录验收页；尚未完成新版本真实SDK/3D被动反馈验收，不计作通过。截图为忽略目录measured-pose-deployed.png与measured-pose-health.png。
