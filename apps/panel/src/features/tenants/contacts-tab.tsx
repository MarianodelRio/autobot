import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { RefreshWarning } from "@/components/refresh-warning";
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
import { downloadJson } from "@/lib/download";
import { errorMessage } from "@/lib/errors";
import { LIVE_FIRST_PAGE, qk } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";

export function ContactsTab({ slug }: { slug: string }) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);
  const exportContact = useApiMutation({
    fn: (id: string) =>
      unwrap(api.GET("/contacts/{id}/export", { params: { path: { id } } })),
    onSuccess: (result, id) => downloadJson(`contacto-${id}.json`, result),
    error: "No se pudo exportar.",
  });
  const forgetContact = useApiMutation({
    fn: (id: string) =>
      unwrap(api.POST("/contacts/{id}/forget", { params: { path: { id } } })),
    success: "Contacto olvidado.",
    error: "No se pudo olvidar el contacto.",
    tenant: slug,
    appliesConfig: false,
    onSuccess: () => {
      setForgetOpen(false);
      setSelected(null);
    },
  });
  const list = useInfiniteQuery({
    queryKey: qk.contactsSearch(slug, search),
    ...LIVE_FIRST_PAGE,
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
    queryKey: qk.contact(selected),
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
      ) : list.isError && !list.data ? (
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
        <>
          {list.isError && (
            <RefreshWarning onRetry={() => void list.refetch()} />
          )}
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
        </>
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
        <p role="alert" className="text-sm text-destructive">
          No se pudieron cargar más contactos.
        </p>
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
                  <div className="flex items-center justify-between gap-2">
                    <h3>
                      {detail.data.contact.display_name ||
                        detail.data.contact.external_id}
                    </h3>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={exportContact.isPending}
                        onClick={() =>
                          selected && exportContact.mutate(selected)
                        }
                      >
                        Exportar datos
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setForgetOpen(true)}
                      >
                        Olvidar contacto
                      </Button>
                    </div>
                  </div>
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
      <ConfirmDialog
        open={forgetOpen}
        onOpenChange={setForgetOpen}
        title="Olvidar contacto"
        description="Borra el contacto, sus conversaciones, mensajes y eventos de entrada. No se puede deshacer."
        confirmLabel="Olvidar"
        confirmText="olvidar"
        onConfirm={() => selected && forgetContact.mutate(selected)}
      />
    </div>
  );
}
