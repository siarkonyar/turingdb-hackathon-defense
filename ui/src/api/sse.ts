// Server-sent events for agent jobs and matches. Every stream ends with a `done` event; we close then,
// so the browser does not reconnect to a finished job. A dropped connection reconnects on its own and
// the server resumes after the last event id, so handlers never see duplicates.

export const JOB_EVENTS = ["job_started", "step", "result", "error", "done"] as const;
export const MATCH_EVENTS = [
  "job_started",
  "match_started",
  "move_started",
  "move",
  "inject",
  "round_done",
  "status",
  "match_done",
  "error",
  "done",
] as const;

export type Unsubscribe = () => void;

export function follow<T extends { type: string }>(
  url: string,
  types: readonly string[],
  onEvent: (event: T) => void,
  onBroken?: (message: string) => void,
): Unsubscribe {
  const source = new EventSource(url);
  for (const type of types) {
    source.addEventListener(type, (raw) => {
      let event: T;
      try {
        event = { ...(JSON.parse((raw as MessageEvent<string>).data) as object), type } as T;
      } catch {
        onBroken?.(`unreadable ${type} event`);
        return;
      }
      if (type === "done") source.close();
      onEvent(event);
    });
  }
  source.onerror = () => {
    // CONNECTING = the browser is retrying by itself; CLOSED = it gave up (e.g. 404 for an unknown job)
    if (source.readyState === EventSource.CLOSED) onBroken?.("event stream closed by the server");
  };
  return () => source.close();
}
