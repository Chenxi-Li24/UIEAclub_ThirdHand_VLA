# Observer Open Registration and Administrator Approval

## Behavior

- Observer registration accepts any valid email when `REGISTRATION_MODE=open`. Email verification, password requirements and shared rate limits remain enforced. Client-supplied role values never grant privileges.
- Email comparison is case-insensitive. Storage and SMTP normalize by trimming and converting to lower case. For example, `Alice.Example@example.invalid` and `alice.example@example.invalid` are the same account, not two accounts.
- The first administrator batch is a fixed, private list of normalized email addresses, imported once by the server maintainer. Existing administrators are preserved. The list is not an Observer registration restriction.
- Verified active accounts already present claim their initial reservation during import. Not-yet-registered or unverified accounts remain unprivileged until they register and successfully verify the matching email.
- Reservations are one-use. Revoking a listed administrator does not grant it again on a later login. The batch remains sealed across process restarts and demotions.
- All other verified Observers apply in Account settings. A distinct active administrator in Administrator mode approves/rejects with current password and fresh authenticator/recovery proof. No self-approval.
- Approvals and rejections are serialized, recorded with reviewer/reason/time, and cannot be replayed. Account changes invalidate approval. Rejected users may apply again, subject to rate limiting.
- The old role grant API requires a pending application too. The member table no longer provides direct promotion; revocation/account disable remain available.
- Promotion revokes the target's existing sessions. The user must sign in again, enroll MFA, and explicitly enter Administrator mode. Promotion does not start SDKs or authorize movement.

## Private Initial List

The user provided eight addresses. The real list is stored locally in the login worktree at `.superpowers/private/initial-admins.json`, ignored by Git. Do not copy those addresses into source, screenshots, test fixtures, release manifests or public logs. No real account is elevated by the isolated synthetic-account tests.

On the server, place the approved JSON array in an OS-protected location outside the release/webroot, for example `/etc/thirdhand-stage/initial-admins.json`, owned by the maintenance identity with mode `0600`. Do not put database credentials or the list on the command line.

## Activation Order

1. Review the release against the running version, retain an immutable release/DB backup and pause account mutations during migration and initial import. This affects only the cloud account API, not robot services.
2. Run the forward migration `010-admin-applications.sql` using the controlled migration identity. Do not edit/reapply old migration versions.
3. Reapply the reviewed staging grants. The runtime needs SELECT/INSERT/UPDATE on `auth.admin_applications`, SELECT on `auth.initial_admin_batch` and `auth.initial_admin_allowlist`, and UPDATE of only `user_id,consumed_at` on the allowlist. It must not receive INSERT/DELETE or email UPDATE permission on the initial list, or write permission on the batch seal.
4. Under the protected maintenance environment containing `MIGRATION_DATABASE_URL`, run:

```sh
node platform/identity/src/initial-admins.js /etc/thirdhand-stage/initial-admins.json --confirm-initial-admins
```

The CLI validates the private regular file and refuses a second import with `BOOTSTRAP_CLOSED`. Its output contains counts, not the email list. The old `bootstrap-admin.js` entry now delegates to this same list-based tool; the old UUID/first-admin arguments no longer work.

5. Set `REGISTRATION_MODE=open` in the private cloud environment. Unset `SMTP_ALLOWED_RECIPIENTS_JSON` to avoid confusion: open mode ignores the legacy delivery list. Keep SMTP sender/auth/TLS configuration intact. If `REGISTRATION_MODE` is absent, the legacy restricted behavior remains deliberately unchanged; editing source alone does not open an existing deployment.
6. Switch only the cloud account release and restart its API after review. Verify public registration with a user-authorized real email, mail delivery/verification, mixed-case duplicate rejection, initial claim and session/MFA behavior. Never send real mail in automated tests.
7. Check Observer application submission, administrator pending list and both decisions. Verify forged target IDs, CSRF failures, missing MFA, duplicate decisions and direct grant attempts are rejected.

## Rollback and Boundaries

Do not delete application, role-change, initial-list or audit records. Retain the forward schema on rollback. Do not roll back to an old backend with unrestricted role promotion while account writes remain enabled. Restore restricted delivery if necessary and disable mutations pending review.

Keep the last-active-administrator guard. Initial membership is fixed by a deliberate server-only import; later membership changes require another administrator's approval, not editing a browser field or modifying the allowlist.

Local implementation/test completion does not mean cloud activation. Record the release, migration, grant and private-import results separately before claiming the site is updated.

## Actual Deployment and Evidence (2026-11-01)

Both phases below were explicitly approved and applied to `https://staging.uiea-thirdhand.com` on the user's own cloud server. Only `thirdhand-stage.service` was restarted. No Robot/SDK/CAN service was restarted and no movement command was sent.

### Initial List First

- Preserved the camera fix in baseline `6edc4258818b6b65`. First review correctly refused an outdated earlier baseline instead of overwriting that fix.
- Published four required account/migration files as `initial-admins-ff7ea312a93fef15`, with 4628 source files verified.
- Applied forward migration 010 and the least-privilege runtime grants. Imported the real list only after the new verification handler was healthy.
- Database verification: the exact eight normalized addresses match the private input; one batch seal; zero matching accounts, zero claims, eight pending reservations at verification time. No unverified account was promoted and no account was created on behalf of a person.
- Running mail configuration accepted each listed address and its upper-case alias. No real verification/test mail was sent by this check. Case-insensitive uniqueness and same-account matching were additionally exercised with synthetic accounts in PostgreSQL tests.
- Private records: `/var/backups/thirdhand/initial-admins-20261101/`, mode 0700; private list and database backup mode 0600. The CLI's OS-postgres-only input is under `/run/thirdhand-initial-admins-20261101/`. These are not release/webroot/Git files.

### Open Registration and Applications

- After verifying the initial list, published the ten full-feature sources as `registration-approval-a570d928578cb5bb`, with 4630 source files verified. No dependency installation or second list import.
- Set `REGISTRATION_MODE=open`; removed `SMTP_ALLOWED_RECIPIENTS_JSON` from the active environment. Other mail/security/device configuration values were preserved.
- Health check passed. Application routes and the new protected script require authentication (401). A registration request for a nonallowlisted synthetic address with an invalid password returned `400 / INVALID_PASSWORD`, proving it reached password validation rather than the former recipient restriction. It created no account and sent no mail.
- Initial batch seal and email membership were unchanged. Claims may legitimately occur later when an actual user verifies an email; the deployment does not reset or replay claims.
- Private deployment report/backups: `/var/backups/thirdhand/registration-approval-20261101/`. Current API PID at application was 835618 (operational detail, not a stable identifier).
- Real end-user registration, inbox delivery and human MFA approval still require those users' own actions. Automated tests and deployment probes did not impersonate them.

### Release Safeguards

The fixed deployment tools are preserved as `tools/operations/activate_initial_admins.py` and `tools/operations/apply_registration_approval.py`. They validate pinned inventories and preserve concurrent camera work. Both use the existing shared installer lock. A PostgreSQL SHARE lock drains lease writes and keeps admission blocked through API shutdown; phase-two rollback additionally drains application mutations and rechecks activity after stopping the API.

Initial-import rollback waits for the role-mutation advisory lock before reading the seal with a fresh READ COMMITTED snapshot. A committed or uncertain import never restores an old handler unaware of the list. No database restore/delete/replay is performed automatically.

Local acceptance completed: 84 Node account/identity/control-mock tests, six installer protection unit tests and 12 English/Chinese browser views at 375, 768 and 1440 pixels, without page overflow or browser errors. Evidence screenshots and logs remain in the ignored implementation ledger, not public deployment payloads.
