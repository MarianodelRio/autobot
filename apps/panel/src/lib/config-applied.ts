import type { QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { invalidateTenantEverything } from "@/lib/queries";

type ConfigState = components["schemas"]["ConfigStateOut"];
type ConfigProcess = ConfigState["processes"][number];

/** Id of the one toast of this flow: a new save replaces the previous one. */
const TOAST_ID = "config-applied";
export const POLL_MS = 500;
/** Overall bound of the wait. */
export const MAX_WAIT_MS = 30_000;
/** Give up early when the number of processes up to date has not grown for this
 * long: the wait lasts while processes are progressing, not while they are stuck. */
export const STALL_MS = 10_000;

let current = 0;

/** A process is behind when the API says so; if it does not, when its revision
 * differs from the target (ahead counts too: a restore to an older version). */
const isBehind = (p: ConfigProcess, target: number) =>
  typeof p.behind === "boolean" ? p.behind : p.revision !== target;

/** How many alive processes run the revision `target` and which services still
 * have one that does not (naming those that also report an error). */
export function summarize(state: ConfigState, target: number) {
  const processes: ConfigProcess[] = Array.isArray(state?.processes)
    ? state.processes
    : [];
  const behind = processes.filter((p) => isBehind(p, target));
  const failing = new Set(
    behind.filter((p) => p.last_error_at).map((p) => p.service),
  );
  return {
    total: processes.length,
    applied: processes.length - behind.length,
    behind: [...new Set(behind.map((p) => p.service))].sort(),
    failing: [...failing].sort(),
  };
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/** After a successful configuration write: shows «Aplicando el cambio…» while the
 * alive backend processes load the revision the write left in the database (up to
 * 30 s, giving up earlier if none makes progress for 10 s), then «Aplicado en N
 * procesos» or a warning naming the services still behind. On either outcome the
 * tenant's queries are refreshed once more. Purely informative (the write is
 * already committed): any failure to read the state just removes the toast. A newer
 * call supersedes an older one. */
export async function confirmApplied(
  client: QueryClient,
  slug: string,
): Promise<void> {
  const run = ++current;
  const superseded = () => run !== current;
  const started = Date.now();
  try {
    let state = await unwrap(api.GET("/system/config"));
    if (superseded()) return;
    const target = state.revision;
    let best = -1;
    let lastProgress = started;
    for (;;) {
      const { total, applied, behind, failing } = summarize(state, target);
      if (total === 0) {
        toast.dismiss(TOAST_ID);
        return;
      }
      if (behind.length === 0) {
        toast.success(
          `Aplicado en ${total} ${total === 1 ? "proceso" : "procesos"}`,
          { id: TOAST_ID, duration: 4000 },
        );
        invalidateTenantEverything(client, slug);
        return;
      }
      const now = Date.now();
      if (applied > best) {
        best = applied;
        lastProgress = now;
      }
      if (now - started >= MAX_WAIT_MS || now - lastProgress >= STALL_MS) {
        const named = behind
          .map((service) =>
            failing.includes(service) ? `${service} (con error)` : service,
          )
          .join(", ");
        toast.warning(
          `Aplicado en ${applied} de ${total}; siguen con la versión anterior: ${named}`,
          { id: TOAST_ID, duration: 15000 },
        );
        invalidateTenantEverything(client, slug);
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
