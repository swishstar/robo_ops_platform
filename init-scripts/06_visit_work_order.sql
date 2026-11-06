-- Client / internal job identifier (e.g. RoboJob_00126)
ALTER TABLE visits
    ADD COLUMN IF NOT EXISTS work_order_number VARCHAR(120);

CREATE INDEX IF NOT EXISTS idx_visits_work_order_number
    ON visits (work_order_number);

-- Backfill from timesheet metadata when present
UPDATE visits v
SET work_order_number = sub.wo
FROM (
    SELECT DISTINCT ON (visit_id)
        visit_id,
        NULLIF(BTRIM(timesheet_metadata->>'work_order_number'), '') AS wo
    FROM labor_logs
    WHERE timesheet_metadata ? 'work_order_number'
    ORDER BY visit_id, created_at DESC
) sub
WHERE v.visit_id = sub.visit_id
  AND sub.wo IS NOT NULL
  AND (v.work_order_number IS NULL OR BTRIM(v.work_order_number) = '');

-- Prefer compact RoboJob_##### when that token appears in the field or location
UPDATE visits v
SET work_order_number = sub.job
FROM (
    SELECT visit_id,
           COALESCE(
               (regexp_match(COALESCE(work_order_number, ''), 'RoboJob_[0-9]+'))[1],
               (regexp_match(location_string, 'RoboJob_[0-9]+'))[1]
           ) AS job
    FROM visits
) sub
WHERE v.visit_id = sub.visit_id
  AND sub.job IS NOT NULL
  AND v.work_order_number IS DISTINCT FROM sub.job;
