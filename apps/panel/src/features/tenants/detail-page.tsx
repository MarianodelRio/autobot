import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { type Status, StatusBadge } from "@/components/status-badge";
import { StatusDot } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Timeline } from "@/features/activity/components/timeline";
import { errorMessage } from "@/lib/errors";
import { formatEur, formatNumber } from "@/lib/format";
import { qk, tenantChanged } from "@/lib/queries";
import { HEALTH_LEVEL, levelOf } from "@/lib/status-levels";
import { useApiMutation } from "@/lib/use-api-mutation";
import { ConfigEditor } from "./config/editor";
import { SetupTab } from "./config/setup-tab";
import { StatusAction } from "./config/status-action";
import { ContactsTab } from "./contacts-tab";
import { DeleteTenantAction } from "./delete-tenant-action";
import { NotificationsTab } from "./notifications-tab";

type Detail = components["schemas"]["TenantDetail"];
const param = (slug: string) => ({ params: { path: { slug } } });

function Summary({ detail }: { detail: Detail }) {
  const [load, setLoad] = useState(false);
  const summary = useQuery({
    queryKey: qk.tenantSummary(detail.slug),
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/summary", param(detail.slug))),
    enabled: load,
  });
  const health = useApiMutation({
    fn: () =>
      unwrap(api.POST("/tenants/{slug}/health-check", param(detail.slug))),
    invalidate: tenantChanged(detail.slug),
  });
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard
          title="Entrada (mes)"
          value={formatNumber(detail.month.inbound)}
        />
        <KpiCard
          title="Salida (mes)"
          value={formatNumber(detail.month.outbound)}
        />
        <KpiCard
          title="Usuarios (mes)"
          value={formatNumber(detail.month.users)}
        />
        <KpiCard
          title="Coste (mes)"
          value={formatEur(Number(detail.month.cost_eur))}
        />
      </div>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Salud del canal</CardTitle>
          <CardAction>
            <Button
              size="sm"
              variant="outline"
              disabled={health.isPending}
              onClick={() => health.mutate()}
            >
              Comprobar ahora
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <StatusDot level={levelOf(HEALTH_LEVEL, detail.health)} />
            <span>
              {detail.health === "ok" ? "Correcta" : detail.health}
              {detail.health_checked_at && (
                <>
                  {" "}
                  · comprobada <TimeAgo date={detail.health_checked_at} />
                </>
              )}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            Comprueba Telegram o Meta y el calendario. Se hace sola cada 24 h.
          </p>
          {detail.health_reasons.length > 0 && (
            <ul className="space-y-1 text-sm">
              {detail.health_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {health.isError && (
            <p role="alert" className="text-sm text-destructive">
              No se pudo comprobar la salud.
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Resumen del dueño</CardTitle>
        </CardHeader>
        <CardContent>
          {!load && (
            <Button variant="outline" onClick={() => setLoad(true)}>
              Cargar
            </Button>
          )}
          {load &&
            (summary.isPending ? (
              <p>Cargando…</p>
            ) : summary.isError ? (
              <ErrorState
                message={errorMessage(
                  summary.error,
                  "No se pudo cargar el resumen.",
                )}
                onRetry={() => void summary.refetch()}
              />
            ) : (
              <div className="space-y-1">
                {summary.data.pack_failed && (
                  <p>No se pudo cargar el resumen del pack.</p>
                )}
                {summary.data.pack_lines.map((line) => (
                  <p key={line.label}>
                    {line.icon} {line.label}:{" "}
                    {line.unit === "eur"
                      ? formatEur(Number(line.value))
                      : formatNumber(Number(line.value))}{" "}
                    {line.note}
                  </p>
                ))}
                <p>
                  Usuarios: {formatNumber(summary.data.users)} · Mensajes:{" "}
                  {formatNumber(summary.data.messages)} · Coste:{" "}
                  {formatEur(Number(summary.data.cost_eur))}
                </p>
              </div>
            ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Alertas abiertas</CardTitle>
        </CardHeader>
        <CardContent>
          {detail.open_alerts.length ? (
            <ul className="space-y-1">
              {detail.open_alerts.map((alert) => (
                <li key={alert.id}>{alert.text}</li>
              ))}
            </ul>
          ) : (
            <EmptyState message="No hay alertas abiertas." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
export function TenantDetailPage({
  slug,
  dirty = false,
  onDirtyChange = () => {},
  initialTab = "resumen",
  initialSection,
  onTabChange,
}: {
  slug: string;
  dirty?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  initialTab?: string;
  initialSection?: "canal";
  /** With it the active tab lives in the URL (the route); without it, in local state. */
  onTabChange?: (tab: string) => void;
}) {
  const [localTab, setLocalTab] = useState(initialTab);
  const tab = onTabChange ? initialTab : localTab;
  const setTab = onTabChange ?? setLocalTab;
  const q = useQuery({
    queryKey: qk.tenant(slug),
    queryFn: () => unwrap(api.GET("/tenants/{slug}", param(slug))),
  });
  if (q.isPending) return <p>Cargando cliente…</p>;
  if (q.isError)
    return (
      <ErrorState
        message={errorMessage(q.error, "No se pudo cargar el cliente.")}
        onRetry={() => void q.refetch()}
      />
    );
  const d = q.data;
  return (
    <div>
      <PageHeader
        title={d.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {d.slug} · {d.pack}
            </span>
            <StatusBadge status={d.status as Status} />
            <StatusBadge status={d.health as Status} />
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            {/* "Activar" moved into the Alta tab, the natural last step of
                onboarding; pause/resume stay here for an already-active tenant. */}
            {d.status !== "onboarding" && (
              <StatusAction slug={slug} status={d.status} />
            )}
            <DeleteTenantAction detail={d} />
          </div>
        }
      />
      <Tabs
        value={tab}
        onValueChange={(value) => {
          if (
            dirty &&
            value !== tab &&
            !window.confirm("Hay cambios sin guardar. ¿Quieres salir?")
          )
            return;
          onDirtyChange(false);
          setTab(value);
        }}
      >
        <TabsList className="max-w-full overflow-x-auto">
          {(
            [
              ["resumen", "Resumen"],
              ["alta", "Alta"],
              ["configuracion", "Configuración"],
              ["actividad", "Actividad"],
              ["contactos", "Contactos"],
              ["avisos", "Avisos"],
            ] as const
          ).map(([id, label]) => (
            <TabsTrigger key={id} value={id}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="resumen">
          <Summary detail={d} />
        </TabsContent>
        <TabsContent value="alta">
          <SetupTab slug={slug} detail={d} />
        </TabsContent>
        <TabsContent value="configuracion">
          <ConfigEditor
            detail={d}
            onDirtyChange={onDirtyChange}
            initialSection={initialSection === "canal" ? "channel" : undefined}
          />
        </TabsContent>
        <TabsContent value="actividad">
          <Timeline tenant={slug} kinds="inbound,outbound" />
        </TabsContent>
        <TabsContent value="contactos">
          <ContactsTab slug={slug} />
        </TabsContent>
        <TabsContent value="avisos">
          <NotificationsTab slug={slug} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
