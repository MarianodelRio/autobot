import { cn } from "@/lib/utils";

function colorFor(value: number): string {
  if (value > 85) return "bg-status-critical";
  if (value > 70) return "bg-status-warning";
  return "bg-status-ok";
}

export function Meter({
  label,
  value,
  className,
}: {
  label: string;
  value: number | null;
  className?: string;
}) {
  const percent = value === null ? 0 : Math.min(100, Math.max(0, value));
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="w-12 shrink-0 text-sm text-muted-foreground">
        {label}
      </span>
      {/* biome-ignore lint/a11y/useSemanticElements: native <meter> can't be styled as a thin threshold bar */}
      <div
        role="meter"
        aria-label={label}
        aria-valuenow={value ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1 flex-1 rounded-full bg-muted"
      >
        {value !== null && (
          <div
            className={cn("h-1 rounded-full", colorFor(value))}
            style={{ width: `${percent}%` }}
          />
        )}
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-sm tabular-nums">
        {value === null ? "—" : `${Math.round(value)} %`}
      </span>
    </div>
  );
}
