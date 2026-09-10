# ThirdHand 统一项目运行指南

适用目录：`/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`
当前分支：`refactor/unified-platform-foundation`

## 1. 当前可运行范围

当前版本完成了统一目录、项目内 Node/Python 运行时、资产清单、服务生命周期管理、Skill Registry 和模拟服务。

可以验证：

- 一条命令启动、查询和停止五个模拟基础服务；
- PID 所有权和重复启动保护；
- Skill manifest 自动发现；
- 缺少实现、服务或模型时失效关闭；
- SDK、模型、运行时的本地哈希校验；
- 合同、边界和模拟生命周期测试。

目前不能通过新结构控制真实机械臂或显示真实视觉/语音页面。默认 profile 中的正式服务仍标记为 `service_not_migrated`，七个 Skill 的 worker 也尚未迁移。不要把模拟 profile 用于硬件操作。

## 2. 登录与进入项目

从 Windows PowerShell 或 VS Code 终端连接：

```powershell
ssh nieqingcao@192.168.58.68
```

进入项目：

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
git branch --show-current
git status --short --branch
```

预期分支为 `refactor/unified-platform-foundation`，工作区应为空。该分支保持本地状态，不合并、不推送。

## 3. 一键命令

```bash
./thirdhand doctor
./thirdhand verify-assets
./thirdhand start
./thirdhand status
./thirdhand stop
```

当前应显式使用模拟 profile：

```bash
./thirdhand doctor --profile simulation
./thirdhand start --profile simulation
./thirdhand status --profile simulation
./thirdhand stop --profile simulation
```

也可以使用环境变量：

```bash
export THIRDHAND_PROFILE=simulation
./thirdhand doctor
./thirdhand start
./thirdhand status
./thirdhand stop
```

每条命令都支持 `--json`，适合脚本和诊断记录。

## 4. 首次检查

### 4.1 只读环境检查

```bash
./thirdhand doctor --profile simulation --json
```

预期：

- `overall: ready`
- repository、Node 24、simulation profile 为 ready
- 命令不会打开 CAN、摄像头、麦克风或模型

### 4.2 本地资产校验

```bash
./thirdhand verify-assets --json
```

该命令会读取 `configs/assets/manifest.local.json` 并计算本地文件哈希，不下载文件、不导入 SDK、不打开设备。

当前预期不是整体 `ok: true`，原因如下：

- Startouch SDK、XVisio SDK、Medium/Real-time/High ASR 模型的许可证状态尚未确认；
- VLA、ACT、Diffusion Policy 权重尚未提供；
- FunASR、标定数据、Python 3.11 和 Node 24 运行时应为 ready。

哈希不一致、架构不匹配和许可证未知必须先处理，不能通过修改状态字符串绕过。

## 5. 模拟启动验收

启动：

```bash
./thirdhand start --profile simulation --json
```

预期五个服务均为 ready：

- robot
- supervisor
- model
- speech
- vision

模拟 profile 使用独立配置端口 13000、13004、13100、13101、13102，不访问 `can0`、USB 相机、音频设备、GPU 或模型文件。当前 fake service 以 readiness 文件和进程身份作为验收，不提供网页或 HTTP 画面。

再次执行相同 start：

```bash
./thirdhand start --profile simulation --json
```

PID 应保持不变，证明没有启动第二套服务。

查看状态：

```bash
./thirdhand status --profile simulation --json
```

查看日志和状态：

```bash
cat runtime/run/state.json
ls -l runtime/run
tail -n 100 runtime/logs/*.stdout.log
tail -n 100 runtime/logs/*.stderr.log
```

停止：

```bash
./thirdhand stop --profile simulation --json
```

停止后再次检查：

```bash
./thirdhand status --profile simulation --json
ps -ef | grep '[f]ake_service.js'
```

预期所有服务为 stopped，且没有残留 fake service。

## 6. 自动化测试

所有测试均为非硬件测试：

```bash
PYTHONPATH=src:. python -m pytest \
  tests/unit/platform \
  tests/integration/test_simulated_lifecycle.py -q

npm run test:contracts

node --test \
  tests/node/launcher/*.test.js \
  tests/node/skill_registry/*.test.js

PYTHONPATH=src:. python \
  tools/diagnostics/audit_boundaries.py --root . --json

git diff --check
```

Python 3.14 的基础 Conda 环境目前会提示未知 `asyncio_mode`，因为该环境未安装 pytest-asyncio；Foundation 测试仍可执行。项目内正式运行时是 Python 3.11.15。

## 7. 端口与现状

| 端口 | 规划所有者 | 当前状态 |
|---:|---|---|
| 9983 | Web Gateway | 本机已有其他系统监听；正式 Web 尚未迁移 |
| 3000 | Robot Service | 旧 `proxy.js` 已停止；正式 Robot 尚未迁移 |
| 3100 | Vision Service | 正式 Vision 尚未迁移 |
| 3101 | Supervisor | 正式 Supervisor 尚未迁移 |
| 3102 | Model Service | 正式 Model 尚未迁移 |
| 3004 | Speech Service | 正式 Speech 尚未迁移 |

检查端口：

```bash
ss -ltnp | grep -E ':(9983|3000|3004|3100|3101|3102)\b' || true
```

正式 Web 接入前必须先确定当前 9983 监听者，并决定释放端口还是调整配置。不要直接结束未知系统进程。

## 8. 默认 profile 的行为

```bash
./thirdhand start --profile default
```

当前会返回 degraded，因为全部正式服务都显式禁用为 `service_not_migrated`。这是安全设计，不是启动故障。完成逐服务迁移和验收前，不应把这些条目改为 enabled。

真实启动顺序应为 Robot、Supervisor/Model/Speech/Vision、Skill workers、Orchestrator、Web。Robot 连接后只能采样状态，不允许自动回零或发送运动目标。

## 9. Skill 状态

```bash
./thirdhand status --profile simulation --json
```

当前七个 Skill 会被发现，但显示 unavailable。主要原因是 `implementation_not_migrated`，策略 Skill 还会显示缺少模型。详细协议见：

- `docs/SKILL_PROTOCOL.md`
- 每个 `skills/*/*/SKILL.md`
- `platform/contracts/schemas/`

只有服务、设备、模型、entrypoint 和健康检查全部 ready 后，Registry 才能发布 Skill 为 ready。

## 10. 原服务回退

旧的 Startouch `node proxy.js` 已按用户要求停止，3000 已释放。若后续明确决定临时回退到旧控制页，应在确认机械臂周围安全、硬件急停可触达后单独运行：

```bash
cd /home/nieqingcao/arm/web-control-startouch/server
npm start
```

不要同时运行旧服务和未来的新 Robot Service；两者不能竞争 `can0` 或 3000 端口。

## 11. 真机迁移门槛

启用任何真实运动前，至少完成：

1. Robot Service 从迁移快照提升为正式代码，且消除旧目录绝对路径。
2. Startouch 构造阶段不运动、反馈连续性、突发全零保护通过真机验收。
3. J1-J6 限位、速度、夹爪 90 度全行程映射通过测试。
4. Vision、稳定 TargetRef 和标定版本通过回放及真机测试。
5. Supervisor 独立在线，丢失时锁定自动运动。
6. 计划、风险摘要和一次性授权完整实现。
7. 用户针对具体真机测试再次授权。

软件停止不替代独立硬件急停或物理断电。

## 12. Git 与更新

当前 remote：

```text
origin   https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA.git
upstream https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
```

当前要求是不合并、不推送。检查本地提交：

```bash
git log --oneline --decorate -12
git status --short --branch
```

拉取或合并远端更新前，应先停止新结构服务、确认工作区干净，并评估远端变更与本地提交的关系。
