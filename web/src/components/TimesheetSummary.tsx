import {
  completionStatusLabel,
  followUpStatusLabel,
  workCategoryLabel,
  type TimesheetMetadata,
} from "../constants/timesheet";

interface TimesheetSummaryProps {
  metadata?: TimesheetMetadata | null;
}

export function TimesheetSummary({ metadata }: TimesheetSummaryProps) {
  if (!metadata || Object.keys(metadata).length === 0) {
    return null;
  }

  return (
    <div className="panel timesheet-summary">
      <h3>Timesheet details</h3>
      <dl className="detail-grid">
        {metadata.service_date && (
          <>
            <dt>Date of site visit</dt>
            <dd>{metadata.service_date}</dd>
          </>
        )}
        {metadata.customer_site_name && (
          <>
            <dt>Customer / site</dt>
            <dd>{metadata.customer_site_name}</dd>
          </>
        )}
        {metadata.work_order_number && (
          <>
            <dt>Work order</dt>
            <dd>{metadata.work_order_number}</dd>
          </>
        )}
        {metadata.invoice_number && (
          <>
            <dt>Invoice number</dt>
            <dd>{metadata.invoice_number}</dd>
          </>
        )}
        {metadata.completion_status && (
          <>
            <dt>Work completed</dt>
            <dd>{completionStatusLabel(metadata.completion_status)}</dd>
          </>
        )}
        {metadata.follow_up_status && (
          <>
            <dt>Follow-up</dt>
            <dd>{followUpStatusLabel(metadata.follow_up_status)}</dd>
          </>
        )}
        {metadata.difficulty_rating != null && (
          <>
            <dt>Difficulty</dt>
            <dd>{metadata.difficulty_rating} / 5</dd>
          </>
        )}
        {metadata.work_categories && metadata.work_categories.length > 0 && (
          <>
            <dt>Work categories</dt>
            <dd>{metadata.work_categories.map(workCategoryLabel).join(", ")}</dd>
          </>
        )}
        {metadata.tools_equipment && (
          <>
            <dt>Tools / equipment</dt>
            <dd>{metadata.tools_equipment}</dd>
          </>
        )}
        {metadata.media_files && metadata.media_files.length > 0 && (
          <>
            <dt>Media files</dt>
            <dd>
              <ul className="media-file-list compact">
                {metadata.media_files.map((file) => (
                  <li key={file.name}>{file.name}</li>
                ))}
              </ul>
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}
