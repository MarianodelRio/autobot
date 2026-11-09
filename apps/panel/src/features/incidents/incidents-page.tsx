import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { type Status, StatusBadge } from "@/components/status-badge";
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
import { IncidentRow } from "./incident-row";

type Alert = components["schemas"]["AlertOut"];
type Outbound = components["schemas"]["OutboundIncidentOut"];
type Job = components["schemas"]["JobOut"];

const DELIVERY_LABEL: Record<string, string> = {
  sent: "Entregada",
  failed: "Fallida",
  cooldown: "En espera (cooldown)",
  unconfigured: "Sin bot configurado",
  "": "Sin intentos",
};

function logsWindow(at: string): { start: string; end: string } {
  const center = new Date(at).getTime();
  return {
    start: new Date(center - 15 * 60_000).toISOString(),
    end: new Date(center + 5 * 60_000).toISOString(),
  };
}

function invalidateIncidents(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: ["incidents"] });
  void client.invalidateQueries({ queryKey: ["alerts"] });
  void client.invalidateQueries({ queryKey: ["overview"] });
  void client.invalidateQueries({ queryKey: ["activity"] });
}

function GroupHeading({ children }: { children: string }) {
  return (
    <p className="px-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
      {children}
    </p>
  );
}

function EmptyGroup({ message }: { message: string }) {
  return (
    <p className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
      <span aria-hidden="true">✓</span> {message}
    </p>
  );
}

function ResolveAction({ alert }: { alert: Alert }) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/alerts/{id}/resolve", {
          params: { path: { id: alert.id } },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      toast.success("Alerta resuelta.");
      invalidateIncidents(client);
    },
  });
  if (alert.auto_resolves) return null;
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Resolver
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Resolver alerta"
        description={`¿Confirmas que "${alert.text}" está resuelta?`}
        confirmLabel="Resolver"
        onConfirm={() => mutation.mutate()}
      />
      {mutation.isError && (
        <p role="alert">
          {errorMessage(mutation.error, "No se pudo resolver la alerta.")}
        </p>
      )}
    </>
  );
}

function OpenAlerts({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return <EmptyGroup message="No hay alertas abiertas." />;
  return (
    <div>
      {alerts.map((alert) => (
        <IncidentRow
          key={alert.id}
          severity={alert.severity as Status}
          text={alert.text}
          meta={
            <>
              {alert.tenant ?? "—"} · <TimeAgo date={alert.last_seen_at} /> ·{" "}
              {alert.occurrences} veces ·{" "}
              {DELIVERY_LABEL[alert.last_delivery] ?? alert.last_delivery}
            </>
          }
          logsLink={{
            tenant: alert.tenant ?? undefined,
            ...logsWindow(alert.last_seen_at),
          }}
          actions={<ResolveAction alert={alert} />}
        />
      ))}
    </div>
  );
}

function MarkSentAction({ message }: { message: Outbound }) {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/outbound/{id}/mark-sent", {
          params: { path: { id: message.id } },
        }),
      ),
    onSuccess: () => {
      toast.success("Envío marcado como enviado.");
      invalidateIncidents(client);
    },
  });
  if (!message.can_mark_sent) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      Marcar enviado
    </Button>
  );
}

function ResendAction({ message }: { message: Outbound }) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/outbound/{id}/resend", {
          params: { path: { id: message.id } },
          body: { confirm_duplicate_risk: true },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      toast.success("Mensaje reenviado.");
      invalidateIncidents(client);
    },
  });
  if (!message.can_resend) return null;
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Reenviar
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Reenviar mensaje"
        description="Puede que el destinatario ya lo haya recibido: reenviar puede crear un duplicado. ¿Confirmas el reenvío?"
        confirmLabel="Reenviar"
        onConfirm={() => mutation.mutate()}
      />
      {mutation.isError && (
        <p role="alert">
          {errorMessage(mutation.error, "No se pudo reenviar el mensaje.")}
        </p>
      )}
    </>
  );
}

