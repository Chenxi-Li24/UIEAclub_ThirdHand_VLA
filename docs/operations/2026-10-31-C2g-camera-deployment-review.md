# C2g 受保护相机测试部署审阅（2026-10-31）

状态：本文件是已获用户批准的配置范围历史记录，配置现已应用。实际版本、排障、通过项和待验收项见 [C2g 实际记录](2026-10-31-C2g-camera-change.md)；后文的“候选／尚未应用”描述保留其审阅时点含义，不代表当前状态。

## 目标与边界

把 Ubuntu 已有 XVisio 视频送到 `https://staging.uiea-thirdhand.com/control#vision`，已登录的观察员和管理员均可观看。首期最多两个观看会话，单路发布上限沿用 800 kbps、15 fps；服务器固定公网带宽 3 Mbps，实际双观看、长时稳定性和退出撤销仍需测量，不能宣称十人容量已通过。

本阶段只接相机。云端不组合 controlService，SDK 控制接口保持不可用；设备能力明确为 `remoteControlEnabled=false`，中继也拒绝带控制能力的登记记录。浏览器无发布、麦克风、数据发送或房间管理权限。

## 已有证据

- [真机与相机预检](2026-10-31-C3-device-camera-preflight.md)：实际 SDK 非运动通信通过，真实相机经本机 SFU 解码通过；两者最终状态明确。
- Node 公网业务全套 130/130 通过、0 跳过；Python Ubuntu 边缘测试 26/26，须 root 所有者的 TLS 助手模拟测试 3/3；发布包私钥过滤测试 1/1。
- 官方浏览器 SDK 2.23.0 默认走 `/rtc/v1`。补充新旧路径和同源诊断验证，观察到旧规则 403 的 RED 后修复为 GREEN；退出后两条路径仍被拒绝。
- 候选 Nginx 片段已在云端独立备份目录用实际 `/usr/sbin/nginx -t` 校验通过；没有 reload、启动测试监听或修改活动配置。
- 云端本次采样总内存 1,647,516 KiB，可用 658,936 KiB，磁盘可用 28,802,064,384 字节。该采样不是峰值或容量结论。

## 确切网络变更

| 位置 | 候选变更 |
|---|---|
| 阿里云该实例安全组及当前有效主机防火墙 | 仅新增公网 TCP 7881、UDP 7882 入站，供经过鉴权的 WebRTC 媒体连接 |
| TCP 7880 | 仅监听 127.0.0.1；不新增安全组放行，不暴露原生 SFU API |
| staging HTTPS 443 | 添加 `/media/rtc`、`/media/rtc/validate`、`/media/rtc/v1`、`/media/rtc/v1/validate`；每次建连/重连经过业务会话鉴权 |
| 内部鉴权 | `/internal/v1/media-auth` 是 Nginx internal 路由，外部直接访问不得成功；转发覆盖 Cookie、原 URI、Origin、Sec-Fetch-Site |
| edge HTTPS 443 | 严格 mTLS 保持；新增唯一相机证书的路由及 `/edge/v1/media-grant`，旧探针 connect/healthz 继续走原中继 |
| Ubuntu | 仅主动向现有 edge/staging 443 和媒体端口建立连接；源适配器只监听 127.0.0.1:3112 |

不增加 DNS 记录，不把 Ubuntu 3000、3100、3112、9983、SDK、相机原始地址或数据库开放到公网。不购买资源。TURN/SIP/录制服务均不启用；若校园网同时限制两个 ICE 端口，应先报告测试失败，再审阅 TURN/TLS 方案。

