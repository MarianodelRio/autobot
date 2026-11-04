import { createFileRoute } from "@tanstack/react-router";
import type { LogsFilters } from "@/features/logs/logs-page";
import { LogsPage } from "@/features/logs/logs-page";

type LogsSearch = Partial<LogsFilters>;

export const Route = createFileRoute("/_app/logs")({
  component: LogsRoute,
  validateSearch: (search: Record<string, unknown>): LogsSearch => {
    const out: LogsSearch = {};
    if (typeof search.tenant === "string" && search.tenant)
      out.tenant = search.tenant;
    if (typeof search.level === "string" && search.level)
      out.level = search.level;
    if (typeof search.service === "string" && search.service)
      out.service = search.service;
    if (typeof search.q === "string" && search.q) out.q = search.q;
    if (typeof search.start === "string" && search.start)
      out.start = search.start;
    if (typeof search.end === "string" && search.end) out.end = search.end;
    return out;
  },
});

function LogsRoute() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <LogsPage
      filters={{
        tenant: search.tenant ?? "",
        level: search.level ?? "",
        service: search.service ?? "",
        q: search.q ?? "",
        start: search.start ?? "",
        end: search.end ?? "",
      }}
      onFilterChange={(next) =>
        void navigate({
          search: (prev) => ({ ...prev, ...next }),
          replace: true,
        })
      }
    />
  );
}
