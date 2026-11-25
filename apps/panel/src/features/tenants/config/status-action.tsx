import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
import { RefreshWarning } from "@/components/refresh-warning";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorDetail } from "@/lib/errors";
import { LIVE, qk } from "@/lib/queries";
import { recordSetupResult } from "@/lib/setup-checks";
import { useApiMutation } from "@/lib/use-api-mutation";

export function StatusAction({
  slug,
  status,
  version,
}: {
  slug: string;
  status: string;
  version: number | null | undefined;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const action =
    status === "active"
      ? "pause"
      : status === "paused"
        ? "resume"
        : status === "onboarding"
          ? "activate"
          : null;
  const label =
    action === "pause"
      ? "Pausar"
      : action === "resume"
        ? "Reactivar"
        : "Activar";
  const checklist = useQuery({
    queryKey: qk.activationChecklist(slug),
    ...LIVE,
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/activation-checklist", {
          params: { path: { slug } },
        }),
      ),
    enabled: open && action === "activate",
    staleTime: 0,
    // Reading never calls Meta, Telegram or Google: only «Comprobar» does.
    refetchOnWindowFocus: false,
  });
  const refresh = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/setup/check/{step}", {
          params: { path: { slug, step: "health" } },
        }),
      ),
    tenant: slug,
    channel: true,
    appliesConfig: false, // a health check only reads and records
    onSuccess: (result) => recordSetupResult(client, slug, result, version),
  });
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/status", {
          params: { path: { slug } },
          body: {
            action: action ?? "",
            ...(action === "activate" ? { confirm_slug: typed } : {}),
          },
        }),
      ),
    success: "Estado actualizado.",
    tenant: slug,
    channel: true,
    onSuccess: () => {
      setOpen(false);
      setTyped("");
    },
  });
  if (!action) return null;
  return (
    <>
      <Button
        disabled={mutation.isPending}
        onClick={() => {
          mutation.reset();
          setOpen(true);
        }}
      >
        {label}
      </Button>
      {mutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorDetail(mutation.error, "No se pudo cambiar el estado.")}
        </p>
      )}
      {action !== "activate" ? (
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          title={`${label} cliente`}
          description={`¿Quieres ${label.toLowerCase()} este cliente?`}
          confirmLabel={label}
          onConfirm={() => mutation.mutate()}
        />
      ) : (
        <Dialog
          open={open}
          onOpenChange={(value) => {
            setOpen(value);
            if (!value) setTyped("");
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Activar cliente</DialogTitle>
              <DialogDescription>
                Completa las comprobaciones y escribe el slug para confirmar.
              </DialogDescription>
            </DialogHeader>
            {checklist.isPending ? (
              <p>Cargando comprobaciones…</p>
            ) : checklist.isError && !checklist.data ? (
              <ErrorState
                message="No se pudieron cargar las comprobaciones."
                onRetry={() => void checklist.refetch()}
              />
            ) : (
              <>
                {checklist.isError && (
                  <RefreshWarning onRetry={() => void checklist.refetch()} />
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={refresh.isPending}
                  onClick={() => refresh.mutate()}
                >
                  Comprobar ahora
                </Button>
                {refresh.isError && (
                  <p role="alert" className="text-sm text-destructive">
                    {errorDetail(refresh.error, "No se pudo comprobar.")}
                  </p>
                )}
                <ul>
                  {checklist.data.map((item) => (
                    <li key={item.key}>
                      {item.ok ? "✓" : "✗"} {item.label}: {item.detail}
                      {!item.ok && item.blocking && " (bloqueante)"}
                    </li>
                  ))}
                </ul>
                <Label htmlFor="activation-slug">Escribe {slug}</Label>
                <Input
                  id="activation-slug"
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                />
                <Button
                  disabled={
                    typed !== slug ||
                    checklist.data.some((item) => item.blocking && !item.ok) ||
                    mutation.isPending
                  }
                  onClick={() => mutation.mutate()}
                >
                  Activar
                </Button>
                {mutation.isError && (
                  <p role="alert" className="text-sm text-destructive">
                    {errorDetail(
                      mutation.error,
                      "No se pudo activar el cliente.",
                    )}
                  </p>
                )}
              </>
            )}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
