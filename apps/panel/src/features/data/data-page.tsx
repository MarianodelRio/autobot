import { useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QueryConsole, readLastQuery } from "./query-console";
import { TableInfoDialog } from "./table-info-dialog";
import { TableList } from "./table-list";
import type { TableSummary } from "./use-tables";

export function DataPage() {
  const [sql, setSql] = useState(() => readLastQuery()?.sql || "SELECT 1");
  const [selected, setSelected] = useState<TableSummary | null>(null);

  return (
    <div className="space-y-6">
      <PageHeader title="Datos" />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader>
            <CardTitle>Consola SQL</CardTitle>
          </CardHeader>
          <CardContent>
            <QueryConsole sql={sql} onSqlChange={setSql} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Tablas</CardTitle>
          </CardHeader>
          <CardContent>
            <TableList onSelect={setSelected} />
          </CardContent>
        </Card>
      </div>
      <TableInfoDialog
        table={selected}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        onInsert={setSql}
      />
    </div>
  );
}
