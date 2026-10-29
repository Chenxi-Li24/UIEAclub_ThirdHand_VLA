# 网页工作区改版 · 2026-10-30

本次将机器人控制网页整理为白橙配色的分页工作区。代码基线为
`372ac80a98e279e85bd25dfe8f219b399b97cb80`，发布范围包含静态网页、网页测试、
测试开发依赖和本说明。

## 页面与视觉

- 提供概览、手动控制、视觉、标定、助手、系统六个页面，替代同时展开的大量面板。
- 主工作区保留同一个三维机械臂模型，页面内容独立滚动，切页保留输入和模型状态。
- 侧边栏支持收放并保存偏好；窄屏使用覆盖式导航。
- 手动控制分为关节、TCP、夹爪页签，原控件与事件绑定继续使用。
  Send 根据当前页签执行；切离 TCP 后清除旧预览。
- 使用亮白背景、橙色强调、不同卡片层次和轻量 SVG 几何装饰。
- 模型自动取景；主光与补光固定在观察视角，旋转视角时模型明暗和真实地面投影随之变化。
  坐标轴、网格仍固定在世界坐标。
- TCP 标定页适配新布局，保留原服务确认流程；服务不可用时明确显示不可用状态。

## 新手引导与语言

- 增加可跳过、恢复、重新播放的六步引导：目标区域高亮，其余区域变暗，弹窗解释当前操作。
- 高亮随滚动、窗口缩放和目标裁切更新；支持键盘焦点、Escape 和 Tab。
- 软件停止入口始终保留。任务执行、示教开启或切换处理中限制相关页面跳转。
- 练习进度区分模型交互与信息确认，不把教程完成显示为实机操作成功。
- 支持英文和简体中文；新浏览器默认英文，已有语言偏好继续保留，切换即时生效。

## 账户与设置

- 左下角账户入口切换整组导航：个人资料、偏好设置、连接、关于。
  返回工作区时恢复上一个工作页面。
- 语言选择和外观选项集中到偏好设置，可在此重新打开新手引导。
- 当前提供页面样式和资料接口，尚未接入登录、数据库或真实账户服务。
  无数据服务时明确显示未连接并禁用保存，不生成虚构用户资料。
- 后续可通过 `shell.setAccountDataProvider({ loadProfile, saveProfile })` 接入资料服务；
  旧请求返回时不会覆盖更新后的资料源。

## SDK / Web 状态灯

- 顶部、概览和账户连接页展示一致的连接状态，直接使用现有反馈。
- 绿色要求 Web 链路打开、SDK 已连接、`healthy === true`，并收到六个有限关节值。
- 红色表示链路断开、SDK 掉线或反馈超过 2500 ms 未更新；从未收到首帧也会超时。
- 等待反馈使用黄色，未知状态使用灰色。重连后旧反馈立即失效。
- 状态灯只读，不发送运动、重连、启停或其他设备控制请求。

## 范围与接入

新增依赖仅为 DOM 测试使用的 `linkedom@0.18.14`（开发依赖），锁文件同步更新。
机器人服务、SDK/CAN 控制、速度限制、抓取执行权限、坐标变换、手眼/TCP 参数及其来源校验均未修改。

静态资源由原网页服务提供，无需因此重启机器人服务。运行中的本地工作区保留原样；
本次仓库推送不代表远端实机已部署，也没有执行实机动作或验证物理抓取。

## 验证结果

在 macOS / Node.js 24 环境中，以干净 main 和本次候选版本分别运行全量 Node 测试：

| 检查 | 原 main | 本次版本 |
| --- | --- | --- |
| 全量 Node | 502 / 510 通过，8 失败 | 564 / 572 通过，8 失败 |
| 新增测试 | — | 增加 62 项，失败列表没有新增 |
| `npm ci --ignore-scripts` | — | 通过 |
| 仓库运行边界检查 | — | 通过 |
| `git -c core.whitespace=cr-at-eol diff --check` | — | 通过 |

复现 Node 测试（`PYTHON` 指向安装了项目 Python 依赖的解释器）：

```sh
node --test --test-force-exit --test-timeout=25000 \
  tests/node/authorization/*.test.js tests/node/contracts/*.test.js \
  tests/node/gripper_skill/*.test.js tests/node/launcher/*.test.js \
  tests/node/robot_service/*.test.js tests/node/skill_registry/*.test.js \
  tests/node/task_engine/*.test.js tests/node/vision_service/*.test.js \
  tests/node/web/*.test.js
python tools/diagnostics/audit_boundaries.py --root .
```

两次均存在的 8 项失败：

- `tests/node/launcher/one-click.test.js`：5 项；涉及 macOS 临时路径
  `/var` 与 `/private/var` 差异，以及修复进程探测的 `ENOENT`。
- `tests/node/vision_service/projected-state-route.test.js`：1 项。
- `tests/node/web/grasp-runtime-integration.test.js`：1 项。
- `tests/node/web/grasp-tcp-e2e.test.js`：1 项。

后三项均为 `frame_policy_source_changed`：main 中机器人控制源码与现有坐标策略记录的来源哈希不一致。
本次未重写哈希、跳过校验或更改标定证据，因此全量测试仍为非全绿状态。
