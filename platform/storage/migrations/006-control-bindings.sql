-- Existing records do not gain authority from these nullable additions. New
-- control code requires every binding and never restores a persisted lease.
ALTER TABLE ops.control_leases
  ADD COLUMN browser_connection_id uuid,
  ADD COLUMN device_connection_id uuid,
  ADD COLUMN certificate_id uuid REFERENCES ops.device_credentials(id),
  ADD COLUMN renewal_sequence bigint NOT NULL DEFAULT 0;
ALTER TABLE ops.control_takeovers ADD COLUMN browser_connection_id uuid;
ALTER TABLE ops.commands ADD COLUMN request_digest text;
