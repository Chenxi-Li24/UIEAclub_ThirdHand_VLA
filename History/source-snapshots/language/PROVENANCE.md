# Provenance: Language Delivery Source

- Source: `/home/nieqingcao/Thirdhand_language`
- Source state: delivery directory without an outer Git repository
- Snapshot date: 2026-09-10
- Intended destinations: `apps/web`, `services/speech`, audio driver, voice tests, configuration and operator documentation
- Excluded: `models`, `runtime`, `FunASR`, logs, artifacts, nested repositories, installed dependencies, credentials and caches
- Separate local assets: ASR models, FunASR and Python/Node runtimes are recorded in `configs/assets/ubuntu20.manifest.json`
- Runtime status: migration input only; formal code must not import this snapshot

The old 66,216-line `MANIFEST.sha256` was not retained because it described excluded nested Git data, models and runtimes rather than this filtered source snapshot.
