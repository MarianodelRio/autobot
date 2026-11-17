function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatValue(value: unknown): string {
  if (value === undefined) return "—";
  if (value === null) return "(vacío)";
  if (typeof value === "boolean") return value ? "sí" : "no";
  if (typeof value === "string") return value === "" ? '""' : value;
  if (Array.isArray(value) || typeof value === "object")
    return JSON.stringify(value);
  return String(value);
}

type Row = { path: string; before: unknown; after: unknown };

/** Every changed leaf, by field path (C17: a legible final review, not a raw
 * diff-library dump). Arrays and nested documents that differ are compared and
 * shown whole, never element by element — good enough to read, much simpler
 * than reconstructing jsondiffpatch's delta format. */
function diffRows(before: unknown, after: unknown, path: string[] = []): Row[] {
  if (isPlainObject(before) && isPlainObject(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    return keys.flatMap((key) =>
      diffRows(before[key], after[key], [...path, key]),
    );
  }
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  return [{ path: path.join("."), before, after }];
}

/** A legible before/after for configuration and history comparisons: one row
 * per changed field, never a raw diff-library dump. */
export function JsonDiff({
  before,
  after,
}: {
  before: unknown;
  after: unknown;
}) {
  const rows = diffRows(before, after);
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Sin cambios.</p>;
  }
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((row) => (
        <li key={row.path} className="space-y-0.5">
          <p className="font-medium">{row.path || "(documento)"}</p>
          {row.before !== undefined && (
            <p className="text-status-critical line-through">
              {formatValue(row.before)}
            </p>
          )}
          {row.after !== undefined && (
            <p className="text-status-ok">{formatValue(row.after)}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
