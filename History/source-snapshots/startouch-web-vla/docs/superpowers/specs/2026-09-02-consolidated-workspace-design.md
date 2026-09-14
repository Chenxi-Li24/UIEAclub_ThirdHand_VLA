# ThirdHand VLA 统一收纳设计

## 目标

在 Ubuntu 主机上新建一个独立的统一收纳目录，完整保留当前 ThirdHand VLA 项目使用的源码、模型、SDK、标定结果和必要的本地构建产物，同时保持各原项目的目录边界和 Git 历史。第一阶段不合并代码、不修改原项目、不迁移 Conda 或虚拟环境；第二阶段再基于该收纳目录设计规范化单仓库。

## 原则

1. 原目录保持不变，统一目录仅通过复制生成，不移动或删除任何原文件。
2. 保留项目边界，避免在尚未厘清重复实现和运行链路前进行源码合并。
3. 保留可复现性资料，排除体积大且不可移植的解释器环境和依赖缓存。
4. 先记录并停止项目后台服务，再复制动态文件，降低日志、数据库或状态文件在复制过程中变化的风险。
5. 对硬件控制保持保守：不启动机械臂、不发送 CAN 控制命令，只记录当前接口和配置。

## 目标目录

目标路径：

```text
/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/
├── projects/
│   ├── UIEAclub_ThirdHand_VLA/
│   ├── th0814/
│   ├── TH_new_asr_0820/
│   ├── TH-Fanxy/
│   └── auxiliary/
├── sdk/
│   ├── startouch_sdk/
│   └── camera/
├── calibration/
├── environment/
│   ├── conda-environments/
│   ├── python-packages/
│   ├── system-packages/
│   ├── node-runtime/
│   └── hardware-and-ports.md
├── manifests/
│   ├── source-paths.md
│   ├── git-status/
│   ├── running-processes-before.txt
│   ├── running-processes-after.txt
│   ├── exclusions.md
│   └── copied-files.sha256
└── README.md
```

## 纳入范围

### 核心项目

- `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA`
- `/home/nieqingcao/th0814`
- `/home/nieqingcao/TH_new_asr_0820`
- `/home/nieqingcao/TH-Fanxy`

### SDK、相机和标定

- `/home/nieqingcao/arm/startouch_sdk`
- `/home/nieqingcao/FastUMI_Hardware_SDK`
- `/home/nieqingcao/FastUMI_Camera`
- `/home/nieqingcao/calibration`
- `/home/nieqingcao/ros2_ws` 中与当前相机、深度桥或标定链路相关的源码、配置和必要构建产物

### 辅助项目

以下目录先根据源码引用、启动配置和运行进程复核；确认属于当前项目后放入 `projects/auxiliary/`：

- `/home/nieqingcao/thirdhand-policy-integration-20260817-01`
- `/home/nieqingcao/thirdhand-policy*`
- `/home/nieqingcao/TH-Fanxy-deliverables*`

每个来源都记录原始绝对路径、复制时间、目录大小、Git 分支、提交号、远端地址和脏工作区摘要。

## 排除范围

统一目录不复制以下可重建或与源码无关的内容：

- Conda 安装和环境目录：`miniconda3/`、`envs/`
- Python 虚拟环境：`.venv/`、`venv/`、`.conda-execution/`
- Node 依赖：`node_modules/`
- 通用缓存：`.cache/`、`__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`
- 临时文件、普通运行日志、编辑器缓存和系统生成文件
- Ubuntu 主目录下来源不明的畸形或转义目录名

模型权重、标定数据、运行所需本地动态库和无法从包管理器直接重建的 SDK 构建产物不按缓存排除。

## Git 和工作区处理

- 普通 Git 仓库连同 `.git` 一起复制，以保留提交历史、分支和未提交改动。
- `th0814/ThirdHand-XVisio-handeye-web` 是链接工作树，其 `.git` 文件指向原目录。复制时不保留失效的绝对指针；将工作树内容作为源码快照收纳，并在清单中记录原分支、提交号和 Git 状态。
- 所有脏工作区在复制前后分别保存 `git status --short --branch`，不执行清理、还原、切换分支或自动提交。
- 统一收纳目录本身第一阶段不推送到 GitHub，避免意外上传模型、标定数据、密钥或机器专用配置。

## 配置与敏感信息

- 项目实际依赖的 `.env` 和机器配置在本机收纳目录中保留，但统一标记为私密配置，并限制文件权限。
- 同时生成脱敏的环境变量清单，只记录变量名、用途和示例值，不记录令牌、密码或私钥内容。
- 在未来创建规范化仓库前再次执行秘密信息扫描，私密配置不得进入提交。

## 环境复现资料

不复制 Conda、`.venv` 或 `node_modules`，改为生成：

- `LumosTouch`、`voice-bridge`、`thirdhand-groundedsam2` 的 Conda `--from-history` YAML
- 对应环境的完整包列表和 `pip freeze`
- 项目自带 `.venv` 的 Python 版本和 `pip freeze`（环境仍存在时）
- Ubuntu 版本、内核、CPU/GPU、CUDA、CAN 接口状态、USB/相机设备摘要
- Node.js/npm 版本，以及各项目现有 `package.json` 和锁文件
- 与运行链路有关的系统包清单、端口说明和启动命令

这些资料用于在 Ubuntu 22.04 上重建环境，但不承诺二进制包可跨 Ubuntu 版本直接复用。

## 服务停止范围

停止前记录进程、父进程、工作目录、监听端口和启动参数。仅停止已确认属于本项目的后台服务，包括当前占用以下端口的 Node/Python 服务：

- `3000`：机械臂 WebSocket/网页控制代理
- `3003`、`3004`：语音桥
- `9983`：上层 Web/语言代理
- `8085`：如复核后仍为本项目相机或深度桥

优先使用服务管理器或向主进程发送 `SIGTERM`，等待退出后再处理仍存活的子进程。不得停止 SSH、VS Code、远程桌面、浏览器、普通交互式 shell 或系统服务。停止后验证上述项目端口不再监听，并写入 `running-processes-after.txt`。

## 执行流程

1. 复核目标目录不存在、磁盘空间充足，并生成源目录和运行状态快照。
2. 识别项目进程的管理方式和父子关系，按停止范围优雅关闭并验证端口。
3. 创建目标目录骨架和清单文件。
4. 按明确的来源到目标映射复制文件；不使用删除同步，不覆盖原目录。
5. 对链接工作树、环境目录、缓存和私密配置应用专门规则。
6. 导出环境、系统、Git、硬件和启动方式说明。
7. 生成文件校验和、目录大小、排除项清单和总 README。
8. 抽样比对关键源码、模型、SDK、标定文件和 Git 状态，确认没有启动任何机械臂控制服务。

## 验收标准

- 目标目录独立存在，原项目目录和文件未被移动或删除。
- 核心项目、已确认的辅助项目、Startouch SDK、相机依赖和标定数据均有明确映射。
- Conda、`.venv`、`.conda-execution` 和 `node_modules` 未被复制，且环境重建资料齐全。
- 每个 Git 来源都有提交号、分支、远端和未提交状态记录；链接工作树不会留下失效 Git 指针。
- 项目后台端口已停止监听，普通远程连接和系统服务不受影响。
- `README.md` 能说明目录结构、运行入口、环境重建顺序、硬件依赖和当前安全限制。
- 校验和与抽样核对通过，统一目录未自动提交或上传到远端。

## 第二阶段边界

本次不执行源码去重、包名统一、服务整合、Git 历史重写或单仓库迁移。完成收纳后，再以实际依赖图和可运行入口为依据，单独设计规范化项目结构与迁移计划。
