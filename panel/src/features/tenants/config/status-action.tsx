import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
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

export function StatusAction({
  slug,
  status,
}: {
  slug: string;
  status: string;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const client = useQueryClient();
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
    queryKey: ["activation-checklist", slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/activation-checklist", {
          params: { path: { slug } },
        }),
      ),
    enabled: open && action === "activate",
    staleTime: 0,
  });
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/status", {
          params: { path: { slug } },
          body: {
            action: action ?? "",
            ...(action === "activate" ? { confirm_slug: typed } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      setTyped("");
      toast.success("Estado actualizado.");
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["tenants"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
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
      {mutation.isError && <p role="alert">No se pudo cambiar el estado.</p>}
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
            ) : checklist.isError ? (
              <ErrorState
                message="No se pudieron cargar las comprobaciones."
                onRetry={() => void checklist.refetch()}
              />
            ) : (
              <>
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
                  <p role="alert">No se pudo activar el cliente.</p>
                )}
              </>
            )}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
