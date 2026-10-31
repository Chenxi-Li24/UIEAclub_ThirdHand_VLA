# Public-access readiness — 2026-10-30

## C6 model waypoints — 2026-11-01, deployed to staging

User approved the fixed9-file release and minimal simulation table grants;
current is7c7f4b5f3792288e. Full4634-file verification, protected configuration,
readonly health and anonymous401 passed. Real owner save/refresh/admin recall,
same-account Observer recall and logout/new Observer login reread/recall passed;
the retained test point is confirmed in PostgreSQL. The owner reported a long
login spinner that later completed; its cause is unconfirmed, not marked fixed.
Two-login durability/account isolation also passed isolated PG/HTTP tests. Related
Node348/348 and deployment Python5/5 passed before release. No SDK/Ubuntu/device
action; zero new ops.commands during model acceptance. [C6 actual record](2026-11-01-C6-model-waypoints-change.md).

## Latest C3e/C3f result — 2026-11-01

Ubuntu worker software cancellation is installed in independent
robot-6a801e6404e6265e; actual worker path and all new/old hashes verified.
SDKfalse/movingfalse, permanentlyreadOnly, no connect/motion this execution.
Actual Ubuntu SIM expiry cancels itself with stdinopen; physicalStop remains
unknown. Native controlledStop and independent hardware watchdog are unverified,
so physical motion remains disabled. [C3e actual record](2026-11-01-C3e-worker-watchdog-change.md).

Camera explicit-Watch bounded recovery is deployed and retained by the parallel
registration-approval-a570d928578cb5bb identity release. Actual browser still
decoded0frames; current two-viewer stability/35s fault test is not passed.
OwnerObserver login is confirmed, gripper scope is now0–100%; physical calibration,
stop/limits/baseline and capture timing remain open. User cannot currently change
network. [C3f actual record](2026-11-01-C3f-camera-ui-change.md).

Pre-identity-merge bounded regression321Node/233Python,0fail/0skip; derived
site-preserving candidate56Node/35Python and installer17 pass. IsolatedPG55442
is stopped with data retained. The chronological sections below retain their
point-in-time values and must not be read as current release IDs.

## Latest C3d result — 2026-10-31 22:39 China time

Current cloud986ca7c282e532a8 and Ubuntu camera source4e49ee54335e9af3 are active.
Signed camera-only compact renewals are actually observed as987-byte TCP
payloads; full credential refresh remains full-sized. Root final regression:
268Node and205Python pass,0fail/0skip. SDKfalse/readOnlytrue/movingfalse verified;
no SDKconnect/motion this execution, local test PostgreSQL stopped/data retained.

Actual120s check stillfailed7times(3response-header600ms timeouts,4expiredleases).
Short responses do not establish stable video. No current two-viewer30min/35s
fault or physical-motion pass; restored ownerlogin, physicalstop/controller
specifications, grippertravel, newlimit/baseline and captureclock proof remain
pending. Exact changes, rollback and evidence: [C3d record](2026-10-31-C3d-compact-camera-change.md).

Additional90s paired trace had5failures. One exact TCP-sequence match measured
cloud receipt-to-response3.876ms versus client total666.876ms, with response
retransmission. This case is dominated by the return transport path; the exact
network hop is not identified. Awaiting onsite wired/alternate-network options;
no school/Ubuntu network configuration has been changed. Timed captures ended.

## Latest C3c result — 2026-10-31 21:58 China time

Current cloud release04cc19054caa45a6 includes the bounded WebSocket burst fix;
Ubuntu edge/camera publication sources were independently switched and verified.
Robot and camera source processes remain unchanged, SDKfalse/readOnlytrue, no
motion commands. The new physical-stop/scope/acceptance modules are local only.

The post-update120s camera test still had8 response-header600ms timeouts.
Header-only TCP capture shows the leading1428-byte response segment arriving
after the deadline while the tail arrived earlier. Gzip-only was measured and
rejected as insufficient; a smaller authenticated renewal is being developed
locally, not yet deployed. No stable-video or physical-motion pass is claimed.
The physical RGB timestamp candidate compiled against real xv/OpenCV onUbuntu
but has not been executed or installed; UTC uncertainty is stillunknown.
Actual stop/watchdog specifications, gripper travel, fresh physical limits/baseline
and restored owner login remain pending. See [C3c actual record](2026-10-31-C3c-transport-change.md).

The chronological sections below retain their original point-in-time results;
their release IDs and earlier camera passes do not describe the current state.

## Latest C4 result — 2026-10-31 18:57 China time

