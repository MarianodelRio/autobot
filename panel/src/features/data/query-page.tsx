import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { CodeEditor } from "@/components/code-editor";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { downloadCsv, toDelimited } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { SavedQueriesPanel } from "./saved-queries-panel";
import { sqlSchemaFrom, useTables } from "./use-tables";

const STORAGE_KEY = "autobot.panel.data.lastQuery";

function readLastQuery(): { sql: string; tenant: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeLastQuery(value: { sql: string; tenant: string }): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // localStorage can be unavailable (private mode, quota); losing the
    // "remember my last query" convenience is not worth failing the run for.
  }
}

export function QueryPage({ initialSql }: { initialSql?: string }) {
  const last = readLastQuery();
  const [sql, setSql] = useState(initialSql || last?.sql || "SELECT 1");
  const [tenant, setTenant] = useState(initialSql ? "" : last?.tenant || "");
  const tables = useTables();
  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: () => unwrap(api.GET("/tenants")),
  });
  const run = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/data/query", { body: { sql, tenant } })),
    onSuccess: () => writeLastQuery({ sql, tenant }),
  });
  const result = run.data;
  return (
    <div>
      <PageHeader title="Consulta" />
      <div className="flex gap-6">
        <div className="flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <select
              className="rounded-md border bg-background px-3 py-2 text-sm"
              aria-label="Cliente"
              value={tenant}
              onChange={(event) => setTenant(event.target.value)}
            >
              <option value="">Todos los clientes</option>
              {(tenants.data ?? []).map((row) => (
                <option key={row.slug} value={row.slug}>
                  {row.name}
                </option>
              ))}
            </select>
            <Button disabled={run.isPending} onClick={() => run.mutate()}>
              Ejecutar (⌘↵)
            </Button>
          </div>
          <CodeEditor
            value={sql}
            onChange={setSql}
            language="sql"
            sqlSchema={sqlSchemaFrom(tables.data)}
            onRun={() => run.mutate()}
          />
          {run.isError && (
            <p role="alert" className="text-destructive">
              {errorMessage(run.error, "No se pudo ejecutar la consulta.")}
            </p>
          )}
          {result && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                <span>{result.duration_ms} ms</span>
                <span>{result.rows.length} filas</span>
                {result.truncated && (
                  <span className="text-status-notice">
                    Resultado truncado: afina la consulta.
                  </span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void navigator.clipboard?.writeText(
                      toDelimited(
                        result.columns.map((c) => c.name),
                        result.rows,
                        "\t",
                      ),
                    )
                  }
                >
                  Copiar
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    downloadCsv(
                      "consulta.csv",
                      toDelimited(
                        result.columns.map((c) => c.name),
                        result.rows,
                        ",",
                      ),
                    )
                  }
                >
                  Descargar CSV
                </Button>
              </div>
              <div className="overflow-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      {result.columns.map((column) => (
                        <th
                          key={column.name}
                          className="border-b px-2 py-1 text-left"
                        >
                          {column.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row) => (
                      <tr key={row.join("\u0000")}>
                        {row.map((value, index) => (
                          <td
                            key={result.columns[index]?.name ?? index}
                            className="border-b px-2 py-1"
                          >
                            {value === null ? "—" : String(value)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        <SavedQueriesPanel currentSql={sql} onLoad={setSql} />
      </div>
    </div>
  );
}
