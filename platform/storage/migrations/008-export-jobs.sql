ALTER TABLE ops.export_jobs ADD COLUMN format text NOT NULL DEFAULT 'ndjson' CHECK(format IN ('csv','ndjson'));
ALTER TABLE ops.export_jobs ADD COLUMN error_code text;
ALTER TABLE ops.export_jobs ADD COLUMN started_at timestamptz;
ALTER TABLE ops.export_jobs ADD COLUMN heartbeat_at timestamptz;
CREATE INDEX export_jobs_queue ON ops.export_jobs(created_at,id) WHERE status='queued';
CREATE INDEX export_jobs_owner ON ops.export_jobs(user_id,created_at DESC);
-- Export artifacts are private disposable copies. This migration adds no
-- historical-data deletion or automatic retention rule.
