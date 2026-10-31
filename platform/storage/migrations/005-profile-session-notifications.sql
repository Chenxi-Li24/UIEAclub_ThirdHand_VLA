ALTER TABLE auth.users ADD COLUMN organization text NOT NULL DEFAULT '' CHECK(length(organization)<=120);

CREATE FUNCTION auth.notify_session_revoked() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
    PERFORM pg_notify('thirdhand_session_revoked',json_build_object('sessionId',NEW.id,'reason',NEW.revocation_reason)::text);
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER notify_session_revoked AFTER UPDATE ON auth.sessions
  FOR EACH ROW EXECUTE FUNCTION auth.notify_session_revoked();
