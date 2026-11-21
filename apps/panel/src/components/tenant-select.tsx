import { useQuery } from "@tanstack/react-query";
import { tenantsQueryOptions } from "@/lib/queries";

export function TenantSelect({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const tenants = useQuery(tenantsQueryOptions());
  return (
    <select
      className={
        className ?? "rounded-md border bg-background px-3 py-2 text-sm"
      }
      aria-label="Cliente"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Todos los clientes</option>
      {(tenants.data ?? []).map((row) => (
        <option key={row.slug} value={row.slug}>
          {row.name}
        </option>
      ))}
    </select>
  );
}
