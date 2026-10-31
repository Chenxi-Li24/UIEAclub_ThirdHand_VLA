-- Apply as PostgreSQL owner, never from the application on startup.
-- Preserve existing grants. No DELETE, DDL, credential enrollment or device
-- enablement privileges are added to the application identity.
BEGIN;
GRANT UPDATE(control_epoch) ON ops.devices TO "thirdhand-stage";
GRANT INSERT ON ops.device_boots,ops.execution_instances TO "thirdhand-stage";
GRANT UPDATE(binding_confirmation) ON ops.execution_instances TO "thirdhand-stage";
GRANT INSERT,UPDATE ON ops.control_leases,ops.control_takeovers,ops.runs,ops.commands TO "thirdhand-stage";
GRANT INSERT ON ops.device_events,ops.command_events,telemetry.ingest_batches,
  telemetry.ingest_batch_payloads,telemetry.invalid_samples,telemetry.robot_samples TO "thirdhand-stage";
GRANT USAGE ON SEQUENCE ops.device_events_id_seq,ops.command_events_id_seq,
  telemetry.invalid_samples_id_seq TO "thirdhand-stage";
COMMIT;
