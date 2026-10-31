# ThirdHand Public Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution method is selected by the user before implementation; this planning task does not dispatch implementers.

**Goal:** 在 uiea-thirdhand.com 提供独立登录、注册、两类角色、完整运行记录与 Three.js 模拟，并在验证通过后开放管理员外网真机控制。

**Architecture:** 云端前端、业务后端、私有 PostgreSQL；Ubuntu Agent 主动连接云端设备中继。模拟、只读数据和真机命令分通道，真机控制采用单设备独占控制权和设备本地失联策略。

**Tech Stack:** 现有 Node.js 24、Three.js 与 i18n；PostgreSQL；Python 3.11 Agent、SQLite outbox；Nginx/宝塔；mTLS/WSS；独立 WebRTC 媒体服务。

**Spec:** [已认可的设计 v0.4.1](../specs/2026-10-29-public-access-roles-database-design.md)；[校园网网关说明](../specs/2026-10-29-campus-network-gateway-deployment-guide.md)。

状态：2026-10-30 实施中。用户已选择在本会话逐项实施；登录视觉已批准。A/B 本地实现与证据见[实施状态](../../integration/public-access-implementation-status.md)。复选框仍区分本地实现与实际部署/现场验收，不因模拟测试通过就标为上线完成。

C1a网络准备已完成。C1b具体配置也已获批准，probe-only服务/mTLS及1802.250秒、3周期校园探测通过；详见[C1b实际记录](../../operations/2026-10-30-C1b-probe-change.md)。活动入口是系统Nginx。尚未发布账号或设备控制业务；真实公共证书续期尚未发生。

## Global Constraints

- 工作目录 `D:/claudeworkplace/thirdhand-login`，分支 `login`；已按用户澄清同步主仓库 Chenxi-Li24/UIEAclub_ThirdHand_VLA 的 main 至 `24c6f9c`。origin 仍是 fork，不覆盖原 main 未提交代码。
- 两类角色均注册，一个人一个账号；登录默认 Observer；角色必须由服务端授予，Administrator 模式强制 MFA。
- 观察员可看相机和全部机械臂记录、导出及回放；滑条、固定点位、动作序列仅驱动其独立 Three.js 模型；不能连接 SDK、语音控制或发送真实动作。
- 管理员可多端并发登录；每设备只允许一个具体会话/标签页持有控制权；接管先警告并确认停止，原人仍保持登录。
- 首次无偏好默认为英文、浅色，主题/背景/语言同步记忆；登录页的新视觉效果图先审批再编码。
- 队友拥有教程实现；仅做入口与接口适配，具体合并时连接，不自建另一套教程和进度数据库。
- Agent 传输心跳与管理员控制续期分开；起始控制续期 250 ms、本地期限 1 s，现有 Robot 状态新鲜度 500 ms 不放宽；参数需现场验证。
- SDK 默认不自动连接；重连不恢复动作；未知执行结果不自动重发；本地停止不依赖数据库可用。
- 原始采样及事件完整入库，观察员不因角色被降采样；无批准删除策略时不自动删除历史；首期不默认录像。
- 不把 3000/3004/3100/8766/5432 或旧裸控制代理公开。服务器配置、提交、推送、合并与真机动作分别按具体结果获得授权，不随本计划自动执行。

## Review Focus

1. 用户直接伪造模式、重放旧会话、绕过页面访问接口：逐请求与逐消息拒绝；由 A3、A5 验证。
2. 浏览器失联而云到设备仍通：云不得代续控制权；旧响应不能复活授权；由 B3 验证。
3. 相同采样换批次或时间戳、并发补传：数据库拒绝重叠序号范围，不能静默覆盖；由 B4 验证。
4. 共享电脑、多标签、多账号偏好和教程返回：不串账号、不循环跳转、不隐式连接 SDK；由 A4、A5 验证。
5. Agent 在线但 SDK worker 重启、停止未确认或相机过期：旧控制权失效，禁止接管/新运动；由 B2、B3、B6、C3 验证。

## 1. 子计划与顺序

系统跨账号界面、设备与数据、上线验收三个子系统，分别维护可独立验收的子计划，避免一次变更混入全部功能。

| 顺序 | 交付阶段 | 具体任务 | 验收结果 |
|---|---|---|---|
| 0 | 基线与协作边界 | A0 | login 基线明确，展示站来源和教程适配契约有记录 |
| 1 | 新登录视觉 | A4 的视觉步骤 | 浅色、英文、角色标签及注册/错误状态效果图获审阅 |
| 2 | PostgreSQL 与身份后端 | A1～A3 | 注册、验证邮箱、登录、MFA、会话、角色及用户管理可独立测试 |
| 3 | 登录和观察员工作台 | A4～A5 | 主题同步、教程适配、模型模拟和受保护入口可用，硬件调用计数为零 |
| 4 | 云入口与无硬件探针 | B1、C1 | 主域 SSL、edge DNS/mTLS/WSS 通过校园 Ubuntu 的持续测试 |
| 5 | 本机网关与模拟控制权 | B2～B3 | 模拟设备验证唯一控制、接管、撤销、过期与停止，不接真机 |
| 6 | 运行数据与历史 | B4～B5 | 原始数据持久化、断网补传、完整历史、导出和模型回放通过 |
| 7 | 受保护相机 | B6 | 两角色可看视频；退出可撤销，远控画面时效有测量 |
| 8 | 测试环境部署 | C2 | 账号、记录、视频、模拟全链路通过，旧静态站可回退 |
| 9 | 内网真机验收 | C3 | 现场确认后验证 SDK 状态、停止能力和全部本机入口仲裁 |
| 10 | 公网小范围试运行 | C4 | 首期一设备、10 观看者、单控制者，通过失联和接管验收后开放功能 |

