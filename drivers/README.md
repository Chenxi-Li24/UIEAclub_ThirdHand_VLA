# Drivers

`drivers/` 是第三方设备 SDK、原生库与服务代码之间的适配边界。

当前只有 `xvisio/`：负责 XVisio 相机枚举、序列号校验、RGB-D 帧协议和原生构建。视觉业务、检测模型和目标选择属于 `services/vision`，不应写进驱动层。

约束：

- 驱动不得发送机器人控制命令；
- 原生构建产物写入 `runtime/build`；
- 大型 SDK 或二进制载荷放入 `local/` 并由清单校验，不提交 Git；
- 设备不可用时应给出明确状态，不能静默退化为假数据。

XVisio 细节见 [`xvisio/README.md`](xvisio/README.md)。
