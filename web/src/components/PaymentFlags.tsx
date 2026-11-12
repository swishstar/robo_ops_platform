export const PAYMENT_FLAG_FIELDS = [
  ["billed_to_client", "Billed to client"],
  ["paid_by_client", "Paid by client"],
  ["paid_to_contractor", "Paid to contractor"],
] as const;

export type PaymentFlagKey = (typeof PAYMENT_FLAG_FIELDS)[number][0];

export type PaymentFlagValues = Record<PaymentFlagKey, boolean | null>;

export function PaymentFlagReadout({ value }: { value: boolean | null | undefined }) {
  const tone = value === true ? "yes" : value === false ? "no" : "open";
  const label = value === true ? "Yes" : value === false ? "No" : "Not set";
  return <span className={`flag-pill flag-${tone}`}>{label}</span>;
}

export function PaymentFlagEditor({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: boolean | null;
  disabled?: boolean;
  onChange: (next: boolean | null) => void;
}) {
  const options: Array<{ id: string; value: boolean | null; text: string }> = [
    { id: "yes", value: true, text: "Yes" },
    { id: "no", value: false, text: "No" },
    { id: "open", value: null, text: "—" },
  ];
  return (
    <div className="flag-editor" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className={value === option.value ? `on flag-${option.id}` : undefined}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.text}
        </button>
      ))}
    </div>
  );
}
