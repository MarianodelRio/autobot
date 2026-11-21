import { useQuery } from "@tanstack/react-query";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { packsQueryOptions } from "@/lib/queries";

export function PackStep({
  pack,
  onSelect,
  onNext,
}: {
  pack: string;
  onSelect: (name: string) => void;
  onNext: () => void;
}) {
  const packs = useQuery(packsQueryOptions());
  return (
    <section className="space-y-4">
      <h2 className="font-semibold">Elige un pack</h2>
      {packs.isPending ? (
        <p>Cargando packs…</p>
      ) : packs.isError ? (
        <ErrorState
          message="No se pudieron cargar los packs."
          onRetry={() => void packs.refetch()}
        />
      ) : packs.data.length === 0 ? (
        <p>No hay packs disponibles.</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          {packs.data.map((item) => (
            <button
              key={item.name}
              type="button"
              aria-pressed={pack === item.name}
              className="rounded-lg border p-4 aria-pressed:border-primary"
              onClick={() => onSelect(item.name)}
            >
              {item.name}
            </button>
          ))}
        </div>
      )}
      <Button disabled={!pack} onClick={onNext}>
        Siguiente
      </Button>
    </section>
  );
}
