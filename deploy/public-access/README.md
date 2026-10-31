# Public-access deployment candidate

Current status (2026-11-01): C6 personal model waypoints are deployed to staging,
preserving account registration/approval, authenticated media and read-only device
access. Showcase hero/navigation links are deployed from tracked `showcase/`
source. Physical motion and current camera stability remain unaccepted. Use the
[current implementation guide](../../docs/features/PUBLIC_ACCESS.md) and
[status ledger](../../docs/integration/public-access-implementation-status.md)
before the chronological C1/C2 notes below; older phase limits are historical.

The isolated C2 business staging environment is deployed at
<https://staging.uiea-thirdhand.com/login>; see the [actual C2 report](../../docs/operations/2026-10-30-C2-business-staging-change.md).
Aliyun SMTP is now connected with an explicit single-recipient restriction;
real inbox/registration/MFA acceptance is tracked in the [C2c SMTP report](../../docs/operations/2026-10-30-C2c-aliyun-smtp.md).
Production business/control/media templates remain review material. The separately approved C1b
probe-only mTLS/systemd subset is installed and its1802.250s/3-cycle campus soak passed;
see the [actual C1b record](../../docs/operations/2026-10-30-C1b-probe-change.md).
C1a DNS/public HTTPS was approved and
applied on 2026-10-30; see the [actual change and verification report](../../docs/operations/2026-10-30-C1a-network-change.md).
These templates do not enable a hardware acceptance callback. Existing showcase
source, homepage and navigation buttons are explicitly deferred by the user.
Their files and `/www/wwwroot/uiea-thirdhand-static/` stay in place.

## Approval boundaries

1. **C1a — network only:** confirm the authoritative DNS provider; add only
   `edge.uiea-thirdhand.com A 47.94.95.244` (DNS-only if the provider offers proxying).
   Obtain public server certificates for the main and edge names with Baota's
   existing ACME mechanism. Enable the main HTTPS listener, verify the actual
   cloud security group and host firewall allow TCP443. Keep the edge site closed
   with404 until mTLS, the private socket and registry are ready. Do not publish
   any business/control route or install database/software in this substep.
2. **C1b — private services/probe:** separately approve a fixed release, Node24,
   private PostgreSQL location/capacity, least-privilege roles, the device CA and
   enrollment, Unix socket access and relay unit. Prepare `edge.conf.template`
   against the actual certificate paths, then run `nginx -t` before reload. Enroll
   the Ubuntu device with `remoteControlEnabled=false`. Only bounded no-SDK
   health/WSS probes may run, followed by the approved30–60min campus test.
   The approved concrete scope is [C1b deployment review](../../docs/operations/2026-10-30-C1b-deployment-review.md):
   independent patched Node24.22.1, a dedicated Unix-only PostgreSQL17.11 probe
   registry, read-only relay role, short-lived network-probe credentials and a
   fixed probe-only entry point. `edge-probe.conf.template` is this phase's ingress;
   `edge.conf.template` still belongs to the later full device composition.
3. **C2 — business staging:** applied on the separate staging domain, database,
   keys and synthetic-only inbox using [staging configuration](staging/).
   Eight migrations, unprivileged API/export workers, both-role browser flows,
   history/export, maintenance rollback and base+WAL restore passed.
   [Backup](backup.md) and [rollback](rollback.md) document the actual targets.
   The main showcase vhost remains unchanged. Real inbox/initial administrator acceptance,
   teammate tutorial and media/source capacity remain separate acceptance items.
4. **B6/C3/C4:** camera signalling, media capacity, full action adapters, onsite
   stopping/CAN isolation and real-control acceptance remain separate gates.
   Current physical hardware acceptance is false. Installing templates cannot
   make it true. Never point public routes at the old9983 bare control server.

## Exact changes for C1a review

- **Verified active topology:** the public listener is Ubuntu's system Nginx
  `/usr/sbin/nginx` (1.18.0), managed by `nginx.service`; its active main file is
  `/etc/nginx/sites-available/uiea-thirdhand.com`, linked from `sites-enabled`.
  Baota's Nginx1.28.3 and its66-line main vhost are a separate, inactive public
  serving configuration. Baota certificate issuance still works after the active
  server permits `/.well-known/acme-challenge/`. Do not install later business
  templates into Baota's extension directory and assume they are public.
- Main site: retain the existing HTTP vhost/root/static rules/logs and hidden-file
  denial. The applied C1a change adds only an ACME prefix exception and a separate
  HTTPS vhost for `uiea-thirdhand.com`, TLS1.2/1.3, using Baota's issued certificate
  paths. The unresolved `www` name was not added to DNS or the certificate.
- Edge: create a separate site/dedicated ACME directory. During C1a its only
  public content is ACME validation; all other HTTP/HTTPS requests return404.
  `edge-probe.conf.template` is the approved C1b ingress; `edge.conf.template`
  belongs to the later full device composition.
- Security group/firewall: inspect before changing. Add TCP443 only if missing;
  do not expose3200/3201/5432/3000/3004/3100/8766/9983 or widen SSH/panel access.
- No root/www DNS replacement, no wildcard DNS and no UDP/TURN ports yet.
- No credential values or private keys in Git, chat, command output, screenshots
  or deployment reports. Certificate issuance private keys stay on their hosts.

## Back up, validate, roll back

Before any approved application, record UTC time and effective `nginx -T` locally
in an owner-only server backup directory; copy the existing main vhost, its
extension directory and the panel's certificate references with permissions.
Verify both the actual listener/service and target paths before copying. Record
prior DNS values and security-group rules. C1a backed up both Baota and the active
`/etc/nginx` tree in `/var/backups/thirdhand/access-C1a-20261030T061711Z` on the
server; no backup content containing private keys is uploaded.

Use `nginx -t`; if it fails, restore the specific edited file before any reload.
After a successful reload verify main HTTP/HTTPS and the unchanged showcase,
negative access to bare proxies, and certificate hostname/chain. Revert only the
new include/listener or newly added rule/record if the step fails. Preserve data,
existing site assets and unrelated firewall rules. Business rollback must remain
authenticated/read-only; a public bare-SDK proxy is not a fallback.

The existing cloud snapshot has2CPU, about1.6GB RAM and39GB disk. The synthetic
telemetry capacity report already rules out treating this as an unlimited
all-services host. The systemd memory caps are limits, not evidence these services
plus PostgreSQL/SFU fit concurrently. No media service or resource purchase is
authorized by these files. Choose the database/media placement after capacity
review and measure with the actual device source rate.

Templates require server-side syntax and service checks after paths/users are
resolved; local unit tests do not constitute `nginx -t` or a production rollout.
C1a's actual configuration passed `/usr/sbin/nginx -t` and campus TLS/404 probes.
C1b's actual probe ingress also passed the system Nginx check. Its public-TLS
maintenance service required two measured compatibility fixes: the existing
`/run/nginx.pid` as a writable file and AF_INET6 for the existing IPv6 directives.
The installed unit matches the corrected Git template; the frozen release archive
is retained unchanged. Unchanged-leaf and directory-event checks passed. Actual
CA renewal has not occurred and remains a separate observation.
