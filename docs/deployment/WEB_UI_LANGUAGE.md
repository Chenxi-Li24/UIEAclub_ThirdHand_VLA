# Web UI Language / 网页界面语言

## Scope / 范围

The 9983 robot-control page supports English and Simplified Chinese. A browser
with no saved choice defaults to English. The language selector is in the top
toolbar. Switching does not reload the page, reconnect the robot, or send motion.

9983 机械臂控制页支持英文与简体中文。没有保存过语言的浏览器默认英文。
顶部工具栏可立即切换语言，不刷新网页、不重连机械臂、不发送运动指令。

Covered panels include joints, gripper, TCP labels, vision and grasp progress,
Dummy controls, voice controls, validation messages, and confirmation dialogs.
User commands, AI conversation content, device names, SDK/communication logs,
backend reason codes, target IDs, calibration values, and numbers remain literal.
Camera-image annotations and separate TCP-calibration/camera-test/demo pages are
not translated by this control-page language layer.

翻译范围包含关节、夹爪、TCP 标签、视觉与抓取进度、Dummy、语音、输入校验与确认弹窗。
用户指令、AI 对话内容、设备名称、SDK/通信原始日志、后端原因代码、目标 ID、
校准数值及数字保持原样。视频图像内的检测标注，以及独立的 TCP 标定、
相机测试和演示页面，不属于此控制页语言层的翻译范围。

## Files / 文件

- `apps/web/public/js/i18n.js`: presentation-only language selection, exact-string
  and anchored-template translation, incremental DOM updates, validation text.
- `apps/web/public/js/i18n-catalog.js`: control, vision, grasp, and Dummy strings.
- `apps/web/public/js/i18n-voice-catalog.js`: voice-service status and confirmations.
- `apps/web/public/css/i18n.css`: language selector and responsive text layout.
- `apps/web/public/index.html`: language assets and selector entry.
- `apps/web/public/js/main.js`: localized native input-validation messages only.
- `apps/web/public/js/voice-control.js`: literal device-name exclusions only.
- `tests/node/web/i18n.test.js`: language, storage, literal content, and validation tests.

The storage key is `thirdhand.ui-language`; accepted values are `en` and `zh-CN`.
Preferences belong to the browser and origin, not the Ubuntu account. If browser
storage is blocked, the page still works and remembers the choice for this page
session only. No translation service, network request, or new dependency is used.

语言使用浏览器当前站点的本地存储键 `thirdhand.ui-language`，不写入 Ubuntu 账户配置。
更换浏览器或访问地址会有独立偏好。存储被禁用时仍可切换，刷新后默认英文。
翻译在浏览器本地进行，不调用外部翻译服务，不引入新依赖。

## Verification / 验证

1. Open the control page. A fresh browser shows English. Select 中文, then English;
   labels update immediately and the robot connection/state does not change.
2. Reload. The selected language remains selected.
3. Inspect the joint/gripper/TCP, vision, Dummy, and voice panels. Confirm numbers,
   units, input drafts, enabled/disabled states, and target selection are unchanged.
4. Open the voice panel without enabling the microphone. Its UI follows the
   selected language; user/AI conversation text stays in its original language.
5. Check desktop and narrow screens: the software-stop button and language
   selector remain accessible, and English text wraps without covering controls.

以上步骤仅验证显示，不点击连接、发送运动、夹爪、启动 Dummy 或抓取按钮。
软停止不等于独立硬件急停；切换语言不会改变任何授权、限位或执行门控。

From the repository root / 在项目根目录运行离线测试：

```sh
./local/runtimes/node/bin/node --test tests/node/web/i18n.test.js
./local/runtimes/node/bin/npm run test:node
```

Both the primary repository and the active 9983 web worktree carry these language
assets. Each retains its own existing grasp/TCP implementation; neither page is
replaced by a full copy of the other.

主目录与当前提供 9983 网页的工作树分别应用同一套语言资源，各自保留原有抓取/TCP
实现，没有相互覆盖整份网页。静态资源更新不需要重启 3000、SDK 或其他服务。
