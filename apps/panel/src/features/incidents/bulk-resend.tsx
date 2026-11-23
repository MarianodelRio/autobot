import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/errors";
import { invalidateKeys, qk } from "@/lib/queries";

const STATUSES = [
  { value: "failed", label: "Fallidos" },
  { value: "unknown", label: "Ambiguos" },
  { value: "expired", label: "Caducados" },
] as const;

type Tenant = { id: string; slug: string };

/** Local `datetime-local` value to an ISO instant (or undefined when empty). */
function iso(value: string): string | undefined {
  return value ? new Date(value).toISOString() : undefined;
}

/** Recovery after an incident: resend the failed, ambiguous or expired messages that
 * match a filter, with a preview and a confirmation. The API asks for a fresh TOTP code
 * (step-up) and caps the messages per action. */
export function BulkResend({ tenants }: { tenants: Tenant[] }) {
  const client = useQueryClient();
  const [tenantId, setTenantId] = useState("");
  const [statuses, setStatuses] = useState<string[]>(["failed", "expired"]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [open, setOpen] = useState(false);

  const filter = {
    tenant_id: tenantId || undefined,
    statuses,
    since: iso(since),
    until: iso(until),
  };
  const preview = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/outbound/resend-bulk/preview", { body: filter })),
  });
  const resend = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/outbound/resend-bulk", {
          body: { ...filter, confirm_duplicate_risk: true },
        }),
      ),
    onSuccess: (data) => {
      toast.success(
        data.over_cap > 0
          ? `${data.message} Quedan ${data.over_cap} fuera del límite: repite la acción.`
          : data.message,
      );
      setOpen(false);
      preview.reset();
      invalidateKeys(client, [qk.incidents(), qk.overview(), qk.activityAll()]);
    },
    onError: () => setOpen(false),
  });

  const toggle = (value: string, checked: boolean) => {
    preview.reset();
    setStatuses((current) =>
      checked ? [...current, value] : current.filter((s) => s !== value),
    );
  };
  const data = preview.data;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Reenvía en bloque los mensajes que no llegaron tras una incidencia. Cada
        uno recupera su plazo de entrega; los que ya recibió el destinatario se
        duplicarán.
      </p>
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1">
          <Label htmlFor="bulk-tenant">Negocio</Label>
          <select
            id="bulk-tenant"
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={tenantId}
            onChange={(event) => {
              preview.reset();
              setTenantId(event.target.value);
            }}
          >
            <option value="">Todos</option>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.slug}
              </option>
            ))}
          </select>
        </div>
        <fieldset className="flex items-center gap-3">
          <legend className="sr-only">Estados</legend>
          {STATUSES.map((status) => (
            <label
              key={status.value}
              className="flex items-center gap-1 text-sm"
            >
              <input
                type="checkbox"
                checked={statuses.includes(status.value)}
                onChange={(event) => toggle(status.value, event.target.checked)}
              />
              {status.label}
            </label>
          ))}
        </fieldset>
        <div className="space-y-1">
          <Label htmlFor="bulk-since">Desde</Label>
          <Input
            id="bulk-since"
            type="datetime-local"
            value={since}
            onChange={(event) => {
              preview.reset();
              setSince(event.target.value);
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="bulk-until">Hasta</Label>
          <Input
            id="bulk-until"
            type="datetime-local"
            value={until}
            onChange={(event) => {
              preview.reset();
              setUntil(event.target.value);
            }}
          />
        </div>
        <Button
          variant="outline"
          disabled={statuses.length === 0 || preview.isPending}
          onClick={() => preview.mutate()}
        >
          Previsualizar
        </Button>
      </div>
      {preview.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(preview.error, "No se pudo calcular la previsión.")}
        </p>
      )}
      {data && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">
            {data.total} mensajes coinciden
            {data.total > data.cap
              ? `; se reenviarán los ${data.cap} más antiguos`
              : ""}
            .
          </p>
          <Button
            disabled={data.total === 0 || resend.isPending}
            onClick={() => setOpen(true)}
          >
            Reenviar en bloque
          </Button>
        </div>
      )}
      {data && (
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          title="Reenviar en bloque"
          description={`Se reenviarán hasta ${data.will_resend} mensajes. Puede que algunos destinatarios ya los hayan recibido y reciban un duplicado. ¿Confirmas?`}
          confirmLabel="Reenviar"
          onConfirm={() => resend.mutate()}
        />
      )}
      {resend.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(resend.error, "No se pudo reenviar en bloque.")}
        </p>
      )}
    </div>
  );
}
