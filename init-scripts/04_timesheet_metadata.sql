-- Timesheet metadata for Google Form migration fields (stored alongside labor_logs)
ALTER TABLE labor_logs
    ADD COLUMN IF NOT EXISTS timesheet_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_labor_logs_timesheet_metadata
    ON labor_logs USING gin (timesheet_metadata);
