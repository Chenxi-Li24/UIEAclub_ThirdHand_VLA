-- Shared across API instances, not process-local login counters.
CREATE TABLE security.rate_limits (
  bucket_hash text PRIMARY KEY CHECK(bucket_hash ~ '^[a-f0-9]{64}$'),
  window_started_at timestamptz NOT NULL,
  attempts integer NOT NULL CHECK(attempts>0)
);
