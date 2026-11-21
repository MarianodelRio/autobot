import type { components } from "@/api/schema";
import { type StatusDotLevel, toStatusDotLevel } from "@/components/status-dot";

/** How each state the backend reports maps to a StatusDot level. Unknown states
 * (a newer backend) read as `unknown` through `levelOf`. */

export const HEALTH_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  notice: "notice",
  warning: "warning",
  critical: "critical",
  unknown: "unknown",
};

export const FLOW_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  idle: "notice",
  critical: "critical",
};

export const INTEGRATION_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  critical: "critical",
  off: "unknown",
  unknown: "unknown",
};

export const STEP_LEVEL: Record<
  components["schemas"]["SetupStepOut"]["state"],
  StatusDotLevel
> = {
  ok: "ok",
  pending: "notice",
  error: "critical",
  "n/a": "unknown",
};

export function levelOf(
  map: Record<string, StatusDotLevel>,
  state: string,
): StatusDotLevel {
  return map[state] ?? "unknown";
}

/** A level the API sends as a plain string (containers). */
export const containerLevel = toStatusDotLevel;

export function backupLevel(ok: boolean | null): StatusDotLevel {
  if (ok === null) return "unknown";
  return ok ? "ok" : "critical";
}

export function tlsLevel(daysLeft: number | null | undefined): StatusDotLevel {
  if (daysLeft === null || daysLeft === undefined) return "unknown";
  if (daysLeft < 7) return "critical";
  if (daysLeft < 20) return "warning";
  return "ok";
}
