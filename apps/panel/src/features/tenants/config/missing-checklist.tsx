import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";

export function MissingChecklist({ slug }: { slug: string }) {
  const q = useQuery({
    queryKey: ["activation-checklist", slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenants/{slug}/activation-checklist", {
          params: { path: { slug } },
        }),
      ),
    staleTime: 0,
  });
  if (q.isPending) return <p>Cargando comprobaciones…</p>;
  if (q.isError)
    return (
      <ErrorState
        message="No se pudieron cargar las comprobaciones."
        onRetry={() => void q.refetch()}
      />
    );
  const missing = q.data.filter((item) => !item.ok);
  return (
    <section>
      <h2 className="font-semibold">Pendiente para activar</h2>
      {missing.length ? (
        <ul>
          {missing.map((item) => (
            <li key={item.key}>
              {item.label}: {item.detail}
              {item.blocking && " (bloqueante)"}
            </li>
          ))}
        </ul>
      ) : (
        <p>No quedan comprobaciones pendientes.</p>
      )}
    </section>
  );
}
