import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { QrCode } from "@/components/qr-code";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorMessage } from "@/lib/errors";

type Detail = components["schemas"]["TenantDetail"];
type Invite = components["schemas"]["OwnerInviteOut"];

export function OwnerSection({ detail }: { detail: Detail }) {
  const client = useQueryClient();
  const [link, setLink] = useState<Invite | null>(null);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const invite = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/owner-invite", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: (result) => {
      setLink(result);
      void client.invalidateQueries({ queryKey: ["tenant", detail.slug] });
    },
  });
  const unlink = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/owner-unlink", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: (result) => {
      toast.success(
        result.had_chat ? "Dueño desconectado." : "Invitación cancelada.",
      );
      setConfirmUnlink(false);
      void client.invalidateQueries({ queryKey: ["tenant", detail.slug] });
    },
  });
  const label = detail.owner_linked
    ? "Dueño enlazado"
    : detail.owner_invite_pending
      ? "Invitación pendiente"
      : "Dueño sin enlazar";
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between text-sm">
        <StatusDot
          level={
            detail.owner_linked
              ? "ok"
              : detail.owner_invite_pending
                ? "notice"
                : "unknown"
          }
          label={label}
        />
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={invite.isPending}
            onClick={() => invite.mutate()}
          >
            Invitar al dueño
          </Button>
          {(detail.owner_linked || detail.owner_invite_pending) && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setConfirmUnlink(true)}
            >
              Desconectar
            </Button>
          )}
        </div>
      </div>
      {invite.isError && (
        <p role="alert">
          {errorMessage(invite.error, "No se pudo generar el enlace.")}
        </p>
      )}
      {unlink.isError && (
        <p role="alert">
          {errorMessage(unlink.error, "No se pudo desconectar.")}
        </p>
      )}
      <ConfirmDialog
        open={confirmUnlink}
        onOpenChange={setConfirmUnlink}
        title="Desconectar al dueño"
        description={
          detail.owner_linked
            ? "El chat conectado dejará de recibir avisos. ¿Continuar?"
            : "Se cancela la invitación pendiente. ¿Continuar?"
        }
        confirmLabel="Desconectar"
        onConfirm={() => unlink.mutate()}
      />
      <Dialog
        open={link !== null}
        onOpenChange={(open) => !open && setLink(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enlace para el dueño</DialogTitle>
            <DialogDescription>
              Se muestra una sola vez: cópialo o escanéalo ahora.
            </DialogDescription>
          </DialogHeader>
          <code className="block overflow-auto rounded-md border p-2 text-sm">
            {link?.url}
          </code>
          {link && (
            <>
              {/* C14: the owner scans this from their own phone to open the chat
               * and link it; the code shows only once (the hash is all that's
               * kept), so the QR cannot be regenerated after this dialog closes. */}
              <QrCode
                value={link.url}
                title="QR de invitación del dueño"
                fileName={`dueno-${detail.slug}`}
              />
              <div className="space-y-1 text-sm">
                <p>
                  Caduca el {new Date(link.expires_at).toLocaleString("es-ES")}.
                </p>
                {link.replaces_chat && (
                  <p className="text-status-warning">
                    Ya hay un chat conectado; este enlace lo sustituirá cuando
                    se use.
                  </p>
                )}
              </div>
            </>
          )}
          <DialogFooter>
            <Button
              type="button"
              onClick={() =>
                link && void navigator.clipboard?.writeText(link.url)
              }
            >
              Copiar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
