# Runtime delivery assets

The assets listed individually in configs/assets/runtime-assets.json are tracked
in Git/Git LFS: matched Startouch/XVisio SDKs, Python 3.11 bindings, all three ASR
model families, pinned Grounding DINO/SAM2 snapshots, and the modified FunASR
source used by the working deployment. The largest ASR checkpoint is restored
from 1 GB parts by tools/assets/restore_runtime_assets.py.

Run bash tools/assets/setup_clone.sh in a fresh Ubuntu x86_64 clone with Python
3.11, Node.js 24 and Git LFS installed. See
[the fresh-clone guide](../docs/assets/FRESH_CLONE_CN.md).

Copied environments, logs, caches, tokens, credentials and raw calibration
captures stay ignored. Environments are created in the new checkout and do not
retain executable symlinks or virtualenv paths into the original project.
ubuntu20.manifest.json records the historical deployment; runtime-assets.json
is the authoritative per-file delivery manifest.
