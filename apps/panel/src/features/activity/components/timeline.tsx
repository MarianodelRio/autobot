import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  Bell,
  ChevronDown,
  ChevronRight,
  MessageSquareText,
  Reply,
} from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TimeAgo } from "@/components/time-ago";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const KIND_ICON: Record<string, typeof MessageSquareText> = {
  inbound: MessageSquareText,
  outbound: Reply,
  notification: Bell,
};

const KIND_LABEL: Record<string, string> = {
  inbound: "Mensaje recibido",
  outbound: "Respuesta",
  notification: "Aviso al dueño",
};

function ActivityDetailBody({ kind, id }: { kind: string; id: string }) {
  const query = useQuery({
    queryKey: ["activity-detail", kind, id],
    queryFn: () =>
      unwrap(
        api.GET("/activity/{kind}/{id}", {
          params: { path: { kind, id } },
        }),
      ),
    staleTime: Infinity,
    gcTime: 0,
  });
  if (query.isPending) return <p className="text-sm">Cargando…</p>;
  if (query.isError || !query.data)
    return (
      <ErrorState
        message="No se pudo cargar el detalle."
        onRetry={() => void query.refetch()}
      />
    );
  const detail = query.data;
  return (
    <div className="space-y-2 text-sm">
      <p>{detail.text}</p>
      {detail.facts.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {detail.facts.map((fact) => (
            <Badge key={fact} variant="outline">
              {fact}
            </Badge>
          ))}
        </div>
      )}
      {detail.contact && (
        <p className="text-muted-foreground">Contacto: {detail.contact}</p>
      )}
      {detail.contact_link && (
        <a className="underline" href={detail.contact_link}>
          Ver cliente
        </a>
      )}
    </div>
  );
}

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
    // Only the first page refreshes, so "Cargar más" keeps its place.
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
          const Icon = KIND_ICON[item.kind] ?? MessageSquareText;
          return (
            <li key={key} className="border-b pb-2">
              <button
                type="button"
                className="flex w-full flex-wrap items-center gap-2 text-left"
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
                <Icon className="size-4 shrink-0" aria-hidden="true" />
                <strong>{KIND_LABEL[item.kind] ?? item.label}</strong>
                {item.tenant && (
                  <span className="text-sm text-muted-foreground">
                    {item.tenant}
                  </span>
                )}
                {item.channel && (
                  <Badge variant="outline">{item.channel}</Badge>
                )}
                {item.status && (
                  <Badge variant="secondary">{item.status}</Badge>
                )}
                <span className="text-sm text-muted-foreground">
                  · <TimeAgo date={item.at} />
                </span>
              </button>
              {open && (
                <div className="mt-2 ml-6">
                  <ActivityDetailBody kind={item.kind} id={item.id} />
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
