import { useNavigate } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TableSummary } from "./use-tables";

export function TableInfoDialog({
  table,
  open,
  onOpenChange,
  onInsert,
}: {
  table: TableSummary | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInsert: (sql: string) => void;
}) {
  const navigate = useNavigate();
  if (!table) return null;
  const cataloged = table.group !== "Sin catalogar";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-mono">{table.name}</DialogTitle>
          {table.description && (
            <DialogDescription>{table.description}</DialogDescription>
          )}
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {table.written_by && (
            <Badge variant="outline">Escrita por: {table.written_by}</Badge>
          )}
          {table.retention && (
            <Badge variant="outline">Retención: {table.retention}</Badge>
          )}
          {table.rls && <Badge variant="outline">RLS</Badge>}
        </div>
        <div className="max-h-64 overflow-auto rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {["Nombre", "Tipo", "Descripción"].map((label) => (
                  <th key={label} className="border-b px-2 py-1 text-left">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.columns.map((column) => (
                <tr key={column.name}>
                  <td className="border-b px-2 py-1 font-mono">
                    {column.name}
                  </td>
                  <td className="border-b px-2 py-1">{column.type}</td>
                  <td className="border-b px-2 py-1">{column.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onInsert(`SELECT * FROM "${table.name}" LIMIT 100`);
              onOpenChange(false);
            }}
          >
            Insertar SELECT
          </Button>
          {cataloged && (
            <Button
              onClick={() => {
                onOpenChange(false);
                void navigate({
                  to: "/datos/$table",
                  params: { table: table.name },
                });
              }}
            >
              Ver detalle
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
