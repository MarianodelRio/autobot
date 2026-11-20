import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/error-state";
import { StatusDot } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { errorDetail } from "@/lib/errors";

type Detail = components["schemas"]["TenantDetail"];

/** C23: "Horarios en uso" and "Aplicar" for a pack with a dataset (today, `bus`'s
 * "timetable"); the content itself never reaches the panel, only its origin and
 * whether a newer library version exists. */
export function DatasetSection({
  detail,
  dataset,
}: {
  detail: Detail;
  dataset: string;
}) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const status = useQuery({
    queryKey: ["tenant-dataset", detail.slug, dataset],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/datasets/{dataset}", {
          params: { path: { slug: detail.slug, dataset } },
        }),
      ),
  });
  const apply = useMutation({
    mutationFn: () => {
      const name = status.data?.source_name;
      if (!name) throw new Error("Sin origen conocido");
      return unwrap(
        api.POST("/tenants/{slug}/datasets/{dataset}/apply", {
          params: { path: { slug: detail.slug, dataset } },
          body: { name, comment: "" },
        }),
      );
    },
    onSuccess: () => {
      toast.success("Horarios actualizados.");
      setConfirming(false);
      void client.invalidateQueries({
        queryKey: ["tenant-dataset", detail.slug, dataset],
      });
    },
  });
  if (status.isPending) return <p className="text-sm">Cargando horarios…</p>;
  if (status.isError)
    return (
      <ErrorState
        message={errorDetail(
          status.error,
          "No se pudieron cargar los horarios.",
        )}
        onRetry={() => void status.refetch()}
      />
    );
  const d = status.data;
  return (
    <div className="space-y-2 border-t pt-4 text-sm">
      <h3 className="font-medium text-muted-foreground">Horarios en uso</h3>
      {d.version === null ? (
        <p className="text-status-warning">
          Sin horarios elegidos todavía (C22 los exige al dar de alta).
        </p>
      ) : (
        <>
          <p>
            {d.source_name ? (
              <>
                <strong>{d.source_name}</strong> v{d.source_version} de la
                biblioteca
              </>
            ) : (
              "Importados directamente (fuera de la biblioteca)"
            )}
            {d.created_at && (
              <>
                {" "}
                · <TimeAgo date={d.created_at} />
              </>
            )}
          </p>
          {d.newer_version_available != null && (
            <div className="flex items-center gap-2">
              <StatusDot level="notice" />
              <span>
                Hay una versión más nueva ({d.source_name} v
                {d.newer_version_available}).
              </span>
              {!confirming ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirming(true)}
                >
                  Aplicar
                </Button>
              ) : (
                <>
                  <Button
                    type="button"
                    size="sm"
                    disabled={apply.isPending}
                    onClick={() => apply.mutate()}
                  >
                    Confirmar
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setConfirming(false)}
                  >
                    Cancelar
                  </Button>
                </>
              )}
            </div>
          )}
        </>
      )}
      {apply.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorDetail(apply.error, "No se pudo aplicar.")}
        </p>
      )}
    </div>
  );
}
