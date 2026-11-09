import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type TableSummary = components["schemas"]["TableSummaryOut"];

export function useTables() {
  return useQuery({
    queryKey: ["data-tables"],
    queryFn: () => unwrap(api.GET("/data/tables")),
  });
}

export function sqlSchemaFrom(
  tables: { name: string; columns: { name: string }[] }[] | undefined,
): Record<string, string[]> {
  const schema: Record<string, string[]> = {};
  for (const table of tables ?? [])
    schema[table.name] = table.columns.map((c) => c.name);
  return schema;
}
