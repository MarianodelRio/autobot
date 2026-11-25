import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

type ConfigState = components["schemas"]["ConfigStateOut"];

/** Id of the one toast of this flow: a new save replaces the previous one. */
const TOAST_ID = "config-applied";
export const POLL_MS = 500;
export const POLL_ATTEMPTS = 20; // ~10 s

let current = 0;

/** How many alive processes have loaded `target` (or later) and which services
 * still have one behind. */
export function summarize(state: ConfigState, target: number) {
  const processes = Array.isArray(state?.processes) ? state.processes : [];
  const behind = processes.filter((p) => p.revision < target);
  return {
    total: processes.length,
    applied: processes.length - behind.length,
    behind: [...new Set(behind.map((p) => p.service))].sort(),
  };
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/** After a successful configuration write: shows «Aplicando el cambio…» until every
 * alive backend process has loaded the revision the write left in the database, then
 * «Aplicado en N procesos», or a warning naming the services still behind after
 * ~10 s. Purely informative (the write is already committed): any failure to read
 * the state just removes the toast. A newer call supersedes an older one. */
export async function confirmApplied(): Promise<void> {
  const run = ++current;
  const superseded = () => run !== current;
  try {
    let state = await unwrap(api.GET("/system/config"));
    if (superseded()) return;
    const target = state.revision;
    for (let attempt = 0; ; attempt++) {
      const { total, applied, behind } = summarize(state, target);
      if (total === 0) {
        toast.dismiss(TOAST_ID);
        return;
      }
      if (behind.length === 0) {
        toast.success(
          `Aplicado en ${total} ${total === 1 ? "proceso" : "procesos"}`,
          { id: TOAST_ID, duration: 4000 },
        );
        return;
      }
      if (attempt >= POLL_ATTEMPTS) {
        toast.warning(
          `Aplicado en ${applied} de ${total}; siguen con la versión anterior: ${behind.join(", ")}`,
          { id: TOAST_ID, duration: 15000 },
        );
        return;
      }
      toast.loading("Aplicando el cambio…", { id: TOAST_ID });
      await sleep(POLL_MS);
      if (superseded()) return;
      state = await unwrap(api.GET("/system/config"));
      if (superseded()) return;
    }
  } catch {
    if (!superseded()) toast.dismiss(TOAST_ID);
  }
}
