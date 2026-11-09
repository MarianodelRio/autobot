import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/error-state";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";
import { SecretsForm } from "./secrets-form";

type Detail = components["schemas"]["TenantDetail"];

function CopyButton({ value }: { value: string }) {
  return (
    <button
      type="button"
      aria-label="Copiar"
      className="text-muted-foreground hover:text-foreground"
      onClick={() => void navigator.clipboard?.writeText(value)}
    >
      ⧉
    </button>
  );
}

export function ChannelSection({ detail }: { detail: Detail }) {
  const client = useQueryClient();
  const secrets = useQuery({
    queryKey: ["tenant-secrets", detail.slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/secrets", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    enabled: detail.channel_type !== null,
  });
  const webhook = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/telegram-webhook", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    onSuccess: () => {
      toast.success("Webhook registrado.");
      void client.invalidateQueries({ queryKey: ["tenant", detail.slug] });
    },
  });
  if (detail.channel_type === null) return null;
  return (
    <div className="space-y-3 border-t pt-4">
      {detail.public_link && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Enlace público</span>
          <a className="underline" href={detail.public_link}>
            {detail.public_link}
          </a>
          <CopyButton value={detail.public_link} />
          <div className="ml-auto w-16 bg-white p-1">
            <QRCodeSVG
              value={detail.public_link}
              title="QR del canal público"
            />
          </div>
        </div>
      )}
      {detail.channel_type === "telegram" && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Webhook</span>
          <code className="truncate">{detail.webhook_url ?? "—"}</code>
          {detail.webhook_url && <CopyButton value={detail.webhook_url} />}
          <StatusDot
            level={detail.webhook_url ? "ok" : "unknown"}
            label={detail.webhook_url ? "Registrado" : "Sin registrar"}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={webhook.isPending}
            onClick={() => webhook.mutate()}
          >
            Registrar webhook
          </Button>
        </div>
      )}
      {webhook.isError && (
        <p role="alert">
          {errorMessage(webhook.error, "No se pudo registrar el webhook.")}
        </p>
      )}
      <div className="space-y-2 border-t pt-3">
        <h3 className="text-sm font-medium text-muted-foreground">
          Credenciales
        </h3>
        {secrets.isPending ? (
          <p className="text-sm">Cargando estado de secretos…</p>
        ) : secrets.isError ? (
          <ErrorState
            message="No se pudo cargar el estado de secretos."
            onRetry={() => void secrets.refetch()}
          />
        ) : (
          <>
            {!secrets.data.readable && (
              <p className="text-sm text-status-warning">
                No se pueden leer los secretos configurados.
              </p>
            )}
            {secrets.data.fields.map((field) => (
              <div
                key={field.name}
                className="flex items-center justify-between text-sm"
              >
                <span>{field.label}</span>
                <StatusDot
                  level={field.set ? "ok" : "unknown"}
                  label={field.set ? "Configurado" : "Sin configurar"}
                />
              </div>
            ))}
            <SecretsForm slug={detail.slug} fields={secrets.data.fields} />
          </>
        )}
      </div>
    </div>
  );
}
