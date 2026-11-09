import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { errorMessage } from "@/lib/errors";

type Detail = components["schemas"]["TenantDetail"];

export function DeleteTenantAction({ detail }: { detail: Detail }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const client = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/delete", {
          params: { path: { slug: detail.slug } },
          body: { confirm_slug: detail.slug },
        }),
      ),
    onSuccess: (result) => {
      toast.success("Cliente eliminado.");
      if (result.telegram_webhook_removed === false) {
        toast.warning(
          "No se pudo retirar el webhook de Telegram. Retíralo manualmente si procede.",
        );
      }
      void client.invalidateQueries({ queryKey: ["tenants"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
      void client.invalidateQueries({ queryKey: ["incidents"] });
      void navigate({ to: "/clientes" });
    },
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
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setTyped("");
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
            <p role="alert">
              {errorMessage(mutation.error, "No se pudo eliminar el cliente.")}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
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
