import { cn } from "@/lib/utils";

export const STATUS_DOT_LEVELS = [
  "ok",
  "notice",
  "warning",
  "critical",
  "unknown",
] as const;
export type StatusDotLevel = (typeof STATUS_DOT_LEVELS)[number];

/** A level the backend sent as a free string: anything unexpected reads as unknown. */
export function toStatusDotLevel(value: string): StatusDotLevel {
  return (STATUS_DOT_LEVELS as readonly string[]).includes(value)
    ? (value as StatusDotLevel)
    : "unknown";
}

export const STATUS_DOT_COLOR: Record<StatusDotLevel, string> = {
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
        className={cn("size-1.5 rounded-full", STATUS_DOT_COLOR[level])}
        aria-hidden="true"
      />
      {label && <span className="text-sm">{label}</span>}
    </span>
  );
}
