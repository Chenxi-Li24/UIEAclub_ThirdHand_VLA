# Ubuntu 20.04 Local Asset Provenance

Recorded: 2026-09-10

The physical payloads listed here exist only below `local/` in the isolated Ubuntu checkout. GitHub receives this provenance, the measured sizes and hashes in `configs/assets/ubuntu20.manifest.json`, and the import/verification tools. It does not receive SDK binaries, model weights, copied runtimes, calibration captures, or vendor payloads.

| Asset | Read-only source | Destination | License status | Notes |
|---|---|---|---|---|
| Startouch SDK | `/home/nieqingcao/arm/startouch_sdk` | `local/sdk/startouch` | Unknown | Copied without source `.git` or Python cache; do not publish until authorization is confirmed. |
| XVisio/FastUMI SDK | `/home/nieqingcao/FastUMI_Hardware_SDK` | `local/sdk/xvisio` | Unknown | No clear distributable license was found in the inspected root. |
| FunASR source | `/home/nieqingcao/Thirdhand_language/FunASR` | `local/vendor/funasr` | MIT recorded | Copied without `.git` and cache. Two unsafe absolute links under the Triton example were skipped. |
| Medium ASR | `Thirdhand_language/models/whisper-small` | `local/models/asr/medium` | Unknown | Local use only pending model-license review. |
| Real-time ASR | `Thirdhand_language/models/paraformer-streaming` | `local/models/asr/realtime` | Unknown | Local use only pending model-license review. |
| High ASR | `Thirdhand_language/models/fun-asr-nano` | `local/models/asr/high` | Unknown | Local use only pending model-license review. |
| Python runtime | `Thirdhand_language/runtime/python` | `local/runtimes/python` | Local-only | Python 3.11.15; copied to avoid dependence on the old project path. |
| Node runtime | `Thirdhand_language/runtime/node` | `local/runtimes/node` | Local-only | Node 24.18.0; selected by `./thirdhand` when present. |
| Calibration source | `/home/nieqingcao/calibration` | `local/calibration/source` | Local-only | Raw input for later review; no calibration is promoted automatically. |

## Copy Rules

- Every destination was required to be absent before copying.
- `rsync -a --safe-links` preserved valid relative links and skipped unsafe absolute links.
- Source `.git` directories and `__pycache__` were excluded.
- No source directory was moved, edited, cleaned, reset, or deleted.
- The custom directory hash includes each regular file's relative path and bytes in sorted order. Broken links and empty directories do not contribute to the hash.

The copied FunASR tree retains two broken relative links in old WenetSpeech examples. They point only within the copied FunASR tree, not to old projects, and are not used by the formal speech service. They are recorded rather than silently repaired.

## Verification

Create the ignored host manifest from the tracked record, then verify:

```bash
cp configs/assets/ubuntu20.manifest.json configs/assets/manifest.local.json
./thirdhand verify-assets --json
```

The current report is intentionally not fully ready because Startouch, XVisio, and model license statuses remain `unknown`. File size and SHA-256 checks still detect missing or changed payloads. Change a license status only after recording the governing license or written authorization.
