import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { type Status, StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";

export function IncidentRow({
  severity,
  text,
  meta,
  actions,
  logsLink,
  runbook,
}: {
  severity: Status;
  text: string;
  meta: ReactNode;
  actions?: ReactNode;
  logsLink?: { tenant?: string; start: string; end: string };
  /** `/docs/...` page that explains what to do, from the API. */
  runbook?: string | null;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b py-3 last:border-b-0">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={severity} />
          <span>{text}</span>
        </div>
        <p className="text-sm text-muted-foreground">{meta}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {logsLink && (
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/logs"
              search={{
                tab: "technical",
                tenant: logsLink.tenant,
                start: logsLink.start,
                end: logsLink.end,
              }}
            >
              Ver logs
            </Link>
          </Button>
        )}
        {runbook && (
          <Button size="sm" variant="outline" asChild>
            <a href={runbook} target="_blank" rel="noopener">
              Ver runbook
            </a>
          </Button>
        )}
        {actions}
      </div>
    </div>
  );
}
