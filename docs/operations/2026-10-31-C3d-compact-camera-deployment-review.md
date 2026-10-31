# C3d 相机短格式续期：部署审阅草稿

状态：**最终候选 d4f289af2fdac93c 已完成回归和目标预检，云端22:33、Ubuntu22:34应用成功。120秒实测仍有7次失败，相机稳定性未通过。** 两个旧候选 d5ca9/1d918 已作废，未上传。实际执行见[C3d记录](2026-10-31-C3d-compact-camera-change.md)。本批延续只读部署，不开放真机运动。

## 允许范围和当前基线

云端基线为 `/opt/thirdhand-stage/releases/04cc19054caa45a6`，manifest SHA-256 为 `04cc19054caa45a6406450ac058caf76935be4d51e0590499d28bac5a2fa4917`。旧 manifest 列出 4624 件文件；新 manifest 应列出 4625 件文件，唯一新增文件是 `services/cloud-api/src/media/compact-grant.js`。

| 位置 | 唯一允许的源码差异 | 服务操作 |
|---|---|---|
| 云端 | `services/device-relay/src/server.js`、`services/cloud-api/src/media/policy.js`、`services/cloud-api/src/device-runtime.js`；新增 `services/cloud-api/src/media/compact-grant.js` | 建立独立发布并切换 current，仅重启 `thirdhand-stage.service` |
| Ubuntu 相机发布 | `thirdhand_edge/media_upload.py`、`media_publisher.py`、`camera_runtime.py`；新增 `media_renewal.py` | 更新既有相机 publisher 的 PYTHONPATH drop-in，仅重启 `thirdhand-stage-camera-publisher.service` |

Ubuntu 旧源码为 `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-5bf518471ff7aa60`，以已冻结 C3c 相机 tar 的实际 20 模块及 manifest 为基线。新快照完整保留其余模块，共 21 个 `.py` 加 `source-manifest.json`；新目录名由完整文件摘要映射的 canonical SHA 前 16 位生成。

本批不修改 Agent 当前 `agent-source-aef304c8c1efc5de`，不重启 user edge、Robot、Vision 或 camera-source。不修改相机原生二进制、采集时间戳候选、SDK、CAN、限位、停止能力、运动门禁、数据库结构/权限、认证凭据、环境配置、邮件、端口或展示站。

compact-v1 仅在独立 camera-only 路径协商；已有 full grant 和旧路径保留兼容。600 ms HTTP 读超时、950 ms 授权有效期保持原值。具体协议正确性与冻结源码测试由相机实现证据单独记录；本部署工具不会代替它们，也不会通过放宽超时制造验收通过。

## 制品与冻结要求

主任务使用本地唯一构建器从准确 C3c 基线构建，不从当前工作树混入其余未提交内容。固定候选为 `compact-candidate-d4f289af2fdac93c`，完整 candidateDigest 为 `d4f289af2fdac93cdb0e4b292b6d12c64c9063bdc1b3f191cb878c633d51a4a9`。

| 制品 | 大小 | SHA-256 |
|---|---:|---|
| cloud.delta.json.gz | 292721 B | `55288baf01dcc7fc1cc1af998e680f25ab343fd563ab9eedbf54854cd79fdb7f` |
| camera.source.tar.gz | 32570 B | `f57ed683b2d406d87817caf4ad25e2ea63ccf1e569c497207f3440262024b142` |
| baseline-public.json | 2897 B | `c3481f0618852c8d409f2f863dd94d49806417a9faedc474ed307e0c5820ded3` |
| camera-publisher-compact.conf.template | 119 B | `d1b6632d07125f68f126cbc3d168fb14c9b7f0a9ed48d0fda138d324eb2f9d6a` |

新云发布为 `/opt/thirdhand-stage/releases/986ca7c282e532a8`，新 manifest SHA-256 为 `986ca7c282e532a83b91195759c7328c8ec906d57bd4113c9ccb3ac6ac9cafdb`。相机新来源为 `/home/nieqingcao/.local/share/thirdhand-stage-camera/20261031/source-4e49ee54335e9af3`，完整 sourceDigest 为 `4e49ee54335e9af34f3fffd365e6a0f9b776051cb8f03f9986220ae69f5110d6`，新相机 manifest SHA-256 为 `bfacedf9d5d068191d7e53842348011994f93de11d04019a673bb48355ce653a`。

最终云应用器 SHA-256：`58e465acbc8326d8023c7ed40eaa9eca4487ce010c56c7d2b7cb883693ae3cd2`；Ubuntu 应用器：`c59d14dbaa3da1a7bd84e7acc20336a39a065bf877e40afdb7ade29af68de9e4`。当前代码已填入最终固定常量。

旧相机 manifest 的实际完整 SHA 为 `4f5202619c9957377396532c8d889e6b704b6529c7f50cb76c310e16c015437a`；它不同于旧来源目录名的前缀，必须核对实际文件。最终操作前须核验：

- 新云发布路径和新 manifest 的完整 SHA-256。
- `cloud.delta.json.gz` 的 SHA-256；包内 changes 必须精确为上述四个云文件，beforeHashes 必须精确为三个已有文件。
- `camera.source.tar.gz`、`baseline-public.json`、`camera-publisher-compact.conf.template` 的 SHA-256，以及相机新源码完整摘要。
- 旧相机 `source-manifest.json` 完整 SHA-256；不得只核对目录名前缀。
- 两个应用器与以上最终 SHA-256 一致；所有实际目标检查通过后才应用。

