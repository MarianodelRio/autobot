import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { StatusDot } from "@/components/status-dot";

type Detail = components["schemas"]["TenantDetail"];

// D4: Google does not cover a personal account with its data-processing addendum;
// only a few domains can be told apart for sure, the rest (Workspace or not) need
// asking in person.
const PERSONAL_GMAIL = /@(gmail|googlemail)\.com$/i;

export function CalendarSection({ detail }: { detail: Detail }) {
  const account = useQuery({
    queryKey: ["calendar-service-account"],
    queryFn: () => unwrap(api.GET("/calendar/service-account")),
  });
  const calendarId =
    typeof detail.document.config === "object" &&
    detail.document.config !== null &&
    "calendar_id" in detail.document.config &&
    typeof (detail.document.config as Record<string, unknown>).calendar_id ===
      "string"
      ? ((detail.document.config as Record<string, unknown>)
          .calendar_id as string)
      : "";
  return (
    <div className="space-y-3 border-t pt-4">
      <h3 className="text-sm font-medium text-muted-foreground">
        Calendario de Google
      </h3>
      {account.isPending ? (
        <p className="text-sm">Cargando cuenta de servicio…</p>
      ) : account.isError ? (
        <ErrorState
          message="No se pudo cargar la cuenta de servicio."
          onRetry={() => void account.refetch()}
        />
      ) : !account.data.configured ? (
        <p className="text-sm text-status-warning">
          El servidor no tiene configurada la cuenta de servicio de Google.
        </p>
      ) : !account.data.email ? (
        <p className="text-sm text-status-warning">
          No se pudo leer el email de la cuenta de servicio.
        </p>
      ) : (
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">
              Email de la cuenta de servicio
            </span>
            <code>{account.data.email}</code>
            <CopyButton value={account.data.email} />
          </div>
          <p className="text-muted-foreground">
            Pide al negocio que comparta su calendario con ese email, con
            permiso «Hacer cambios y ver todos los detalles de eventos», y que
            te dé el id del calendario (en los ajustes del calendario, «Integrar
            calendario»).
          </p>
        </div>
      )}
      {calendarId && PERSONAL_GMAIL.test(calendarId) && (
        <div className="flex items-center gap-2 text-sm">
          <StatusDot level="warning" />
          <span className="text-status-warning">
            Es un Gmail personal: Google no lo cubre con su contrato de
            tratamiento de datos. Confirma que es una cuenta de Workspace.
          </span>
        </div>
      )}
    </div>
  );
}
