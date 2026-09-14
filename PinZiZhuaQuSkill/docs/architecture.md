# 通用瓶子 V+A Skill 架构

## 模块依赖

```text
                       apps/bottle_pick
                 _________|___________
                /                     \
        vision adapters          action adapters
                |                     |
          vision modules         action modules
                \________ common ____/
```

- `common` 只拥有可验证、不可变的数据契约和配置。
- `vision` 只负责从 Lumos RGB-D 产生稳定 ID 和相机坐标抓取证据。
- `action` 只消费版本化视觉事件和机器人状态，拥有对准、抓放与安全状态机。
- `apps/bottle_pick` 组合进程、网络和生命周期；算法模块导入时没有副作用。
- V 不依赖 A；A 不依赖 V 的模型、NumPy 掩膜或追踪器内部对象。

## 运行数据流

```text
RgbdFrame
   -> GroundedSamBackend
   -> NorfairTrackerAdapter + StableTrackManager
   -> RGB-D grasp candidates
   -> VisionPipeline
   -> thirdhand-va-detection-v3
   -> VisionClient
   -> BaseFrameTargetLock
   -> VisualAlignController
   -> execution gate + immutable plan
   -> GraspController
   -> RobotWebSocketClient
```

L 只提供 `target_id`。Stable ID 由 V 管理，不因目标在图像中的左右顺序变化而改变；A 会
将 `target_id + request_id + calibration_id + motion_epoch + evidence_id` 一起锁定。机械臂
每次运动后旧深度证据立即失效，必须在机械臂静止后重新积累同一 ID 的新鲜深度证据。

## 完整动作状态机

```text
ACQUIRING -> MOVING_TO_PREGRASP -> SETTLING -> REOBSERVING
 -> OPEN -> FINAL_APPROACH -> CLOSE -> LIFT -> TRANSFER
 -> LOWER -> RELEASE -> RETREAT -> RETURN_HOME -> COMPLETE
```

闭合阶段必须收到可测的实际夹爪宽度并落在接触区间内。闭合后任一阶段失败都进入人工
恢复，不会自动张爪或回 Home；释放必须收到实际开口宽度证明，撤离/Home 必须与冻结的
物理路径验证工件完全一致。

## 安全不变量

- `configs/action.yaml` 的 `execution_enabled` 和 `place.validated` 默认均关闭。
- 真实相机、机器人还需要独立环境开关，单独满足其中一个条件不能执行。
- 视觉结果永远声明 `robot_control_enabled=false`；执行权只在 A 的安全门之后产生。
- ID、三帧视觉/预览/机械臂证据、运动 epoch、深度、模型哈希、标定、邻瓶通道、机械臂
  静止、夹爪宽度、固定点、物理路径验证和工作区任一项
  不满足即 fail-closed。
- 服务默认绑定 `127.0.0.1:8766`，不暴露到非受控网络。
- 停止只发送一个低层 `software_stop`；不调用上游黑盒抓取流程。
- 邻瓶通道必须沿最终执行的 robot-base `+X` 插入轴验证；生产端状态序号/时间、静止速度和
  `reached=true` 任一缺失都不能推进动作。

## 当前部署边界

离线模块和内存端到端流程已验证。2026-08-23 对本机实际 `ws://127.0.0.1:3000/ws`
实现的只读检查表明：浏览器协议尚未公开 VA 所需的、带 request ID 回执的低层
`move_l` 路径，并且 UI 广播的机器人状态字段与低层 adapter 合同不同。因此 Action 配置
继续关闭。必须先完成协议适配测试、固定点/标定验证和受监督真机验收，才能改变部署门；
不能用内存模拟结果替代上述证据。
