# 日常操作

## 启动前

```bash
cd /home/nieqingcao/Thirdhand_language
scripts/preflight
```

预检确认目录内Python、Node、三个模型、CUDA和正式端口状态。Claude认证只检查当前启动环境是否能够继续提供，不修改认证来源。

## 正式启动与状态

```bash
scripts/start
scripts/status
```

日志：

- `logs/voice-3004.log`
- `logs/web-9983.log`
- `logs/run/voice-3004.pid`
- `logs/run/web-9983.pid`

## 正式停止

```bash
scripts/stop
```

停止脚本只终止PID文件记录且工作目录位于本项目内的独立进程组。它不会按端口盲目结束其他工程进程。

## 临时无运动测试

```bash
export RUNTIME_ENV_FILE="$PWD/config/runtime.staging.env"
scripts/preflight --voice-port 3005 --web-port 9984
scripts/start
scripts/status
scripts/stop
unset RUNTIME_ENV_FILE
```

临时配置关闭手动、Language和方向控制的真实执行开关，但允许读取外部3000状态。不要在临时页面进行真实运动验收。

## 禁止事项

- 不使用 `sudo scripts/start`；
- 不从旧工程启动同名服务；
- 不执行联网安装或模型下载；
- 不修改Claude调用、共享认证或3000；
- 不在未确认机械臂现场安全时进行真实动作验收。
