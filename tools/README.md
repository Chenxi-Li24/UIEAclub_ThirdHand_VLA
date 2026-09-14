# Tools

`tools/` 保存开发、迁移、诊断和资产准备工具，不包含生产常驻服务。

| 路径 | 用途 |
|---|---|
| `assets/` | 记录、校验、导入 SDK/模型/运行时，生成 Startouch Python 绑定 |
| `diagnostics/` | 设备、端口、环境和边界诊断 |
| `fixtures/` | 测试使用的固定输入或生成工具 |

工具应默认只读或显式指定输出目录。下载、覆盖本机资产、访问硬件或修改系统配置的工具必须在运行前清楚提示影响。

资产准备流程见 [`../local/README.md`](../local/README.md) 和 [`../docs/assets/ASSET_PROVENANCE.md`](../docs/assets/ASSET_PROVENANCE.md)。