Active business release is4e858d8b13b8ea6b. Owner-provided showcase source was
verified by exact matching online JavaScript/CSS, and hero/nav/mobile control
login links are deployed. Administrator member CSV and both-role operational
CSV tables are enabled. Actual authenticated downloads verified6accounts and
685hardware samples in54columns, digest/ownership checks and observer denial
for member data.149/149 bounded Node regressions pass. See the
[C4 actual report](2026-10-31-C4-showcase-and-tables.md).
This update does not resolve the C3a camera/renewal/ingestion-latency limits.

## Latest C3a result — 2026-10-31 18:02 China time

Approved read-only SDK deployment is active. Actual administrator web SDK
connection produced685 hardware six-axis samples;132 exact raw batches and
source sequences1–703 pass completeness/digest checks. Administrator web account
directory/history and observer history200/control+identity403 checks passed.
SDK is disconnected, no motion commands were submitted. Current active release
is f2c14f11d88c289e. See the [actual C3a report](2026-10-31-C3a-read-only-change.md).

This is bounded read-only/data evidence. Continuous control renewal failed once,
ingestion median latency was13.312s/P9516.320s, and the current camera browser
check failed with repeated publisher authorization timeouts. Earlier C2i success
does not override these current limits. Realtime telemetry, stable video/control,
physical movement/stop and final production release remain unaccepted.
The chronological sections below retain their original point-in-time results.

## Current C1a result

The user confirmed Alibaba Cloud DNS and approved the exact network-only scope.
C1a was applied and checked on2026-10-30 at14:53 China time:

| Check | Actual result |
|---|---|
| DNS | Main and edge both resolve to47.94.95.244; only edge was added, TTL600s |
| Main HTTP / HTTPS |200 /200; index SHA256 matches the pre-change server manifest |
| Public certificates | Separate Let's Encrypt certificates for main and edge, expiring2027-01-28 UTC |
| TLS | Trusted chain and hostname checks pass with TLS1.2 and TLS1.3 from campus Ubuntu |
| Edge publication | HTTP/HTTPS root and tested device/control/hidden-file paths404 |
| Firewall | Existing UFW443 allowance and ECS security-group443 allowance verified; no rule changed |
| Effective service | System `/usr/sbin/nginx`, `/etc/nginx/sites-enabled/`, service active, syntax test passed |
| Route from campus | Wi-Fi via192.168.58.1; Tailscale carries management SSH only |

Backup, exact paths, limitations and rollback are in the
[C1a change report](2026-10-30-C1a-network-change.md). The table describes C1a's
acceptance snapshot. The approved C1b probe-only installation below supersedes
the closed-edge state. Business and SDK operations remain unpublished.

## Before-change read-only observations

Campus Ubuntu check at **2026-10-29T21:50:01Z** (2026-10-30 05:50 China time):

| Check | Actual result |
|---|---|
| Source | Ubuntu `100.85.63.78`, SSH with the previously verified host-key alias |
| Public route | `47.94.95.244 via192.168.58.1 dev wlp7s0 src192.168.58.68` |
| Main DNS | `uiea-thirdhand.com →47.94.95.244` |
| Device DNS | `edge.uiea-thirdhand.com`: resolution failed |
| Public IP TCP80 | Connected |
| Public IP TCP443 | ConnectionRefusedError, errno111 |
| Baota main site | Running, SSL not deployed, HTTPS port not enabled |
| Panel-visible main vhost |66lines; `listen80`; static root `/www/wwwroot/uiea-thirdhand-static/`; later found separate from the public system Nginx |

The public connection test uses the Ubuntu OS route over Wi-Fi. Tailscale carries
the management SSH session, not this outbound HTTPS route. No SDK/CAN/camera was
opened. A refusal alone cannot distinguish every firewall REJECT from an absent
listener; the visible vhost also has no443 listener. Check both during C1a.

## Local evidence and remaining gates

- Latest related Node regression:171passed,0failed,0skipped, including current
  identity/control/history/media and affected web/Vision tests.
- Full Python edge suite:21passed. A real SQLite lock stop regression and blocked
  publication/source expiry are included.
- Source SSE → independent Python capture → isolated PostgreSQL:6/6 source samples
  retained, source sequences1–6, simulation provenance retained, SDK calls0.
- Full immutable outbox → mTLS HTTPS → PostgreSQL and raw-byte digest verification
  already pass in the isolated environment. No production certificate is used.
- Local history page renders restored geometry and switches English/Chinese;
  actual history/export API authorization is separately tested with real sessions.
- Exact deployment proposal: [deployment candidate](../../deploy/public-access/README.md).

**Pending:** Actual public-certificate renewal, campus re-authentication/network switching, B6 runtime
composition, full admin action adapters, actual SFU integration/load test,
teammate tutorial merge and C3/C4 hardware/field acceptance.
The ECS console reports2vCPU/2GiB and3Mbps fixed public bandwidth; the earlier OS
snapshot showed about1.6GiB usable memory. Media/database placement and viewer
capacity still require an explicit resource decision. No resource purchase,
database/SMTP credential deployment or SDK/hardware operation occurred in C1a.