function PendingSends({ sends }: { sends: Outbound[] }) {
  if (!sends.length) return <EmptyGroup message="No hay envíos pendientes." />;
  return (
    <div>
      {sends.map((message) => (
        <IncidentRow
          key={message.id}
          severity="critical"
          text={`Sin confirmar · ${message.channel} · ${message.tenant}`}
          meta={
            <>
              <TimeAgo date={message.created_at} /> ·{" "}
              {message.mark_sent_reason ||
                message.resend_reason ||
                message.last_error ||
                "—"}
            </>
          }
          logsLink={{
            tenant: message.tenant,
            ...logsWindow(message.created_at),
          }}
          actions={
            <>
              <MarkSentAction message={message} />
              <ResendAction message={message} />
            </>
          }
        />
      ))}
    </div>
  );
}

function RetryAction({ job }: { job: Job }) {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/jobs/{id}/retry", { params: { path: { id: job.id } } }),
      ),
    onSuccess: () => {
      toast.success("Trabajo reencolado.");
      invalidateIncidents(client);
    },
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

function FailedJobs({ jobs }: { jobs: Job[] }) {
  if (!jobs.length) return <EmptyGroup message="Sin trabajos fallidos." />;
  return (
    <div>
      {jobs.map((job) => (
        <IncidentRow
          key={job.id}
          severity="critical"
          text={`Trabajo ${job.task_name} falló`}
          meta={`Intento ${job.attempts} · ${job.retry_reason || "—"}`}
          logsLink={
            job.at
              ? {
                  tenant:
                    typeof job.ids.tenant_id === "string"
                      ? job.ids.tenant_id
                      : undefined,
                  ...logsWindow(job.at),
                }
              : undefined
          }
          actions={<RetryAction job={job} />}
        />
      ))}
    </div>
  );
}

function ResolvedHistory() {
  const query = useInfiniteQuery({
    queryKey: ["alerts", "resolved"],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/alerts", {
          params: { query: { state: "resolved", cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  if (query.isPending) return <p>Cargando historial…</p>;
  if (query.isError && !query.data)
    return (
      <ErrorState
        message="No se pudo cargar el historial de alertas."
        onRetry={() => void query.refetch()}
      />
    );
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  if (!items.length) return <EmptyState message="No hay alertas resueltas." />;
  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            {["Severidad", "Texto", "Cliente", "Resuelta", "Por"].map(
              (label) => (
                <TableHead key={label}>{label}</TableHead>
              ),
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((alert) => (
            <TableRow key={alert.id}>
              <TableCell>
                <StatusBadge status={alert.severity as Status} />
              </TableCell>
              <TableCell>{alert.text}</TableCell>
              <TableCell>{alert.tenant ?? "—"}</TableCell>
              <TableCell>
                {alert.resolved_at ? <TimeAgo date={alert.resolved_at} /> : "—"}
              </TableCell>
              <TableCell>{alert.resolved_by || "—"}</TableCell>
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
    queryKey: ["incidents"],
    queryFn: () => unwrap(api.GET("/incidents")),
    refetchInterval: 30_000,
  });
  const openCount = query.data
    ? query.data.alerts.length +
      query.data.outbound.length +
      query.data.jobs.length
    : 0;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidencias"
        actions={
          query.data && (
            <span className="text-sm text-muted-foreground">
              {openCount} abiertas
            </span>
          )
        }
      />
      {query.isPending ? (
        <p>Cargando incidencias…</p>
      ) : query.isError ? (
        <ErrorState
          message={errorMessage(
            query.error,
            "No se pudieron cargar las incidencias.",
          )}
          onRetry={() => void query.refetch()}
        />
      ) : openCount === 0 ? (
        <Card>
          <CardContent className="py-6 text-center text-muted-foreground">
            Todo en orden.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <OpenAlerts alerts={query.data.alerts} />
          <div>
            <GroupHeading>
              {query.data.outbound.length > 0
                ? `Envíos sin confirmar (${query.data.outbound.length})`
                : "Envíos sin confirmar"}
            </GroupHeading>
            <PendingSends sends={query.data.outbound} />
          </div>
          <div>
            <GroupHeading>Trabajos fallidos</GroupHeading>
            <FailedJobs jobs={query.data.jobs} />
          </div>
        </div>
      )}
      <details
        open={historyOpen}
        onToggle={(event) =>
          setHistoryOpen((event.target as HTMLDetailsElement).open)
        }
      >
        <summary className="cursor-pointer text-sm text-muted-foreground">
          Alertas resueltas
        </summary>
        {historyOpen && (
          <div className="mt-3">
            <ResolvedHistory />
          </div>
        )}
      </details>
    </div>
  );
}
