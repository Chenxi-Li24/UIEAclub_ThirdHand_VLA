-- Observing sessions may initialize the SDK but cannot acquire motion authority.
-- Existing administrator leases keep their original scope; never restore a lease
-- from storage after service restart.
ALTER TABLE ops.control_leases
  ADD COLUMN scope text NOT NULL DEFAULT 'control'
  CHECK (scope IN ('sdk', 'control'));
