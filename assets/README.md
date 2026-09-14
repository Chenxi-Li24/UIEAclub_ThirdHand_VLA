# Assets

`assets/` 保存可以被 Git 跟踪的资产说明、元数据和小型资源。大型或受许可限制的 SDK、模型、URDF/STL 载荷通过 `tools/assets` 准备到 `local/` 或指定资产目录。

当前 `robot/` 描述 Startouch 网页模型的来源、目录约定和准备方法。实际 URDF/STL 载荷可在 Ubuntu 本机存在，但受 `.gitignore` 和资产清单管理。

资产来源与准备规则见 [`../docs/assets/ASSET_PROVENANCE.md`](../docs/assets/ASSET_PROVENANCE.md)，本机资产说明见 [`../local/README.md`](../local/README.md)。
