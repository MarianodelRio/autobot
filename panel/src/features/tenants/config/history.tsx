import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function History({ slug }: { slug: string }) {
  const client = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const versions = useQuery({
    queryKey: ["tenant-versions", slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/versions", { params: { path: { slug } } }),
      ),
  });
  const previous = versions.data?.findIndex((v) => v.version === selected);
  const previousVersion =
    previous !== undefined && previous >= 0
      ? versions.data?.[previous + 1]?.version
      : undefined;
  const current = useQuery({
    queryKey: ["tenant-version", slug, selected],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/versions/{version}", {
          params: { path: { slug, version: selected ?? 0 } },
        }),
      ),
    enabled: selected !== null,
  });
  const prior = useQuery({
    queryKey: ["tenant-version", slug, previousVersion],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/versions/{version}", {
          params: { path: { slug, version: previousVersion ?? 0 } },
        }),
      ),
    enabled: previousVersion !== undefined,
  });
  const rollback = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/rollback", {
          params: { path: { slug } },
          body: { version: selected ?? 0, comment: comment.trim() },
        }),
      ),
    onSuccess: (result) => {
      toast.success(
        `Recuperada como versión ${result.version}; se aplica en unos segundos`,
      );
      setSelected(null);
      setComment("");
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["tenant-versions", slug] });
      void client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  if (versions.isPending) return <p>Cargando historial…</p>;
  if (versions.isError)
    return (
      <ErrorState
        message="No se pudo cargar el historial."
        onRetry={() => void versions.refetch()}
      />
    );
  if (!versions.data.length) return <EmptyState message="No hay versiones." />;
  return (
    <div className="space-y-4">
      <ul>
        {versions.data.map((v) => (
          <li className="border-b py-3" key={v.version}>
            <button
              type="button"
              className="underline"
              onClick={() => {
                setSelected(v.version);
                setComment("");
                rollback.reset();
              }}
            >
              Versión {v.version}
            </button>{" "}
            · {v.author} · <TimeAgo date={v.created_at} /> · {v.comment}
          </li>
        ))}
      </ul>
      {selected !== null && (
        <section className="space-y-3">
          <h2 className="font-semibold">
            Versión {selected}: diferencias con la anterior
          </h2>
          {current.isPending ||
          (previousVersion !== undefined && prior.isPending) ? (
            <p>Cargando diferencias…</p>
          ) : current.isError ||
            (previousVersion !== undefined && prior.isError) ? (
            <ErrorState
              message="No se pudieron cargar las versiones."
              onRetry={() => {
                void current.refetch();
                if (previousVersion !== undefined) void prior.refetch();
              }}
            />
          ) : (
            <JsonDiff
              before={previousVersion === undefined ? {} : prior.data?.document}
              after={current.data?.document}
            />
          )}
          <Label htmlFor="rollback-comment">Comentario obligatorio</Label>
          <Input
            id="rollback-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <Button
            disabled={!comment.trim() || rollback.isPending}
            onClick={() => rollback.mutate()}
          >
            Volver a esta versión
          </Button>
          {rollback.isError && (
            <p role="alert">No se pudo recuperar la versión.</p>
          )}
        </section>
      )}
    </div>
  );
}
