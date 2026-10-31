\set ON_ERROR_STOP on
BEGIN;
GRANT USAGE ON SCHEMA simulation TO "thirdhand-stage";
GRANT SELECT,INSERT,DELETE ON simulation.user_programs TO "thirdhand-stage";
COMMIT;
