# 单次 GRIP 抓取演示

`scripts/action/grip_live_demo.js` 是独立的受监督客户端，只访问回环地址上的
`/api/va/test/*`，不直接连接 CAN 或向 SDK 发送原始运动指令。机器人实际执行仍由现有
VA 服务、Startouch SDK 和服务端安全门槛负责；目标采用服务端预览中的
`grip_target_xyz_m`，不在脚本中另加夹爪偏移。

```sh
node scripts/action/grip_live_demo.js --target-id 2
node scripts/action/grip_live_demo.js --target-id 2 --execute
```

第一条只读展示相机点、目标表面点、GRIP 点、阻断原因和机器人状态。第二条仅在
相机、Home、实际三维坐标、机器人状态及服务端执行计划全部就绪时才可继续。
操作者须清空工作区、确认实体急停可用，并依次输入 `START 2`、各阶段的
`NEXT <阶段名>`。拒绝确认、目标变化、服务异常或超时会请求软件停止；
软件停止不是安全额定急停，操作者仍须现场观察并在必要时使用实体急停。
不要在抓着物体时依赖自动重试、自动放瓶或自动回 Home。

完整抓取及放置路径的事先批准、手眼点的批准状态不再是计划门控。
但当前部署的 `execution_enabled=false`，视觉服务尚未产出底座 GRIP 点，
监督路径也没有注入动作计划，因此脚本现在仍不能移动机械臂。
手眼矩阵及相机身份必须匹配，目标的三维坐标、法兰偏移和实际计划不能缺失；
这些是计算与运动所需的数据，不是批准标志。
