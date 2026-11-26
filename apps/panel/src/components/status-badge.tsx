import { cn } from "@/lib/utils";

export type Status =
  | "ok"
  | "notice"
  | "warning"
  | "critical"
  | "unknown"
  | "info"
  | "active"
  | "paused"
  | "onboarding"
  | "offboarded";

const STATUS: Record<Status, { label: string; color: string }> = {
  ok: { label: "Ok", color: "bg-status-ok" },
  notice: { label: "Aviso", color: "bg-status-notice" },
  warning: { label: "Alerta", color: "bg-status-warning" },
  critical: { label: "Crítico", color: "bg-status-critical" },
  unknown: { label: "Desconocido", color: "bg-status-unknown" },
  info: { label: "Info", color: "bg-status-ok" },
  active: { label: "Activo", color: "bg-status-ok" },
  paused: { label: "Pausado", color: "bg-status-unknown" },
  onboarding: { label: "En alta", color: "bg-status-notice" },
  offboarded: { label: "De baja", color: "bg-status-unknown" },
};

export function StatusBadge({
  status,
  className,
}: {
  // A value outside `Status` (a new severity the API sends) reads «Desconocido».
  status: Status | (string & {});
  className?: string;
}) {
  const { label, color } = STATUS[status as Status] ?? STATUS.unknown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-foreground",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", color)} aria-hidden="true" />
      {label}
    </span>
  );
}
