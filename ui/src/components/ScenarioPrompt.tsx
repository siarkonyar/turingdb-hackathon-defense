interface Props {
  value: string;
  onChange: (text: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  disabled?: boolean;
  submitLabel: string;
  busyLabel?: string;
  placeholder?: string;
  rows?: number;
  label: string;
  children?: React.ReactNode; // extra controls next to the button
}

/** A plain-English event box: the scenario question, or an event injected into a running wargame. */
export function ScenarioPrompt({ value, onChange, onSubmit, busy, disabled, submitLabel, busyLabel, placeholder, rows = 3, label, children }: Props) {
  const blocked = Boolean(busy || disabled) || value.trim().length < 3;
  return (
    <>
      <textarea
        className="scenario__input"
        aria-label={label}
        rows={rows}
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !blocked) onSubmit();
        }}
        placeholder={placeholder}
      />
      <div className="scenario__actions">
        <button type="button" className="btn" disabled={blocked} onClick={onSubmit}>
          {busy ? (busyLabel ?? submitLabel) : submitLabel}
        </button>
        {children}
      </div>
    </>
  );
}
