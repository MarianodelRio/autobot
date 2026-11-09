import { cn } from "@/lib/utils";

export type StatusDotLevel =
  | "ok"
  | "notice"
  | "warning"
  | "critical"
  | "unknown";

const COLOR: Record<StatusDotLevel, string> = {
  ok: "bg-status-ok",
  notice: "bg-status-notice",
  warning: "bg-status-warning",
  critical: "bg-status-critical",
  unknown: "bg-status-unknown",
};

export function StatusDot({
  level,
  label,
  className,
}: {
  level: StatusDotLevel;
  label?: string;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn("size-1.5 rounded-full", COLOR[level])}
        aria-hidden="true"
      />
      {label && <span className="text-sm">{label}</span>}
    </span>
  );
}
