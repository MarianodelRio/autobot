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

export function OwnerSection({ detail }: { detail: Detail }) {
  const [link, setLink] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/owner-invite", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: (result) => setLink(result.url),
  });
  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between text-sm">
        <StatusDot
          level={detail.owner_linked ? "ok" : "unknown"}
          label={detail.owner_linked ? "Dueño enlazado" : "Dueño sin enlazar"}
        />
        <Button
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
            {link}
          </code>
          <DialogFooter>
            <Button
              onClick={() => link && void navigator.clipboard?.writeText(link)}
            >
              Copiar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
