import { Link } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { TimeAgo } from "@/components/time-ago";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SEND_STATUS_LABEL } from "@/features/activity/components/timeline";
import { errorMessage } from "@/lib/errors";
import { useApiMutation } from "@/lib/use-api-mutation";
import {
  type Case,
  incidentsChanged,
  type JobCase,
  NOTICE_STATUS_LABEL,
  type NoticeCase,
  type SendCase,
} from "./shared";

/** A button that is off for a reason: the reason is the tooltip, not extra text. */
function ReasonButton({
  reason,
  enabled,
  children,
  ...props
}: {
  reason?: string | null;
  enabled: boolean;
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <span title={enabled ? undefined : (reason ?? undefined)}>
      <Button
        size="sm"
        variant="outline"
        {...props}
        disabled={!enabled || props.disabled}
      >
        {children}
      </Button>
    </span>
  );
}

function SendItem({ item, tenant }: { item: SendCase; tenant?: string }) {
  const [confirm, setConfirm] = useState<"resend" | "discard" | null>(null);
  const refresh = {
    invalidate: incidentsChanged(),
    tenant,
    appliesConfig: false,
  };
  const markSent = useApiMutation({
    ...refresh,
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/mark-sent", {
          params: { path: { id: item.id } },
        }),
      ),
    success: "Envío marcado como enviado.",
  });
  const discard = useApiMutation({
    ...refresh,
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/discard", {
          params: { path: { id: item.id } },
        }),
      ),
    success: "Envío descartado.",
    onSuccess: () => setConfirm(null),
  });
  const resend = useApiMutation({
    ...refresh,
    fn: () =>
      unwrap(
        api.POST("/outbound/{id}/resend", {
          params: { path: { id: item.id } },
          body: { confirm_duplicate_risk: true },
        }),
      ),
    success: "Mensaje reenviado.",
    onSuccess: () => setConfirm(null),
  });
  const failed = resend.error ?? discard.error ?? markSent.error;
  return (
    <li className="space-y-1 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{item.channel}</Badge>
        <Badge variant="secondary">
          {SEND_STATUS_LABEL[item.status] ?? item.status}
        </Badge>
        <span className="text-muted-foreground">
          Envío <TimeAgo date={item.created_at} />
        </span>
      </div>
      {item.error_title && (
        <p>
          <strong>{item.error_title}</strong>
          {item.error_advice ? ` ${item.error_advice}` : ""}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <ReasonButton
          enabled={item.can_mark_sent}
          reason={item.mark_sent_reason}
          disabled={markSent.isPending}
          onClick={() => markSent.mutate()}
        >
          Marcar enviado
        </ReasonButton>
        <ReasonButton
          enabled={item.can_resend}
          reason={item.resend_reason}
          onClick={() => setConfirm("resend")}
        >
          Reenviar
        </ReasonButton>
        <ReasonButton
          enabled={item.can_discard}
          reason={item.discard_reason}
          onClick={() => setConfirm("discard")}
        >
          Descartar
        </ReasonButton>
      </div>
      {failed && (
        <p role="alert" className="text-destructive">
          {errorMessage(failed, "No se pudo completar la acción.")}
        </p>
      )}
      <ConfirmDialog
        open={confirm === "resend"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Reenviar mensaje"
        description="Puede que el destinatario ya lo haya recibido: reenviar puede crear un duplicado. ¿Confirmas el reenvío?"
        confirmLabel="Reenviar"
        onConfirm={() => resend.mutate()}
      />
      <ConfirmDialog
        open={confirm === "discard"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Descartar envío"
        description="No se reenviará ni volverá a aparecer como pendiente de decidir. ¿Descartarlo?"
        confirmLabel="Descartar"
        onConfirm={() => discard.mutate()}
      />
    </li>
  );
}

function JobItem({ item, tenant }: { item: JobCase; tenant?: string }) {
  const retry = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/jobs/{id}/retry", { params: { path: { id: item.id } } }),
      ),
    success: "Trabajo reencolado.",
    invalidate: incidentsChanged(),
    tenant,
    appliesConfig: false,
  });
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
      <strong>{item.task_label}</strong>
      <span className="text-muted-foreground">
        {item.failed_at ? (
          <>
            falló <TimeAgo date={item.failed_at} />
          </>
        ) : (
          "falló"
        )}
      </span>
      {(item.can_retry || item.retry_reason) && (
        <ReasonButton
          enabled={item.can_retry}
          reason={item.retry_reason}
          disabled={retry.isPending}
          onClick={() => retry.mutate()}
        >
          Reintentar
        </ReasonButton>
      )}
    </li>
  );
}

function NoticeItem({ item, tenant }: { item: NoticeCase; tenant?: string }) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
      <strong>Aviso al dueño</strong>
      <Badge variant="secondary">
        {NOTICE_STATUS_LABEL[item.status] ?? item.status}
      </Badge>
      <span className="text-muted-foreground">
        <TimeAgo date={item.created_at} />
      </span>
      {tenant && (
        <Link
          className="underline"
          to="/clientes/$slug"
          params={{ slug: tenant }}
          search={{ tab: "configuracion", section: "personas" }}
        >
          Invitar al dueño
        </Link>
      )}
    </li>
  );
}

export function CaseItem({ item, tenant }: { item: Case; tenant?: string }) {
  if (item.type === "send") return <SendItem item={item} tenant={tenant} />;
  if (item.type === "job") return <JobItem item={item} tenant={tenant} />;
  return <NoticeItem item={item} tenant={tenant} />;
}
