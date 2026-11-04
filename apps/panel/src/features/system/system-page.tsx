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

const GITHUB_REPO = "https://github.com/MarianodelRio/autobot";

function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${formatNumber(value)} %`;
}

function ServiceBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? "text-status-ok" : "text-status-critical"}>
      {ok ? "🟢" : "🔴"} {label}
    </span>
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

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Servicios</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {Object.entries(data.services).map(([name, ok]) => (
              <div key={name}>
                <ServiceBadge ok={Boolean(ok)} label={name} />
              </div>
            ))}
          </CardContent>
        </Card>
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
            <a
              className="underline"
              href={`${GITHUB_REPO}/commit/${data.release}`}
            >
              {data.release}
            </a>
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
                      <a
                        className="underline"
                        href={`${GITHUB_REPO}/commit/${deploy.sha}`}
                      >
                        {deploy.sha}
                      </a>
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
