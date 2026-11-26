import type { components } from "@/api/schema";
import { qk } from "@/lib/queries";

export type Incident = components["schemas"]["IncidentOut"];
export type ClosedIncident = components["schemas"]["ClosedIncidentOut"];
export type Case = Incident["cases"][number];
export type SendCase = components["schemas"]["SendCase"];
export type JobCase = components["schemas"]["JobCase"];
export type NoticeCase = components["schemas"]["NoticeCase"];

/** What an action on an incident or one of its cases makes stale (besides the
 * tenant's own queries, see `useApiMutation`'s `tenant`). `incidents()` covers the
 * open list, the history and every case page; `overview()` feeds the sidebar. */
export const incidentsChanged = () => [
  qk.incidents(),
  qk.overview(),
  qk.activityAll(),
];

/** Logs of the 15 minutes before and the 5 after the incident was last seen. */
export function logsWindow(at: string): { start: string; end: string } {
  const center = new Date(at).getTime();
  return {
    start: new Date(center - 15 * 60_000).toISOString(),
    end: new Date(center + 5 * 60_000).toISOString(),
  };
}

/** How the operator was told, only when it says something. */
export const DELIVERY_HINT: Record<string, string> = {
  sent: "Aviso enviado",
  panel: "Solo en el panel",
  failed: "Aviso pendiente de reintento",
};

export const CLOSED_LABEL: Record<string, string> = {
  auto: "Se cerró sola",
  outage: "Se cerró por una caída",
  review: "Revisada",
  info: "Informativa",
};

export const NOTICE_STATUS_LABEL: Record<string, string> = {
  held: "Retenido: el dueño aún no tiene chat",
  expired: "Caducado sin entregar",
  pending: "Pendiente",
  failed: "No se pudo entregar",
};
