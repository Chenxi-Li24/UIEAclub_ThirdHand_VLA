# ThirdHand History

`History/` contains retired implementations, frozen migration sources, old web
pages, superseded configuration, and implementation records. It is retained for
traceability only. Formal applications, services, drivers, Skills, launch
profiles, and default tests must never import from or execute this tree.

## Layout

| Path | Purpose |
|---|---|
| `source-snapshots/` | Filtered copies used as migration evidence |
| `retired/` | Retired robot, camera, and first-party implementations |
| `legacy-web/` | Superseded standalone browser control pages |
| `legacy-platform/` | Old Python package, configuration, scripts, tests, and docs |
| `project-records/` | Migration baselines, accepted designs, and implementation plans |

## Runtime Boundary

The supported runtime is rooted at `apps/`, `services/`, `drivers/`, `platform/`,
and `skills/`. The `thirdhand` launcher never starts anything under `History/`.
The repository boundary audit rejects executable references from formal source
to this directory.

## Provenance

Imported source snapshots keep their original `PROVENANCE.md`. Those records
contain the source path, copy date, Git state, exclusions, and intended successor.
Snapshot files remain unchanged except for their enclosing directory.

The consolidation was performed on 2026-09-11 in branch
`refactor/unified-platform-foundation`. Original source directories elsewhere in
the Ubuntu home folder were not changed.

## Exclusions

Runtime environments, `node_modules`, model and SDK payloads, logs, captures,
build output, caches, and credentials are not historical source and are not
committed here. They remain governed by `.gitignore` and the project-local
`local/` or `runtime/` directories.
