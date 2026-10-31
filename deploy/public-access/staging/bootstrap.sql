\set ON_ERROR_STOP on
DO $$ BEGIN
  IF EXISTS(SELECT FROM pg_database WHERE datname='thirdhand_stage') OR EXISTS(SELECT FROM pg_roles WHERE rolname IN ('thirdhand-stage','thirdhand-stage-export','thirdhand-stage-migrate')) THEN
    RAISE EXCEPTION 'Existing staging identity: inspect, never reset';
  END IF;
END $$;
CREATE ROLE "thirdhand-stage-migrate" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE "thirdhand-stage" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8;
CREATE ROLE "thirdhand-stage-export" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
CREATE DATABASE thirdhand_stage OWNER "thirdhand-stage-migrate";
ALTER DATABASE thirdhand_stage SET TimeZone='UTC';
REVOKE ALL ON DATABASE thirdhand_stage FROM PUBLIC;
GRANT CONNECT ON DATABASE thirdhand_stage TO "thirdhand-stage","thirdhand-stage-export";
\connect thirdhand_stage
REVOKE ALL ON SCHEMA public FROM PUBLIC;
