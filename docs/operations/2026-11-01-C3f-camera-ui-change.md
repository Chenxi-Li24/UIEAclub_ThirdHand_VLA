# C3f 相机观看页面恢复：实际变更记录

2026-11-01 已将唯一前端文件修复部署到staging。实际云端预检与apply均exit0；应用完成UTC epoch1793463671.7288525（北京时间00:21:11）。新发布为`/opt/thirdhand-stage/releases/6edc4258818b6b65`，manifest完整摘要`6edc4258818b6b65cc305a15af6b075a217f7b836e7d51e90ec836c5a1add0bd`。原986发布保留。

只替换`apps/web/public/js/camera-view.js`，4625件文件中其余4624件保持原值。应用器在切换前后与API重启后核验完整库存、摘要、零控制租约、环境和展示站摘要；仅重启业务API。不改授权期限、数据库、权限、端口、相机源、SDK或CAN。具体范围及回退见[C3f审阅](2026-11-01-C3f-camera-ui-deployment-review.md)。

## 实际验证结果

浏览器重新加载新版控制页，保留原Observer会话，加载并选择Lab Ubuntu/XVisio相机后明确点击Watch。实际视频始终readyState=0、currentTime=0、videoWidth/videoHeight=0，最后仍显示“相机暂不可用”；没有解码帧。之后点击Close结束测试意图，不声称视频已修复。当前网络没有调整，用户表示暂不能提供其他网络作对照。

Ubuntu独立状态采样UTC epoch1793463893.2133496：SDK connected=false、moving=false。camera-source PID28559/NRestarts0保持原值；publisher active/PID321954/NRestarts276，最近180秒仍记录6次camera.unavailable。此项为自然失败计数，非本轮人为故障注入；旧服务启动以来累计重启次数不能全部归因于本次修复。

本轮仅通过页面恢复逻辑和发布完整性，**未通过真实持续观看、当前双路或35秒故障恢复验收**。缺少正常可解码的双路基线，故未注入管理端口故障，避免把原有不可用误判为故障保护成功。既有C3d双端TCP证据仍表明至少一例返回链路重传占主要耗时；本批前端恢复不改变该事实。

最终再观察180秒（UTC1793465314.3758256截止）仍有9次MEDIA_GRANT_UNAVAILABLE/response_headers：其中8次总耗时601ms，另一次排队等阶段后总耗时1942ms、响应头阶段600ms。仍属于当前请求期限失败，未删除或放宽期限。最终设备部署后再做一次明确Watch，仍须以实际解码结果为准。

最终设备部署后的这次Watch亦结束为不可用，DOM实测readyState=0、currentTime=0、宽高0；随后Close清除观看意图，未退出用户Observer会话。截图为本计划`evidence/C3e-C3f-final-view.png`。没有运行人为故障规则或遗留后台抓包。

## 证据

- 本地统一相关回归Node321/321、Python233/233，0fail/0skip；前端独立审阅13/13及应用器24/24。
- root私有目录`/var/backups/thirdhand/access-C3f-camera-ui-20261101`保存准确上传包、应用器、review-output.json、apply-output.json和before-public.json。应用器SHA`d10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f`。
- 本计划证据`evidence/C3f-cloud-camera-ui-applied.png`、`evidence/C3f-real-video-unavailable.png`保存实际发布和浏览器状态。

没有Git提交、push、PR、新增公网端口或真机连接/运动指令。Ubuntu失联保护由独立C3e批次记录。

## 并行账号发布的保留核对

之后用户确认另一聊天“连接局域网Ubuntu电脑”（019fa403-5ee9-7782-a260-01f1995aa1c3）正在实施经其授权的注册/管理员审批。云端current因此切换到`initial-admins-ff7ea312a93fef15`，manifest摘要`73fb03ea149771c703f8bf02d8339d9478be3717103b70c14b1bac57cb24559c`。本聊天的旧current断言正常拦截，未覆盖账号改动。

随后只读核对确认：该账号版本的camera-view.js仍为本批新摘要`1928d6017925dc09ca35acca021f24d48ca40ae0b3ac7354c79091c8e89bd64f`，相对C3f仅4个账号/迁移文件改变，设备控制仍报告explicit-read-only。另一聊天第二阶段账号发布尚在进行；这里的6ed发布标识是本批应用时的历史值，不应作为当前服务器版本的永久断言。对并行身份版本不得使用旧C3f回退工具覆盖，需先按届时真实基线重新审阅。

第二阶段账号发布随后完成，实际current为`registration-approval-a570d928578cb5bb`，manifest摘要`4ece5d6ce0577bfce2e734dbe43f6df617484b01868242f9b813a250f171f552`。再次核对相机脚本仍为本批新摘要，设备控制为explicit-read-only；相对C3f仅13件账号/网页/迁移文件有变化。该账号发布由另一聊天负责，未被这里覆盖。