`baseline-public.json` 包含公开 cloud/camera 基线。新相机 manifest 使用 `role=camera-compact-candidate`、`automaticSdkConnect=false`、旧20/新21个精确文件摘要及上述四个 changedFiles。模板严格只有 `[Service]` 和一行新 PYTHONPATH，不包含私有配置。新源码包只编译 Python 字节检查语法，不执行模块导入。

## 云端应用器

工具为 `tools/operations/apply_compact_camera_cloud.py`。须使用已核验的 Linux root 和 **Python≥3.9** 环境；固定审阅目录为 `/var/backups/thirdhand/access-C3d-compact-camera-20261031`，由 root 持有且权限 0700。默认仅审阅，不创建发布或备份。原 manifest 中单件文件受 16 MiB 读取上限保护；真实旧文件超界时应停止，不能未经核验调大阈值。

`--apply` 和显式 `--rollback` 取得同一个非阻塞安装锁；占用时返回 `INSTALLER_BUSY`。应用前完整检查旧发布清单和每件文件，拒绝未知额外文件、链接或已有新目录碰撞。新发布只覆盖允许四个文件及 manifest；验证完整新清单后才原子切换 current。每次切换、API 重启和最终确认前都检查 requested/active/revoking 租约数量为零，并检查原 `cloud.env` 与展示站首页摘要保持一致。

固定备份目录保存旧发布标识与受保护文件摘要，不复制或打印文件内容。失败时在无租约且状态仍明确的条件下恢复旧发布并仅重启同一 API；无法确认则报告回退 blocked。显式回退依赖固定旧 04cc 发布及本机备份，**不依赖上传包或完整新发布**；新包丢失、新目录文件损坏均不能成为拒绝恢复已核验旧版本的条件。新旧发布均保留。

## Ubuntu 相机应用器

工具为 `tools/operations/apply_compact_camera_ubuntu.py`，由 **nieqingcao / UID1000、Python≥3.11** 执行。固定 incoming 为 `.../thirdhand-stage-device/20261031/incoming/compact-camera-candidate`；固定私有审阅目录为 `.../thirdhand-stage-camera/20261031/compact-camera-review-C3d`，0700、UID1000。默认审阅不写入。

仅允许覆盖原已知文件：

```text
/etc/systemd/system/thirdhand-stage-camera-publisher.service.d/50-C3c-transport.conf
```

原主单元 SHA 固定为 `c604a65a072f9cc83d1ebe0d08c72f8f95c7faf12148fd64f99c2c0dc0c42e51`；既有 drop-in 必须逐字节指向旧相机来源。默认/apply/rollback 均检查磁盘目录中所有 `.conf` 与已加载 DropInPaths；任何外部配置、符号链接、主单元或原文件未知改动均停止。新目录只允许精确 21 模块和 manifest，拒绝 tar 链接、路径逃逸、重复成员或额外文件；校验后文件设为 0400、目录 0500。

应用前必须提供本次真实核验的公开云记录 `--cloud-review-file` 和 `--cloud-review-sha256`。其格式沿用 C3c：verified=true、准确新云 currentRelease、准确 deviceId、整数 activeLeases=0、带时区 checkedAt。记录由 UID1000 持有、0600、非链接，最多60秒、未来误差最多5秒。它不能代替跨主机维护约束；主任务须保证切换期间无人重新申请控制权。

应用器只在内存读取现有 `private/edge.token`，对回环 Robot GET 查询 SDK/readOnly/connected/moving。必须 SDK=false、readOnly=true、connected=false、moving=false；未知即停止，不主动连接或停止 SDK。每次 drop-in 写入、daemon-reload、实际 restart 和最终成功前重复检查同一云记录、本机状态和外部配置。记录过期返回 `CLOUD_REVIEW_STALE`；回退过程报告 blocked，保留已恢复部分，凭新的真实记录继续。

备份仅保存公开固定基线与原 PYTHONPATH 文件。回退**恢复原 50-C3c 文件内容，不删除该文件**，因为 C3c 的这份 drop-in 原本已存在；不撤回第一批 C3c 修复。显式回退与 apply 取得同一安装锁，自动回退沿用已持有锁。新包丢失或新源码损坏时，仍可凭固定旧基线恢复。即使配置已指向旧目录，也会完成仅 publisher 的重载/重启，以确认中断后的实际进程恢复；不重启其它单元，不清空状态/outbox，不以重启代替物理停止。

## 本地验证与尚待执行

当前自包含云工具 **14 项**、Ubuntu 工具 **22 项**合成测试通过；连同第一批 C3c 工具、打包及既有部署专项共 **87/87** 通过，无跳过。覆盖默认无写、精确新增文件清单、未知源与新目录碰撞、坏 tar、SDK状态变化、两入口安装锁冲突、上传/新源码损坏后独立回退、回退各阶段60秒记录过期与新记录恢复、磁盘未加载外部配置和私有备份目录链接拒绝。夹具不依赖忽略目录中的真实源码包或私有文件，不触发网络/服务命令。证据为本计划 `compact-camera-helpers-green.txt`、`compact-camera-helpers-regression.txt`。

最终实际制品本地只读校验和两个目标环境预检均通过；云端旧4624件、精确4差异、Ubuntu旧20/新21模块及唯一既有drop-in均核验后分步应用。最终相关Node268/268、Python205/205通过。实际120秒仍有7次超时/到期；部署完成不等于相机稳定或外网运动可用。
