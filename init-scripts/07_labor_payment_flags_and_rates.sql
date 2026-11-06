-- One timesheet row per technician per submission.
-- Payment flags are the Google Sheet checkboxes (blank / true / false).
-- amount_cents is the sheet Amount (contractor pay). amount_source records how it was chosen:
--   technician_rate | explicit | estimate_fallback

ALTER TABLE labor_logs
    ADD COLUMN IF NOT EXISTS paid_to_contractor BOOLEAN,
    ADD COLUMN IF NOT EXISTS billed_to_client BOOLEAN,
    ADD COLUMN IF NOT EXISTS paid_by_client BOOLEAN,
    ADD COLUMN IF NOT EXISTS billable_hours NUMERIC(6, 2),
    ADD COLUMN IF NOT EXISTS amount_cents INT,
    ADD COLUMN IF NOT EXISTS payout_cents INT,
    ADD COLUMN IF NOT EXISTS invoice_cents INT,
    ADD COLUMN IF NOT EXISTS amount_source VARCHAR(32);

COMMENT ON COLUMN labor_logs.amount_source IS
    'technician_rate, explicit, or estimate_fallback';

CREATE INDEX IF NOT EXISTS idx_labor_logs_clock_in ON labor_logs (clock_in);
CREATE INDEX IF NOT EXISTS idx_labor_logs_technician_identity ON labor_logs (technician_identity);

CREATE TABLE IF NOT EXISTS technician_rates (
    technician_email VARCHAR(255) PRIMARY KEY,
    technician_name VARCHAR(255),
    payout_cents_per_hour INT NOT NULL,
    invoice_cents_per_hour INT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
