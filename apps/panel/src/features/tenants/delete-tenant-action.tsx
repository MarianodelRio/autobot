import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { downloadJson } from "@/lib/download";
import { errorMessage } from "@/lib/errors";
import { removeTenantQueries, tenantRemoved } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";

type Detail = components["schemas"]["TenantDetail"];

export function DeleteTenantAction({ detail }: { detail: Detail }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const navigate = useNavigate();
  const client = useQueryClient();
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/delete", {
          params: { path: { slug: detail.slug } },
          body: { confirm_slug: detail.slug },
        }),
      ),
    success: "Cliente eliminado.",
    // Not `tenant`: the tenant is gone, so its queries are dropped instead of
    // refetched (they would 404), and there is no configuration to confirm: the
    // delete purges the tenant's rows instead of publishing a revision to wait for.
    invalidate: tenantRemoved(),
    onSuccess: (result) => {
      if (result.telegram_webhook_removed === false) {
        toast.warning(
          "No se pudo retirar el webhook de Telegram. Retíralo manualmente si procede.",
        );
      }
      void navigate({ to: "/clientes" });
      removeTenantQueries(client, detail.slug);
    },
  });
  function close() {
    setOpen(false);
    setTyped("");
    mutation.reset();
  }
  const exportData = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/export", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: (result) => {
      downloadJson(`${detail.slug}-datos.json`, result);
    },
    error: "No se pudo exportar.",
  });
  if (detail.document.demo) return null;
  const active = detail.status === "active";
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="icon" aria-label="Más acciones">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={active}
            onSelect={(event) => {
              event.preventDefault();
              setOpen(true);
            }}
          >
            Eliminar cliente
          </DropdownMenuItem>
          {active && (
            <p className="px-2 py-1 text-xs text-muted-foreground">
              Páusalo antes de eliminarlo.
            </p>
          )}
          <DropdownMenuItem
            disabled={exportData.isPending}
            onSelect={(event) => {
              event.preventDefault();
              exportData.mutate();
            }}
          >
            Exportar datos del negocio
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (next) setOpen(true);
          else close();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminar cliente</DialogTitle>
          </DialogHeader>
          <div className="space-y-2 text-sm">
            <p>
              Se borra todo lo que el sistema guarda de{" "}
              <strong>{detail.name}</strong>: contactos, conversaciones,
              mensajes, avisos, métricas, sesiones y eventos de demo, el enlace
              del dueño, secretos, versiones de configuración y datasets, y su
              fila de cliente. El slug queda libre.
            </p>
            <p className="text-muted-foreground">
              Quedan fuera: una entrada de auditoría sin datos del cliente, los
              logs técnicos (caducan en 31 días) y las copias de seguridad
              (según su retención). La app en Meta, el bot de Telegram y el
              calendario de Google son del negocio: esto no los toca.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="delete-tenant-confirm">
              Escribe <span className="font-mono">{detail.slug}</span> para
              confirmar
            </Label>
            <Input
              id="delete-tenant-confirm"
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(mutation.error, "No se pudo eliminar el cliente.")}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={close}>
              Cancelar
            </Button>
            <Button
              disabled={typed !== detail.slug || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              Eliminar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
