import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TimeAgo } from "@/components/time-ago";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function Timeline({
  tenant = "",
  kinds = "",
  status = "",
}: {
  tenant?: string;
  kinds?: string;
  status?: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const query = useInfiniteQuery({
    queryKey: ["activity", tenant, kinds, status],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/activity", {
          params: { query: { tenant, kinds, status, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    // DESIGN §9.7: only the first page refreshes, so "Cargar más" keeps its place.
    refetchInterval: (q) =>
      (q.state.data?.pages.length ?? 0) <= 1 ? 15_000 : false,
  });
  if (query.isPending) return <p>Cargando actividad…</p>;
  if (query.isError && !query.data)
    return (
      <ErrorState
        message="No se pudo cargar la actividad."
        onRetry={() => void query.refetch()}
      />
    );
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  if (!items.length) return <EmptyState message="No hay actividad." />;
  return (
    <div>
      <ul className="space-y-2">
        {items.map((item) => {
          const key = `${item.kind}-${item.id}`;
          const open = expanded.has(key);
          return (
            <li key={key} className="border-b pb-2">
              <button
                type="button"
                className="flex w-full items-center gap-2 text-left"
                aria-expanded={open}
                onClick={() =>
                  setExpanded((current) => {
                    const next = new Set(current);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
              >
                {open ? (
                  <ChevronDown className="size-4 shrink-0" aria-hidden="true" />
                ) : (
                  <ChevronRight
                    className="size-4 shrink-0"
                    aria-hidden="true"
                  />
                )}
                <span>{item.icon}</span>
                <strong>{item.title}</strong>
                <span className="text-sm text-muted-foreground">
                  · <TimeAgo date={item.at} />
                </span>
              </button>
              {open && (
                <div className="mt-2 ml-6 space-y-2 text-sm">
                  <p>{item.detail}</p>
                  <div className="flex flex-wrap gap-2">
                    {item.tenant && (
                      <Badge variant="outline">{item.tenant}</Badge>
                    )}
                    {item.channel && (
                      <Badge variant="outline">{item.channel}</Badge>
                    )}
                    {item.status && (
                      <Badge variant="secondary">{item.status}</Badge>
                    )}
                  </div>
                  {item.link && (
                    <a className="underline" href={item.link}>
                      Ver cliente
                    </a>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {query.isFetchNextPageError && <p>No se pudo cargar más actividad.</p>}
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
