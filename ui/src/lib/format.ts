// Display formatting. Numbers, ids and times render in JetBrains Mono, so keep them compact.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 0.1) return "<0.1";
  if (ms < 10) return ms.toFixed(1);
  return Math.round(ms).toLocaleString("en-GB");
}

export function formatInt(n: number | null | undefined): string {
  return n == null ? "—" : Math.round(n).toLocaleString("en-GB");
}

export function formatMw(mw: number | null | undefined): string {
  if (mw == null) return "—";
  return mw >= 1000 ? `${(mw / 1000).toFixed(1)} GW` : `${Math.round(mw)} MW`;
}

export function formatCoord(lat: number | null | undefined, lon: number | null | undefined): string {
  if (lat == null || lon == null) return "—";
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)}°${ns}  ${Math.abs(lon).toFixed(4)}°${ew}`;
}

/** 29 Sep 06:09Z */
export function formatUtc(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${hh}:${mm}Z`;
}

export function formatIso(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? iso : formatUtc(ms / 1000);
}

export function formatPercent(p: number | null | undefined): string {
  return p == null ? "—" : `${Math.round(p * 100)}%`;
}

/** "POWERED_BY" -> "Powered by" */
export function humanRel(rel: string): string {
  const s = rel.toLowerCase().replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? formatInt(value) : String(+value.toFixed(4));
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}
