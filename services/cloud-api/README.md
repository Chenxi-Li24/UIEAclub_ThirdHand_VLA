# Cloud identity and model workspace

This process serves the separate login/register pages and the protected `/control`
workspace, protected `/history`, bounded raw-history queries and private background
exports and account-bound personal model waypoints. The API has no embedded SDK,
RobotProxy, voice or Dummy bootstrap. Explicit device/media configuration composes
the authenticated relay; the deployed tier permits approved SDK reads only.
Physical motion remains disabled. See the current
[implementation and startup guide](../../docs/features/PUBLIC_ACCESS.md).

Use Node 24, PostgreSQL 17 and `npm ci` at the repository root. Copy the template
from `.env.example` to an owner-readable file outside the checkout; do not use the
example passwords. Node does not implicitly load environment files:

```sh
node --env-file=/etc/thirdhand/cloud.env platform/storage/src/migrate-cli.js
node --env-file=/etc/thirdhand/cloud.env services/cloud-api/src/main.js
```

The migration process uses `MIGRATION_DATABASE_URL`; runtime uses
`IDENTITY_DATABASE_URL`. Migrations are explicit and checksum protected. Production
runtime rejects a PostgreSQL superuser, CREATEDB or CREATEROLE account. The complete
schema/object grants, backup/WAL restore, Nginx, DNS and TLS configuration still
require the deployment acceptance review; these commands are not a production
deployment approval. Runtime listens only on loopback and expects an HTTPS public
origin. Secure cookies must be tested through HTTPS, rather than weakening the
cookie flags for HTTP previews.

Configure SMTP TLS/STARTTLS before registration. Verification/reset links use URL
fragments, are one-use and expire. Never print the mail transport configuration or
verification tokens to application logs. The first administrator is an existing
verified user promoted by the explicit `platform/identity/src/bootstrap-admin.js`
CLI; no first-user administrator rule or HTTP bootstrap exists. Administrators set
up an authenticator from observer mode before signing in in administrator mode.

The teammate-owned tutorial UI is consumed through
[`tutorial-adapter-contract.md`](../../docs/integration/tutorial-adapter-contract.md).
Trusted progress stays unavailable until its provider is merged; browser UI
progress is account scoped and never becomes a control authorization claim.
The owner-provided showcase source is tracked separately under `showcase/`;
its hero/navigation/mobile entries now point to the staging control login.

Run the tests against a **dedicated** database whose name starts with
`thirdhand_test`; test fixtures create/drop their own randomly named databases:

```sh
TEST_DATABASE_URL=postgresql://thirdhand_test:LOCAL_TEST_PASSWORD@127.0.0.1:5432/thirdhand_test npm run test:public-access
```

The device relay tests additionally require the pinned edge test dependencies and
Python 3.11+. `EDGE_TEST_PYTHON` selects that interpreter. CI supplies both.

Set `EXPORT_PRIVATE_DIRECTORY` outside every webroot to enable export jobs and run
`services/cloud-api/src/jobs/export-main.js` as a separate unprivileged worker.
Downloads recheck the current session; row/byte/deadline limits fail explicitly,
not as a truncated successful file. Export expiry never deletes source history.
The local joint-only history preview is separate from all real command transports.

Cloud assets are published under `/control-assets/`; showcase source and its
`/js/`/`/css/` paths are not modified. Device catalog reads do not connect SDK.
The staging entry composes camera authorization/publishing only with complete
explicit configuration; the generic entry stays opt-in. See [media acceptance boundary](../../docs/integration/media-acceptance-boundary.md)
for source-timing and actual SFU acceptance work still required.
