# Registration and Administrator Approval

**Goal:** Allow public Observer registration while granting administrator access only through a sealed initial batch or another administrator's approval.

**Approved direction:** Public registration still requires email verification. The initial administrator email list is supplied privately by the server maintainer, stored atomically and permanently sealed after successful import. Existing verified accounts claim their reservation during import; future accounts claim only after email verification. Existing administrators remain unchanged. Later users submit an application; a distinct administrator approves or rejects it after password and MFA reauthentication. Promotion revokes existing sessions. Administrator mode still requires MFA.

**Scope:** Cloud identity, storage migration, account UI, tests and operational documentation. No robot changes, commits or pushes. User supplied eight initial administrator emails; preserve the real list outside Git. Local tests never elevate real accounts. Server activation requires the migration, private list import and reviewed release.

**Architecture:** Keep SMTP restricted delivery as the legacy default; explicitly select `REGISTRATION_MODE=open` to ignore the recipient restriction for the cloud service. Add an application repository using the existing role mutation transaction lock. The old role grant endpoint must consume a pending application rather than bypass approval. Initial batch import is a server-only CLI, never HTTP.

## Tasks
- [x] Write failing tests for open SMTP configuration, sealed initial batch and application approval.
- [x] Add forward migration and repository. Test validation, pending uniqueness, self-approval rejection, disabled/unverified targets, stale roles, concurrent decisions and session revocation.
- [x] Add authenticated application routes and password/MFA-protected approval routes. Preserve CSRF, origin checks and existing last-admin protection.
- [x] Add Observer application and administrator decision controls with English/Chinese labels, loading/error states and no direct grant bypass.
- [x] Run isolated PostgreSQL and HTTP/UI regressions, review the change, copy only verified deltas to the original login worktree and stage exactly changed files.

## Decisions
- A missing/empty initial list never grants anyone privileges. No automatic first registrant promotion.
- Batch import stores a fixed normalized list even for not-yet-registered accounts. Privileges can be claimed once, only by the verified active account matching the normalized email. Revocation never recreates the reservation. Successful import seals the list across restarts or later demotion.
- Applications store the target role version; changes to status/role invalidate approval. Each decision is serialized and can occur once. Denial permits a later application subject to rate limiting.
- Keep mail/password validation and rate limiting. Open registration is not unlimited mail sending.
- Use a writable isolated source copy because the original login worktree has concurrent unrelated changes. Before copying back, compare source hashes and refuse to overwrite any concurrent edits.

## Execution Record (2026-11-01)
- User explicitly prioritized and approved the eight-address initial list online before the rest of the feature. Separate action-time approval covered the exact recipient set and transmission of the necessary account sources to the user's own cloud server.
- Phase one preserved the concurrent camera-only update and used the shared installer lock. The initial list was imported once, sealed, and independently compared against the private file: eight exact normalized entries, zero existing matching accounts, zero claims. Runtime SMTP policy accepted upper-case aliases without sending real mail.
- User then approved uploading the ten full-feature sources and opening Observer registration. Phase two is live at `/opt/thirdhand-stage/releases/registration-approval-a570d928578cb5bb`, with the initial list unchanged and legacy delivery restriction removed from the process environment.
- Local verification: 84 account/session/control-mock tests, 12 responsive English/Chinese browser views, and six installer safety unit tests passed. No robot commands, real test account creation or test email delivery.
- Both cloud phases completed health checks and full source inventory verification. Unauthenticated application/admin/new-script endpoints returned 401; a nonallowlisted invalid-password request returned 400/INVALID_PASSWORD before account creation or mail sending.
- A reviewer found the revoked-administrator reapplication UI bug and two deployment rollback races. All were corrected and rechecked before application.
- No Git commits or pushes authorized in this task. Actual email addresses remain in ignored private configuration, not source or test fixtures.