云端网络准备可穿插本地开发，但不能用生产机械臂代替模拟测试；账号或网络完成并不表示真机控制自动开放。

- [子计划 A：身份、登录与观察员工作台](2026-10-30-login-identity-workspace.md)
- [子计划 B：设备网关、控制权、数据与相机](2026-10-30-device-data-control.md)
- [子计划 C：部署、校园网与真机验收](2026-10-30-deployment-acceptance.md)

## 2. 实施前的已知事实与输入

以下来自 2026-10-29 检查，执行时重新确认，不视为持续有效的在线状态：

- 云服务器 `47.94.95.244`，宝塔运维入口 35399；主域静态目录 `/www/wwwroot/uiea-thirdhand-static`，面板显示站点 SSL 未部署。
- 云端约 2 核、1.6 GB 内存、39 GB 磁盘；先确定 PostgreSQL 与视频的容量或拆分位置，不直接把全部生产服务塞进现有资源。
- 设备 Ubuntu `100.85.63.78` 可用 Tailscale SSH；用户 `nieqingcao`，仍验证原主机密钥，不关闭主机校验。
- 从 Ubuntu 到公网 IP 的路由为 wlp7s0 → 192.168.58.1，未使用 Tailscale Exit Node；HTTP 成功、443 被拒，设备子域尚未解析。
- `services/robot/src/config.js` 配置的轮询间隔为 50 ms，约 20 Hz 配置频率，并非实测发布速率；容量验收要用实际状态发布率，不能直接采用设计中的 10 Hz 算例。
- 展示站源码归属、队友教程真实接口与最终视频/停止指标在集成前确定。没有拿到接口时使用明确的未接入适配器，不编造完成状态。

## 3. 新模块边界

| 路径 | 职责 |
|---|---|
| `platform/identity/` | 人员账号、会话、模式、权限；不混用现有 platform/authorization 的机器人动作授权 |
| `platform/storage/` | PostgreSQL 连接、迁移、账号/动作/采样仓储 |
| `services/cloud-api/` | 同域业务 API、用户实时通道、历史查询和受保护工作台入口 |
| `services/device-relay/` | 设备证书绑定、设备连接、挑战/命令封装和转发；首期由 cloud-api 组合启动，模块独立 |
| `services/edge-agent/` | Python Agent、设备凭据、本地 outbox、Robot 适配与证据上报 |
| `apps/web/public/` | 复用现有 Three.js，新增独立登录/注册界面与模拟适配，不重写框架 |
| `deploy/public-access/` | 后续经审阅的 Nginx、进程、私网数据库、媒体配置模板和回退资料 |
| `tests/node/public_access/`、`tests/python/edge_agent/` | 权限、数据、网关与故障测试；不收集或导出生产密钥 |

上述目录已按阶段创建；仅批准的C1b探针部署子集已应用，业务/媒体/控制模板尚未应用。本地测试依赖和缓冲均不构成生产业务部署。

## 4. 阶段交接与检查点

- [x] 审阅本执行计划，选择在本会话逐项实施、阶段结束后复核。
- [ ] A 阶段通过后演示：注册、默认观察员、管理员无权限提示、MFA、模型模拟和多人会话。
- [ ] B 阶段通过后演示：无硬件设备在线、模拟接管、全量历史和相机，不宣称真机已可操作。
- [ ] C1/C2 对照拟应用配置、数据库迁移、服务列表和回退方案进行部署审阅；批准具体变更后再修改服务器。
- [ ] C3 前记录现场人员、设备绑定、允许目标和速度、停止判据；未填写不得发送运动。
- [ ] 每个阶段完成有针对性的测试与变更审阅，再整理范围明确的提交；提交、推送和 PR/合并须获得对应授权，不混入原 main 的改动。
- [ ] 实施记录与验收结果回填本计划，失败时停在本阶段解决，不跳过安全与数据完整性检查。

## 5. 自查结果

本次计划已按设计中的 22 个验收项核对任务归属：账号/模式与前端对应 A，网关/数据/媒体对应 B，生产运行与现场验收对应 C。旧控制入口旁路、设备执行代次、跨批次序号、教程单一来源与数据保留均有明确任务；实际测试与硬件结果尚未产生。
