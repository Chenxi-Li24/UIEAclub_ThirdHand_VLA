# Read-Only Source Snapshots

This directory temporarily preserves active source-project boundaries while the unified services are migrated. It is not a runtime module and no formal application, service, driver, Skill, or launcher profile may import from `migration/sources/`.

Each child is a filtered copy from an accepted Ubuntu source. Nested Git repositories, environments, dependency installations, SDK/model payloads, build output, logs, captures, artifacts, credentials, and caches are excluded. The original source directories remain unchanged.

The snapshots are removed only after their required code, tests, configuration, and documentation have been promoted into the normalized project structure and verified. Removal and production cutover require separate approval.
