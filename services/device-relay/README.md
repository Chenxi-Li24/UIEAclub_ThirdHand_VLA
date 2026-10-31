# Authenticated device ingress — B1 probe

`createDeviceRelay` supports two explicit ingress configurations:

- Direct HTTPS/WSS with a server certificate and a dedicated device CA; client
  certificates are mandatory and validated by TLS.
- An HTTP Unix socket behind the reviewed local Nginx mTLS virtual host. TCP peers
  are rejected in this mode. Nginx must overwrite `X-SSL-Client-Verify` and the
  escaped `X-SSL-Client-Cert`, and verify against the dedicated device CA.

Both modes match the complete SHA-256 certificate fingerprint, validity, enabled
device and unrevoked credential in PostgreSQL. Registered keys are Ed25519. An
additional single-use challenge requires the corresponding device private key,
so possession of a public certificate or forwarded headers alone is insufficient.
The challenge binds boot, connection, certificate and device, with a five-second
deadline. Every new connection has a new ID and no control authorization.

The first implementation is deliberately **probe only**. The hello has
`executorEpoch: null`, capabilities `["probe"]`; the Agent does not import any
Robot Service, SDK, CAN or camera code. There is no automatic reconnect or queued
command delivery. A disconnect ends that probe. Device-channel heartbeat is
separate from future browser-derived control renewal and cannot grant control.
Credential changes are rechecked per message/send and at one-second intervals;
the latter bounds idle channel closure and does not establish a hardware stop.

Keep device keys outside Git/browser storage, Linux directory mode 0700 and key
mode 0600, with a dedicated service user. Cloud command-signing keys and personnel
session keys are separate. Certificate enrollment/revocation, private socket
ownership and actual Nginx/systemd settings are prepared/reviewed in C1 before
application to the server. The C1b candidate now has a separate `src/probe-main.js`
entry point; it is not installed on the server. It binds only the fixed private
Unix socket, uses a dedicated local PostgreSQL peer role, checks read-only grants
at startup, and composes no control signer, execution binding, data ingest or media.
It rejects control-enabled registry records rather than changing mode. See the
[exact deployment review](../../docs/operations/2026-10-30-C1b-deployment-review.md).

For a bounded probe after that approved enrollment, install the Python package in
a dedicated Python 3.11+ environment and use the reviewed TOML file:

```sh
python -m thirdhand_edge.probe --config /etc/thirdhand/probe.toml --heartbeats 15
```

The reviewed sustained check uses `--duration-seconds 1800 --cycles 3` instead of
`--heartbeats`. Only completed planned cycles reconnect; an unexpected failure
ends the run. A monotonic ping/pong report includes p50/p95/p99/max RTT and the
longest heartbeat gap. These are network measurements, not physical-stop timing.

Campus NAT requires outbound DNS and TCP 443 to the device hostname, server
certificate trust and synchronized clocks. No inbound campus port, public Ubuntu
IP, Tailscale exit node or router forwarding is required. Probe success is not a
permission to connect the SDK or move the arm.

Tests generate an ephemeral CA and keys locally, exercise Node↔Python mTLS and
byte-exact Ed25519 verification, and do not install static private keys.

Protocol references: [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html),
[cryptography Ed25519](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/),
[Node TLS](https://nodejs.org/api/tls.html).
