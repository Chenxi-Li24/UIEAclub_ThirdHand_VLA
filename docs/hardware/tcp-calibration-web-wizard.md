# TCP 标定网页向导

该页面把已安装在夹爪中心线上的尖头探针做枢轴标定，再用卡尺测得的“探针尖端到抓取平面”距离换算抓取 TCP。页面只读取 3000 服务发布的规范化 `robot_flange` 位姿；它不会控制机械臂、相机、夹爪或自动寻找接触点。

## 安全前提

- 全程由操作员人工示教，低速移动；一名急停人员始终能触达独立硬件急停。
- 探针须居中、刚性固定且未弯曲；枢轴尖点在全部采样期间保持物理固定。
- 每次点击“记录”前，机械臂须静止、状态新鲜，探针只轻触尖点且不承受侧向载荷。
- 软件停止依赖网络和进程，不能替代硬件急停或物理断电。
- 最终还必须进行低速真机验证和瓶子抓取审批；软件测试通过不等于完成物理 TCP 标定。

## 启用与访问

先准备规范化坐标策略文件，使用独立、可备份的产物目录启动网页网关：

```bash
export TCP_CALIBRATION_ENABLED=1
export TCP_CALIBRATION_FRAME_POLICY_FILE=/absolute/path/to/frame-policy.json
export TCP_CALIBRATION_ARTIFACT_ROOT=/absolute/path/to/tcp-calibration-artifacts
export TCP_CALIBRATION_PYTHON=python
./thirdhand ensure --profile manual-control
```

浏览器打开 `http://192.168.58.68:9983/tcp-calibration.html`。若 3000 未连接、状态不健康、正在运动、状态过期或坐标策略不匹配，采样按钮会保持锁定。

## 七个阶段

0. **连接与安全检查**：填写操作员、卡尺距离/不确定度和夹具轴向，逐项确认安全条件。
1. **8 姿态采集**：人工保持同一尖点接触，采集至少 8 个相差 5° 以上的姿态；误采可删除重录。
2. **求解与诊断**：检查绿色/黄色/红色分级、秩、奇异值、RMS、最大残差和最差样本。红色不得继续。
3. **独立验证**：另取至少 3 个未参与拟合的姿态，不得复用拟合样本。
4. **换算夹爪 TCP**：核对 SDK 工具、探针尖端与抓取 TCP 三套变换，确认卡尺距离只应用一次。
5. **保存候选结果**：保存只生成 `pending` 候选，不会改变生产活动值。
6. **激活与回滚**：经负责人明确确认后才原子切换活动清单；发现异常立即停止并回滚。

## 产物、恢复与回滚

产物目录包含不可变的 `sessions/`、`candidates/`，以及原子更新的 `gripper-tcp.pending.json` 和 `active-manifest.json`。文件权限为 `0600`。网关重启会从 `sessions/current.json` 校验哈希并恢复当前会话；损坏或哈希不匹配会拒绝启用，而不是静默使用。

先备份整个产物目录。网页中的回滚要求当前活动 ID 与页面所见一致，并切回 `previousActiveId`。Git 代码恢复点为：

```bash
git switch backup/xavier-before-tcp-web-20261006
# 开发实现位于：
git switch feature/tcp-calibration-web-wizard-20261006
```

不要手工编辑候选文件或活动清单；这会破坏内容哈希或并发版本检查。

## 无硬件仿真

```bash
artifact_root="$(mktemp -d)"
node tools/tcp_calibration/demo_simulated.js --artifact-root "$artifact_root"
```

该命令以固定夹具运行第 0–6 阶段，验证保存、重启恢复、激活与回滚，只允许发出 `software_stop`，并打印运动命令数 `0`。它不连接真实机器人，不执行运动、接触、生产激活或瓶子抓取。

## 真机后续验收

仿真和自动测试通过后，仍需在隔离区域完成：探针安装检查、卡尺复测、8+3 次人工接触、残差审阅、低速多姿态触点复验、移除探针确认、空载低速抓取轨迹检查、测试瓶抓取与负责人签字。完成这些步骤前，候选值不得视为生产批准值。
