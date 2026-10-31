# ThirdHand Deployment and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans after plan review. Checkboxes track work actually completed; writing a template does not apply a production configuration.

**Goal:** 从校园 Ubuntu 验证云入口，在测试环境集成账号/数据/媒体，完成现场安全验证后分阶段开放公网真机功能。

**Architecture:** 宝塔/Nginx 管理用户和设备入口；云业务与 PostgreSQL 私有访问；设备 Agent 由 systemd 管理；物理执行始终在 Ubuntu，保持独立急停和控制仲裁。

**Tech Stack:** 已有宝塔、Nginx、Node.js 24、Python 3.11、PostgreSQL、独立媒体服务、mTLS、Tailscale 仅运维。

**Spec:** [设计 v0.4.1](../specs/2026-10-29-public-access-roles-database-design.md)、[网关配置说明](../specs/2026-10-29-campus-network-gateway-deployment-guide.md)、[总计划](2026-10-30-public-access-rollout.md)。

## Global Constraints

所有实际配置在实施前先展示确切目标、配置差异、备份与回退。数据库/硬件不用于破坏性测试；外网仅开放所需业务/媒体入口，不公开裸 SDK。真实运动需明确现场确认及允许范围，设计认可不替代实际运动授权。

## Review Focus

配置不同于旧快照、TLS/WSS 只在某一网络可用、备份恢复复活旧授权、SDK 停止未确认和上线后旁路，分别由 C1～C4 验证。

## C1 云入口与校园网探针

**Files:** 新增 `deploy/public-access/nginx/site.conf.template`、`edge.conf.template`、`env.example`、`README.md`；新增 `tools/diagnostics/public-access-probe.py`、`docs/operations/public-access-readiness.md`。模板只有占位路径，实际密钥不入库。

**Interfaces:** B1 `/edge/v1/healthz` 与 WSS 设备连接；实际持续探针为独立venv中的 `thirdhand_edge.probe --config <私有配置> --duration-seconds 1800 --cycles 3`，输出不含私钥/令牌的连接与RTT报告，不加载SDK或相机。

2026-10-30更新：C1a网络准备完成；C1b具体批准范围已应用并通过，probe-only PG/relay/mTLS及1802.250秒/3周期校园探测完成，见[C1b实际记录](../../operations/2026-10-30-C1b-probe-change.md)。真实公共CA换证、校园重新认证/网络切换仍未测，故不把C1全部标为通过。活动服务是系统Nginx，宝塔用于运维与签发。

- [x] 重新只读确认 DNS、主域/edge 站点 SSL、云端 443 监听、安全组与系统防火墙；校园目标使用 Ubuntu `100.85.63.78`，通过验证过的 SSH 密钥接入；复查公共目标路由与 Exit Node，记录实际测试来源。
- [x] 在用户批准的C1a范围内备份并应用：edge A、主域/edge公共HTTPS、TCP443现有规则检查；主站200、edge关闭404、可信TLS1.2/1.3验证通过，未发布业务。
- [ ] 审阅并验证续期后的活动系统Nginx重载；不把宝塔续签状态等同于公网已换证。后续业务模板调整为实际 `/etc/nginx` 站点include。
- [x] 安装针对实际系统Nginx的公共TLS维护单元；受限环境无变化检查及目录事件触发通过，实际CA换证仍待观察。
- [x] 准备主域 SSL、edge DNS/SSL/mTLS、反代本机中继、进程与端口差异，以及旧站点备份和回退；先审阅实际配置，再在获准范围内应用，不整段覆盖未知宝塔配置。
- [x] 在不带设备证书时验证设备入口拒绝；带有效设备证书时 health 与 WSS 101 正常；普通网页不能被设备证书要求误挡。确认宝塔运维账号不等于网站管理员。
- [x] 完成本次批准的1800秒/3周期校园无SDK探测：实际1802.250秒、840次心跳、无意外中断；结束后原站HTTP/HTTPS200、哈希保持一致。
- [ ] 只用 B1 探针从校园 Ubuntu 连续跑至少 30～60 分钟，覆盖 ping/pong、重连、夜间认证/网络切换情形；记录最大停顿和高分位 RTT；不连接 SDK、不上传视频。未通过就先排障，不进入公网真机。

## C2 测试环境集成、部署和恢复

**Files:** 新增 `deploy/public-access/compose.test.yml`、`systemd/thirdhand-edge.service.template`、`backup.md`、`rollback.md`；新增 `tests/integration/public_access/test_remote_flow.py`、`tests/node/public_access/restore-state.test.js`；更新 `.github/workflows/ci.yml` 纳入无硬件集成测试。

**Interfaces:** 使用 A 的身份/模式/工作台、B 的模拟设备/采样/媒体；测试域名与数据库、设备证书和密钥空间独立于生产。

- [x] 写集成断言：注册到 Observer、管理员 MFA、观察员访问全部记录、模拟调用零真机命令、多管理员登录不抢占、显式接管才撤权。
- [x] 运行 `python -m pytest -q tests/integration/public_access/test_remote_flow.py`、`node --test tests/node/public_access/restore-state.test.js` 确认未接好时明确失败；实现隔离编排与测试桩，不用真实现场设备填补测试缺口。
- [x] 在独立staging域名应用迁移/运行身份/模板；两角色浏览器流程、教程适配契约、英文浅色默认及账号偏好持久化通过。未合并的正式教程不计上线完成。
- [ ] 队友正式教程合并、两个展示入口（用户暂缓），以及不同真实终端的进一步验收仍保留。
- [x] 同一无硬件测试命令绿灯；实际基准备份+后续WAL命名恢复点、维护回退和7类数据导出通过。恢复副本撤销会话/一次性令牌/旧MFA/设备凭据与控制权，模拟外部BigInt下界核对通过，不重放未决命令。
- [ ] 真实设备保留的最高代次及恢复后新握手依赖C3现场证据；本次未用模拟数据冒充。
- [ ] 核实数据库与视频容量：以真实源频率、运行时长、采样/事件和备份增长确认资源；达不到预算时拆分或调整经批准的保留策略，不默默丢原始数据。

