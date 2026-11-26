import { useInfiniteQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { qk } from "@/lib/queries";
import { CLOSED_LABEL, type ClosedIncident } from "./shared";

function closedHow(row: ClosedIncident): string {
  if (row.closed === "review")
    return row.closed_by ? `Revisada por ${row.closed_by}` : "Revisada";
  return CLOSED_LABEL[row.closed] ?? row.closed;
}

export function ClosedHistory() {
  const query = useInfiniteQuery({
    queryKey: qk.incidentsHistory(),
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/incidents/history", {
          params: { query: { cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  if (query.isPending) return <p>Cargando historial…</p>;
  if (query.isError && !query.data)
    return (
      <ErrorState
        message="No se pudo cargar el historial de incidencias."
        onRetry={() => void query.refetch()}
      />
    );
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  if (!items.length)
    return <EmptyState message="No hay incidencias cerradas." />;
  return (
    <div className="space-y-2">
      <ul className="divide-y">
        {items.map((row) => (
          <li key={row.id} className="space-y-1 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={row.severity} />
              <span className="text-sm text-muted-foreground">
                {row.tenant ?? "Plataforma"}
              </span>
              <span>{row.title}</span>
            </div>
            <p className="text-sm text-muted-foreground">
              {closedHow(row)} · <TimeAgo date={row.resolved_at} />
              {row.case_count > 0 &&
                ` · ${row.case_count} ${row.case_count === 1 ? "caso" : "casos"}`}
            </p>
          </li>
        ))}
      </ul>
      {query.isFetchNextPageError && <p>No se pudo cargar más historial.</p>}
      {query.hasNextPage && (
        <Button
          variant="outline"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          Cargar más
        </Button>
      )}
    </div>
  );
}
