# Public access implementation status

Updated 2026-11-01. Worktree: D:/claudeworkplace/thirdhand-login, branch login,
based on canonical/fork main24c6f9c. The user subsequently authorized functional
commits and ordinary pushing to fork origin/login. Completed source/resources/docs
are being committed together; no main merge or PR is requested. The original
working directories and unfinished capture-timing changes remain preserved.
See the [Git delivery record](../operations/2026-11-01-login-git-delivery.md).

The active cloud release is **7c7f4b5f3792288e** at staging.uiea-thirdhand.com
(C6 personal model waypoints, verified2026-11-01 02:07 China). It preserves the
parallel registration/admin-approval release. [C6 actual change](../operations/2026-11-01-C6-model-waypoints-change.md)
records this scope; existing transport/video failures remain in the C3 reports.
It supports real registration/email verification, MFA administrator sessions,
account management, model simulation, history/export and authenticated live camera
viewing and an explicitly credential-scoped read-only SDK tier. Actual public
administrator SDK connection produced685 genuine six-axis samples. SDK is now
disconnected; full motion remains disabled. Current video/control stability and
realtime ingestion have not passed acceptance; see the limits below.

| Area | Completed evidence | Still pending |
|---|---|---|
| Accounts/login | Real Aliyun SMTP delivery and owner registration/verification/admin/MFA; separate EN/ZH login and account pages; password feedback, verification redirect, QR and password/code step layout deployed | Real password-reset acceptance, production rotation/release |
| Role boundaries | Actual administrator account directory/history loaded; actual synthetic observer hardware history200 and identity/control403; model simulation remains independent | Full remote-motion acceptance |
| Camera | C3c/C3d compact renewal and C3f bounded viewer recovery deployed and preserved by parallel identity release. RGB timing candidate compiled, not installed | Actual C3f viewer decoded0frames; final180s publisher check9response-header failures. Current two-viewer30min/fault acceptance and captureUTC remain pending |
| Data/history |685 genuine hardware samples,132 exact raw batches, source1–703 continuous/no duplicates,0 invalid; final outbox pending0; actual web history | Latency median13.312s/P9516.320s/max17.253s; sustained realtime/capacity not accepted |
| C3a deployment | User approved and cloud/Ubuntu activated; actual SDK connect completed, automatic SDK release on unconfirmed renewal, later explicit idempotent disconnect; final SDKfalse | Continuous renewal stability; explicit disconnect while still connected not independently proven this round |
| Full robot control | C3e independent worker lease cancellation installed in permanently read-only adapter; actual Ubuntu SIM expiry passed. Bounded20deg scope and private hardware-profile loader remain local | Motion disabled. Independent physical stop, true limits/new baseline, gripper calibration and video timing remain unverified; allowed gripper range now0–100% |
| Tutorial | Adapter and account-scoped progress boundary | Teammate's real tutorial integration at merge |
| Personal model waypoints | C6 fixed9-file release and minimal grants deployed; real owner save/refresh/admin and Observer recall, actual new-login reread/recall, database persistence, full4634-file verification;348 related Node and5 deployment Python tests pass | Login once showed a long spinner then completed; delay cause unconfirmed. Hardware points remain future scope |
| Showcase | Owner-provided ZIP rebuild exactly matched online JS/CSS; hero/nav/mobile control login links deployed and browser-click verified | Production control hostname when separately approved |
| Spreadsheet downloads | Actual6-account administrator CSV/observer403;685 real robot rows in54-column CSV with digest and ownership checks | Existing realtime/capacity limits remain separate |

C3a remains a read-only deployed tier. The user subsequently authorized onsite
supervised six-axis motion up to20degrees from a new measured baseline and
confirmed J7 is the gripper; this is a test scope, not proof of hardware readiness.
The owner now permits 0–100% normalized gripper opening; its physical calibration
and independent fault-stop specifications remain unverified, so motion admission stays closed. C3a permits explicit SDK connection and state reading; model edits never send
hardware commands. Its SDK-release acknowledgement is not a verified physical
motor stop. The current full-control runtime readiness gate remains closed.

Latest final bounded regression after the local worker guard, terminal gateway
and camera-view recovery changes (2026-11-01):
**321/321** combined public-access/Robot Node tests (real isolated PostgreSQL,
Node24 and dedicated Python runtime), **233/233** edge/stop/deployment/packaging/
camera-protocol Python tests;0fail/0skip. The test database was stopped cleanly
afterward, with its data retained. These are bounded scopes, not a claim that
all repository tests or physical acceptance pass.
Earlier C3a review found
four issues; each was reproduced and fixed before the final suites: delayed SDK
connect surviving revocation, insufficient telemetry row-lock privileges,
database-outage rollback dependency and lost version metadata. Whole-repository
tests are not claimed green; previously documented unrelated platform/dependency
failures remain outside these bounded suites.

Deployment references:

- [C3a exact deployment review](../operations/2026-10-31-C3a-read-only-deployment-review.md)
- [C3a actual read-only/data acceptance and remaining failures](../operations/2026-10-31-C3a-read-only-change.md)
- [C4 current showcase source, control links and table downloads](../operations/2026-10-31-C4-showcase-and-tables.md)
- [C3c current transport deployment and remaining motion blockers](../operations/2026-10-31-C3c-transport-change.md)
- [C3d current compact-camera deployment and failed stability check](../operations/2026-10-31-C3d-compact-camera-change.md)
- [C3e installed Ubuntu software cancellation and physical-stop limits](../operations/2026-11-01-C3e-worker-watchdog-change.md)
- [C3f deployed camera viewer recovery and failed real-video check](../operations/2026-11-01-C3f-camera-ui-change.md)
- [C6 deployed personal model waypoints and actual acceptance](../operations/2026-11-01-C6-model-waypoints-change.md)
- [C2i camera test and remaining limits](../operations/2026-10-31-C2i-camera-request-timeout.md)
- [Readiness ledger](../operations/public-access-readiness.md)
- [Approved rollout plan](../superpowers/plans/2026-10-30-public-access-rollout.md)

Historical C1/C2 reports retain their original test counts and point-in-time
limitations; they do not supersede the current status above. C3a proves bounded
read-only SDK access and genuine persisted data, not stable realtime control,
current camera availability, physical motion acceptance or production readiness.
