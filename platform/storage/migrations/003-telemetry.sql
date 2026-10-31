CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE SCHEMA telemetry;

CREATE TABLE telemetry.ingest_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL, boot_id uuid NOT NULL,
  stream_kind text NOT NULL CHECK(stream_kind IN ('robot_samples','device_events','command_events')),
  batch_seq bigint NOT NULL CHECK(batch_seq>=0), first_seq bigint NOT NULL CHECK(first_seq>=0),
  last_seq bigint NOT NULL CHECK(last_seq>=first_seq),
  seq_range int8range GENERATED ALWAYS AS (int8range(first_seq,last_seq,'[]')) STORED,
  digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
  row_count integer NOT NULL CHECK(row_count>0), completed_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id),
  UNIQUE(device_id,boot_id,stream_kind,batch_seq),
  CHECK(last_seq-first_seq+1=row_count),
  EXCLUDE USING gist (device_id WITH =, boot_id WITH =, stream_kind WITH =, seq_range WITH &&)
);

CREATE TABLE telemetry.robot_samples (
  device_id uuid NOT NULL, boot_id uuid NOT NULL, sample_seq bigint NOT NULL CHECK(sample_seq>=0),
  captured_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
  monotonic_ns bigint NOT NULL CHECK(monotonic_ns>=0),
  clock_quality text NOT NULL CHECK(clock_quality IN ('synchronized','estimated','unreliable')),
  schema_version integer NOT NULL CHECK(schema_version>0), run_id uuid REFERENCES ops.runs(id),
  command_id uuid REFERENCES ops.commands(command_id),
  joint_position_rad double precision[] NOT NULL CHECK(array_ndims(joint_position_rad)=1 AND cardinality(joint_position_rad)=6),
  joint_velocity_rad_s double precision[] CHECK(array_ndims(joint_velocity_rad_s)=1 AND cardinality(joint_velocity_rad_s)=6),
  joint_current_a double precision[] CHECK(array_ndims(joint_current_a)=1 AND cardinality(joint_current_a)=6),
  joint_torque_nm double precision[] CHECK(array_ndims(joint_torque_nm)=1 AND cardinality(joint_torque_nm)=6),
  joint_temperature_c double precision[] CHECK(array_ndims(joint_temperature_c)=1 AND cardinality(joint_temperature_c)=6),
  field_availability jsonb NOT NULL DEFAULT '{}'::jsonb,
  tcp_position_m double precision[] CHECK(array_ndims(tcp_position_m)=1 AND cardinality(tcp_position_m)=3),
  tcp_orientation_xyzw double precision[] CHECK(array_ndims(tcp_orientation_xyzw)=1 AND cardinality(tcp_orientation_xyzw)=4),
  tcp_frame_id text, tool_version text, calibration_version text, gripper jsonb,
  sdk_connected boolean NOT NULL, moving boolean NOT NULL, fault_code text,
  state_age_ms integer CHECK(state_age_ms>=0), quality_flags text[] NOT NULL DEFAULT '{}',
  extra jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(extra)='object'),
  PRIMARY KEY(device_id,captured_at,boot_id,sample_seq),
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id)
) PARTITION BY RANGE(captured_at);

-- Create partitions explicitly before ingest. Out-of-window data must fail visibly,
-- never silently land in an ever-growing default partition or be discarded.
CREATE FUNCTION telemetry.ensure_month_partition(month_start date) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  first_day date := date_trunc('month',month_start)::date;
  next_day date := (date_trunc('month',month_start)+interval '1 month')::date;
  partition_name text := 'robot_samples_' || to_char(month_start,'YYYY_MM');
BEGIN
  PERFORM pg_advisory_xact_lock(240103, 3);
  EXECUTE format('CREATE TABLE IF NOT EXISTS telemetry.%I PARTITION OF telemetry.robot_samples FOR VALUES FROM (%L) TO (%L)',
    partition_name,first_day::text || ' 00:00:00+00',next_day::text || ' 00:00:00+00');
END;
$$;
SELECT telemetry.ensure_month_partition((now() AT TIME ZONE 'UTC')::date);
SELECT telemetry.ensure_month_partition(((now() AT TIME ZONE 'UTC')+interval '1 month')::date);
CREATE INDEX samples_by_device_time ON telemetry.robot_samples(device_id,captured_at,sample_seq);
CREATE INDEX samples_by_run_time ON telemetry.robot_samples(run_id,captured_at,sample_seq) WHERE run_id IS NOT NULL;

CREATE TABLE telemetry.invalid_samples (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, device_id uuid NOT NULL, boot_id uuid NOT NULL,
  batch_id uuid NOT NULL REFERENCES telemetry.ingest_batches(id), sample_seq bigint NOT NULL CHECK(sample_seq>=0),
  reason_code text NOT NULL, sanitized_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  received_at timestamptz NOT NULL DEFAULT now(), UNIQUE(device_id,boot_id,sample_seq),
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id)
);
