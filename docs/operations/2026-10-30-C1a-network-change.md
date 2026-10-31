# C1a 公网网络准备变更记录 — 2026-10-30

本次执行用户已批准的网络范围：新增设备子域解析、主域与设备子域公共
HTTPS、检查并按需放行TCP443、变更前备份。公网应用、数据库、设备身份注册、
SDK和机械臂操作均未发布或执行。展示站首页与导航按钮继续按用户要求暂缓。

## 已应用结果

| 项目 | 实际结果 |
|---|---|
| 阿里云DNS | 原有 `@ A 47.94.95.244` 保留；新增 `edge A 47.94.95.244`，默认线路，TTL600秒，已启用 |
| 主站 | `http://uiea-thirdhand.com/` 与 `https://uiea-thirdhand.com/` 均200，继续提供原展示站 |
| 设备子域 | `edge.uiea-thirdhand.com` 的HTTP/HTTPS只允许标准ACME文件验证，其余路径返回404 |
| 主域证书 | Let's Encrypt，SAN仅 `uiea-thirdhand.com`，到期 `2027-01-28T05:43:27Z` |
| 设备子域证书 | Let's Encrypt，SAN仅 `edge.uiea-thirdhand.com`，到期 `2027-01-28T05:52:14Z` |
| HTTPS协议 | 两个名称均从学校Ubuntu验证TLS1.2、TLS1.3，启用信任链和名称校验 |
| 主机防火墙 | UFW原本已允许443/tcp及对应IPv6规则，未修改 |
| 云安全组 | 北京实例 `i-2zech7zehrgs6s8z8pm4`，安全组 `sg-2zeax5c0m6qq74hi2dsx` 原有TCP443/443允许规则，未修改 |
| 服务状态 | 活动的系统Nginx继续运行，所有实际配置应用前均先语法检查，再reload；最终检查通过 |

没有添加 `www`、通配符、UDP/TURN或业务服务端口。当前 `www` 无DNS记录，
不在本次证书覆盖范围。HTTP继续提供原站点，尚未强制重定向或添加HSTS。

## 实际生效的Nginx与故障原因

宝塔界面显示Nginx1.28.3，但公网监听由系统Nginx1.18.0提供：

- 可执行文件：`/usr/sbin/nginx`；服务：`nginx.service`。
- 主配置：`/etc/nginx/nginx.conf`。
- 主站：`/etc/nginx/sites-available/uiea-thirdhand.com`，由 `sites-enabled` 链接。
- 新增设备站：`/etc/nginx/sites-available/edge.uiea-thirdhand.com`，新增同名启用链接。
- 展示根目录仍是 `/www/wwwroot/uiea-thirdhand-static/`。
- 设备ACME专用目录：`/www/wwwroot/thirdhand-edge-acme/`。

首次证书申请返回403，原因是活动主站的隐藏路径拒绝规则拦截
`/.well-known/acme-challenge/`。仅新增 `location ^~` 验证目录例外，
保留其他隐藏路径拒绝。重载后本机与学校Ubuntu均验证该路径200，再完成签发。

主站保留原HTTP块，新增仅覆盖主域的HTTPS块；设备站的HTTP/HTTPS块均
`location / { return 404; }`。两份活动站点文件均无 `proxy_pass`。
未切换Nginx二进制或重启到宝塔的另一套服务，未修改其他默认站点。

证书由宝塔原有ACME机制签发，活动服务引用：

```text
/www/server/panel/vhost/cert/uiea-thirdhand.com/fullchain.pem
/www/server/panel/vhost/cert/uiea-thirdhand.com/privkey.pem
/www/server/panel/vhost/cert/edge.uiea-thirdhand.com/fullchain.pem
/www/server/panel/vhost/cert/edge.uiea-thirdhand.com/privkey.pem
```

两份私钥最终权限均为0600；私钥内容未打印、下载、提交或放入截图。
宝塔仍保存其自身的站点配置和签发状态；不要通过启动宝塔Nginx来替代系统服务。
后续业务模板必须针对实际活动配置重新审阅，不能仅写入宝塔扩展目录。

## 验证证据

