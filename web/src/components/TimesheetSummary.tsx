import {
  formatCents,
  platformLabel,
  serviceTypeLabel,
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
            <dt>Service date</dt>
            <dd>{metadata.service_date}</dd>
          </>
        )}
        {metadata.robot_platform && (
          <>
            <dt>Robot platform</dt>
            <dd>{platformLabel(metadata.robot_platform)}</dd>
          </>
        )}
        {metadata.robot_model && (
          <>
            <dt>Robot model</dt>
            <dd>{metadata.robot_model}</dd>
          </>
        )}
        {metadata.serial_number && (
          <>
            <dt>Serial / asset ID</dt>
            <dd>{metadata.serial_number}</dd>
          </>
        )}
        {metadata.service_type && (
          <>
            <dt>Service type</dt>
            <dd>{serviceTypeLabel(metadata.service_type)}</dd>
          </>
        )}
        {metadata.break_minutes != null && metadata.break_minutes > 0 && (
          <>
            <dt>Break time</dt>
            <dd>{metadata.break_minutes} min</dd>
          </>
        )}
        {metadata.issues_found && (
          <>
            <dt>Issues found</dt>
            <dd>{metadata.issues_found}</dd>
          </>
        )}
        {metadata.resolution && (
          <>
            <dt>Resolution</dt>
            <dd>{metadata.resolution}</dd>
          </>
        )}
        {metadata.parts_used && (
          <>
            <dt>Parts used</dt>
            <dd>{metadata.parts_used}</dd>
          </>
        )}
        {metadata.travel_miles != null && (
          <>
            <dt>Travel miles</dt>
            <dd>{metadata.travel_miles}</dd>
          </>
        )}
        {metadata.travel_hours != null && (
          <>
            <dt>Travel time</dt>
            <dd>{metadata.travel_hours} hr</dd>
          </>
        )}
        {metadata.expenses_cents != null && (
          <>
            <dt>Expenses</dt>
            <dd>{formatCents(metadata.expenses_cents)}</dd>
          </>
        )}
        {metadata.follow_up_required && (
          <>
            <dt>Follow-up</dt>
            <dd>Required</dd>
          </>
        )}
      </dl>
    </div>
  );
}
