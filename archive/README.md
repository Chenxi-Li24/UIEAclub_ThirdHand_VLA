# Historical Implementations

`archive/` preserves retired first-party implementations for traceability. Formal applications, services, drivers, Skills, launch profiles, and default tests must never import from or execute this tree.

Each archived component must include a `PROVENANCE.md` containing its original absolute path, copy date, source Git remote/branch/commit and dirty state, reason for retirement, replacement module, license status, and any files intentionally omitted. Runtime environments, `node_modules`, model payloads, logs, captures, build output, and credentials are not archived in Git.

Moving a component here is a later cutover action. Nothing is removed from the original Ubuntu directories during the isolated migration.
