import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TimeAgo } from "@/components/time-ago";
import { Card, CardContent } from "@/components/ui/card";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";

export function NotificationsTab({ slug }: { slug: string }) {
  const q = useQuery({
    queryKey: qk.notifications(slug),
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/notifications", {
          params: { path: { slug } },
        }),
      ),
  });
  if (q.isPending) return <p>Cargando avisos…</p>;
  if (q.isError)
    return (
      <ErrorState
        message={errorMessage(q.error, "No se pudieron cargar los avisos.")}
        onRetry={() => void q.refetch()}
      />
    );
  return q.data.length ? (
    <Card>
      <CardContent className="divide-y p-0">
        {q.data.map((n, index) => (
          <div
            className="px-6 py-3"
            // biome-ignore lint/suspicious/noArrayIndexKey: two notices can share a timestamp and kind
            key={`${index}-${n.created_at}-${n.kind}`}
          >
            <p>{n.text}</p>
            <p className="text-sm text-muted-foreground">
              {n.status} · <TimeAgo date={n.created_at} />
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  ) : (
    <EmptyState message="No hay avisos." />
  );
}
