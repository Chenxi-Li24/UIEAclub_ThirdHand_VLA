-- Existing camera/probe credentials never gain SDK authority when a device is
-- enabled for control. An operator must explicitly enroll a separate credential.
ALTER TABLE ops.device_credentials
  ADD COLUMN control_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN control_mode text NOT NULL DEFAULT 'read-only'
    CHECK (control_mode IN ('read-only','full'));
