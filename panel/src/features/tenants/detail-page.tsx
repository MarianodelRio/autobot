import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
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
import { formatEur, formatNumber } from "@/lib/format";
import { errorMessage } from "./error-message";

type Detail = components["schemas"]["TenantDetail"];
const param = (slug: string) => ({ params: { path: { slug } } });

function Summary({ detail }: { detail: Detail }) {
  const [load, setLoad] = useState(false);
  const summary = useQuery({
    queryKey: ["tenant-summary", detail.slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/summary", param(detail.slug))),
    enabled: load,
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
      <section>
        <h2 className="font-semibold">Salud: {detail.health}</h2>
        {detail.health_reasons.map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
        {detail.health_checked_at && (
          <p>
            Comprobada <TimeAgo date={detail.health_checked_at} />
          </p>
        )}
      </section>
      <section>
        <h2 className="font-semibold">Resumen del dueño</h2>
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
            <div>
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
      </section>
      <section>
        <h2 className="font-semibold">Alertas abiertas</h2>
        {detail.open_alerts.length ? (
          detail.open_alerts.map((alert) => <p key={alert.id}>{alert.text}</p>)
        ) : (
          <EmptyState message="No hay alertas abiertas." />
        )}
      </section>
    </div>
  );
}
function Channel({ detail }: { detail: Detail }) {
  const secrets = useQuery({
    queryKey: ["tenant-secrets", detail.slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/secrets", param(detail.slug))),
    enabled: detail.channel_type !== null,
  });
  return (
    <div className="space-y-4">
      <p>Canal: {detail.channel_type ?? "Demo"}</p>
      <p>Webhook: {detail.webhook_url ?? "—"}</p>
      {detail.public_link && (
        <div>
          <a className="underline" href={detail.public_link}>
            {detail.public_link}
          </a>
          <div className="mt-4 w-fit bg-white p-4">
            <QRCodeSVG
              value={detail.public_link}
              title="QR del canal público"
            />
          </div>
        </div>
      )}
      <p>Dueño enlazado: {detail.owner_linked ? "Sí" : "No"}</p>
      <p>
        Canal: <code>{JSON.stringify(detail.document.channel ?? null)}</code>
      </p>
      <p>
        Testers: <code>{JSON.stringify(detail.document.testers ?? null)}</code>
      </p>
      <p>
        Dueño: <code>{JSON.stringify(detail.document.owner ?? null)}</code>
      </p>
      {detail.channel_type &&
        (secrets.isPending ? (
          <p>Cargando estado de secretos…</p>
        ) : secrets.isError ? (
          <ErrorState
            message={errorMessage(
              secrets.error,
              "No se pudo cargar el estado de secretos.",
            )}
            onRetry={() => void secrets.refetch()}
          />
        ) : (
          <div>
            <h2 className="font-semibold">Secretos</h2>
            {!secrets.data.readable && (
              <p>No se pueden leer los secretos configurados.</p>
            )}
            {secrets.data.fields.map((field) => (
              <p key={field.name}>
                {field.name}: {field.set ? "Configurado" : "No configurado"}
              </p>
            ))}
            <p>
              Actualizado:{" "}
              {secrets.data.updated_at ? (
                <TimeAgo date={secrets.data.updated_at} />
              ) : (
                "Nunca"
              )}
              {secrets.data.updated_by && ` · ${secrets.data.updated_by}`}
            </p>
            <Button disabled>Sustituir secretos</Button>
          </div>
        ))}
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
    <ul>
      {q.data.map((n) => (
        <li className="border-b py-3" key={`${n.created_at}-${n.kind}`}>
          <p>{n.text}</p>
          <p>
            {n.status} · <TimeAgo date={n.created_at} />
          </p>
        </li>
      ))}
    </ul>
  ) : (
    <EmptyState message="No hay avisos." />
  );
}
function Datasets({ slug }: { slug: string }) {
  const q = useQuery({
    queryKey: ["datasets", slug],
    queryFn: () => unwrap(api.GET("/tenants/{slug}/datasets", param(slug))),
  });
  if (q.isPending) return <p>Cargando datos…</p>;
  if (q.isError)
    return (
      <ErrorState
        message={errorMessage(q.error, "No se pudieron cargar los datos.")}
        onRetry={() => void q.refetch()}
      />
    );
  return q.data.length ? (
    <ul>
      {q.data.map((d) => (
        <li className="border-b py-3" key={d.name}>
          {d.name} · v{d.version} · {d.author} · <TimeAgo date={d.created_at} />{" "}
          · {d.comment}
          <p className="font-mono text-xs">{d.sha256}</p>
        </li>
      ))}
    </ul>
  ) : (
    <EmptyState message="No hay datasets." />
  );
}
export function TenantDetailPage({ slug }: { slug: string }) {
  const client = useQueryClient();
  const q = useQuery({
    queryKey: ["tenant", slug],
    queryFn: () => unwrap(api.GET("/tenants/{slug}", param(slug))),
  });
  const health = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/tenants/{slug}/health-check", param(slug))),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["overview"] });
    },
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
  const action =
    d.status === "active"
      ? "Pausar"
      : d.status === "paused"
        ? "Reactivar"
        : d.status === "onboarding"
          ? "Activar"
          : null;
  return (
    <div>
      <PageHeader
        title={d.name}
        description={`${d.slug} · ${d.pack} · ${d.status} · salud: ${d.health}`}
        actions={
          <div className="flex gap-2">
            {action && <Button disabled>{action}</Button>}
            <Button
              variant="outline"
              disabled={health.isPending}
              onClick={() => health.mutate()}
            >
              Comprobar salud
            </Button>
          </div>
        }
      />
      {health.isError && <p role="alert">No se pudo comprobar la salud.</p>}
      {health.data && (
        <div role="status">
          {health.data.length
            ? health.data.map((issue) => (
                <p key={issue.code}>{issue.message}</p>
              ))
            : "Comprobación completada sin problemas."}
        </div>
      )}
      <Tabs defaultValue="resumen">
        <TabsList className="max-w-full overflow-x-auto">
          {[
            "Resumen",
            "Canal",
            "Actividad",
            "Contactos",
            "Avisos",
            "Datos",
          ].map((tab) => (
            <TabsTrigger key={tab} value={tab.toLowerCase()}>
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="resumen">
          <Summary detail={d} />
        </TabsContent>
        <TabsContent value="canal">
          <Channel detail={d} />
        </TabsContent>
        <TabsContent value="actividad">
          <Timeline tenant={slug} />
        </TabsContent>
        <TabsContent value="contactos">
          <Contacts slug={slug} />
        </TabsContent>
        <TabsContent value="avisos">
          <Notifications slug={slug} />
        </TabsContent>
        <TabsContent value="datos">
          <Datasets slug={slug} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
