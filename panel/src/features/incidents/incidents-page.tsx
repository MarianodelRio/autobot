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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";

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

function invalidateIncidents(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: ["incidents"] });
  void client.invalidateQueries({ queryKey: ["alerts"] });
  void client.invalidateQueries({ queryKey: ["overview"] });
  void client.invalidateQueries({ queryKey: ["activity"] });
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
  if (!alerts.length) return <EmptyState message="No hay alertas abiertas." />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {[
            "Severidad",
            "Texto",
            "Cliente",
            "Primera vez",
            "Última vez",
            "Ocurrencias",
            "Última entrega",
            "",
          ].map((label) => (
            <TableHead key={label}>{label}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {alerts.map((alert) => (
          <TableRow key={alert.id}>
            <TableCell>
              <StatusBadge status={alert.severity as Status} />
            </TableCell>
            <TableCell>{alert.text}</TableCell>
            <TableCell>{alert.tenant ?? "—"}</TableCell>
            <TableCell>
              <TimeAgo date={alert.first_seen_at} />
            </TableCell>
            <TableCell>
              <TimeAgo date={alert.last_seen_at} />
            </TableCell>
            <TableCell>{alert.occurrences}</TableCell>
            <TableCell>
              {DELIVERY_LABEL[alert.last_delivery] ?? alert.last_delivery}
              {alert.last_sent_at && (
                <>
                  {" · "}
                  <TimeAgo date={alert.last_sent_at} />
                </>
              )}
            </TableCell>
            <TableCell>
              <ResolveAction alert={alert} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
  if (!sends.length) return <EmptyState message="No hay envíos pendientes." />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {["Cliente", "Canal", "Estado", "Creado", "Motivo", "Acciones"].map(
            (label) => (
              <TableHead key={label}>{label}</TableHead>
            ),
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {sends.map((message) => (
          <TableRow key={message.id}>
            <TableCell>{message.tenant}</TableCell>
            <TableCell>{message.channel}</TableCell>
            <TableCell>{message.status}</TableCell>
            <TableCell>
              <TimeAgo date={message.created_at} />
            </TableCell>
            <TableCell>
              {message.mark_sent_reason ||
                message.resend_reason ||
                message.last_error ||
                "—"}
            </TableCell>
            <TableCell className="flex gap-2">
              <MarkSentAction message={message} />
              <ResendAction message={message} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
  if (!jobs.length) return <EmptyState message="No hay trabajos fallidos." />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {["Tarea", "Cola", "Intentos", "Último evento", "Motivo", ""].map(
            (label) => (
              <TableHead key={label}>{label}</TableHead>
            ),
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id}>
            <TableCell>{job.task_name}</TableCell>
            <TableCell>{job.queue}</TableCell>
            <TableCell>{job.attempts}</TableCell>
            <TableCell>{job.at ? <TimeAgo date={job.at} /> : "—"}</TableCell>
            <TableCell>{job.retry_reason || "—"}</TableCell>
            <TableCell>
              <RetryAction job={job} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
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
  const query = useQuery({
    queryKey: ["incidents"],
    queryFn: () => unwrap(api.GET("/incidents")),
    refetchInterval: 30_000,
  });
  return (
    <div className="space-y-6">
      <PageHeader title="Incidencias" />
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
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Alertas abiertas</CardTitle>
            </CardHeader>
            <CardContent>
              <OpenAlerts alerts={query.data.alerts} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Envíos sin confirmar</CardTitle>
            </CardHeader>
            <CardContent>
              <PendingSends sends={query.data.outbound} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Trabajos fallidos</CardTitle>
            </CardHeader>
            <CardContent>
              <FailedJobs jobs={query.data.jobs} />
            </CardContent>
          </Card>
        </>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Historial de alertas resueltas</CardTitle>
        </CardHeader>
        <CardContent>
          <ResolvedHistory />
        </CardContent>
      </Card>
    </div>
  );
}
