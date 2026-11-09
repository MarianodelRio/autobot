import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { type Status, StatusBadge } from "@/components/status-badge";
import { StatusDot, type StatusDotLevel } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Timeline } from "@/features/activity/components/timeline";
import { errorMessage } from "@/lib/errors";
import { formatEur, formatNumber } from "@/lib/format";
import { ConfigEditor } from "./config/editor";
import { StatusAction } from "./config/status-action";
import { DeleteTenantAction } from "./delete-tenant-action";

type Detail = components["schemas"]["TenantDetail"];
const param = (slug: string) => ({ params: { path: { slug } } });

const HEALTH_LEVEL: Record<string, StatusDotLevel> = {
  ok: "ok",
  notice: "notice",
  warning: "warning",
  critical: "critical",
  unknown: "unknown",
};

function Summary({ detail }: { detail: Detail }) {
  const [load, setLoad] = useState(false);
  const client = useQueryClient();
  const summary = useQuery({
    queryKey: ["tenant-summary", detail.slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/summary", param(detail.slug))),
    enabled: load,
  });
  const health = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/tenants/{slug}/health-check", param(detail.slug))),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tenant", detail.slug] });
      void client.invalidateQueries({ queryKey: ["overview"] });
    },
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
            <StatusDot level={HEALTH_LEVEL[detail.health] ?? "unknown"} />
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
          {health.isError && <p role="alert">No se pudo comprobar la salud.</p>}
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
function Contacts({ slug }: { slug: string }) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const list = useInfiniteQuery({
    queryKey: ["contacts", slug, search],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/tenants/{slug}/contacts", {
          params: { path: { slug }, query: { search, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const detail = useQuery({
    queryKey: ["contact", selected],
    queryFn: () =>
      unwrap(
        api.GET("/contacts/{id}", { params: { path: { id: selected ?? "" } } }),
      ),
    enabled: selected !== null,
    gcTime: 0,
    staleTime: 0,
  });
  return (
    <div className="space-y-4">
      <Input
        aria-label="Buscar contactos"
        placeholder="Buscar contactos"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {list.isPending ? (
        <p>Cargando contactos…</p>
      ) : list.isError ? (
        <ErrorState
          message={errorMessage(
            list.error,
            "No se pudieron cargar los contactos.",
          )}
          onRetry={() => void list.refetch()}
        />
      ) : list.data.pages.every((page) => page.items.length === 0) ? (
        <EmptyState message="No hay contactos." />
      ) : (
        <ul>
          {list.data.pages
            .flatMap((page) => page.items)
            .map((contact) => (
              <li key={contact.id} className="border-b py-3">
                <button
                  className="underline"
                  type="button"
                  onClick={() => setSelected(contact.id)}
                >
                  {contact.display_name || contact.external_id}
                </button>{" "}
                · {contact.phone_e164 ?? contact.external_id}
              </li>
            ))}
        </ul>
      )}
      {list.hasNextPage && (
        <Button
          variant="outline"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
        >
          Cargar más
        </Button>
      )}
      {list.isFetchNextPageError && (
        <p role="alert">No se pudieron cargar más contactos.</p>
      )}
      <Sheet
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Conversación</SheetTitle>
            <SheetDescription>Últimos 50 intercambios</SheetDescription>
          </SheetHeader>
          <div className="space-y-4 px-4">
            {detail.isPending ? (
              <p>Cargando conversación…</p>
            ) : detail.isError ? (
              <ErrorState
                message={errorMessage(
                  detail.error,
                  "No se pudo cargar la conversación.",
                )}
                onRetry={() => void detail.refetch()}
              />
            ) : (
              detail.data && (
                <>
                  <h3>
                    {detail.data.contact.display_name ||
                      detail.data.contact.external_id}
                  </h3>
                  {detail.data.exchanges.length === 0 ? (
                    <EmptyState message="No hay intercambios." />
                  ) : (
                    detail.data.exchanges.map((exchange) => (
                      <div key={exchange.outbound_id} className="border-b pb-3">
                        <p>Entrada: {exchange.inbound ?? "—"}</p>
                        <p>
                          Salida: {exchange.outbound} · {exchange.status}
                        </p>
                        <TimeAgo date={exchange.outbound_at} />
                      </div>
                    ))
                  )}
                  <h3 className="font-semibold">Estado</h3>
                  <pre className="overflow-auto">
                    {JSON.stringify(detail.data.state, null, 2)}
                  </pre>
                </>
              )
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
function Notifications({ slug }: { slug: string }) {
  const q = useQuery({
    queryKey: ["notifications", slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/notifications", param(slug))),
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
        {q.data.map((n) => (
          <div className="px-6 py-3" key={`${n.created_at}-${n.kind}`}>
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
export function TenantDetailPage({
  slug,
  dirty = false,
  onDirtyChange = () => {},
  initialTab = "resumen",
  initialSection,
}: {
  slug: string;
  dirty?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  initialTab?: string;
  initialSection?: "canal";
}) {
  const [tab, setTab] = useState(initialTab);
  const q = useQuery({
    queryKey: ["tenant", slug],
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
            <StatusAction slug={slug} status={d.status} />
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
          <Contacts slug={slug} />
        </TabsContent>
        <TabsContent value="avisos">
          <Notifications slug={slug} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
