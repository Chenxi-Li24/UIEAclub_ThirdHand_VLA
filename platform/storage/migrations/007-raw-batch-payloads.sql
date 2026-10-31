-- Preserve exact accepted bytes so raw records and their digest can be audited.
CREATE TABLE telemetry.ingest_batch_payloads (
  batch_id uuid PRIMARY KEY REFERENCES telemetry.ingest_batches(id),
  payload_bytes bytea NOT NULL CHECK(octet_length(payload_bytes)<=262144),
  certificate_id uuid REFERENCES ops.device_credentials(id)
);
ALTER TABLE telemetry.invalid_samples
  ADD COLUMN stream_kind text NOT NULL DEFAULT 'robot_samples' CHECK(stream_kind IN ('robot_samples','device_events','command_events'));
ALTER TABLE telemetry.invalid_samples DROP CONSTRAINT invalid_samples_device_id_boot_id_sample_seq_key;
ALTER TABLE telemetry.invalid_samples ADD UNIQUE(device_id,boot_id,stream_kind,sample_seq);
