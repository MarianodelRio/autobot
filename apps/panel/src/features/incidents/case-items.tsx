import { type ReactNode, useState } from "react";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { TimeAgo } from "@/components/time-ago";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { STATUS_LABEL } from "@/features/activity/components/timeline";
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

/** An action button; when it is off, the reason is shown as small text under it
 * (and as tooltip), so it reads on touch screens and to screen readers too. */
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
  const why = enabled ? undefined : (reason ?? undefined);
  return (
    <div className="flex max-w-56 flex-col items-start gap-1" title={why}>
      <Button
        size="sm"
        variant="outline"
        {...props}
        disabled={!enabled || props.disabled}
      >
        {children}
      </Button>
      {why && <span className="text-xs text-muted-foreground">{why}</span>}
    </div>
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
  const all = [markSent, discard, resend];
  // Pending or done: the send is being settled, so none of its actions applies twice.
  const busy = all.some((m) => m.isPending || m.isSuccess);
  // A new action forgets the error of the others.
  const run = (current: (typeof all)[number]) => () => {
    for (const m of all) if (m !== current) m.reset();
    current.mutate(undefined);
  };
  const failed = all.find((m) => m.isError)?.error;
  // A rejected (not ambiguous) send has nothing to decide: no dead buttons.
  const noActions =
    !item.can_mark_sent &&
    !item.can_resend &&
    !item.can_discard &&
    item.status !== "unknown";
  return (
    <li className="space-y-1 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{item.channel}</Badge>
        <Badge variant="secondary">
          {STATUS_LABEL[item.status] ?? item.status}
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
      {!noActions && (
        <div className="flex flex-wrap items-start gap-2 pt-1">
          <ReasonButton
            enabled={item.can_mark_sent}
            reason={item.mark_sent_reason}
            disabled={busy}
            onClick={run(markSent)}
          >
            Marcar enviado
          </ReasonButton>
          <ReasonButton
            enabled={item.can_resend}
            reason={item.resend_reason}
            disabled={busy}
            onClick={() => {
              for (const m of [markSent, discard]) m.reset();
              setConfirm("resend");
            }}
          >
            Reenviar
          </ReasonButton>
          <ReasonButton
            enabled={item.can_discard}
            reason={item.discard_reason}
            disabled={busy}
            onClick={() => {
              for (const m of [markSent, resend]) m.reset();
              setConfirm("discard");
            }}
          >
            Descartar
          </ReasonButton>
        </div>
      )}
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
        onConfirm={run(resend)}
      />
      <ConfirmDialog
        open={confirm === "discard"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Descartar envío"
        description="No se reenviará ni volverá a aparecer como pendiente de decidir. ¿Descartarlo?"
        confirmLabel="Descartar"
        onConfirm={run(discard)}
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
    <li className="space-y-1 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-start gap-2">
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
            disabled={retry.isPending || retry.isSuccess}
            onClick={() => retry.mutate()}
          >
            Reintentar
          </ReasonButton>
        )}
      </div>
      {retry.isError && (
        <p role="alert" className="text-destructive">
          {errorMessage(retry.error, "No se pudo reintentar el trabajo.")}
        </p>
      )}
    </li>
  );
}

function NoticeItem({ item }: { item: NoticeCase }) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
      <strong>Aviso al dueño</strong>
      <Badge variant="secondary">
        {NOTICE_STATUS_LABEL[item.status] ?? item.status}
      </Badge>
      <span className="text-muted-foreground">
        <TimeAgo date={item.created_at} />
      </span>
    </li>
  );
}

export function CaseItem({ item, tenant }: { item: Case; tenant?: string }) {
  if (item.type === "send") return <SendItem item={item} tenant={tenant} />;
  if (item.type === "job") return <JobItem item={item} tenant={tenant} />;
  if (item.type === "notice") return <NoticeItem item={item} />;
  // A case type this panel does not know (a newer backend): a neutral row.
  return (
    <li className="rounded-md border p-3 text-sm text-muted-foreground">
      Caso de un tipo que este panel no conoce.
    </li>
  );
}
