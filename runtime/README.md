# Runtime State

This ignored directory is created and owned by `./thirdhand` while the unified project runs:

- `run/`: PID ownership, process start markers, command hashes, sockets, and authorization state.
- `logs/`: one stdout/stderr stream per managed service plus launcher events.
- `captures/`: temporary RGB, depth, point-cloud, audio, and diagnostic captures.
- `artifacts/`: task plans, approvals, results, supervision evidence, and exported reports.
- `cache/`: rebuildable inference and application caches.

No file below these subdirectories is source code or a durable configuration. `stop` only signals processes whose recorded identity still matches; it never trusts a PID by itself.
