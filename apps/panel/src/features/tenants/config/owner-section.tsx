import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
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
  const [link, setLink] = useState<Invite | null>(null);
  const invite = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/owner-invite", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: (result) => setLink(result),
  });
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between text-sm">
        <StatusDot
          level={detail.owner_linked ? "ok" : "unknown"}
          label={detail.owner_linked ? "Dueño enlazado" : "Dueño sin enlazar"}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={invite.isPending}
          onClick={() => invite.mutate()}
        >
          Invitar al dueño
        </Button>
      </div>
      {invite.isError && (
        <p role="alert">
          {errorMessage(invite.error, "No se pudo generar el enlace.")}
        </p>
      )}
      <Dialog
        open={link !== null}
        onOpenChange={(open) => !open && setLink(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enlace para el dueño</DialogTitle>
            <DialogDescription>
              Se muestra una sola vez: cópialo ahora.
            </DialogDescription>
          </DialogHeader>
          <code className="block overflow-auto rounded-md border p-2 text-sm">
            {link?.url}
          </code>
          {link && (
            <div className="space-y-1 text-sm">
              <p>
                Caduca el {new Date(link.expires_at).toLocaleString("es-ES")}.
              </p>
              {link.replaces_chat && (
                <p className="text-status-warning">
                  Ya hay un chat conectado; este enlace lo sustituirá cuando se
                  use.
                </p>
              )}
            </div>
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
