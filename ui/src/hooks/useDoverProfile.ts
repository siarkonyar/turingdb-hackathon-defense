import { useOps } from "../state/store";

/** Keep the focused demo layout stable while its graph metadata is loading. */
export function useDoverProfile(): boolean {
  return useOps((s) => s.meta
    ? s.meta.graph === "dover"
    : import.meta.env.VITE_OPSMAP_PROFILE === "dover");
}