C1b was separately approved and applied: independent Node24.22.1, Unix-only
PostgreSQL17.11, read-only two-table registry, temporary client identity and the
probe-only mTLS ingress. Certificate rejection, browser denial and online
revocation passed. The public-TLS checker now passes under systemd restrictions,
including its directory event. No actual public-CA renewal has occurred.
The campus run completed2026-10-30T11:05:34Z–11:35:36Z:1802.250seconds,
3successful independent connections,840heartbeats, P95 RTT158.819ms and
P99251.177ms, no unexpected interruption. Post-run main HTTP/HTTPS both200
with the original index digest; cloud audit found no additional TCP listeners.
Relay/PG had zero restarts and no OOM events. Precise cgroup peak counters are
unavailable; the report distinguishes sampled memory maxima from main-process RSS.
See the [actual C1b record](2026-10-30-C1b-probe-change.md).

C2's approved no-hardware business subset is deployed on its separate staging
domain. Eight migrations/private roles, four synthetic verified accounts, MFA,
both-role browser flows, model controls, full operational history/private export,
maintenance rollback and physical base+WAL recovery passed. Recovery also revokes
old MFA credentials; its fixed offline maintenance tool is independently pinned.
Node119/119 and专项pytest5/5 passed. SMTP/real administrator remain deferred by the
user at initial C2. In C2c, Aliyun SMTP was connected with a single authorized
recipient; real test-message receipt is now confirmed. Owner registration/email
verification, admin grant, owner MFA binding and admin-mode entry are complete.
Live password feedback and successful verification redirect are deployed and tested
in [C2d](2026-10-30-C2d-auth-ui-feedback.md), with126/126 related Node tests passing.
The later [C2e MFA update](2026-10-31-C2e-mfa-qr.md) adds password-first input and
offline QR with128/128 related tests plus actual HTTPS acceptance. The later
[C2f fix](2026-10-31-C2f-mfa-layout.md) isolates step layout and hides password
fields when unnecessary; its read-only audit confirms owner MFA and admin entry.
The showcase remains unchanged because original source
was not found and the owner explicitly deferred it again on2026-10-31.
The deployed cloud release now enables camera-only device/media composition;
controlService remains absent and public SDK control stays unavailable.
On2026-10-31 the [C3 preflight](2026-10-31-C3-device-camera-preflight.md)
passed real local SDK connect/read/disconnect with24six-joint states and
no motion commands. XVisio recovered after changing USB ports; actual local
SFU decoding passed8frames640×480. Neither result authorizes public motion.
The [C2g reviewed scope](2026-10-31-C2g-camera-deployment-review.md) was explicitly
approved and applied. [Actual C2g results](2026-10-31-C2g-camera-change.md) include
131/131 Node and33/33 edge Python tests, real Administrator video, two simultaneous
browser subscribers and both-role HTTPS authorization. Capture timing remains
unknown/view-only. Real connected-viewer logout removed both active subscribers
while the publisher remained. Network removal-failure injection has been executed,
but the initial three C2g attempts failed synchronization. Later C2i passed the
complete synchronized fault retest. Long-duration/load, decoder privacy deadline
and production identity rotation remain pending. New results do not overwrite
the earlier failed operator-synchronization assertions.
Automatic approval rejected the proposed35-second private SFU-management firewall
fault initially; the user subsequently explicitly approved it. No fault rule
remains active: the three initial attempts and the subsequent passing C2i attempt
each cleared their exact rule. Original reports and failed timing assessments are
retained. No additional fault is running. One natural response-header timeout
after the C2i fix remains recorded; lease deadlines are unchanged.
The [C2h startup fix](2026-10-31-C2h-workspace-startup.md) is deployed, with133/133
business regressions passing. It makes account/camera/monitoring independent of
the22.4MB model load; existing authentication and idle/attempt limits remain.
The owner has confirmed Observer login, and actual browser evidence shows account,
logout and camera controls available while model loading is still pending.
See also the [C2 report](2026-10-30-C2-business-staging-change.md).

[C2i](2026-10-31-C2i-camera-request-timeout.md) correlates request fragmentation,
TCP retransmission and actual client timeouts with fast cloud processing. Its
single-file coalesced TLS-send fix is deployed only to the camera publisher;
35edge tests and5actual Ubuntu TLS tests pass. A five-minute zero-viewer baseline
has no grant failures; temporary Nginx timing configuration is restored. The owner
subsequently restored the session and both actual Observer viewers decoded640x480.
A300.018second/61sample double-viewer check, the strict35second management-removal
fault test, independent cleanup and post-recovery viewing passed. One natural
grant timeout after the fix but before this viewing window remains recorded;
full long-duration stability is not claimed. SDK stays off.
