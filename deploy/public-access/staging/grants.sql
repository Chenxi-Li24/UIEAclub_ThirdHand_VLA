\set ON_ERROR_STOP on
BEGIN;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth,telemetry FROM PUBLIC;
GRANT USAGE ON SCHEMA auth,security,ops,telemetry TO "thirdhand-stage";
GRANT SELECT,INSERT,UPDATE ON auth.users,auth.user_preferences,auth.sessions,auth.one_time_tokens,auth.mfa_credentials,security.rate_limits TO "thirdhand-stage";
GRANT SELECT,INSERT ON auth.role_changes,security.audit_events TO "thirdhand-stage";
GRANT SELECT,INSERT,UPDATE ON auth.admin_applications TO "thirdhand-stage";
GRANT SELECT ON auth.initial_admin_batch,auth.initial_admin_allowlist TO "thirdhand-stage";
GRANT UPDATE(user_id,consumed_at) ON auth.initial_admin_allowlist TO "thirdhand-stage";
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA security TO "thirdhand-stage";
GRANT SELECT ON ALL TABLES IN SCHEMA ops,telemetry TO "thirdhand-stage";
GRANT INSERT,UPDATE ON ops.export_jobs TO "thirdhand-stage";
GRANT USAGE ON SCHEMA ops,telemetry TO "thirdhand-stage-export";
GRANT SELECT ON ALL TABLES IN SCHEMA ops,telemetry TO "thirdhand-stage-export";
GRANT UPDATE ON ops.export_jobs TO "thirdhand-stage-export";
ALTER DEFAULT PRIVILEGES FOR ROLE "thirdhand-stage-migrate" IN SCHEMA telemetry GRANT SELECT ON TABLES TO "thirdhand-stage","thirdhand-stage-export";
COMMIT;
