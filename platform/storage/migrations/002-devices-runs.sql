CREATE SCHEMA ops;
CREATE SCHEMA simulation;

CREATE TABLE ops.devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
  hardware_serial text NOT NULL UNIQUE, enabled boolean NOT NULL DEFAULT false,
  last_seen_at timestamptz, control_epoch bigint NOT NULL DEFAULT 0 CHECK(control_epoch>=0),
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb, config_version text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ops.device_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL REFERENCES ops.devices(id),
  certificate_serial text NOT NULL UNIQUE, fingerprint_sha256 text NOT NULL UNIQUE,
  public_key text NOT NULL, not_before timestamptz NOT NULL, expires_at timestamptz NOT NULL,
  revoked_at timestamptz, CHECK(expires_at>not_before)
);
CREATE TABLE ops.device_boots (
  boot_id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES ops.devices(id),
  agent_version text NOT NULL, sdk_version text, config_hash text, calibration_hash text,
  started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz, sealed_at timestamptz,
  UNIQUE(device_id,boot_id)
);
CREATE TABLE ops.execution_instances (
  executor_epoch uuid PRIMARY KEY, device_id uuid NOT NULL, boot_id uuid NOT NULL,
  worker_instance_id text NOT NULL, hardware_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
  config_hash text, binding_confirmation jsonb,
  started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id),
  UNIQUE(device_id,boot_id,executor_epoch)
);
CREATE TABLE ops.control_leases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL REFERENCES ops.devices(id),
  user_id uuid NOT NULL REFERENCES auth.users(id), session_id uuid NOT NULL REFERENCES auth.sessions(id),
  client_instance_id uuid NOT NULL, boot_id uuid NOT NULL, executor_epoch uuid NOT NULL,
  lease_epoch bigint NOT NULL CHECK(lease_epoch>0),
  state text NOT NULL CHECK(state IN ('requested','active','revoking','released','expired','failed')),
  requested_at timestamptz NOT NULL DEFAULT now(), confirmed_at timestamptz, expires_at timestamptz,
  released_at timestamptz, release_reason text,
  FOREIGN KEY(device_id,boot_id,executor_epoch) REFERENCES ops.execution_instances(device_id,boot_id,executor_epoch),
  UNIQUE(device_id,lease_epoch)
);
CREATE UNIQUE INDEX one_control_holder ON ops.control_leases(device_id) WHERE state IN ('requested','active','revoking');
CREATE TABLE ops.control_takeovers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL REFERENCES ops.devices(id),
  user_id uuid NOT NULL REFERENCES auth.users(id), session_id uuid NOT NULL REFERENCES auth.sessions(id),
  client_instance_id uuid NOT NULL, target_lease_id uuid NOT NULL REFERENCES ops.control_leases(id),
  target_epoch bigint NOT NULL, nonce_hash text NOT NULL UNIQUE,
  state text NOT NULL CHECK(state IN ('pending','stopping','granted','rejected','expired','failed')),
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  confirmed_at timestamptz, stop_result jsonb, granted_lease_id uuid REFERENCES ops.control_leases(id)
);
CREATE TABLE ops.runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL REFERENCES ops.devices(id),
  boot_id uuid NOT NULL, actor_user_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  actor_kind text NOT NULL CHECK(actor_kind IN ('user','local_os')), actor_display_name text NOT NULL,
  local_os_identity text, maintenance_evidence jsonb,
  source text NOT NULL CHECK(source IN ('manual','preset','sequence','voice','grasp','dummy','local_maintenance')),
  status text NOT NULL CHECK(status IN ('requested','running','completed','stopped','rejected','failed','unknown')),
  versions jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id),
  CHECK((actor_kind='user' AND actor_user_id IS NOT NULL) OR (actor_kind='local_os' AND local_os_identity IS NOT NULL)),
  UNIQUE(id,device_id,boot_id)
);
CREATE INDEX runs_by_device_time ON ops.runs(device_id,started_at DESC,id);
CREATE TABLE ops.commands (
  command_id uuid PRIMARY KEY, run_id uuid NOT NULL, device_id uuid NOT NULL, boot_id uuid NOT NULL,
  session_id uuid REFERENCES auth.sessions(id), lease_id uuid REFERENCES ops.control_leases(id),
  executor_epoch uuid NOT NULL, lease_epoch bigint NOT NULL, sequence bigint NOT NULL CHECK(sequence>=0),
  opcode text NOT NULL, schema_version integer NOT NULL CHECK(schema_version>0), parameters jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  state text NOT NULL CHECK(state IN ('accepted','started','completed','stopped','rejected','failed','unknown')),
  result jsonb, created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(run_id,device_id,boot_id) REFERENCES ops.runs(id,device_id,boot_id),
  FOREIGN KEY(device_id,boot_id,executor_epoch) REFERENCES ops.execution_instances(device_id,boot_id,executor_epoch),
  UNIQUE(device_id,boot_id,lease_epoch,sequence)
);
CREATE TABLE ops.command_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  command_id uuid NOT NULL REFERENCES ops.commands(command_id), edge_event_id uuid NOT NULL UNIQUE,
  event_code text NOT NULL, captured_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
  details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX command_events_by_command ON ops.command_events(command_id,id);
CREATE TABLE ops.device_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, device_id uuid NOT NULL REFERENCES ops.devices(id),
  boot_id uuid, edge_event_id uuid NOT NULL UNIQUE, event_code text NOT NULL,
  level text NOT NULL CHECK(level IN ('info','warning','error','critical')),
  captured_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), details jsonb NOT NULL DEFAULT '{}'::jsonb,
  FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id)
);
CREATE INDEX device_events_by_time ON ops.device_events(device_id,captured_at,id);
CREATE TABLE ops.device_latest_state (
  device_id uuid PRIMARY KEY REFERENCES ops.devices(id), boot_id uuid NOT NULL,
  captured_at timestamptz NOT NULL, received_at timestamptz NOT NULL,
  state jsonb NOT NULL, FOREIGN KEY(device_id,boot_id) REFERENCES ops.device_boots(device_id,boot_id)
);
CREATE TABLE simulation.user_programs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES auth.users(id),
  name text NOT NULL CHECK(length(name) BETWEEN 1 AND 120), model_version text NOT NULL,
  program jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX programs_owner ON simulation.user_programs(user_id);
CREATE TABLE ops.export_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid NOT NULL REFERENCES auth.users(id),
  filter jsonb NOT NULL, status text NOT NULL CHECK(status IN ('queued','running','completed','failed','expired')),
  private_object_key text, row_count bigint, digest text, expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE TABLE ops.artifact_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text NOT NULL, version text NOT NULL,
  digest text NOT NULL, private_resource_ref text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(kind,version)
);

-- Device/command events are append-only to application code; roles are granted in deployment.
-- No default video recording table or tutorial-progress table is introduced.
