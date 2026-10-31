# Project delivery preferences

The user explicitly requested on 2026-11-01 that every completed independent
feature be committed automatically after its necessary checks pass. Do not ask
again for an ordinary local commit. Report the commit hash and validation.

Update the feature's Markdown documentation in the same delivery: behavior,
modules/APIs, data flow, database changes, resources/configuration, local/cloud
startup, validation, limits and remaining work. Prefer existing relevant docs.
See `docs/features/PUBLIC_ACCESS.md` for the cloud workspace implementation.

Preserve other tasks' changes and existing Git history. Review staged and
untracked files before committing. Never include real credentials, private
administrator lists, database contents, environment directories or runtime
outputs. Runtime assets belong in Git or existing Git LFS rules; document how
to restore them after a fresh clone.

For the current delivery, the user authorized ordinary pushing to the existing
fork `origin` on branch `login`. Do not infer force-push, main-branch publication,
PR merging or future automatic deployment from the local-commit preference.
