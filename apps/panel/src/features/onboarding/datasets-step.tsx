import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { qk } from "@/lib/queries";
import type { Draft } from "./draft";

function DatasetChoiceField({
  pack,
  dataset,
  value,
  onChange,
}: {
  pack: string;
  dataset: string;
  value: string;
  onChange: (name: string) => void;
}) {
  const entries = useQuery({
    queryKey: qk.datasetLibrary(pack, dataset),
    queryFn: () =>
      unwrap(
        api.GET("/packs/{pack}/datasets/{dataset}/library", {
          params: { path: { pack, dataset } },
        }),
      ),
  });
  if (entries.isPending) return <p>Cargando biblioteca de {dataset}…</p>;
  if (entries.isError)
    return (
      <ErrorState
        message={`No se pudo cargar la biblioteca de ${dataset}.`}
        onRetry={() => void entries.refetch()}
      />
    );
  if (entries.data.length === 0)
    return (
      <p role="alert" className="text-sm text-destructive">
        No hay ninguna entrada subida para «{dataset}». Súbela primero con{" "}
        <code>make bus-subir</code>.
      </p>
    );
  return (
    <fieldset className="space-y-2 rounded-md border p-3">
      <legend className="px-1 font-medium">{dataset}</legend>
      {entries.data.map((entry) => {
        const towns = entry.summary.pueblos;
        return (
          <label key={entry.name} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name={`dataset-${dataset}`}
              checked={value === entry.name}
              onChange={() => onChange(entry.name)}
            />
            <span>
              <strong>{entry.name}</strong> (v{entry.version})
              {Array.isArray(towns) && (
                <span className="text-muted-foreground">
                  {" "}
                  · {towns.join(", ")}
                </span>
              )}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function DatasetsStep({
  draft,
  datasetNames,
  update,
  onBack,
  onNext,
}: {
  draft: Draft;
  datasetNames: string[];
  update: (patch: Partial<Draft>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const chosen = datasetNames.every((name) => draft.datasetChoices[name]);
  return (
    <section className="space-y-4">
      <h2 className="font-semibold">Horarios</h2>
      <p className="text-sm text-muted-foreground">
        Elige, para cada conjunto, la entrada de la biblioteca que usará este
        negocio. El alta no se completa sin elegir uno.
      </p>
      {datasetNames.map((dataset) => (
        <DatasetChoiceField
          key={dataset}
          pack={draft.pack}
          dataset={dataset}
          value={draft.datasetChoices[dataset] ?? ""}
          onChange={(name) =>
            update({
              datasetChoices: { ...draft.datasetChoices, [dataset]: name },
            })
          }
        />
      ))}
      <div className="flex gap-2">
        <Button variant="outline" onClick={onBack}>
          Anterior
        </Button>
        <Button disabled={!chosen} onClick={onNext}>
          Siguiente
        </Button>
      </div>
    </section>
  );
}
