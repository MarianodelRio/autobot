import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RefreshWarning } from "@/components/refresh-warning";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { errorMessage } from "@/lib/errors";
import { LIVE, qk } from "@/lib/queries";
import { ClosedHistory } from "./history";
import { IncidentCard } from "./incident-card";

const SEVERITIES = ["critical", "warning", "notice"] as const;

export function IncidentsPage() {
  const [historyOpen, setHistoryOpen] = useState(false);
  const query = useQuery({
    queryKey: qk.incidents(),
    queryFn: () => unwrap(api.GET("/incidents")),
    ...LIVE,
  });
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidencias"
        help="incidencias/"
        actions={
          query.data && query.data.total > 0 ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              {SEVERITIES.filter((s) => query.data.by_severity[s] > 0).map(
                (s) => (
                  <span key={s} className="flex items-center gap-1.5">
                    <StatusBadge status={s} />
                    {query.data.by_severity[s]}
                  </span>
                ),
              )}
            </div>
          ) : undefined
        }
      />
      {query.isPending ? (
        <p>Cargando incidencias…</p>
      ) : query.isError && !query.data ? (
        <ErrorState
          message={errorMessage(
            query.error,
            "No se pudieron cargar las incidencias.",
          )}
          onRetry={() => void query.refetch()}
        />
      ) : query.data.total === 0 ? (
        <Card>
          <CardContent className="py-6 text-center">
            <p className="font-medium">Todo en orden</p>
            <p className="text-sm text-muted-foreground">
              No hay incidencias abiertas.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {query.isError && (
            <RefreshWarning onRetry={() => void query.refetch()} />
          )}
          {query.data.items.map((incident) => (
            <IncidentCard key={incident.id} incident={incident} />
          ))}
        </div>
      )}
      <details
        open={historyOpen}
        onToggle={(event) =>
          setHistoryOpen((event.target as HTMLDetailsElement).open)
        }
      >
        <summary className="cursor-pointer text-sm text-muted-foreground">
          Historial
        </summary>
        {historyOpen && (
          <div className="mt-3">
            <ClosedHistory />
          </div>
        )}
      </details>
    </div>
  );
}
