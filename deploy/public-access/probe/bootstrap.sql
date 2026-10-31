-- C1b REVIEW CANDIDATE: run only as local PostgreSQL administrator after approval.
-- Dedicated network-probe DB, never an existing production database.
\set ON_ERROR_STOP on
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_database WHERE datname='thirdhand_probe')
     OR EXISTS (SELECT FROM pg_roles WHERE rolname='thirdhand-relay') THEN
    RAISE EXCEPTION 'Probe DB/role already exists: inspect it, do not reset';
  END IF;
END $$;
CREATE ROLE "thirdhand-relay" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
ALTER ROLE "thirdhand-relay" SET default_transaction_read_only=on;
CREATE DATABASE thirdhand_probe OWNER postgres;
REVOKE ALL ON DATABASE thirdhand_probe FROM PUBLIC;
GRANT CONNECT ON DATABASE thirdhand_probe TO "thirdhand-relay";
\connect thirdhand_probe
BEGIN;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA ops AUTHORIZATION postgres;
-- Same two registry-table definitions as canonical migration002; no user tables,
-- control leases, execution bindings, telemetry or application migrations here.
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
GRANT USAGE ON SCHEMA ops TO "thirdhand-relay";
GRANT SELECT ON ops.devices,ops.device_credentials TO "thirdhand-relay";
COMMIT;
