import { createFileRoute } from "@tanstack/react-router";
import { type LogsSearch, LogsTabs } from "@/features/logs/logs-tabs";

type PartialLogsSearch = Partial<LogsSearch>;

export const Route = createFileRoute("/_app/logs")({
  component: LogsRoute,
  validateSearch: (search: Record<string, unknown>): PartialLogsSearch => {
    const out: PartialLogsSearch = {};
    if (
      search.tab === "technical" ||
      search.tab === "conversations" ||
      search.tab === "operator"
    )
      out.tab = search.tab;
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
    if (typeof search.kinds === "string" && search.kinds)
      out.kinds = search.kinds;
    if (typeof search.status === "string" && search.status)
      out.status = search.status;
    if (typeof search.action === "string" && search.action)
      out.action = search.action;
    return out;
  },
});

function LogsRoute() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <LogsTabs
      search={{
        tab: search.tab ?? "technical",
        tenant: search.tenant ?? "",
        level: search.level ?? "",
        service: search.service ?? "",
        q: search.q ?? "",
        start: search.start ?? "",
        end: search.end ?? "",
        kinds: search.kinds ?? "",
        status: search.status ?? "",
        action: search.action ?? "",
      }}
      onChange={(next) =>
        void navigate({
          search: (prev) => ({ ...prev, ...next }),
          replace: true,
        })
      }
      onTabChange={(tab) =>
        void navigate({
          search: (prev) => ({ tab, tenant: prev.tenant }),
          replace: true,
        })
      }
    />
  );
}
