# Local Delivery Assets

This directory contains the large or license-sensitive payloads required by the Ubuntu installation. It is physically inside the unified project so one launcher can find everything without reaching into old projects, but its payload is not published to GitHub.

Expected payloads include:

- `sdk/startouch/`: the hardware-matched Startouch SDK and native libraries.
- `vendor/funasr/`: the pinned FunASR source tree used by the speech service.
- `models/asr/{medium,realtime,high}/`: the three approved ASR model families.
- `models/policies/{vla,act,dp}/`: optional policy checkpoints; missing assets keep the corresponding Skill unavailable.
- `runtimes/{python,node}/`: project-local runtimes validated for the host Ubuntu release.

Use `./thirdhand setup-assets` for an explicit copy and `./thirdhand verify-assets` before startup. Imports must record source, size, SHA-256, compatibility, and license status. Startup never downloads assets implicitly. Never commit binaries, model weights, copied runtimes, credentials, or vendor payloads from this directory.
