CREATE TABLE auth.initial_admin_batch (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  closed_at timestamptz NOT NULL DEFAULT now(),
  member_count integer NOT NULL CHECK (member_count BETWEEN 1 AND 100)
);

CREATE TABLE auth.initial_admin_allowlist (
  email text PRIMARY KEY CHECK (email=lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
  user_id uuid UNIQUE REFERENCES auth.users(id) ON DELETE RESTRICT,
  consumed_at timestamptz,
  CHECK ((user_id IS NULL) = (consumed_at IS NULL))
);

CREATE TABLE auth.admin_applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  role_version integer NOT NULL CHECK (role_version > 0),
  reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','superseded')),
  reviewer_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  review_reason text CHECK (length(btrim(review_reason)) BETWEEN 1 AND 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  CHECK (reviewer_id IS NULL OR reviewer_id <> user_id),
  CHECK ((status='pending' AND reviewer_id IS NULL AND reviewed_at IS NULL AND review_reason IS NULL)
    OR (status IN ('approved','rejected') AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)
    OR (status='superseded' AND reviewer_id IS NULL AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL))
);
CREATE UNIQUE INDEX one_pending_admin_application ON auth.admin_applications(user_id) WHERE status='pending';