学校Ubuntu `100.85.63.78` 的只读网络探测时间为
`2026-10-30T06:53:04Z`（北京时间14:53）。检查DNS、HTTP、HTTPS及证书，
没有执行SDK、CAN、相机或动作命令。

- 主站HTTP/HTTPS均200，1348字节首页的SHA256均为
  `639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd`，
  与变更前服务器备份清单一致。
- 设备子域根路径HTTP/HTTPS均404；HTTPS下 `/device/v1/channel`、
  `/api/robot/connect`、`/.git/config`、不存在的ACME文件均404。
- 两个名称分别强制TLS1.2和TLS1.3连接，信任链/主机名校验均成功。
- Ubuntu公网路由为 `47.94.95.244 via 192.168.58.1 dev wlp7s0 src 192.168.58.68`。
  Tailscale用于管理SSH；本次HTTPS走校园出口，不需要学校入站端口映射。
- 最终 `/usr/sbin/nginx -t` 返回0；服务active，IPv4/IPv6均监听443。
- 浏览器HTTPS主站正常渲染；宝塔列表显示两个站点证书均剩余89天。

本地完整JSON及截图保存在忽略的工作记录目录
`.superpowers/sdd/2026-10-30-public-access-rollout/evidence/`，包括
`C1a-campus-verification.json`、`C1a-dns.jpg`、`C1a-ecs443.jpg`、
`C1a-main-https.jpg`、`C1a-cert-status.jpg`。证据不包含密钥。
这些检查验证公网网络准备，不代表后续WSS、mTLS、相机或真机控制验收。

## 备份与回滚

服务器备份目录为 `/var/backups/thirdhand/access-C1a-20261030T061711Z`，
在仅所有者可访问的目录中。备份包括：

- 变更前宝塔站点/全局配置、扩展目录、监听与UFW状态及清单。
- `active-nginx/etc-nginx/`：变更前实际系统Nginx整棵配置，保留符号链接。
- `active-nginx/effective.txt`：变更前实际Nginx展开配置。
- `main-before-tls.conf`：已修复ACME、尚未添加HTTPS的主站配置。
- `edge-before-tls.conf`：设备站已关闭业务的HTTP配置。
- `active-nginx/after-C1a-effective.txt` 与 `final-<域名>.conf`：最终配置副本。

只回退本次相关文件，不覆盖之后的其他任务变更。若需撤回全部C1a站点配置，
先比较当前文件与最终副本，确认期间没有新修改；恢复备份中的原主站文件，
移出本次新增设备站启用链接并保留源文件供追溯。运行
`/usr/sbin/nginx -t` 成功后，才执行 `systemctl reload nginx`。
不要重启另一套Nginx，不要还原整个 `/etc/nginx` 覆盖无关站点。
若只回退TLS，可使用两份 `*-before-tls.conf`，保留已验证的HTTP/ACME行为。

DNS回退仅针对本次新增edge记录；原 `@` 记录不变。没有新增安全组或UFW
规则可供回退。已有证书保留在服务器，不需要为网络回滚撤销或删除。

## 下一阶段前必须处理

1. **续期后的实际服务重载**：宝塔提示自动续期，但它与活动系统Nginx并非
   同一套部署。尚未验证宝塔续期会重载 `nginx.service`。后续必须补充经过审阅的
   成功续期后语法检查/实际服务reload机制，并通过公共证书序列号验证已生效。
   在自动机制验证前，续期后需由运维执行 `/usr/sbin/nginx -t` 和
   `systemctl reload nginx`，再检查公网证书；不能把界面“续期成功”当成已换证。
2. **C1b**：审阅私有CA、设备注册、Unix socket、运行身份、活动Nginx配置和
   relay后，再执行无SDK的持续WSS校园探测。当前edge404是预期结果。
3. **容量**：ECS控制台为2vCPU/2GiB、固定3Mbps公网带宽。数据库、媒体服务位置
   和多观察员相机容量需单独决策和实测，本次没有购买资源或安装服务。
4. **后续验收**：认证业务上线前必须强制其HTTPS入口；目前HTTP仅提供既有展示站。
   业务发布、SMTP/数据库权限与恢复、真实媒体链路、现场停止/
   CAN隔离、新手教程接口合并仍按既定阶段处理。管理员登录本身不授予真机控制。
