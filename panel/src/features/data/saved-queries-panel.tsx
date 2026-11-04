import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SavedQueriesPanel({
  currentSql,
  onLoad,
}: {
  currentSql: string;
  onLoad: (sql: string) => void;
}) {
  const client = useQueryClient();
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");
  const [toDelete, setToDelete] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ["saved-queries"],
    queryFn: () => unwrap(api.GET("/data/saved-queries")),
  });
  const create = useMutation({
    mutationFn: (payload: { name: string; sql: string }) =>
      unwrap(api.POST("/data/saved-queries", { body: payload })),
    onSuccess: () => {
      setSaveOpen(false);
      setName("");
      toast.success("Consulta guardada.");
      void client.invalidateQueries({ queryKey: ["saved-queries"] });
    },
  });
  const update = useMutation({
    mutationFn: (payload: { id: number; name: string; sql: string }) =>
      unwrap(
        api.PUT("/data/saved-queries/{id}", {
          params: { path: { id: payload.id } },
          body: { name: payload.name, sql: payload.sql },
        }),
      ),
    onSuccess: () => {
      toast.success("Consulta actualizada.");
      void client.invalidateQueries({ queryKey: ["saved-queries"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) =>
      api.DELETE("/data/saved-queries/{id}", { params: { path: { id } } }),
    onSuccess: () => {
      setToDelete(null);
      toast.success("Consulta eliminada.");
      void client.invalidateQueries({ queryKey: ["saved-queries"] });
    },
  });
  const queries = query.data ?? [];
  return (
    <div className="w-64 shrink-0 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Consultas guardadas</h2>
        <Button size="sm" onClick={() => setSaveOpen(true)}>
          Guardar
        </Button>
      </div>
      {query.isPending ? (
        <p className="text-sm">Cargando…</p>
      ) : queries.length === 0 ? (
        <EmptyState message="No hay consultas guardadas." />
      ) : (
        <ul className="space-y-1">
          {queries.map((saved) => (
            <li
              key={saved.id}
              className="flex items-center justify-between gap-1 rounded-md border px-2 py-1 text-sm"
            >
              <button
                type="button"
                className="truncate text-left underline"
                title={saved.sql}
                onClick={() => onLoad(saved.sql)}
              >
                {saved.name}
              </button>
              <div className="flex shrink-0 gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate({
                      id: saved.id,
                      name: saved.name,
                      sql: currentSql,
                    })
                  }
                >
                  Actualizar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setToDelete(saved.id)}
                >
                  Eliminar
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Guardar consulta</DialogTitle>
          </DialogHeader>
          <Label htmlFor="saved-query-name">Nombre</Label>
          <Input
            id="saved-query-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <DialogFooter>
            <Button
              disabled={!name || create.isPending}
              onClick={() => create.mutate({ name, sql: currentSql })}
            >
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Eliminar consulta guardada"
        description="¿Quieres eliminar esta consulta guardada?"
        confirmLabel="Eliminar"
        onConfirm={() => toDelete !== null && remove.mutate(toDelete)}
      />
    </div>
  );
}
