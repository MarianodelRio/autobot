import { useInfiniteQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";

export function Timeline({ tenant }: { tenant: string }) {
  const query = useInfiniteQuery({
    queryKey: ["activity", tenant],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/activity", {
          params: { query: { tenant, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
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
      <ul className="space-y-4">
        {items.map((item) => (
          <li key={`${item.kind}-${item.id}`} className="border-b pb-3">
            <p>
              {item.icon} <strong>{item.title}</strong> ·{" "}
              <TimeAgo date={item.at} />
            </p>
            <p className="text-sm text-muted-foreground">
              {item.detail} {item.status && `· ${item.status}`}
            </p>
          </li>
        ))}
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