本次获准的C2无硬件业务部署范围已完成，见[C2实际记录](../../operations/2026-10-30-C2-business-staging-change.md)。
随后真实阿里云SMTP、用户注册验证、初始管理员及MFA已完成。C2g相机部署另获具体批准并已应用，见[C2g实际记录](../../operations/2026-10-31-C2g-camera-change.md)：真实管理员视频、双观看、两角色鉴权及正常退出清除通过。用户随后明确批准35秒网络撤销故障，已执行三轮且规则均自动清理；观察到503停播，但同步时序断言未通过，完整故障验收仍未完成。正常运行仍偶发响应头超时。长时/十人容量和遥测真实源容量仍未完成。

后续[C2i](../../operations/2026-10-31-C2i-camera-request-timeout.md)部署小报告合并发送修复。用户恢复会话后，两路真实Observer视频、300.018秒/61次后台监测、同步35秒撤销失败故障、独立清理和恢复后观看通过；原三轮未通过记录保留。另有一次修复后、双路窗口前的自然超时保留，未将长期稳定性、十人容量、解码隐私截止或公网SDK控制一并标为完成。

## C3 内网真机与现场验收

**Files:** 新增 `docs/acceptance/public-access-hardware.md`、`tools/diagnostics/remote-control-preflight.py`；按 B2/B3 修改配置，只有经过验证的环境可启用 remote_control；用户账号、设备私钥和轨迹实测文件按资料策略保存，不提交秘密。

**Interfaces:** preflight 只读取身份、配置、源状态时间、控制代次、视频时效和停止能力证据；默认不 connect、不运动。硬件测试记录包含值守人员、设备绑定、目标/速度/最大时长、停止阈值和实际结果。

- [ ] 现场确认机械臂/适配器与配置，核对可用唯一身份；没有可靠身份接口时执行设计中的人工绑定。确认物理急停可用、工作区清空、人员与允许动作已明确批准。
- [x] 先做授权 connect/status/disconnect 与状态读取，观察电机状态，不自动执行 Home 或全零点；核对六关节、CAN 反馈、配置与时间。2026-10-31现场条件确认后，本机24条六关节状态与断开确认通过，运动命令0条，见[C3预检](../../operations/2026-10-31-C3-device-camera-preflight.md)；公网控制/唯一身份/运动和停止验收仍未完成。
- [ ] 在单独批准的最小运动范围内验证手动、固定点、序列、夹爪、语音、抓取与 Dummy 的对应路径；尚无可验收动作的功能保持禁用，不用“全功能管理员”绕过前置条件。
- [ ] 逐项故障注入：浏览器断开、云到设备断开、Agent 终止、SDK worker 重启、停止失败、视频陈旧、云数据库不可写；测量本地超时与实际停止确认。停止不达标时终止该功能验收，保留硬件急停/现场处理，不自动扩大安全超时。
- [ ] 验证本机网页、CLI 与后台任务均参与控制仲裁，维护状态撤销远控；验收记录明确通过/未通过/未测，而非全部默认完成。

## C4 小范围外网试运行与交付

**Files:** 新增 `docs/acceptance/public-access-release.md`、`docs/operations/public-access-runbook.md`；更新部署配置与用户文档；准备 login 的分阶段提交与 PR 说明，不混入其他分支改动。

**Interfaces:** A/B/C1～C3 的验收报告；发布物固定提交、迁移版本、依赖锁、模型资产清单、证书引用和回退步骤。生产真实凭据不进入发布包。

- [ ] 整理候选差异和全量无硬件回归，复查权限与 WebSocket 会话撤销；核对外网开放端口、备份和告警，生成可审阅发布清单。按用户授权提交、推送或创建 PR；未获授权不执行最终发布。
- [ ] 获准后先上线注册、观察、模型模拟、历史和相机；使用明确范围的初始管理员账号，验证观察员直接调用旧路径也不能触达 SDK。
- [ ] 现场值守下逐步开放已验收真机功能；从外网测试一个控制者与第二管理员接管，再压测首期 10 个观看者；检查带宽、CPU、内存、数据积压、状态与画面时效。
- [ ] 异常时关闭新真机授权、请求本地停止并确认，再切回只读/维护；不能直接用旧无鉴权 9983 服务回退为公网控制入口。数据库通常前滚修复，不以破坏性降级迁移实现回退。
- [ ] 交付管理员/观察员说明、设备登记与密钥轮换、告警、备份恢复和队友教程合并记录；最终发布报告列出每个启用功能、未启用功能与实测指标。

## 运行与提交规则

计划编写阶段不执行上述部署、SDK 或运动步骤。实施时每个阶段均需要相应测试证据；频繁小提交是代码组织方式，提交/推送和外部配置仍遵循用户授权。服务器扩容、付费服务、邮件实际发送、设备访问控制变化和生产发布不得由测试自动触发。
