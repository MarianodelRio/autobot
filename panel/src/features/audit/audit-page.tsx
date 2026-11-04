import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/errors";

export interface AuditFilters {
  tenant: string;
  action: string;
}

export function AuditPage({
  filters,
  onFilterChange,
}: {
  filters: AuditFilters;
  onFilterChange: (next: Partial<AuditFilters>) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: () => unwrap(api.GET("/tenants")),
  });
  const query = useInfiniteQuery({
    queryKey: ["audit", filters.tenant, filters.action],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/audit", {
          params: {
            query: {
              tenant: filters.tenant,
              action: filters.action,
              cursor: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div>
      <PageHeader title="Auditoría" />
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          className="rounded-md border bg-background px-3 py-2 text-sm"
          aria-label="Cliente"
          value={filters.tenant}
          onChange={(event) => onFilterChange({ tenant: event.target.value })}
        >
          <option value="">Todos los clientes</option>
          {(tenants.data ?? []).map((row) => (
            <option key={row.slug} value={row.slug}>
              {row.name}
            </option>
          ))}
        </select>
        <Input
          className="max-w-xs"
          aria-label="Acción"
          placeholder="Acción (p. ej. alert.resolve)"
          value={filters.action}
          onChange={(event) => onFilterChange({ action: event.target.value })}
        />
      </div>
      {query.isPending ? (
        <p>Cargando auditoría…</p>
      ) : query.isError && !query.data ? (
        <ErrorState
          message={errorMessage(query.error, "No se pudo cargar la auditoría.")}
          onRetry={() => void query.refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState message="No hay eventos de auditoría." />
      ) : (
        <div>
          <ul className="divide-y">
            {items.map((event) => {
              const open = expanded.has(event.id);
              return (
                <li key={event.id} className="py-2">
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-center gap-2 text-left text-sm"
                    aria-expanded={open}
                    onClick={() =>
                      setExpanded((current) => {
                        const next = new Set(current);
                        if (next.has(event.id)) next.delete(event.id);
                        else next.add(event.id);
                        return next;
                      })
                    }
                  >
                    <TimeAgo date={event.at} />
                    <strong>{event.action}</strong>
                    <span>{event.actor}</span>
                    {event.tenant && (
                      <span className="text-muted-foreground">
                        {event.tenant}
                      </span>
                    )}
                    <span>{event.summary}</span>
                  </button>
                  {open && (
                    <pre className="mt-2 overflow-auto rounded-md border p-2 text-xs">
                      {JSON.stringify(event.details, null, 2)}
                    </pre>
                  )}
                </li>
              );
            })}
          </ul>
          {query.isFetchNextPageError && (
            <p>No se pudo cargar más auditoría.</p>
          )}
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
      )}
    </div>
  );
}
