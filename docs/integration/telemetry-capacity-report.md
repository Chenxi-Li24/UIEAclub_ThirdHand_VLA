# Telemetry capacity scenario — development measurement

Measured at **2026-10-29 20:43:24 UTC** / **2026-10-30 04:43:24 China time**,
with Node 24.19.0 and PostgreSQL 17.11 on the Windows development host. A fresh
dedicated `thirdhand_test_capacity_*` database was created and removed for this
measurement. No SDK, CAN, camera or production database was used.

| Item | Measured result |
|---|---:|
| Synthetic samples persisted | 72,000 / 72,000 |
| Immutable raw batches persisted | 720 / 720 |
| Scenario publication rate | 20 Hz |
| Represented duration | 3,600 seconds |
| Actual development ingestion time | 9.020 seconds |
| Accepted original payload bytes | 101,463,916 bytes |
| Database growth including normalized samples, exact raw payloads and indexes | 129,310,720 bytes, about 123.3 MiB |
| Cluster WAL advance during the measurement | 134,228,560 bytes, about 128.0 MiB |
| Database growth per sample | 1,795.98 bytes |

The generator includes varying measured joints/velocity/torque, separate target
values, raw source state, unavailable fields, units/frames and version identifiers.
It keeps all fields and sequences. The 20 Hz value is an explicit scenario input;
it is **not** a measured physical arm publication rate. The 9.020-second bulk run
does not establish the latency or throughput of the 2-core cloud host or campus
network. WAL is a cluster-wide counter and may include background work.

Using the measured database growth only, the same scenario would imply:

| Assumed operation time | Database growth over 30 days |
|---|---:|
| 1 hour/day | about 3.88 GB |
| 8 hours/day | about 31.03 GB |
| 24 hours/day | about 93.10 GB |

These decimal-GB estimates exclude backups, retained WAL, other services, command
events and future field changes. There is no video recording in this scenario.
The previously observed 39 GB system disk cannot be treated as 39 GB available
for database history. Source rate, duty cycle, retention, backup/WAL policy and
available storage must be measured/reviewed before production allocation. No
automatic history deletion, source downsampling or resource purchase was applied.

Reproduce with the bundled/approved Node 24 and a dedicated test database account:

```sh
TEST_DATABASE_URL=postgresql://thirdhand_test:LOCAL_TEST_PASSWORD@127.0.0.1:5432/thirdhand_test \
  node tools/diagnostics/measure_telemetry_storage.js
```

Next acceptance: capture the actual configured Ubuntu source rate without changing
it, measure full fields/outbox growth and upload latency, then repeat on the
reviewed staging/cloud storage. Physical-source access and deployment follow the
approved C-stage gates.
