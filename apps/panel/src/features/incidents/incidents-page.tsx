// Minimal screen over the ADR-031 incidents API; the full redesign comes later.
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RefreshWarning } from "@/components/refresh-warning";
import { StatusBadge } from "@/components/status-badge";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";
import { IncidentRow } from "./incident-row";

type Incident = components["schemas"]["IncidentOut"];
type SendCase = components["schemas"]["SendCase"];
type JobCase = components["schemas"]["JobCase"];
type Case = Incident["cases"][number];

const DELIVERY_LABEL: Record<string, string> = {
  sent: "Avisada",
  failed: "Aviso fallido",
  unconfigured: "Sin bot configurado",
  panel: "Solo en el panel",
  throttled: "Ya avisada hace menos de una hora",
  cooldown: "En espera",
  "": "Sin avisar",
};

const CLOSED_LABEL: Record<string, string> = {
  auto: "Sola",
  outage: "Por una caída",
  review: "Revisada",
  info: "Informativa",
};

function logsWindow(at: string): { start: string; end: string } {
  const center = new Date(at).getTime();
  return {
    start: new Date(center - 15 * 60_000).toISOString(),
    end: new Date(center + 5 * 60_000).toISOString(),
  };
}

const incidentsChanged = () => [
  qk.incidents(),
  qk.alerts(),
  qk.overview(),
  qk.activityAll(),
];

function ReviewAction({ incident }: { incident: Incident }) {
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/incidents/{id}/review", {
          params: { path: { id: incident.id } },
        }),
      ),
    success: "Incidencia revisada.",
    invalidate: incidentsChanged(),
  });
  if (!incident.reviewable) return null;
  return (
    <Button
      size="sm"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      Lo he revisado
    </Button>
  );
}

function SendActions({ message }: { message: SendCase }) {
  const [open, setOpen] = useState(false);
  const markSent = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/mark-sent", {
          params: { path: { id: message.id } },
        }),
      ),
    success: "Envío marcado como enviado.",
    invalidate: incidentsChanged(),
  });
  const discard = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/discard", {
          params: { path: { id: message.id } },
        }),
      ),
    success: "Envío descartado.",
    invalidate: incidentsChanged(),
  });
  const resend = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/resend", {
          params: { path: { id: message.id } },
          body: { confirm_duplicate_risk: true },
        }),
      ),
    success: "Mensaje reenviado.",
    invalidate: incidentsChanged(),
    onSuccess: () => setOpen(false),
  });
  return (
    <>
      {message.can_mark_sent && (
        <Button
          size="sm"
          variant="outline"
          disabled={markSent.isPending}
          onClick={() => markSent.mutate()}
        >
          Marcar enviado
        </Button>
      )}
      {message.can_resend && (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
          Reenviar
        </Button>
      )}
      {message.can_discard && (
        <Button
          size="sm"
          variant="outline"
          disabled={discard.isPending}
          onClick={() => discard.mutate()}
        >
          Descartar
        </Button>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Reenviar mensaje"
        description="Puede que el destinatario ya lo haya recibido: reenviar puede crear un duplicado. ¿Confirmas el reenvío?"
        confirmLabel="Reenviar"
        onConfirm={() => resend.mutate()}
      />
      {resend.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(resend.error, "No se pudo reenviar el mensaje.")}
        </p>
      )}
    </>
  );
}

function RetryAction({ job }: { job: JobCase }) {
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/jobs/{id}/retry", { params: { path: { id: job.id } } }),
      ),
    success: "Trabajo reencolado.",
    invalidate: incidentsChanged(),
  });
  if (!job.can_retry) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      Reintentar
    </Button>
  );
}

function CaseLine({ item }: { item: Case }) {
  if (item.type === "send") {
    return (
      <li className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {item.channel} · {item.status} · <TimeAgo date={item.created_at} />
          {item.error_title ? ` · ${item.error_title}` : ""}
        </span>
        <SendActions message={item} />
      </li>
    );
  }
  if (item.type === "job") {
    return (
      <li className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {item.task_label} · trabajo {item.id}
          {item.failed_at ? (
            <>
              {" "}
              · <TimeAgo date={item.failed_at} />
            </>
          ) : null}
          {item.retry_reason ? ` · ${item.retry_reason}` : ""}
        </span>
        <RetryAction job={item} />
      </li>
    );
  }
  return (
    <li className="text-sm">
      Aviso {item.status} · <TimeAgo date={item.created_at} />
    </li>
  );
}

function OpenIncident({ incident }: { incident: Incident }) {
  const count =
    incident.new_since_review != null
      ? `${incident.new_since_review} nuevos desde tu revisión`
      : `${incident.case_count} casos`;
  return (
    <div>
      <IncidentRow
        severity={incident.severity}
        runbook={incident.runbook}
        text={
          incident.tenant
            ? `${incident.tenant}: ${incident.title}`
            : incident.title
        }
        meta={
          <>
            {incident.advice} · <TimeAgo date={incident.last_seen_at} /> ·{" "}
            {count} · {DELIVERY_LABEL[incident.delivery] ?? incident.delivery}
          </>
        }
        logsLink={{
          tenant: incident.tenant ?? undefined,
          ...logsWindow(incident.last_seen_at),
        }}
        actions={<ReviewAction incident={incident} />}
      />
      {incident.cases.length > 0 && (
        <ul className="space-y-1 pb-3 pl-4">
          {incident.cases.map((item) => (
            <CaseLine key={`${item.type}-${item.id}`} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ClosedHistory() {
  const query = useInfiniteQuery({
    queryKey: qk.alertsResolved(),
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
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            {["Severidad", "Incidencia", "Cliente", "Cerrada", "Cómo"].map(
              (label) => (
                <TableHead key={label}>{label}</TableHead>
              ),
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <StatusBadge status={row.severity} />
              </TableCell>
              <TableCell>{row.title}</TableCell>
              <TableCell>{row.tenant ?? "—"}</TableCell>
              <TableCell>
                <TimeAgo date={row.resolved_at} />
              </TableCell>
              <TableCell>
                {CLOSED_LABEL[row.closed] ?? row.closed}
                {row.closed_by ? ` (${row.closed_by})` : ""}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
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

export function IncidentsPage() {
  const [historyOpen, setHistoryOpen] = useState(false);
  const query = useQuery({
    queryKey: qk.incidents(),
    queryFn: () => unwrap(api.GET("/incidents")),
    refetchInterval: 30_000,
  });
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidencias"
        help="incidencias/"
        actions={
          query.data && (
            <span className="text-sm text-muted-foreground">
              {query.data.total} abiertas
            </span>
          )
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
          <CardContent className="py-6 text-center text-muted-foreground">
            Todo en orden.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {query.isError && (
            <RefreshWarning onRetry={() => void query.refetch()} />
          )}
          {query.data.items.map((incident) => (
            <OpenIncident key={incident.id} incident={incident} />
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
          Incidencias cerradas
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
