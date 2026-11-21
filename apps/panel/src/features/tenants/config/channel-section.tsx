import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";
import { SecretsForm } from "./secrets-form";

type Detail = components["schemas"]["TenantDetail"];

export function ChannelSection({ detail }: { detail: Detail }) {
  const secrets = useQuery({
    queryKey: qk.tenantSecrets(detail.slug),
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/secrets", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    enabled: detail.channel_type !== null,
  });
  const isTelegram = detail.channel_type === "telegram";
  const webhookStatus = useQuery({
    queryKey: qk.tenantWebhook(detail.slug),
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/telegram-webhook", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    enabled: isTelegram,
    retry: false,
  });
  const registered = webhookStatus.data?.registered ?? null;
  const webhook = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/telegram-webhook", {
          params: { path: { slug: detail.slug } },
        }),
      ),
    success: "Webhook registrado.",
    invalidate: [qk.tenant(detail.slug), qk.tenantWebhook(detail.slug)],
  });
  if (detail.channel_type === null) return null;
  return (
    <div className="space-y-3 border-t pt-4">
      {detail.public_link ? (
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Enlace público</span>
            <a className="underline" href={detail.public_link}>
              {detail.public_link}
            </a>
            <CopyButton value={detail.public_link} />
          </div>
          <p className="text-xs text-muted-foreground">
            El QR está en la pestaña Alta.
          </p>
        </div>
      ) : (
        // shown, never hidden — there is no QR until this is fixed.
        <div className="flex items-center gap-2 text-sm">
          <StatusDot level="warning" />
          <span className="text-status-warning">
            {detail.channel_type === "telegram"
              ? "Falta el usuario del bot (bot_username): sin él no hay enlace ni QR."
              : "Falta el teléfono público (display_phone): sin él no hay enlace ni QR."}
          </span>
        </div>
      )}
      {detail.channel_type === "telegram" && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Webhook</span>
          <code className="truncate">{detail.webhook_url ?? "—"}</code>
          {detail.webhook_url && <CopyButton value={detail.webhook_url} />}
          <StatusDot
            level={
              registered === true
                ? "ok"
                : registered === false
                  ? "warning"
                  : "unknown"
            }
            label={
              registered === true
                ? "Registrado"
                : registered === false
                  ? "Sin registrar"
                  : "Sin comprobar"
            }
          />
          <Button
            type="button"
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
        <p role="alert" className="text-sm text-destructive">
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
