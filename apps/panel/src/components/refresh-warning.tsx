import { Button } from "@/components/ui/button";

/** Non-blocking notice for a failed background refetch: the screen keeps the last
 * data (and any unsaved input) and says so. A full `ErrorState` is only for the
 * case with no data at all (`isError && !data`). */
export function RefreshWarning({ onRetry }: { onRetry: () => void }) {
  return (
    <p
      role="status"
      className="flex flex-wrap items-center gap-2 text-sm text-status-warning"
    >
      No se pudo actualizar; se muestran los últimos datos.
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        Reintentar
      </Button>
    </p>
  );
}
