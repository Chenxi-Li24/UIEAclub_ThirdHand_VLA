# C8 SDK 初始化核验

2026-11-01。用户要求优先解决 SDK 问题，并提供《FastUMI Touch 用户手册(1).pdf》。本轮只读取文件、官方仓库和 ELF 静态反汇编；没有导入/实例化 SDK、连接 CAN、重启服务、使能或运动。C8 修正版部署仍未应用。

## 手册及官方来源

手册第 11 页第 3 节列出 https://github.com/lumos-open/startouch_sdk 。本次核对的 main 固定提交为 `040412542c0b6b6fd2bb6dd652c0de6c666631be`，递归目录未截断。

- [README](https://github.com/lumos-open/startouch_sdk/blob/040412542c0b6b6fd2bb6dd652c0de6c666631be/README.md)：发布 Python 接口和预编译 C++ 运行库；不等于发布原生控制器完整实现。
- [安装说明](https://github.com/lumos-open/startouch_sdk/blob/040412542c0b6b6fd2bb6dd652c0de6c666631be/README_INSTALL.md)：Basic Verification 区分被动读取和硬件连接测试；普通 SingleArm 初始化后需要等待控制器稳定。
- [API](https://github.com/lumos-open/startouch_sdk/blob/040412542c0b6b6fd2bb6dd652c0de6c666631be/README_API.md)：gripper 参数包含启用夹爪含义。
- [被动读取入口](https://github.com/lumos-open/startouch_sdk/blob/040412542c0b6b6fd2bb6dd652c0de6c666631be/interface_py/read_joints_passive.py)：不构造 SingleArm，而是启动相邻 `startouchlib/build/print_joints`；目标不存在时直接报错。该依赖未包含在本次公开仓库目录中。

不能将当前上游版本行为直接等同于现场旧二进制，也不能直接覆盖现场 SDK/动力学配置。

## Ubuntu 实际版本及源码查找

服务的 SDK 目录为 `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/local/sdk/startouch`，模块目录为 `local/generated/startouch-python/startouch_sdk/interface_py`（同一仓库根目录）。

实际模块旁的 `libstartouch.so` SHA256：
`8284d216ab4e7b0195ffaf8e7fc70ee160b834511b9c05e77c0ba33ad545e24b`。
该摘要与 SDK src 下及 `/home/nieqingcao/arm/startouch_sdk/src/libstartouch.so` 一致。Python 模块 NEEDED 为 libstartouch.so，RUNPATH 为 `$ORIGIN`；Robot 服务环境未设置 LD_LIBRARY_PATH/LD_PRELOAD。未通过执行库来验证加载。

在 home、/opt、/usr/local、/media、/mnt 的可读代码目录扫描 147,413 个 C/C++ 源文件，未匹配到限定名 `ArmController::ArmController(` 实现；排除了依赖缓存及私有配置目录。这不证明所有未扫描位置都没有源码。找到的 SDK、历史备份和三个 startouch 命名压缩包主要包含声明、封装、预编译库或项目桥接代码。

另按目录和文件名查找 `startouchlib`、`print_joints`，同一搜索范围未找到。公开 SDK 的 CMake 仅构建 pybind 并链接预编译原生库，不能据此重建缺失实现。

## 本机二进制的静态证据

使用 nm/readelf/objdump 读取上述固定摘要的库，没有加载运行它。

| 调用链/地址 | 证据及含义 |
|---|---|
| ArmController 构造函数 `0x9ea30` | 调用 Impl 构造函数；非 dry_run 路径会启动控制线程 |
| Impl 构造函数 `0xadc72` | 调用 `initial_startouch()`；该硬件初始化路径位于 dry_run 判断之后 |
| initial_startouch `0x9d405` | 调用 `Startouch::enable_all()`；之前还存在清错、模式及超时设置调用 |
| ArmController `0x9eac3` | gripper_exist 为真且 dry_run 为假时调用 `closeGripper()` |
| ArmController `0x9eadf` | 非 dry_run 时调用 `start_two_thread()` |

参数传递及 Impl 存储核对：偏移 `0x970` 对应 gripper_exist，`0x764` 对应 dry_run。当前桥接默认启用夹爪，服务未设置 STARTOUCH_GRIPPER；STARTOUCH_DRY_RUN=0。因此普通 SingleArm 构造不能作为不使能、不动作的被动连接。

上述为静态调用证据，不是本轮实测发生运动的记录。也未证明回零行为或通信超时的实际停止效果。不能用 dry_run 冒充真机反馈，不能仅设置 gripper=False 就声称整个初始化只读，不能通过二进制补丁删除调用后直接上机。

## 修复路径与待补材料

**后续授权更新（2026-11-01）**：用户已明确允许所有有效登录用户显式连接普通 SDK，并接受初始化使能电机和默认夹爪闭合；初始化之外的运动仅管理员可发。故下述被动接口材料不再是这条普通连接路径的前置条件，仍是“完全无动作被动采集”所需材料。新的权限拆分实现及测试见 [SDK连接权限](2026-11-01-sdk-connection-permissions.md)。这不表示已部署或已进行现场连接，也不将原固定 C8 包自动扩大为新数据库/权限部署。

优先索取厂商与现场版本匹配的 `startouchlib`（含 print_joints 实现及 CAN 依赖），或受支持的无使能、无夹爪动作、无控制线程输出的只读初始化接口和说明。拿到后先审查所有发送路径与单位/有效性处理，离线验证，再形成固定设备候选；真实读取结果必须区别于模型/模拟数据。

如果被动采集无法获得未使能电机反馈，应显示无数据/过期，不自动使能来获取样本。普通 SDK 控制连接是另一条有动作副作用的路径，不能沿用本轮只读验收授权。

本轮仅更新核验文档，无运行代码、依赖、数据库、账户、服务配置或资源变化，启动方式不变。十分钟真实只读验收仍未执行；C8 修正版等待后续明确批准。

本地忽略目录 `.superpowers/sdd/2026-11-01-sdk-source-audit/` 保存手册提取、源码扫描及 `initial-startouch.disassembly.txt`。这些运行证据和手册全文不提交 Git。
