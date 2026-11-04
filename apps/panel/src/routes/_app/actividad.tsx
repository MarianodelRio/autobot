import { createFileRoute } from "@tanstack/react-router";
import type { ActivityFilters } from "@/features/activity/activity-page";
import { ActivityPage } from "@/features/activity/activity-page";

type ActivitySearch = Partial<ActivityFilters>;

export const Route = createFileRoute("/_app/actividad")({
  component: ActivityRoute,
  validateSearch: (search: Record<string, unknown>): ActivitySearch => {
    const out: ActivitySearch = {};
    if (typeof search.tenant === "string" && search.tenant)
      out.tenant = search.tenant;
    if (typeof search.kinds === "string" && search.kinds)
      out.kinds = search.kinds;
    if (typeof search.status === "string" && search.status)
      out.status = search.status;
    return out;
  },
});

function ActivityRoute() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <ActivityPage
      filters={{
        tenant: search.tenant ?? "",
        kinds: search.kinds ?? "",
        status: search.status ?? "",
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
