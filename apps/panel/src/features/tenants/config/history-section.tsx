import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { type ApiError, api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

/** C16: the version-history and rollback API already existed; this is its panel
 * UI, with a legible diff (C17's JsonDiff) against the current document. */
export function HistorySection({
  slug,
  current,
  dirty,
}: {
  slug: string;
  current: Record<string, unknown>;
  dirty: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const client = useQueryClient();
  const versions = useQuery({
    queryKey: ["tenant-versions", slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/versions", { params: { path: { slug } } }),
      ),
    enabled: open,
  });
  const version = useQuery({
    queryKey: ["tenant-version", slug, preview],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/versions/{version}", {
          params: { path: { slug, version: preview ?? 0 } },
        }),
      ),
    enabled: preview !== null,
  });
  const rollback = useMutation({
    mutationFn: (toVersion: number) =>
      unwrap(
        api.POST("/tenants/{slug}/rollback", {
          params: { path: { slug } },
          body: { version: toVersion, comment: comment.trim() },
        }),
      ),
    onSuccess: () => {
      toast.success("Restaurado: se aplica en unos segundos");
      setComment("");
      setPreview(null);
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["tenant-versions", slug] });
    },
    onError: (error: ApiError) =>
      toast.error(error.message || "No se pudo restaurar."),
  });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        Historial
      </Button>
      <Sheet
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (!value) setPreview(null);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Historial de configuración</SheetTitle>
          </SheetHeader>
          <div className="space-y-4 px-4">
            <div>
              <Label htmlFor="rollback-comment">
                Comentario para la restauración (opcional)
              </Label>
              <Input
                id="rollback-comment"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
              />
            </div>
            {versions.isPending ? (
              <p>Cargando versiones…</p>
            ) : versions.isError ? (
              <ErrorState
                message="No se pudo cargar el historial."
                onRetry={() => void versions.refetch()}
              />
            ) : (
              <ul className="space-y-3">
                {versions.data.map((item) => (
                  <li
                    key={item.version}
                    className="space-y-1 border-b pb-3 last:border-b-0"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        Versión {item.version}
                      </span>
                      <TimeAgo date={item.created_at} />
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {item.author} · {item.comment || "sin comentario"}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setPreview(
                            preview === item.version ? null : item.version,
                          )
                        }
                      >
                        {preview === item.version
                          ? "Ocultar cambios"
                          : "Ver cambios"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={rollback.isPending}
                        onClick={() => {
                          if (
                            dirty &&
                            !window.confirm(
                              "Hay cambios sin guardar que se perderán. ¿Continuar?",
                            )
                          )
                            return;
                          if (
                            !window.confirm(
                              `¿Volver a la versión ${item.version}? Se crea una versión nueva con ese contenido.`,
                            )
                          )
                            return;
                          rollback.mutate(item.version);
                        }}
                      >
                        Volver a esta versión
                      </Button>
                    </div>
                    {preview === item.version && (
                      <div className="pt-2">
                        {version.isPending ? (
                          <p>Cargando cambios…</p>
                        ) : version.isError ? (
                          <p role="alert" className="text-sm text-destructive">
                            No se pudieron cargar los cambios.
                          </p>
                        ) : (
                          <JsonDiff
                            before={version.data.document}
                            after={current}
                          />
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
