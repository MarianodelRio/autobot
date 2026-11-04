import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { type Status, StatusBadge } from "@/components/status-badge";
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
import { formatEur, formatNumber } from "@/lib/format";
import { useOverview } from "./use-overview";

type Overview = components["schemas"]["Overview"];
const colors = {
  ok: "border-status-ok",
  warning: "border-status-warning",
  critical: "border-status-critical",
};
const titles = {
  ok: "Todo bien",
  warning: "Atención",
  critical: "Estado crítico",
};

const knownStatuses = new Set<string>([
  "ok",
  "notice",
  "warning",
  "critical",
  "unknown",
  "active",
  "paused",
  "onboarding",
  "offboarded",
]);
function statusLabel(value: string) {
  return knownStatuses.has(value) ? (
    <StatusBadge status={value as Status} />
  ) : (
    value
  );
}

export function OverviewContent({ data }: { data: Overview }) {
  const { status, tenants, month, system } = data;
  const percent = (value: number | null) =>
    value === null ? "—" : `${formatNumber(value)} %`;
  return (
    <div className="space-y-6">
      <PageHeader title="Resumen" />
      <div
        role="status"
        className={`rounded-lg border-l-4 bg-card p-4 ${colors[status.level]}`}
      >
        <strong>{titles[status.level]}</strong> · {formatNumber(tenants.active)}{" "}
        clientes activos · actualizado <TimeAgo date={data.generated_at} />
        {status.problems.length > 0 && (
          <ul className="mt-2 space-y-1">
            {status.problems.map((problem) => (
              <li key={`${problem.text}-${problem.link}`}>
                {problem.link ? (
                  <a className="underline" href={problem.link}>
                    {problem.text}
                  </a>
                ) : (
                  problem.text
                )}
              </li>
            ))}
          </ul>
        )}
        {status.level !== "ok" && (
          <a className="underline" href="/incidencias">
            Ver incidencias
          </a>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          title="Clientes"
          value={`${formatNumber(tenants.active)} activos`}
          subtitle={`${formatNumber(tenants.demos)} demos · ${formatNumber(tenants.paused)} pausados · ${formatNumber(tenants.onboarding)} en alta`}
        />
        <KpiCard
          title="Mensajes (mes)"
          value={`${formatNumber(month.inbound)} entrada`}
          subtitle={`${formatNumber(month.outbound)} salida`}
        />
        <KpiCard title="Usuarios (mes)" value={formatNumber(month.users)} />
        <KpiCard
          title="Coste WhatsApp (mes)"
          value={formatEur(Number(month.cost_eur))}
          subtitle={`${formatNumber(month.billable)} facturables`}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Mensajes por día</CardTitle>
          </CardHeader>
          <CardContent>
            {month.by_day.length === 0 ? (
              <EmptyState message="Sin mensajes este mes." />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={month.by_day}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(value: string) => value.slice(8)}
                    />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar
                      dataKey="inbound"
                      name="Entrada"
                      fill="var(--chart-1)"
                    />
                    <Bar
                      dataKey="outbound"
                      name="Salida"
                      fill="var(--chart-2)"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Métricas de packs</CardTitle>
          </CardHeader>
          <CardContent>
            {month.metrics.length === 0 ? (
              <EmptyState message="Sin métricas este mes." />
            ) : (
              <ul className="space-y-2">
                {month.metrics.map((metric) => (
                  <li key={`${metric.pack}-${metric.kind}`}>
                    {metric.pack} · {metric.label}:{" "}
                    <strong>{formatNumber(Number(metric.total))}</strong>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Clientes</CardTitle>
        </CardHeader>
        <CardContent>
          {data.tenant_rows.length === 0 ? (
            <EmptyState message="No hay clientes." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  {[
                    "Negocio",
                    "Pack",
                    "Canal",
                    "Estado",
                    "Salud",
                    "Mensajes mes",
                    "Coste",
                    "Última actividad",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.tenant_rows.map((row) => (
                  <TableRow key={row.slug}>
                    <TableCell>
                      <a
                        className="underline"
                        href={`/clientes/${encodeURIComponent(row.slug)}`}
                      >
                        {row.name}
                      </a>
                    </TableCell>
                    <TableCell>{row.pack}</TableCell>
                    <TableCell>{row.channel}</TableCell>
                    <TableCell>{statusLabel(row.status)}</TableCell>
                    <TableCell title={row.health_reasons.join(" · ")}>
                      {statusLabel(row.health)}
                    </TableCell>
                    <TableCell>
                      {formatNumber(row.inbound_month)} /{" "}
                      {formatNumber(row.outbound_month)}
                    </TableCell>
                    <TableCell>
                      {formatEur(Number(row.cost_eur_month))}
                    </TableCell>
                    <TableCell>
                      {row.last_activity_at ? (
                        <TimeAgo date={row.last_activity_at} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Sistema</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p>
              CPU: {percent(system.cpu_pct)} · RAM:{" "}
              {percent(system.mem_used_pct)} · Disco:{" "}
              {percent(system.disk_used_pct)}
            </p>
            <p>
              Backup:{" "}
              {system.backup_ok === null
                ? "Desconocido"
                : system.backup_ok
                  ? "Correcto"
                  : "Fallido"}
              {system.last_backup_at && (
                <>
                  {" "}
                  · <TimeAgo date={system.last_backup_at} />
                </>
              )}
            </p>
            <p>
              TLS:{" "}
              {system.tls_days_left === null
                ? "Desconocido"
                : `${formatNumber(system.tls_days_left)} días`}
            </p>
            <p>
              Versión: {system.release || "Desconocida"}
              {system.deployed_at && (
                <>
                  {" "}
                  · <TimeAgo date={system.deployed_at} />
                </>
              )}
            </p>
            <a className="underline" href="/sistema">
              Ver sistema
            </a>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Últimas alertas</CardTitle>
          </CardHeader>
          <CardContent>
            {data.recent_alerts.length === 0 ? (
              <EmptyState message="No hay alertas." />
            ) : (
              <ul className="space-y-3">
                {data.recent_alerts.map((alert) => (
                  <li key={alert.id}>
                    <p>{alert.text}</p>
                    <p className="text-sm text-muted-foreground">
                      {alert.severity} ·{" "}
                      {alert.resolved ? "Resuelta" : "Abierta"}
                      {alert.tenant && ` · ${alert.tenant}`} ·{" "}
                      <TimeAgo date={alert.occurred_at} />
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function OverviewPage() {
  const query = useOverview();
  if (query.isPending) return <p>Cargando resumen…</p>;
  if (query.isError || !query.data)
    return (
      <ErrorState
        message="No se pudo cargar el resumen."
        onRetry={() => void query.refetch()}
      />
    );
  return <OverviewContent data={query.data} />;
}
