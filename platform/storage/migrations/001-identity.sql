CREATE SCHEMA auth;
CREATE SCHEMA security;

CREATE TABLE auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE CHECK (username = lower(btrim(username)) AND username ~ '^[a-z0-9_][a-z0-9_.-]{2,47}$'),
  email text NOT NULL UNIQUE CHECK (email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
  display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 80),
  password_hash text NOT NULL,
  role text NOT NULL DEFAULT 'observer' CHECK (role IN ('observer','admin')),
  status text NOT NULL DEFAULT 'pending_email' CHECK (status IN ('pending_email','active','disabled')),
  locale text NOT NULL DEFAULT 'en' CHECK (locale IN ('en','zh-CN')),
  role_version integer NOT NULL DEFAULT 1 CHECK (role_version > 0),
  email_verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'active' OR email_verified_at IS NOT NULL)
);

CREATE TABLE auth.user_preferences (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
  theme_id text NOT NULL DEFAULT 'light' CHECK (length(theme_id) BETWEEN 1 AND 48),
  background_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(background_config)='object'),
  revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[a-f0-9]{64}$'),
  csrf_hash text CHECK (csrf_hash ~ '^[a-f0-9]{64}$'),
  mode text NOT NULL DEFAULT 'observe' CHECK (mode IN ('observe','admin')),
  role_version integer NOT NULL CHECK (role_version>0),
  mfa_verified_at timestamptz,
  client_label text NOT NULL DEFAULT '' CHECK (length(client_label)<=120),
  created_at timestamptz NOT NULL,
  last_user_activity_at timestamptz NOT NULL,
  idle_expires_at timestamptz NOT NULL,
  absolute_expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  revocation_reason text,
  CHECK (mode <> 'admin' OR mfa_verified_at IS NOT NULL),
  CHECK (idle_expires_at<=absolute_expires_at),
  CHECK (absolute_expires_at>created_at)
);
CREATE INDEX sessions_user_active ON auth.sessions(user_id) WHERE revoked_at IS NULL;

CREATE TABLE auth.one_time_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  purpose text NOT NULL CHECK (purpose IN ('verify_email','reset_password','mfa_enroll')),
  token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[a-f0-9]{64}$'),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tokens_user_purpose ON auth.one_time_tokens(user_id,purpose);

CREATE TABLE auth.mfa_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('totp','recovery')),
  encrypted_secret text,
  secret_key_id text,
  recovery_hash text UNIQUE CHECK (recovery_hash ~ '^[a-f0-9]{64}$'),
  last_used_step bigint,
  enabled_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind='totp' AND encrypted_secret IS NOT NULL AND secret_key_id IS NOT NULL AND recovery_hash IS NULL)
    OR (kind='recovery' AND recovery_hash IS NOT NULL AND encrypted_secret IS NULL))
);
CREATE UNIQUE INDEX one_active_totp ON auth.mfa_credentials(user_id) WHERE kind='totp' AND revoked_at IS NULL;

CREATE TABLE auth.role_changes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  previous_role text NOT NULL CHECK (previous_role IN ('observer','admin')),
  new_role text NOT NULL CHECK (new_role IN ('observer','admin')),
  actor_user_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE security.audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_user_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  event_code text NOT NULL,
  object_id text,
  outcome text NOT NULL CHECK (outcome IN ('success','denied','failed')),
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- All role/status mutations acquire the same transaction lock in repositories.
-- The trigger also protects migration/admin SQL from accidentally removing the final admin.
CREATE FUNCTION auth.protect_last_admin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.role='admin' AND OLD.status='active' THEN
    IF TG_OP='DELETE' OR NEW.role<>'admin' OR NEW.status<>'active' THEN
      PERFORM pg_advisory_xact_lock(240103, 2);
      IF NOT EXISTS (SELECT 1 FROM auth.users WHERE role='admin' AND status='active' AND id<>OLD.id) THEN
        RAISE EXCEPTION 'Cannot remove the last active administrator' USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER last_active_admin BEFORE UPDATE OR DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION auth.protect_last_admin();
