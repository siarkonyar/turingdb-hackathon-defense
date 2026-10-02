import type { Status } from "../api/types";

const LABEL: Record<Status, string> = { at_risk: "At risk", lost: "Lost", no_power: "No power" };

export function StatusChip({ status }: { status: Status }) {
  const tone = status === "at_risk" ? "amber" : "red";
  return <span className={`chip chip--${tone}`}>{LABEL[status]}</span>;
}
