import { createFileRoute } from "@tanstack/react-router";
import type { AuditFilters } from "@/features/audit/audit-page";
import { AuditPage } from "@/features/audit/audit-page";

type AuditSearch = Partial<AuditFilters>;

export const Route = createFileRoute("/_app/auditoria")({
  component: AuditRoute,
  validateSearch: (search: Record<string, unknown>): AuditSearch => {
    const out: AuditSearch = {};
    if (typeof search.tenant === "string" && search.tenant)
      out.tenant = search.tenant;
    if (typeof search.action === "string" && search.action)
      out.action = search.action;
    return out;
  },
});

function AuditRoute() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <AuditPage
      filters={{ tenant: search.tenant ?? "", action: search.action ?? "" }}
      onFilterChange={(next) =>
        void navigate({
          search: (prev) => ({ ...prev, ...next }),
          replace: true,
        })
      }
    />
  );
}
