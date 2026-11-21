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
import { qk } from "@/lib/queries";
import { tlsLevel } from "@/lib/status-levels";
import { ContainersCard } from "./containers-card";
import { FlowCard } from "./flow-card";
import { StatusCard } from "./status-card";

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

export function SystemPage() {
  const query = useQuery({
    queryKey: qk.system(),
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
  const level = tlsLevel(tlsDays);
  const tlsColor =
    level === "critical"
      ? "text-status-critical"
      : level === "warning"
        ? "text-status-warning"
        : level === "ok"
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
