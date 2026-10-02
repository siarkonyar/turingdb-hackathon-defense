import { useOps } from "../state/store";

export function Toasts() {
  const toasts = useOps((s) => s.toasts);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast glass toast--${t.tone}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
