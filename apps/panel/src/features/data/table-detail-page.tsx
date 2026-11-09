import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatNumber } from "@/lib/format";

export function TableDetailPage({ table }: { table: string }) {
  const query = useQuery({
    queryKey: ["data-table", table],
    queryFn: () =>
      unwrap(
        api.GET("/data/tables/{name}", { params: { path: { name: table } } }),
      ),
  });
  if (query.isPending) return <p>Cargando tabla…</p>;
  if (query.isError)
    return (
      <ErrorState
        message={errorMessage(query.error, "No se pudo cargar la tabla.")}
        onRetry={() => void query.refetch()}
      />
    );
  const detail = query.data;
  return (
    <div className="space-y-6">
      <div>
        <Link to="/datos" className="text-sm underline">
          ← Datos
        </Link>
      </div>
      <PageHeader title={detail.name} description={detail.description} />
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Badge variant="outline">Escrita por: {detail.written_by}</Badge>
        <Badge variant="outline">Retención: {detail.retention}</Badge>
        {detail.rls && <Badge variant="outline">RLS</Badge>}
        <span>
          {detail.approx ? "≈ " : ""}
          {formatNumber(detail.row_count)} filas · {formatBytes(detail.bytes)}
        </span>
      </div>

      <section>
        <h2 className="mb-2 font-semibold">Columnas</h2>
        <Table>
          <TableHeader>
            <TableRow>
              {["Nombre", "Tipo", "Nulable", "Clave", "Descripción"].map(
                (label) => (
                  <TableHead key={label}>{label}</TableHead>
                ),
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {detail.columns.map((column) => (
              <TableRow key={column.name}>
                <TableCell className="font-mono">
                  {column.name}
                  {column.hidden && " 🔒"}
                </TableCell>
                <TableCell>{column.type}</TableCell>
                <TableCell>{column.nullable ? "Sí" : "No"}</TableCell>
                <TableCell>{column.primary_key ? "PK" : ""}</TableCell>
                <TableCell>{column.description}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      {detail.outgoing.length > 0 && (
        <section>
          <h2 className="mb-2 font-semibold">Apunta a</h2>
          <ul className="space-y-1 text-sm">
            {detail.outgoing.map((relation) =>
              relation.columns.map((column, index) => (
                <li key={`${relation.name}-${column}`}>
                  <code>{column}</code> →{" "}
                  <Link
                    className="underline"
                    to="/datos/$table"
                    params={{ table: relation.target }}
                  >
                    {relation.target}
                  </Link>
                  <code>.{relation.target_columns[index]}</code>
                </li>
              )),
            )}
          </ul>
        </section>
      )}

      {detail.incoming.length > 0 && (
        <section>
          <h2 className="mb-2 font-semibold">La usan</h2>
          <ul className="space-y-1 text-sm">
            {detail.incoming.map((relation) =>
              relation.target_columns.map((column, index) => (
                <li key={`${relation.name}-${column}`}>
                  <code>{column}</code> →{" "}
                  <Link
                    className="underline"
                    to="/datos/$table"
                    params={{ table: relation.source }}
                  >
                    {relation.source}
                  </Link>
                  <code>.{relation.columns[index]}</code>
                </li>
              )),
            )}
          </ul>
        </section>
      )}

      {detail.rows_by_tenant.length > 0 && (
        <section>
          <h2 className="mb-2 font-semibold">Filas por cliente</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cliente</TableHead>
                <TableHead>Filas</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.rows_by_tenant.map((row) => (
                <TableRow key={row.tenant_id ?? "null"}>
                  <TableCell>{row.tenant ?? row.tenant_id ?? "—"}</TableCell>
                  <TableCell>{formatNumber(row.count)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      <section>
        <h2 className="mb-2 font-semibold">Últimas 20 filas</h2>
        <div className="overflow-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                {detail.columns.map((column) => (
                  <TableHead key={column.name}>{column.name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.rows.map((row) => (
                <TableRow key={row.join("\u0000")}>
                  {row.map((value, cellIndex) => (
                    <TableCell
                      key={detail.columns[cellIndex]?.name ?? cellIndex}
                    >
                      {value === null ? "—" : String(value)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}
