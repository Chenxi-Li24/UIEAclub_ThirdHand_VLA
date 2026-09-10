# Local Delivery Assets

This directory contains the large or license-sensitive payloads required by the Ubuntu installation. It is physically inside the unified project so one launcher can find everything without reaching into old projects, but its payload is not published to GitHub.

Expected payloads include:

- `sdk/startouch/`: the hardware-matched Startouch SDK and native libraries.
- `vendor/funasr/`: the pinned FunASR source tree used by the speech service.
- `models/asr/{medium,realtime,high}/`: the three approved ASR model families.
- `models/policies/{vla,act,dp}/`: optional policy checkpoints; missing assets keep the corresponding Skill unavailable.
- `runtimes/{python,node}/`: project-local runtimes validated for the host Ubuntu release.

Use `tools/assets/import_assets.py` for an explicit collision-safe copy and `./thirdhand verify-assets` before startup. Imports must record source, size, SHA-256, compatibility, and license status. Startup never downloads assets implicitly. Never commit binaries, model weights, copied runtimes, credentials, or vendor payloads from this directory.

The Ubuntu 20.04 installation currently contains the Startouch and XVisio SDKs, FunASR source, three ASR models, Python 3.11.15, Node 24.18.0, and a read-only calibration source copy. See `docs/assets/ASSET_PROVENANCE.md` and `configs/assets/ubuntu20.manifest.json` for exact mappings and hashes.
