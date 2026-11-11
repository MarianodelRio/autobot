import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { StatusDot, type StatusDotLevel } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
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
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";

// Set at image build time (apps/panel/Dockerfile ARG), from the checkout's own repo
// URL in CI. Empty for a local dev build: commit links are then plain text.
const GITHUB_REPO = import.meta.env.VITE_GITHUB_REPO ?? "";

function CommitLink({ sha }: { sha: string }) {
  if (!GITHUB_REPO) {
    return <span className="font-mono text-sm">{sha}</span>;
  }
  return (
    <a className="underline" href={`${GITHUB_REPO}/commit/${sha}`}>
      {sha}
    </a>
  );
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${formatNumber(value)} %`;
}

const SERVICE_LABEL: Record<string, string> = {
  worker: "worker",
  db: "db",
  victorialogs: "logs",
};

const FLOW_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  idle: "notice",
  critical: "critical",
};

const FLOW_LABEL: Record<string, string> = {
  ok: "Funcionando",
  idle: "Sin tráfico reciente",
  critical: "Con problemas",
};

const INTEGRATION_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  critical: "critical",
  off: "unknown",
  unknown: "unknown",
};

const CONTAINER_STATUS_LABEL: Record<string, string> = {
  running: "En marcha",
  restarting: "Reiniciándose",
  exited: "Parado",
  dead: "Muerto",
  created: "Creado",
  paused: "Pausado",
  removing: "Eliminándose",
  missing: "No existe",
};

const CONTAINER_HEALTH_LABEL: Record<string, string> = {
  healthy: "Bien",
  unhealthy: "Fallando",
  starting: "Arrancando",
  none: "—",
};

function FlowCard({ flow }: { flow: components["schemas"]["FlowOut"] }) {
  const lastAt =
    flow.last_inbound_at && flow.last_outbound_at
      ? flow.last_inbound_at > flow.last_outbound_at
        ? flow.last_inbound_at
        : flow.last_outbound_at
      : (flow.last_inbound_at ?? flow.last_outbound_at);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Flujo de mensajes</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <StatusDot
            level={FLOW_LEVEL[flow.state] ?? "unknown"}
            label={
              flow.state === "critical" && flow.reason
                ? flow.reason
                : FLOW_LABEL[flow.state]
            }
          />
          <p className="mt-1 text-sm text-muted-foreground">
            {lastAt ? (
              <>
                Último mensaje <TimeAgo date={lastAt} />
              </>
            ) : (
              "Sin mensajes todavía"
            )}
          </p>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.received_1h)}
            </p>
            <p className="text-sm text-muted-foreground">recibidos</p>
          </div>
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.answered_1h)}
            </p>
            <p className="text-sm text-muted-foreground">respondidos</p>
          </div>
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.failed_1h)}
            </p>
            <p className="text-sm text-muted-foreground">fallos</p>
          </div>
        </div>
        <p className="text-center text-xs text-muted-foreground">última hora</p>
      </CardContent>
    </Card>
  );
}

function StatusCard({
  services,
  integrations,
}: {
  services: Record<string, boolean>;
  integrations: components["schemas"]["IntegrationOut"][];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Estado</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Plataforma
          </p>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(services).map(([name, ok]) => (
              <StatusDot
                key={name}
                level={ok ? "ok" : "critical"}
                label={SERVICE_LABEL[name] ?? name}
              />
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Integraciones
          </p>
          <div className="space-y-1.5">
            {integrations.map((integration) => (
              <div
                key={integration.key}
                className="flex items-center justify-between text-sm"
              >
                <StatusDot
                  level={INTEGRATION_LEVEL[integration.state] ?? "unknown"}
                  label={integration.label}
                />
                <span className="text-muted-foreground">
                  {integration.state === "off" ? "apagada" : integration.detail}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ContainersCard({
  containers,
}: {
  containers: components["schemas"]["ContainersOut"];
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Contenedores</CardTitle>
        {containers.generated_at && (
          <span className="text-sm text-muted-foreground">
            Actualizado <TimeAgo date={containers.generated_at} />
          </span>
        )}
      </CardHeader>
      <CardContent>
        {!containers.available ? (
          <EmptyState message="Sin datos de contenedores. En producción, revisa autobot-containers.timer." />
        ) : (
          <>
            {containers.stale && (
              <p className="mb-3 text-sm text-status-warning">
                Datos desactualizados: el timer de contenedores puede estar
                parado.
              </p>
            )}
            {containers.maintenance === "deploy" && (
              <p className="mb-3 text-sm text-status-warning">
                Despliegue en curso.
              </p>
            )}
            {containers.maintenance === "restore" && (
              <p className="mb-3 text-sm text-status-warning">
                Restauración a medias.
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Servicio</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Salud</TableHead>
                  <TableHead>Reinicios</TableHead>
                  <TableHead>En marcha desde</TableHead>
                  <TableHead>Imagen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {containers.items.map((item) => (
                  <TableRow key={item.name ?? item.service}>
                    <TableCell>{item.service}</TableCell>
                    <TableCell>
                      <StatusDot
                        level={item.level as StatusDotLevel}
                        label={
                          item.reason ??
                          CONTAINER_STATUS_LABEL[item.status] ??
                          item.status
                        }
                      />
                    </TableCell>
                    <TableCell>
                      {CONTAINER_HEALTH_LABEL[item.health] ?? item.health}
                    </TableCell>
                    <TableCell>{formatNumber(item.restart_count)}</TableCell>
                    <TableCell>
                      {item.status === "running" && item.started_at ? (
                        <TimeAgo date={item.started_at} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell
                      className={
                        item.image_matches === false
                          ? "font-mono text-status-warning"
                          : "font-mono"
                      }
                    >
                      {item.image_tag ? item.image_tag.slice(0, 12) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function SystemPage() {
  const query = useQuery({
    queryKey: ["system"],
    queryFn: () => unwrap(api.GET("/system")),
    refetchInterval: 30_000,
  });
  return (
    <div className="space-y-6">
      <PageHeader title="Sistema" />
      {query.isPending ? (
        <p>Cargando sistema…</p>
      ) : query.isError ? (
        <ErrorState
          message={errorMessage(query.error, "No se pudo cargar el sistema.")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <SystemContent data={query.data} />
      )}
    </div>
  );
}

function SystemContent({ data }: { data: components["schemas"]["SystemOut"] }) {
  const backupCritical = data.backup.ok === false || data.backup.stale;
  const tlsDays = data.tls.days_left;
  const tlsLevel =
    tlsDays === null || tlsDays === undefined
      ? "unknown"
      : tlsDays < 7
        ? "critical"
        : tlsDays < 20
          ? "warning"
          : "ok";
  const tlsColor =
    tlsLevel === "critical"
      ? "text-status-critical"
      : tlsLevel === "warning"
        ? "text-status-warning"
        : tlsLevel === "ok"
          ? "text-status-ok"
          : "text-muted-foreground";
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <FlowCard flow={data.flow} />
        <StatusCard services={data.services} integrations={data.integrations} />
      </div>

      <ContainersCard containers={data.containers} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard title="CPU" value={percent(data.machine.cpu_pct)} />
        <KpiCard title="RAM" value={percent(data.machine.mem_used_pct)} />
        <KpiCard title="Disco" value={percent(data.machine.disk_used_pct)} />
        <KpiCard
          title="Carga"
          value={data.machine.load1 === null ? "—" : String(data.machine.load1)}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>CPU, RAM, disco y carga (mes en curso)</CardTitle>
        </CardHeader>
        <CardContent>
          {data.samples.length === 0 ? (
            <EmptyState message="Sin muestras este mes." />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.samples}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="taken_at"
                    tickFormatter={(value: string) => formatDateTime(value)}
                  />
                  <YAxis allowDecimals={false} />
                  <Tooltip
                    labelFormatter={(value) => formatDateTime(String(value))}
                  />
                  <Legend />
                  <Line
                    dataKey="cpu_pct"
                    name="CPU %"
                    stroke="var(--chart-1)"
                    dot={false}
                  />
                  <Line
                    dataKey="mem_used_pct"
                    name="RAM %"
                    stroke="var(--chart-2)"
                    dot={false}
                  />
                  <Line
                    dataKey="disk_used_pct"
                    name="Disco %"
                    stroke="var(--chart-3)"
                    dot={false}
                  />
                  <Line
                    dataKey="load1"
                    name="Carga"
                    stroke="var(--chart-4)"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Base de datos</CardTitle>
          </CardHeader>
          <CardContent>
            {data.database.ok ? (
              <>
                <p>{formatBytes(Number(data.database.bytes))}</p>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                  {(
                    data.database.tables as { name: string; bytes: number }[]
                  ).map((table) => (
                    <li key={table.name}>
                      {table.name}: {formatBytes(table.bytes)}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <ErrorState message="Base de datos no disponible." />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Colas</CardTitle>
          </CardHeader>
          <CardContent>
            {data.queues.length === 0 ? (
              <EmptyState message="Sin trabajos pendientes." />
            ) : (
              <ul className="space-y-1 text-sm">
                {(
                  data.queues as {
                    queue_name: string;
                    pending: number;
                    oldest: string | null;
                  }[]
                ).map((queue) => (
                  <li key={queue.queue_name}>
                    {queue.queue_name}: {formatNumber(queue.pending)} pendientes
                    {queue.oldest && (
                      <>
                        {" "}
                        (desde <TimeAgo date={queue.oldest} />)
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className={backupCritical ? "border-status-critical" : undefined}>
          <CardHeader>
            <CardTitle>Backup</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={
                backupCritical ? "text-status-critical" : "text-status-ok"
              }
            >
              {backupCritical ? "🔴" : "🟢"}{" "}
              {data.backup.finished_at ? (
                <>
                  Último: <TimeAgo date={String(data.backup.finished_at)} />
                </>
              ) : (
                "Sin backup registrado"
              )}
            </p>
            {data.backup.dump_bytes != null && (
              <p className="text-sm text-muted-foreground">
                {formatBytes(Number(data.backup.dump_bytes))}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>TLS</CardTitle>
          </CardHeader>
          <CardContent>
            <p className={tlsColor}>
              {tlsDays === null || tlsDays === undefined
                ? "Sin comprobar"
                : `${formatNumber(tlsDays)} días hasta caducar`}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Versión y despliegues</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 font-mono text-sm">
            <CommitLink sha={data.release} />
          </p>
          {data.deploys.length === 0 ? (
            <EmptyState message="Sin despliegues registrados." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>SHA</TableHead>
                  <TableHead>Resultado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(
                  data.deploys as {
                    at: string;
                    sha: string;
                    result: string;
                  }[]
                ).map((deploy) => (
                  <TableRow key={`${deploy.sha}-${deploy.at}`}>
                    <TableCell>
                      <TimeAgo date={deploy.at} />
                    </TableCell>
                    <TableCell className="font-mono">
                      <CommitLink sha={deploy.sha} />
                    </TableCell>
                    <TableCell>{deploy.result}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
