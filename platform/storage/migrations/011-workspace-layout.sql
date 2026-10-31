-- Presentation preference only; this does not grant a role or device access.
ALTER TABLE auth.user_preferences ADD COLUMN layout_id text NOT NULL DEFAULT 'workspace'
  CHECK (layout_id IN ('workspace','classic'));
ALTER TABLE auth.user_preferences ADD COLUMN classic_theme_id text NOT NULL DEFAULT 'deepspace'
  CHECK (classic_theme_id IN ('deepspace','industrial','cyber','dark','green','blue','purple','orange','light'));
