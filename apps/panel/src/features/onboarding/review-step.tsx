import YAML from "yaml";
import { Button } from "@/components/ui/button";
import type { Draft } from "./draft";

export function ReviewStep({
  draft,
  showDatasets,
  pending,
  onBack,
  onCreate,
}: {
  draft: Draft;
  showDatasets: boolean;
  pending: boolean;
  onBack: () => void;
  onCreate: () => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="font-semibold">Revisión</h2>
      <p>
        Pack: {draft.pack} · Nombre: {draft.name} · Slug: {draft.slug}
      </p>
      <p>
        Zona horaria: {draft.timezone} · Canal: {draft.channel}
      </p>
      {showDatasets && (
        <p>
          Horarios:{" "}
          {Object.entries(draft.datasetChoices)
            .map(([dataset, name]) => `${dataset} → ${name}`)
            .join(", ")}
        </p>
      )}
      <pre className="overflow-auto rounded-md border p-3">
        {YAML.stringify(draft.config)}
      </pre>
      <div className="flex gap-2">
        <Button variant="outline" disabled={pending} onClick={onBack}>
          Anterior
        </Button>
        <Button disabled={pending} onClick={onCreate}>
          Crear cliente
        </Button>
      </div>
    </section>
  );
}