端口依据：[LiveKit 官方端口说明](https://docs.livekit.io/transport/self-hosting/ports-firewall/)。

## 发布物与实际文件

业务候选包：4,613 个文件、15,790,432 字节，SHA-256 `bbb537fe91f3ce2aa24ca9741598ba5d4a4038b4a89326debe628a6ef05acb82`；manifest SHA-256 `dedd2ce315287733e2846ac8c9ebe7da168de887c67e6bd9a8b6848d96eed171`。只在全量文件清单和逐文件哈希匹配后切换，新目录预计 `/opt/thirdhand-stage/releases/bbb537fe91f3ce2a/`；旧 `c8f42e8d92bbe2c7` 保留。

LiveKit 固定官方版本 1.13.11，归档 SHA-256 `1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb`，二进制 SHA-256 `85a58024d9b36542712514e0e926c0adb74f6182bcb19a664b9d9eb98ad01b52`。使用已有 Node 24.22.1；新增 Node SDK 固定 2.19.2，浏览器 2.23.0，Python RTC 1.2.0。

| 目标 | 内容与权限 |
|---|---|
| `/opt/thirdhand-stage-media/bin/livekit-server` | 校验后的官方二进制，独立 nologin 身份 thirdhand-media 运行 |
| `/etc/thirdhand-stage-media/livekit.yaml` | 0600，thirdhand-media 所有；独立 API 密钥，只有 SFU/API 两个服务持有 |
| `/etc/thirdhand-stage/cloud.env` | 原文件备份后追加完整 MEDIA_*；独立 Ed25519 签名密钥，保留 0600 root，不输出内容 |
| `/etc/systemd/system/thirdhand-stage-media.service` | 新 SFU，MemoryMax 192M、CPUQuota 100%，无 SDK/录制 |
| `/etc/systemd/system/thirdhand-stage.service.d/camera.conf` | API 主组 thirdhand-stage-edge，补充原 stage/db 组；运行目录 0750、socket 0660；API MemoryMax 从 192M 到 256M |
| Unix 共享组 | 新建 thirdhand-stage-edge，仅把现有 Nginx 用户 www-data 加入该组；用于新设备 socket，不扩大数据库权限 |
| `/etc/nginx/conf.d/thirdhand-stage-media-routing.conf` | 精确相机证书 CN 路由、固定 Unix upstream；证书 CN 仅用于选路，授权仍验证登记 SHA-256 与签名 |
| `/etc/thirdhand-stage/media-locations.inc` | 受保护的媒体信令片段，屏蔽含 JWT 的请求日志 |
| `/etc/nginx/sites-available/staging.uiea-thirdhand.com` | 仅在既有 HTTPS server 内加入媒体片段 |
| `/etc/nginx/sites-available/edge.uiea-thirdhand.com` | 仅替换 connect/healthz location 为审阅的三路径 mTLS 转发 |
| Ubuntu 独立私有目录与 source 快照 | 复用已隔离的相机 venv、另存只读源码，不修改两个活动 Git 目录 |
| Ubuntu 新系统单元 | thirdhand-stage-camera-source / thirdhand-stage-camera-publisher，以 nieqingcao 运行，只通过既有相机 HTTP 流读画面；PrivateDevices，地址族不允许 AF_CAN |

模板位于 `deploy/public-access/staging/media/`：livekit.yaml.template、两份云端单元、两个 Ubuntu 单元模板、routing.conf、media-locations.inc、edge-location.inc、camera.env.example。候选尚未把这些文件安装为活动配置。

## 设备登记与秘密

仅在 staging 数据库登记一个相机设备：

- device UUID：`006e0cac-cf10-427e-a84c-42c260b3ac4e`；显示名 `Lab Ubuntu · XVisio camera`。
- credential UUID：`550b647b-1529-4776-8bd1-28f6c2795c26`。
- 能力：camera=true、remoteControlEnabled=false；不写执行实例、控制租约或机器人命令。
- Ubuntu 上生成单独 Ed25519 私钥和 CSR，私钥始终留在 Ubuntu、0600，不复用旧探针私钥。
- 现有临时 staging 探针 CA 为其签发 clientAuth 证书，CN 固定 `thirdhand-stage-camera-20261031`，有效期 14 天且不得超出 CA 的 2026-11-29 到期日。
- 云端只登记证书、公钥、实际 SHA-256、有效期；业务运行身份仍只读登记表，不加数据库超级权限。
- 独立随机 LiveKit API 凭据与媒体租约签名密钥由服务器本地生成，签名公钥交给相机 Agent。秘密不写 Git、聊天或截图。

该证书只允许相机链路，不是公网机械臂控制凭据。正式生产证书轮换和独立 CA 另行验收。

## 应用与验收顺序

1. 重新核对现场相机正常、活动版本、内存、有效安全组、防火墙、Nginx 用户/证书；备份活动配置、组成员、监听、PG dump、现有服务与版本指向，保存校验和。
2. 安装独立固定版本 SFU 与完整候选业务发布物，核验全部哈希；创建私有身份/目录/媒体凭据，签发并登记相机专用证书。
3. 安装云端单元和 Nginx 片段；先测试配置，再受控重启 staging API/新 SFU、reload Nginx。主展示站和旧探针必须继续工作。
4. 仅开放上表两个媒体端口；核对 7880、PG、Robot 均未获得公网监听。
5. Ubuntu 启动独立源适配器与 camera-only publisher；保持旧 Vision/Robot/Web 单元不变，不调用 SDK。
6. 验证真实 mTLS 连通、短期出版租约续期、实际视频帧及两角色浏览器观看；最大两会话，无麦克风/发布权限；无可靠采集时间戳时界面明确 view only。
7. 测试退出/禁用后的实际 SFU 移除及缓存 token 重连拒绝、撤销故障停止续租、源中断/重连、内存/带宽/掉帧。测量前不宣称云端隐私截止时间已通过。
8. 留下实际报告、可复核视频页和待办。若失败，停止相机 publisher，恢复只读维护状态，查明原因；不借用裸 9983 绕过鉴权。

## 回退

先停 Ubuntu 新 publisher/source 单元，再停云端新 SFU。恢复 staging 旧版本指向、cloud.env、API 单元 drop-in、Nginx 原文件并先 nginx -t 后 reload；撤销相机 credential、禁用该相机设备，保留记录，不删历史。恢复新增组成员及本次独有安全组/防火墙规则，核对原站点与探针。不得删除或重置其他数据库/既有服务；不把旧 9983 开到公网作为回退。

备份根目录使用 `/var/backups/thirdhand/access-C2g-camera-<实际时间>/`。候选语法检查目录 `/var/backups/thirdhand/access-C2g-camera-candidate-20261031/` 只含候选片段与检查结果，不代表已部署。
